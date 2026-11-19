import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "public" / "desktop"))
import HavocMidnight as app


class ReleasePreferencesTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name, value in (("ROOT", self.root), ("ASSET_ROOT", self.root / "assets")):
            change = patch.object(app, name, value)
            change.start()
            self.addCleanup(change.stop)
        ctx = app.imgui.create_context()
        self.addCleanup(app.imgui.destroy_context, ctx)

    def panel(self):
        panel = app.Panel()
        self.addCleanup(panel.shutdown)
        return panel

    def test_startup_checks_require_explicit_opt_in_and_never_install(self):
        with patch.object(app.DesktopUpdater, "start", autospec=True) as start:
            self.panel()
            start.assert_not_called()
            app.write_object(
                self.root / "workspace.json", {"update_notifications": True}
            )
            panel = self.panel()
            start.assert_called_once_with(panel.updater)

    def test_visibility_expiration_account_scope_and_quit(self):
        panel = self.panel()
        panel.account.user = "First"
        with (
            patch.object(app, "machine_ids", return_value=("test", "test")),
            patch.object(app.time, "time", return_value=100) as clock,
        ):
            panel._set_visibility(True, "For one hour")
            panel._restore_visibility()
            self.assertEqual(panel.share_until, 3700)
            panel.account.user = "Other"
            panel._restore_visibility()
            self.assertFalse(panel._share_online)
            panel.account.user = "First"
            clock.return_value = 3700
            panel._restore_visibility()
            self.assertFalse(panel._share_online)
            self.assertIsNone(panel._load_cfg()["online_share_for"])
            clock.return_value = 100
            panel._restore_visibility()
            self.assertFalse(panel._share_online)
            panel._set_visibility(True, "Until I quit")
            self.assertTrue(panel._share_online)
            panel._restore_visibility()
            self.assertFalse(panel._share_online)

    def test_workspace_and_nested_style_undo_preserve_other_edits(self):
        p = self.panel()
        p.account.user = "Test"
        key, other = [
            r["key"] for r in p.schema if isinstance(p.values[r["key"]], bool)
        ][:2]
        original = p.values[key]
        p.save_local_preset("Snapshot")
        p.push(key, not original)
        p._prepare_workspace_preset("Snapshot")
        self.assertEqual(p.values[key], not original)
        p._commit_preset("workspace", *p._preset_preview["workspace"])
        self.assertEqual(p.values[key], original)
        independent = not p.values[other]
        p.push(other, independent)
        p._undo_preset("workspace")
        self.assertEqual((p.values[key], p.values[other]), (not original, independent))
        target = p.preferences | {"colors": {"Havoc": {"acc": (1, 2, 3)}}}
        self.assertEqual(
            list(p._preset_changes(p.preferences, target)),
            [(("colors", "Havoc", "acc"), None, (1, 2, 3))],
        )
        p._commit_preset("style", "Test", target)
        p.preferences["colors"]["Havoc"]["bg"] = (4, 5, 6)
        p._undo_preset("style")
        self.assertEqual(p.preferences["colors"]["Havoc"], {"bg": (4, 5, 6)})
        self.assertEqual(p._preset_value("acc", (1, 2, 3), True), "#010203")

    def test_report_only_includes_allowlisted_information(self):
        panel = self.panel()
        h = panel.headset
        h.serial = "secret-device-id"
        h.devices = (app.Headset(h.serial, "secret-model", "unauthorized", "USB"),)
        h.phase = "live"
        report = h.diagnostic_report(True)
        for expected in ("Approval needed", "USB", "approve", "Devices detected: 1"):
            self.assertIn(expected, report)
        self.assertNotIn("secret", report)
        h.phase, h.error = "error", "sensitive error at secret-address"
        self.assertNotIn("secret", h.diagnostic_report(True))
        self.assertIn("Verify your account", h.diagnostic_report(False))

    def test_cached_schedule_crosses_boundaries_offline(self):
        row = {
            "start": "2026-11-19T12:00:00Z",
            "end": "2026-11-19T12:01:00Z",
            "message": "Active",
        }
        path = self.root / "daily-message.json"
        path.write_text(json.dumps({"message": "Default", "schedule": [row]}))
        start = app.message_timestamp(row["start"])
        with patch.object(app.time, "time", return_value=start - 1) as clock:
            notice = app.DailyMessage(path)
            notice.next_check = float("inf")
            for instant, text in (
                (start - 1, "Default"),
                (start, "Active"),
                (start + 59, "Active"),
                (start + 60, "Default"),
            ):
                clock.return_value = instant
                notice.poll()
                self.assertEqual(notice.text, text)
        for rows in (
            [row, row],
            [row | {"end": row["start"]}],
            [row | {"start": "bad"}],
        ):
            with self.assertRaises(ValueError):
                app.parse_message_feed({"message": "Default", "schedule": rows})

    def test_rollback_validation_permissions_and_atomicity(self):
        path = self.root / "Desktop.py"
        old = b"approved test fixture"
        current = b"current desktop"
        path.write_bytes(current)
        os.chmod(path, 0o750)
        digest = hashlib.sha256(current).hexdigest()
        backup = path.with_suffix(".py.previous")
        backup.write_bytes(old)
        with self.assertRaises(app.DesktopServiceError):
            app.restore_desktop(path, digest)
        self.assertEqual(path.read_bytes(), current)
        with patch.dict(
            app.TRUSTED_BACKUPS, {hashlib.sha256(old).hexdigest(): "1.0.0"}
        ):
            with self.assertRaises(app.DesktopServiceError):
                app.restore_desktop(path, "0" * 64)
            with (
                patch.object(os, "replace", side_effect=OSError("locked")),
                self.assertRaises(OSError),
            ):
                app.restore_desktop(path, digest)
            self.assertEqual(path.read_bytes(), current)
            self.assertEqual(backup.read_bytes(), old)
            self.assertEqual(app.restore_desktop(path, digest), "1.0.0")
        self.assertEqual(path.read_bytes(), old)
        if os.name != "nt":
            self.assertEqual(path.stat().st_mode & 0o777, 0o750)
