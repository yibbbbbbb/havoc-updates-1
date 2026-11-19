"""Announce a verified stable release. Uses only the Python standard library."""

import argparse
import ast
import hashlib
import http.client
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

REPO = "yibbbbbbb/havoc-updates-1"
PAGES = "https://havoc-midnight-preview.pages.dev"
CHANNEL = "/desktop/stable.json"
DOWNLOAD = PAGES + "/desktop/HavocMidnight.py"
GITHUB = "https://api.github.com/repos/" + REPO
RAW = "https://raw.githubusercontent.com/" + REPO + "/main/public" + CHANNEL
FILE = Path(__file__).resolve().parents[1] / "public/desktop/stable.json"
LIMIT = 8 * 1024 * 1024


class ReleaseError(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request(url, *, method="GET", data=None, token=None, limit=65536):
    headers = {"User-Agent": "Havoc-Release-Announcements", "Accept": "*/*"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = Request(
        url,
        data=None if data is None else json.dumps(data).encode(),
        headers=headers,
        method=method,
    )
    try:
        try:
            response = build_opener(NoRedirect()).open(req, timeout=15)
        except HTTPError as exc:
            response = exc
        with response:
            body = response.read(limit + 1)
            if len(body) > limit:
                raise ReleaseError("A service response exceeded its size limit.")
            return response.status, body
    except (OSError, URLError, http.client.HTTPException):
        # Underlying HTTP exceptions can contain the secret webhook path.
        raise ReleaseError("A service could not be reached.") from None


def release_number(version):
    if not isinstance(version, str) or not re.fullmatch(
        r"(?:0|[1-9]\d{0,5})(?:\.(?:0|[1-9]\d{0,5})){2}", version, re.ASCII
    ):
        raise ReleaseError("Invalid release number.")
    return tuple(map(int, version.split(".")))


def live_desktop(expected, timeout=900):
    version = release_number(expected.get("version"))
    size = expected.get("size")
    if (
        expected.get("product") != "havoc-midnight-desktop"
        or type(size) is not int
        or not 0 < size <= LIMIT
        or not re.fullmatch("[0-9a-f]{64}", expected.get("sha256", ""))
        or not re.fullmatch("[0-9a-f]{40}", expected.get("revision", ""))
    ):
        raise ReleaseError("Invalid local stable manifest.")
    deadline = time.monotonic() + timeout
    while True:
        try:
            manifests = []
            for url in (RAW, PAGES + CHANNEL):
                status, body = request(url)
                if status == 200:
                    doc = json.loads(body)
                    if isinstance(doc, dict):
                        manifests.append(doc)
            if any(release_number(m.get("version")) > version for m in manifests):
                return None  # A newer stable promotion superseded this one.
            if manifests == [expected, expected]:
                status, desktop = request(DOWNLOAD, limit=LIMIT)
                if (
                    status == 200
                    and len(desktop) == size
                    and hashlib.sha256(desktop).hexdigest() == expected["sha256"]
                ):
                    return desktop
        except (ReleaseError, ValueError):
            pass
        if time.monotonic() >= deadline:
            raise ReleaseError(
                "Timed out waiting for matching public release manifests and download."
            )
        time.sleep(15)


def announcement(version, desktop):
    # Read the same release notes as the desktop without executing downloaded code.
    tree = ast.parse(desktop)
    panel = next(
        n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Panel"
    )
    init = next(
        n for n in panel.body if isinstance(n, ast.FunctionDef) and n.name == "__init__"
    )
    for n in init.body:
        if isinstance(n, ast.Assign) and any(
            isinstance(t, ast.Attribute)
            and isinstance(t.value, ast.Name)
            and t.value.id == "self"
            and t.attr == "changelog"
            for t in n.targets
        ):
            notes = ast.literal_eval(n.value).get("notes")
            if isinstance(notes, str) and 0 < len(notes.strip()) <= 3600:
                break
    else:
        raise ReleaseError(
            "The released desktop needs a changelog with 1–3600 characters."
        )
    return {
        "allowed_mentions": {"parse": []},
        "embeds": [
            {
                "title": f"Havoc {version} is live",
                "url": PAGES + "/",
                "description": notes.strip(),
                "color": 0xB19AF3,
                "fields": [
                    {
                        "name": "How to update",
                        "value": f"Open **Home → Updates → Check for updates**, then choose **Install {version} and restart**.\n[Download Havoc Desktop]({DOWNLOAD})",
                    }
                ],
            }
        ],
    }


def verified_webhook():
    secret = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    match = re.fullmatch(
        r"https://(?:discord\.com|discordapp\.com)/api/(?:v\d+/)?webhooks/([0-9]{15,22})/([A-Za-z0-9_-]{30,200})",
        secret,
    )
    if not match:
        raise ReleaseError(
            "Set DISCORD_WEBHOOK_URL to the URL copied from the Discord channel."
        )
    endpoint = "https://discord.com/api/v10/webhooks/" + "/".join(match.groups())
    status, body = request(endpoint)
    if status != 200:
        raise ReleaseError(f"Discord webhook validation returned HTTP {status}.")
    record = json.loads(body)
    if (
        record.get("id") != match[1]
        or record.get("type") != 1
        or not record.get("channel_id")
    ):
        raise ReleaseError("Discord did not confirm an incoming channel webhook.")
    return endpoint


def reserve(version, revision):
    tag = "tags/discord-announcement/" + version
    token = os.environ["GH_TOKEN"]
    status, _ = request(
        GITHUB + "/git/refs",
        method="POST",
        token=token,
        data={"ref": "refs/" + tag, "sha": revision},
    )
    if status == 201:
        return True
    if (
        status in (409, 422)
        and request(GITHUB + "/git/ref/" + tag, token=token)[0] == 200
    ):
        return False
    raise ReleaseError(
        f"GitHub could not reserve the announcement tag (HTTP {status})."
    )


def deliver(endpoint, payload):
    for attempt in range(3):
        status, body = request(endpoint + "?wait=true", method="POST", data=payload)
        if status == 200 and json.loads(body).get("id"):
            return
        if status == 429 and attempt < 2:
            delay = json.loads(body).get("retry_after")
            if type(delay) in (int, float) and 0 <= delay <= 60:
                time.sleep(delay + 0.25)
                continue
        raise ReleaseError(
            f"Discord did not confirm delivery (HTTP {status}). Check the channel before retrying."
        )


def run(send):
    expected = json.loads(FILE.read_bytes())
    desktop = live_desktop(expected)
    if desktop is None:
        print("A newer version is live. Skipping the older release.")
        return
    version = expected["version"]
    payload = announcement(version, desktop)
    endpoint = verified_webhook()
    if not send:
        print(
            f"Preview verified for {version}. Discord confirmed the webhook without sending a message."
        )
        print(payload["embeds"][0]["description"])
    elif reserve(version, expected["revision"]):
        deliver(endpoint, payload)
        print(f"Discord confirmed the {version} release announcement.")
    else:
        print(
            f"An announcement attempt already exists for {version}. Skipping duplicate."
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--send", action="store_true")
    mode.add_argument("--preview", action="store_true")
    try:
        run(parser.parse_args().send)
    except (ReleaseError, ValueError, SyntaxError, KeyError, StopIteration) as error:
        # JSON decoding errors may derive from the webhook response. Never print that response.
        sys.exit(
            str(error)
            if isinstance(error, ReleaseError)
            else "Release verification failed. Check the release data and workflow configuration."
        )
