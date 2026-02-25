"""Shared test helpers."""

from pathlib import Path
import shutil
import subprocess


def copy_unignored_tree(src: Path, dst: Path) -> None:
    """Copy only files that are not gitignored from src to dst."""
    dst.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            "git",
            "-C",
            str(src),
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
        ],
        capture_output=True,
        text=False,
        check=True,
    )
    files = [Path(p.decode("utf-8")) for p in result.stdout.split(b"\0") if p]
    for rel_path in files:
        src_path = src / rel_path
        dst_path = dst / rel_path
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        if src_path.is_symlink():
            target = src_path.readlink()
            dst_path.symlink_to(target)
        else:
            shutil.copy2(src_path, dst_path)
