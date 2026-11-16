"""Shared test helpers."""

import platform
import re
import shutil
import subprocess
from pathlib import Path


def copy_unignored_tree(src: Path, dst: Path) -> None:
    """Copy only files that are not gitignored from src to dst."""
    dst.mkdir(parents=True, exist_ok=True)
    try:
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
    except (FileNotFoundError, subprocess.CalledProcessError):
        shutil.copytree(src, dst, dirs_exist_ok=True)


def cd_command(directory: str) -> str:
    """The cd command line of a custom command's WORKING_DIRECTORY."""
    if platform.system() == "Windows":
        return f"cd /D {directory}"
    return f"cd {directory}"


def join_command_lines(*lines: str) -> str:
    """The ninja command for a custom command's lines, as the generator writes it."""
    joined = " && ".join(lines)
    if platform.system() == "Windows" and len(lines) > 1:
        return f'cmd.exe /C "{joined}"'
    return joined


def include_flags(ninja_content: str, obj: str) -> list[str]:
    """The -I and -isystem flags of the build edge of an object file, in order."""
    # Undo ninja_syntax's wrapping of long lines with "$" continuations
    ninja_content = re.sub(r"\$\n +", "", ninja_content)
    edge = re.search(
        rf"^build \S*/{re.escape(obj)}: .*\n((?:  .*\n)*)", ninja_content, re.MULTILINE
    )
    assert edge, f"no build edge for {obj}"
    cflags = re.search(r"^  cflags = (.*)$", edge.group(1), re.MULTILINE)
    return re.findall(r"-I\S+|-isystem \S+", cflags.group(1)) if cflags else []
