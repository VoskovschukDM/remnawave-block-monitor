import json
import tempfile
import unittest
from pathlib import Path

from remnawave_block_monitor.models import Verdict
from remnawave_block_monitor.state import StateStore


class StateTests(unittest.TestCase):
    def test_debounce_survives_restart_and_recovers(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "state.json")
            store = StateStore(path)
            self.assertIsNone(store.apply("target", Verdict.LIKELY_RU_BLOCK, 3, 2).action)
            self.assertIsNone(store.apply("target", Verdict.LIKELY_RU_BLOCK, 3, 2).action)

            restarted = StateStore(path)
            restarted.load()
            alert = restarted.apply("target", Verdict.LIKELY_RU_BLOCK, 3, 2)
            self.assertEqual(alert.action, "alert")
            self.assertIsNone(restarted.apply("target", Verdict.LIKELY_RU_BLOCK, 3, 2).action)
            self.assertIsNone(restarted.apply("target", Verdict.OK, 3, 2).action)
            recovery = restarted.apply("target", Verdict.OK, 3, 2)
            self.assertEqual(recovery.action, "recovery")
            self.assertEqual(recovery.previous_notified_verdict, Verdict.LIKELY_RU_BLOCK.value)
            json.loads(path.read_text(encoding="utf-8"))

    def test_unknown_does_not_prove_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(Path(directory, "state.json"))
            store.apply("target", Verdict.GLOBAL_DOWN, 1, 2)
            store.apply("target", Verdict.OK, 1, 2)
            store.apply("target", Verdict.UNKNOWN, 1, 2)
            self.assertIsNone(store.apply("target", Verdict.OK, 1, 2).action)

    def test_disabled_notifications_do_not_consume_alert(self):
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(Path(directory, "state.json"))
            transition = store.apply("target", Verdict.GLOBAL_DOWN, 1, 2, notifications_enabled=False)
            self.assertIsNone(transition.action)
            transition = store.apply("target", Verdict.GLOBAL_DOWN, 1, 2, notifications_enabled=True)
            self.assertEqual(transition.action, "alert")

    def test_failed_delivery_is_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(Path(directory, "state.json"))
            transition = store.apply("target", Verdict.GLOBAL_DOWN, 1, 2)
            store.notification_failed("target", transition)
            self.assertEqual(store.apply("target", Verdict.GLOBAL_DOWN, 1, 2).action, "alert")

    def test_corrupt_state_is_quarantined(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "state.json")
            path.write_text("not json", encoding="utf-8")
            store = StateStore(path)
            store.load()
            self.assertTrue(Path(directory, "state.json.corrupt").exists())

    def test_malformed_entry_is_repaired(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "state.json")
            path.write_text('{"version": 1, "targets": {"target": {"bad_streak": "broken", "notified": "yes"}}}', encoding="utf-8")
            store = StateStore(path)
            store.load()
            transition = store.apply("target", Verdict.GLOBAL_DOWN, 1, 2)
            self.assertEqual(transition.action, "alert")


if __name__ == "__main__":
    unittest.main()
