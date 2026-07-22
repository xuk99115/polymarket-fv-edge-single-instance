#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.core.github_runtime_backup import push_runtime_backup_via_temp_clone


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-dir", default=os.environ.get("RUNTIME_DIR", "/tmp/polymarket-fv-edge/data"))
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--branch", default="runtime-backup")
    parser.add_argument("--backup-subdir", default="runtime-backup")
    args = parser.parse_args()

    remote_url = subprocess.check_output(
        ["git", "-C", str(ROOT_DIR), "remote", "get-url", args.remote],
        text=True,
    ).strip()
    result = push_runtime_backup_via_temp_clone(
        args.runtime_dir,
        remote_url,
        args.branch,
        args.backup_subdir,
    )
    snapshot = result["snapshot"]
    print(
        f"changed={result['changed']} cash={snapshot['cash_balance']} "
        f"pnl={snapshot['realized_pnl']} closed_trades={snapshot['closed_trades']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
