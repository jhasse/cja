"""Command-line interface for cninja."""

import argparse
import sys
from pathlib import Path

from .generator import configure


def main() -> int:
    """Main entry point for cninja CLI."""
    parser = argparse.ArgumentParser(
        prog="cninja",
        description="A CMake reimplementation in Python with Ninja generator"
    )

    parser.add_argument(
        "source_dir",
        nargs="?",
        default=".",
        help="Path to source directory containing CMakeLists.txt (default: current directory)"
    )

    parser.add_argument(
        "-B", "--build-dir",
        dest="build_dir",
        default=None,
        help="Path to build directory (default: source_dir/build)"
    )

    parser.add_argument(
        "-S", "--source-dir",
        dest="source_dir_opt",
        default=None,
        help="Path to source directory (alternative to positional argument)"
    )

    args = parser.parse_args()

    # Determine source directory
    source_dir = Path(args.source_dir_opt or args.source_dir).resolve()

    # Determine build directory
    if args.build_dir:
        build_dir = Path(args.build_dir).resolve()
    else:
        build_dir = source_dir / "build"

    print(f"-- Source directory: {source_dir}")
    print(f"-- Build directory: {build_dir}")

    try:
        configure(source_dir, build_dir)
        return 0
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except SyntaxError as e:
        print(f"Parse error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
