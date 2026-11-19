import importlib.util
import json
import os
import unittest
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

script = Path(__file__).resolve().parents[1] / "service/discord_release.py"
spec = importlib.util.spec_from_file_location("discord_release", script)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class DiscordReleaseTests(unittest.TestCase):
    def setUp(self):
        self.source = b'class Panel:\n def __init__(self):\n  self.changelog={"notes":"Release notes"}\n'
        self.manifest = dict(
            version="1.2.3",
            revision="a" * 40,
            product="havoc-midnight-desktop",
            sha256=sha256(self.source).hexdigest(),
            size=len(self.source),
        )
        self.doc = (200, json.dumps(self.manifest).encode())
        self.id = "123456789012345678"
        self.endpoint = "https://discord.com/api/webhooks/" + self.id + "/" + "x" * 40

    def test_match_supersession_and_incomplete_promotion(self):
        with patch.object(
            release, "request", side_effect=[self.doc, self.doc, (200, self.source)]
        ):
            self.assertEqual(release.live_desktop(self.manifest, 0), self.source)
        newer = (200, json.dumps(self.manifest | {"version": "1.2.4"}).encode())
        with patch.object(release, "request", side_effect=[newer, self.doc]):
            self.assertIsNone(release.live_desktop(self.manifest, 0))
        for responses in (
            [self.doc, (404, b"")],
            [self.doc, self.doc, (200, b"wrong")],
        ):
            with (
                patch.object(release, "request", side_effect=responses),
                self.assertRaises(release.ReleaseError),
            ):
                release.live_desktop(self.manifest, 0)

    def test_notes_disable_mentions_and_include_update_path(self):
        payload = release.announcement("1.2.3", self.source)
        self.assertEqual(payload["allowed_mentions"], {"parse": []})
        embed = payload["embeds"][0]
        self.assertEqual(embed["description"], "Release notes")
        self.assertIn("Install 1.2.3 and restart", embed["fields"][0]["value"])
        self.assertIn(release.DOWNLOAD, embed["fields"][0]["value"])

    def test_webhook_validation_is_read_only_and_rejects_wrong_hosts(self):
        with (
            patch.dict(os.environ, DISCORD_WEBHOOK_URL=self.endpoint),
            patch.object(
                release,
                "request",
                return_value=(
                    200,
                    json.dumps({"id": self.id, "type": 1, "channel_id": "1"}).encode(),
                ),
            ) as req,
        ):
            endpoint = release.verified_webhook()
            req.assert_called_once_with(endpoint)
        with (
            patch.dict(
                os.environ,
                DISCORD_WEBHOOK_URL=self.endpoint.replace("discord.com", "example.org"),
            ),
            patch.object(release, "request") as req,
            self.assertRaises(release.ReleaseError),
        ):
            release.verified_webhook()
        req.assert_not_called()

    def test_preview_and_duplicate_never_send(self):
        with (
            patch.object(release, "live_desktop", return_value=self.source),
            patch.object(release, "verified_webhook", return_value=self.endpoint),
            patch.object(release, "reserve", return_value=False) as reserve,
            patch.object(release, "deliver") as send,
        ):
            release.run(False)
            reserve.assert_not_called()
            release.run(True)
            reserve.assert_called_once()
            send.assert_not_called()

    def test_accepted_ref_existing_tag_and_denied_access(self):
        with patch.dict(os.environ, GH_TOKEN="test"):
            for status, expected in ((201, True), (422, False)):
                with patch.object(
                    release, "request", side_effect=[(status, b""), (200, b"")]
                ):
                    self.assertIs(release.reserve("1.2.3", "a" * 40), expected)
            with (
                patch.object(release, "request", return_value=(403, b"")),
                self.assertRaises(release.ReleaseError),
            ):
                release.reserve("1.2.3", "a" * 40)

    def test_only_rate_limits_can_retry_a_discord_post(self):
        with (
            patch.object(
                release,
                "request",
                side_effect=[(429, b'{"retry_after":0}'), (200, b'{"id":"123"}')],
            ) as req,
            patch.object(release.time, "sleep"),
        ):
            release.deliver(self.endpoint, {})
            self.assertEqual(req.call_count, 2)
        with (
            patch.object(release, "request", return_value=(502, b"")) as req,
            self.assertRaises(release.ReleaseError),
        ):
            release.deliver(self.endpoint, {})
        self.assertEqual(req.call_count, 1)
