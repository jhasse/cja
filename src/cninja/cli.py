"""Command-line interface for cninja."""

import argparse
import subprocess
import sys
from pathlib import Path

from .generator import configure


def parse_define(value: str) -> tuple[str, str]:
    """Parse a -D argument into (name, value) tuple."""
    if "=" in value:
        name, val = value.split("=", 1)
        return (name, val)
    else:
        # -DFOO without value means FOO=ON
        return (value, "ON")


def cmd_configure(args: argparse.Namespace) -> int:
    """Run the configure command."""
    source_dir = Path(".")
    build_dir = args.build_dir

    # Parse -D arguments into variables dict
    variables: dict[str, str] = {}
    for define in args.defines:
        name, value = parse_define(define)
        variables[name] = value

    print(f"-- Source directory: {source_dir.resolve()}")
    print(f"-- Build directory: {build_dir}")

    try:
        configure(source_dir, build_dir, variables=variables if variables else None)
        return 0
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except SyntaxError as e:
        print(f"Parse error: {e}", file=sys.stderr)
        return 1


def cmd_build(args: argparse.Namespace) -> int:
    """Run the build command (configure if needed + ninja)."""
    source_dir = Path(".")

    # Determine build directory and variables based on --release flag
    if args.release:
        build_dir = "build-release"
        variables = {"CMAKE_BUILD_TYPE": "Release"}
    else:
        build_dir = "build"
        variables = {}

    ninja_file = Path(f"{build_dir}.ninja")

    # Only configure if ninja file doesn't exist
    if not ninja_file.exists():
        print(f"-- Source directory: {source_dir.resolve()}")
        print(f"-- Build directory: {build_dir}")

        try:
            configure(source_dir, build_dir, variables=variables if variables else None)
        except FileNotFoundError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        except SyntaxError as e:
            print(f"Parse error: {e}", file=sys.stderr)
            return 1

    # Run ninja
    ninja_cmd = ["ninja", "-f", str(ninja_file)]
    result = subprocess.run(ninja_cmd)
    return result.returncode


def main() -> int:
    """Main entry point for cninja CLI."""
    parser = argparse.ArgumentParser(
        prog="cninja",
        description="A CMake reimplementation in Python with Ninja generator"
    )

    subparsers = parser.add_subparsers(dest="command")

    # Configure command (default behavior, also works without subcommand)
    parser.add_argument(
        "-B", "--build-dir",
        dest="build_dir",
        default="build",
        help="Relative path for build directory (default: build)"
    )

    parser.add_argument(
        "-D",
        dest="defines",
        action="append",
        default=[],
        metavar="VAR=VALUE",
        help="Set a CMake variable (can be used multiple times)"
    )

    # Build subcommand
    build_parser = subparsers.add_parser(
        "build",
        help="Configure and build the project"
    )
    build_parser.add_argument(
        "--release",
        action="store_true",
        help="Build in release mode (CMAKE_BUILD_TYPE=Release)"
    )

    args = parser.parse_args()

    if args.command == "build":
        return cmd_build(args)
    else:
        # Default: configure only
        return cmd_configure(args)


if __name__ == "__main__":
    sys.exit(main())
