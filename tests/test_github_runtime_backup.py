import json
import os
import tempfile
import unittest
from pathlib import Path

from src.core.github_runtime_backup import (
    BACKUP_FILES,
    compute_runtime_snapshot,
    has_runtime_state_changed,
    write_runtime_backup,
)


class TestGithubRuntimeBackup(unittest.TestCase):
    def _seed_runtime(self, runtime_dir: str):
        payloads = {
            "paper_trade_state.json": {"cash_balance": 123.45, "positions": [], "trades": [1, 2], "stats": {"total_trades": 1}, "summary": {"realized_pnl": 23.45}},
            "state_summary.json": {"cash_balance": 123.45, "realized_pnl": 23.45, "total_trades": 1},
            "bot_status.json": {"running": True, "trading_enabled": True},
            "direction_state.json": {"direction": "UP"},
            "sync_health.json": {"sync_healthy": True, "sync_error_count": 0},
        }
        for name, payload in payloads.items():
            Path(runtime_dir, name).write_text(json.dumps(payload), encoding="utf-8")

    def test_compute_runtime_snapshot_reads_required_files(self):
        with tempfile.TemporaryDirectory() as runtime_dir:
            self._seed_runtime(runtime_dir)
            snap = compute_runtime_snapshot(runtime_dir)
            self.assertEqual(snap["cash_balance"], 123.45)
            self.assertEqual(snap["closed_trades"], 1)
            self.assertEqual(snap["positions"], 0)
            self.assertEqual(snap["files"], BACKUP_FILES)
            self.assertEqual(len(snap["file_hashes"]), len(BACKUP_FILES))

    def test_has_runtime_state_changed_detects_same_and_diff(self):
        with tempfile.TemporaryDirectory() as runtime_dir:
            self._seed_runtime(runtime_dir)
            snap1 = compute_runtime_snapshot(runtime_dir)
            snap2 = compute_runtime_snapshot(runtime_dir)
            self.assertFalse(has_runtime_state_changed(snap1, snap2))
            Path(runtime_dir, "paper_trade_state.json").write_text(
                json.dumps({"cash_balance": 120.0, "positions": [], "trades": [1, 2], "stats": {"total_trades": 1}, "summary": {"realized_pnl": 20.0}}),
                encoding="utf-8",
            )
            snap3 = compute_runtime_snapshot(runtime_dir)
            self.assertTrue(has_runtime_state_changed(snap1, snap3))

    def test_write_runtime_backup_exports_files_and_manifest(self):
        with tempfile.TemporaryDirectory() as runtime_dir, tempfile.TemporaryDirectory() as backup_dir:
            self._seed_runtime(runtime_dir)
            snap = compute_runtime_snapshot(runtime_dir)
            write_runtime_backup(runtime_dir, backup_dir, snap)
            for name in BACKUP_FILES:
                self.assertTrue(Path(backup_dir, name).exists(), name)
            manifest = json.loads(Path(backup_dir, "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["snapshot"]["cash_balance"], 123.45)
            self.assertEqual(manifest["snapshot"]["closed_trades"], 1)


if __name__ == "__main__":
    unittest.main()
