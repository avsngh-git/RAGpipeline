"""Code identity helpers for persisted ingestion and discovery outputs."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path


def code_revision() -> str:
    """Identify HEAD plus a digest of local tracked and untracked changes."""
    root_result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        check=False,
        text=True,
    )
    if root_result.returncode != 0:
        return "unknown"

    root = Path(root_result.stdout.strip())
    head_result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        check=False,
        text=True,
    )
    if head_result.returncode != 0:
        return "unknown"
    head = head_result.stdout.strip()

    status_result = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if status_result.returncode != 0:
        return head
    if not status_result.stdout:
        return head

    digest = hashlib.sha256()
    diff_result = subprocess.run(
        ["git", "diff", "--binary", "HEAD", "--"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if diff_result.returncode == 0:
        digest.update(diff_result.stdout)

    untracked_result = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if untracked_result.returncode == 0:
        for raw_path in sorted(untracked_result.stdout.split(b"\0")):
            if not raw_path:
                continue
            relative_path = Path(raw_path.decode("utf-8"))
            file_path = root / relative_path
            if not file_path.is_file():
                continue
            digest.update(raw_path)
            digest.update(file_path.read_bytes())

    return f"{head}+dirty.sha256:{digest.hexdigest()}"
