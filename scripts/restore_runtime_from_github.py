#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.core.github_runtime_backup import BACKUP_FILES


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--branch", default="runtime-backup")
    parser.add_argument("--backup-subdir", default="runtime-backup")
    parser.add_argument("--runtime-dir", default=os.environ.get("RUNTIME_DIR", "/tmp/polymarket-fv-edge/data"))
    args = parser.parse_args()

    remote_url = subprocess.check_output(["git", "-C", str(ROOT_DIR), "remote", "get-url", args.remote], text=True).strip()
    with tempfile.TemporaryDirectory(prefix="polymarket-runtime-restore-") as temp:
        repo = Path(temp) / "repo"
        subprocess.run(["git", "clone", "--quiet", "--branch", args.branch, remote_url, str(repo)], check=True)
        backup_dir = repo / args.backup_subdir
        runtime_dir = Path(args.runtime_dir)
        runtime_dir.mkdir(parents=True, exist_ok=True)
        for name in BACKUP_FILES:
            src = backup_dir / name
            if not src.exists():
                raise FileNotFoundError(f"missing backup file: {src}")
            shutil.copy2(src, runtime_dir / name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
