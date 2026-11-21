from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import recover_snowluma as recovery


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(
            prefix=".recovery-test-",
            dir=Path(__file__).resolve().parent,
        )
        root = Path(self.temp.name)
        self.paths = {
            "LOG_PATH": root / "recovery.log",
            "LOCK_PATH": root / ".lock",
            "STATE_PATH": root / ".state.json",
            "MUTE_PATH": root / ".mute",
        }
        self.patchers = []
        for name, value in self.paths.items():
            patcher = mock.patch.object(recovery, name, value)
            patcher.start()
            self.patchers.append(patcher)

    def tearDown(self):
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temp.cleanup()

    @staticmethod
    def snapshot(*, duplicate=True, ws=0, login=False, hook=False, running=True):
        return recovery.HealthSnapshot(
            container_running=running,
            qq_pids=[101, 102] if duplicate else [101],
            ws_connections=ws,
            login_ok=login,
            login_detail="retcode=0" if login else "unavailable",
            hook_unavailable=hook,
        )

    def test_main_process_parser_ignores_workers(self):
        result = mock.Mock(returncode=0)
        result.stdout = (
            "101 /opt/QQ/qq --relaunch --no-sandbox\n"
            "102 /opt/QQ/qq --type=zygote --no-sandbox\n"
            "103 /proc/self/exe --type=utility --no-sandbox\n"
            "104 qq --no-sandbox --disable-gpu\n"
        )
        with mock.patch.object(recovery, "run_command", return_value=result):
            self.assertEqual(recovery._qq_main_pids(), [101, 104])

    def test_recover_success_and_timestamped_log(self):
        before = self.snapshot(duplicate=True, ws=0, login=False)
        after = self.snapshot(duplicate=False, ws=2, login=True)
        with (
            mock.patch.object(recovery, "snapshot", side_effect=[before, after]),
            mock.patch.object(recovery, "_restart_container", return_value=(True, "ok")) as restart,
            mock.patch.object(recovery.time, "sleep", return_value=None),
        ):
            result = recovery.recover("test", source="test")
        self.assertTrue(result["attempted"])
        self.assertTrue(result["success"])
        restart.assert_called_once()
        record = json.loads(recovery.LOG_PATH.read_text(encoding="utf-8").splitlines()[-1])
        self.assertIn("ts", record)
        self.assertEqual(record["event"], "recovery_result")
        self.assertGreater(recovery.load_state()["last_attempt"], 0)

    def test_restart_failure_is_reported(self):
        before = self.snapshot(duplicate=True)
        with (
            mock.patch.object(recovery, "snapshot", return_value=before),
            mock.patch.object(recovery, "_restart_container", return_value=(False, "failed")),
        ):
            result = recovery.recover("test", source="test")
        self.assertTrue(result["attempted"])
        self.assertFalse(result["success"])
        self.assertEqual(result["detail"], "failed")

    def test_auto_requires_three_failures(self):
        current = self.snapshot(duplicate=True)
        attempted = {"attempted": True, "success": True}
        with (
            mock.patch.object(recovery, "snapshot", return_value=current),
            mock.patch.object(recovery, "recover", return_value=attempted) as recover,
        ):
            self.assertIsNone(recovery.maybe_auto_recover(now=100000))
            self.assertIsNone(recovery.maybe_auto_recover(now=100100))
            result = recovery.maybe_auto_recover(now=100200)
        self.assertIsNotNone(result)
        recover.assert_called_once()
        self.assertEqual(recovery.load_state()["fail_count"], 0)

    def test_cooldown_blocks_repeat_restart(self):
        recovery.save_state({"fail_count": 2, "last_attempt": 100000})
        current = self.snapshot(duplicate=True)
        with (
            mock.patch.object(recovery, "snapshot", return_value=current),
            mock.patch.object(recovery, "recover") as recover,
        ):
            result = recovery.maybe_auto_recover(now=100100)
        self.assertIsNone(result)
        recover.assert_not_called()
        self.assertEqual(recovery.load_state()["fail_count"], 3)

    def test_mute_blocks_all_auto_actions(self):
        self.paths["MUTE_PATH"].write_text("maintenance", encoding="utf-8")
        with mock.patch.object(recovery, "snapshot") as snapshot:
            self.assertIsNone(recovery.maybe_auto_recover(now=100000))
        snapshot.assert_not_called()

    def test_unrecoverable_state_resets_counter(self):
        recovery.save_state({"fail_count": 2, "last_attempt": 0})
        current = self.snapshot(duplicate=False, ws=0, login=False, hook=True)
        with mock.patch.object(recovery, "snapshot", return_value=current):
            self.assertIsNone(recovery.maybe_auto_recover(now=100000))
        self.assertEqual(recovery.load_state()["fail_count"], 0)

    def test_healthy_ws_resets_counter(self):
        recovery.save_state({"fail_count": 2, "last_attempt": 0})
        current = self.snapshot(duplicate=False, ws=2, login=True)
        with mock.patch.object(recovery, "snapshot", return_value=current):
            self.assertIsNone(recovery.maybe_auto_recover(now=100000))
        self.assertEqual(recovery.load_state()["fail_count"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
