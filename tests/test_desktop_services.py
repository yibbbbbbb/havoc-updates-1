import hashlib
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from importlib import import_module
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "public" / "desktop"))
app = import_module("HavocMidnight")


class DesktopReleaseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "My Havoc.py"
        self.previous = b'DESKTOP_RELEASE = "2026.11.18"\n'
        self.path.write_bytes(self.previous)
        self.path.chmod(0o750)
        self.start = hashlib.sha256(self.previous).hexdigest()
        major, minor, build = app.release_number(app.DESKTOP_RELEASE)
        next_version = f"{major}.{minor}.{build + 1}"
        self.data = f'DESKTOP_RELEASE = "{next_version}"\n'.encode()
        self.info = {
            "product": "havoc-midnight-desktop",
            "version": next_version,
            "revision": "a" * 40,
            "sha256": hashlib.sha256(self.data).hexdigest(),
            "size": len(self.data),
        }
        self.mirror = dict(self.info)
        self.payload = self.data

        def fetch(url, limit):
            if url == app.PAGES_ORIGIN + "/desktop/stable.json":
                return json.dumps(self.info).encode()
            if url == app.DESKTOP_REPO + "/main/public/desktop/stable.json":
                return json.dumps(self.mirror).encode()
            self.assertEqual(
                url,
                app.DESKTOP_REPO
                + "/"
                + self.info["revision"]
                + "/public/desktop/HavocMidnight.py",
            )
            return self.payload

        proxy = patch.object(app, "desktop_request", side_effect=fetch)
        self.fetch = proxy.start()
        self.addCleanup(proxy.stop)

    def test_success_atomic_backup_permissions_and_concurrent_modification(self):
        rel = app.desktop_channel()
        app.install_desktop(self.path, self.start, rel)
        self.assertEqual(self.path.read_bytes(), self.data)
        self.assertEqual(
            self.path.with_suffix(".py.previous").read_bytes(), self.previous
        )
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o750)
        with self.assertRaises(app.DesktopServiceError):
            app.install_desktop(self.path, self.start, rel)
        self.assertEqual(self.path.read_bytes(), self.data)

    def test_mirror_tamper_refusal_and_changed_channel(self):
        offered = app.desktop_channel()
        self.mirror["sha256"] = "0" * 64
        with self.assertRaises(app.DesktopServiceError):
            app.install_desktop(self.path, self.start, offered)
        self.mirror = dict(self.info)
        for bad in (b"x" * len(self.data), b"", self.data + b"x"):
            self.payload = bad
            with self.assertRaises(app.DesktopServiceError):
                app.install_desktop(self.path, self.start, offered)
        self.assertEqual(self.path.read_bytes(), self.previous)

    def test_malformed_version_file_bad_schema_and_downgrade(self):
        for invalid in ("1.01.2", None, "1.2.3x", "1.2", {}, "000.1.2"):
            with self.assertRaises(ValueError):
                app.release_number(invalid)
        for value in ("junk", "a" * 39):
            self.info["revision"] = value
            with self.assertRaises(ValueError):
                app.desktop_channel()
        self.info["revision"] = "a" * 40
        for data in (b"not python[", b'DESKTOP_RELEASE="2.0.0"'):
            self.payload = data
            self.info.update(size=len(data), sha256=hashlib.sha256(data).hexdigest())
            self.mirror = dict(self.info)
            rel = app.desktop_channel()
            with self.assertRaises((SyntaxError, app.DesktopServiceError)):
                app.install_desktop(self.path, self.start, rel)
            with self.assertRaises(app.DesktopServiceError):
                app.install_desktop(self.path, self.start, rel, current="2027.1.1")
        self.assertEqual(self.path.read_bytes(), self.previous)

    def test_lock_and_failed_replace_preserve_original(self):
        rel = app.desktop_channel()
        with (
            app.desktop_install_lock(self.path),
            self.assertRaises(app.DesktopServiceError),
        ):
            app.install_desktop(self.path, self.start, rel)
        original = os.replace

        def blocked(src, dst):
            if dst == self.path:
                raise PermissionError("locked")
            return original(src, dst)

        with (
            patch.object(os, "replace", side_effect=blocked),
            self.assertRaises(PermissionError),
        ):
            app.install_desktop(self.path, self.start, rel)
        self.assertEqual(self.path.read_bytes(), self.previous)
        self.assertFalse(list(self.path.parent.glob(".havoc-release-*")))

    def test_background_check_and_install_buttons(self):
        updater = app.DesktopUpdater(self.path)
        updater.start()
        channel = updater.pending
        updater.start()
        self.assertIs(channel, updater.pending)
        until(lambda: (updater.poll(), updater.phase == "offered")[1])
        updater.start(install=True)
        until(lambda: (updater.poll(), updater.phase == "installed")[1])
        self.assertEqual(self.path.read_bytes(), self.data)

    def test_numeric_comparison(self):
        self.assertLess(
            app.release_number("2026.9.10"), app.release_number("2026.11.1")
        )


def until(check):
    stop = time.monotonic() + 3
    while not check():
        if time.monotonic() > stop:
            raise AssertionError("Timed out waiting for desktop worker")
        time.sleep(0.005)


class OnlineDeskTests(unittest.TestCase):
    def test_footer_refreshes_total_without_fetching_names_or_sharing(self):
        calls = []

        def api(route, *args, **kwargs):
            calls.append(route)
            if route == "session":
                return {"token": "d" * 64}
            if route == "members":
                return {"members": [], "next": None}
            if route == "count":
                return {"count": 3}
            return {"ok": True}

        with patch.object(app, "presence_request", side_effect=api):
            online = app.OnlineSession()
            online.set_interest(False, False, watch=True)
            try:
                until(lambda: online.count == 3)
                self.assertEqual(calls, ["session", "count"])
                with patch.object(app.time, "time", return_value=time.time() + 101):
                    self.assertIsNone(online.count)
                online.set_interest(False, True, watch=True)
                until(lambda: online.count == 0 and online.snapshot[1] == ())
                self.assertEqual(calls.count("count"), 1)
            finally:
                online.close()
                online.thread.join(1)
            self.assertIsNone(online.count)

    def test_footer_rejects_invalid_totals(self):
        with patch.object(
            app,
            "presence_request",
            side_effect=[{"token": "d" * 64}, {"count": False}, {"ok": True}],
        ):
            online = app.OnlineSession()
            online.set_interest(False, False, watch=True)
            until(lambda: "unavailable" in online.snapshot[0])
            self.assertIsNone(online.count)
            online.close()
            online.thread.join(1)

    def test_private_default_share_hide_and_logout(self):
        calls = []
        token = "d" * 64

        def api(route, method="GET", auth=None, body=None, **kwargs):
            calls.append((route, method, body))
            if route == "session" and method == "POST":
                return {"token": token}
            if route == "members":
                return {"members": [{"id": "a" * 24, "name": "Ada"}], "next": None}
            return {"ok": True}

        with (
            patch.object(app, "presence_request", side_effect=api),
            patch.object(app, "machine_ids", return_value=("1" * 16, "2" * 16)),
        ):
            online = app.OnlineSession()
            online.set_interest(False, False)
            self.assertIsNone(online.thread)
            online.set_interest(False, True)
            until(lambda: online.snapshot[1] == ("Ada",))
            self.assertIn(("live", "PUT", {"visible": False}), calls)
            online.set_interest(True, False)
            until(lambda: ("live", "PUT", {"visible": True}) in calls)
            online.set_interest(False, False)
            until(lambda: ("session", "DELETE", None) in calls)
            online.close()
            online.thread.join(1)
            self.assertFalse(online.thread.is_alive())

    def test_logout_during_verification_never_makes_session_visible(self):
        got, go = threading.Event(), threading.Event()
        calls = []

        def api(route, method="GET", *args, **kwargs):
            calls.append((method, route))
            if method == "POST":
                got.set()
                go.wait(1)
                return {"token": "1" * 64}
            return {"ok": True}

        with patch.object(app, "presence_request", side_effect=api):
            online = app.OnlineSession()
            online.set_interest(True, True)
            self.assertTrue(got.wait(1))
            online.close()
            go.set()
            online.thread.join(2)
            self.assertNotIn(("PUT", "live"), calls)
            self.assertIn(("DELETE", "session"), calls)
            self.assertEqual(online.snapshot, ("", None))

    def test_paginated_members_duplicates_and_malformed_cursor(self):
        k = "0" * 23
        with patch.object(
            app,
            "presence_request",
            side_effect=[
                {"members": [{"id": k + "1", "name": "Zulu"}], "next": k + "1"},
                {"members": [{"id": k + "2", "name": "Ada"}], "next": None},
            ],
        ):
            self.assertEqual(app.online_roster("t"), ("Ada", "Zulu"))
        with (
            patch.object(
                app, "presence_request", return_value={"members": [], "next": "&bad"}
            ),
            self.assertRaises(ValueError),
        ):
            app.online_roster("t")

    def test_rejected_renewal_backs_off_and_manual_retry_recovers(self):
        tokens = []
        reject = threading.Event()

        def api(route, method="GET", token=None, body=None):
            if route == "session" and method == "POST":
                issued = str(len(tokens) + 1) * 64
                tokens.append(issued)
                return {"token": issued}
            if reject.is_set() and route != "session":
                error = PermissionError("Expired session")
                error.code = 401
                raise app.DesktopServiceError("Session expired") from error
            if route == "count":
                return {"count": 0}
            if route == "members":
                return {"members": [], "next": None}
            return {"ok": True}

        with patch.object(app, "presence_request", side_effect=api):
            online = app.OnlineSession()
            try:
                online.set_interest(False, False, watch=True)
                until(lambda: online.count == 0)
                reject.set()
                online.set_interest(False, True, watch=True)
                until(lambda: online.retry_available)
                self.assertEqual(len(tokens), 2)
                self.assertIsNone(online.count)
                reject.clear()
                online.retry_now()
                online.retry_now()
                until(lambda: online.snapshot[1] == ())
                self.assertEqual(len(tokens), 3)
                self.assertEqual(online.count, 0)
                self.assertFalse(online.retry_available)
            finally:
                online.close()
                online.thread.join(1)

    def test_outage_never_becomes_empty_online_list(self):
        with patch.object(
            app, "presence_request", side_effect=app.DesktopServiceError("offline")
        ):
            online = app.OnlineSession()
            online.set_interest(False, True)
            until(lambda: "unavailable" in online.snapshot[0])
            self.assertIsNone(online.snapshot[1])
            online.close()
            online.thread.join(1)
