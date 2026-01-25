"""Command-line interface for cninja."""

import argparse
import subprocess
import sys
from pathlib import Path

from termcolor import colored

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

    try:
        configure(
            source_dir,
            build_dir,
            variables=variables if variables else None,
            trace=args.trace,
            strict=args.strict,
        )
        return 0
    except FileNotFoundError as e:
        error_label = colored("error:", "red", attrs=["bold"])
        print(f"{error_label} {e}", file=sys.stderr)
        return 1
    except SyntaxError as e:
        if e.filename and e.lineno:
            rel_file = e.filename
            try:
                # Try to make path relative to current directory for cleaner output
                p = Path(e.filename)
                if p.is_absolute():
                    rel_file = str(p.relative_to(Path(".").resolve()))
            except ValueError:
                pass
            error_label = colored("error:", "red", attrs=["bold"])
            print(f"{rel_file}:{e.lineno}: {error_label} {e.msg}", file=sys.stderr)
        else:
            error_label = colored("error:", "red", attrs=["bold"])
            print(f"{error_label} Parse error: {e}", file=sys.stderr)
        return 1
    except RuntimeError as e:
        error_label = colored("error:", "red", attrs=["bold"])
        print(f"{error_label} {e}", file=sys.stderr)
        return 1


def cmd_build(args: argparse.Namespace) -> int:
    """Run the build command (configure if needed + ninja)."""
    return _run_ninja(args, target=None)


def cmd_test(args: argparse.Namespace) -> int:
    """Run the test command (configure if needed + ninja test)."""
    return _run_ninja(args, target="test")


def cmd_run(args: argparse.Namespace) -> int:
    """Run the run target in Ninja."""
    return _run_ninja(args, target="run")


def cmd_command_mode(args: list[str]) -> int:
    """Run CMake-like command mode (-E)."""
    if not args:
        return 1

    cmd = args[0]
    cmd_args = args[1:]

    if cmd == "make_directory":
        for directory in cmd_args:
            Path(directory).mkdir(parents=True, exist_ok=True)
        return 0
    else:
        error_label = colored("error:", "red", attrs=["bold"])
        print(f"{error_label} Unknown command -E {cmd}", file=sys.stderr)
        return 1


def _run_ninja(args: argparse.Namespace, target: str | None) -> int:
    """Internal helper to run ninja with configuration if needed."""
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
        try:
            configure(source_dir, build_dir, variables=variables if variables else None)
        except FileNotFoundError as e:
            error_label = colored("error:", "red", attrs=["bold"])
            print(f"{error_label} {e}", file=sys.stderr)
            return 1
        except SyntaxError as e:
            if e.filename and e.lineno:
                rel_file = e.filename
                try:
                    p = Path(e.filename)
                    if p.is_absolute():
                        rel_file = str(p.relative_to(Path(".").resolve()))
                except ValueError:
                    pass
                error_label = colored("error:", "red", attrs=["bold"])
                print(f"{rel_file}:{e.lineno}: {error_label} {e.msg}", file=sys.stderr)
            else:
                error_label = colored("error:", "red", attrs=["bold"])
                print(f"{error_label} Parse error: {e}", file=sys.stderr)
            return 1

    # Run ninja
    ninja_cmd = ["ninja", "-f", str(ninja_file)]
    if target:
        ninja_cmd.append(target)
    result = subprocess.run(ninja_cmd)
    return result.returncode


def main() -> int:
    """Main entry point for cninja CLI."""
    parser = argparse.ArgumentParser(
        prog="cninja",
        description="A CMake reimplementation in Python with Ninja generator",
    )

    subparsers = parser.add_subparsers(dest="command")

    # Configure command (default behavior, also works without subcommand)
    parser.add_argument(
        "-B",
        "--build-dir",
        dest="build_dir",
        default="build",
        help="Relative path for build directory (default: build)",
    )

    parser.add_argument(
        "-D",
        dest="defines",
        action="append",
        default=[],
        metavar="VAR=VALUE",
        help="Set a CMake variable (can be used multiple times)",
    )

    parser.add_argument(
        "--trace", action="store_true", help="Print each command as it's processed"
    )

    parser.add_argument(
        "--strict",
        action="store_true",
        help="Error on unsupported commands instead of ignoring them",
    )

    parser.add_argument(
        "-E",
        nargs="+",
        metavar="command",
        help="CMake-like command mode (e.g., -E make_directory dir...)",
    )

    # Build subcommand
    build_parser = subparsers.add_parser(
        "build", help="Configure and build the project"
    )
    build_parser.add_argument(
        "--release",
        action="store_true",
        help="Build in release mode (CMAKE_BUILD_TYPE=Release)",
    )

    # Test subcommand
    test_parser = subparsers.add_parser("test", help="Configure and run tests")
    test_parser.add_argument(
        "--release",
        action="store_true",
        help="Run tests in release mode (CMAKE_BUILD_TYPE=Release)",
    )

    # Run subcommand
    run_parser = subparsers.add_parser(
        "run", help="Configure, build and run the first executable"
    )
    run_parser.add_argument(
        "--release",
        action="store_true",
        help="Run in release mode (CMAKE_BUILD_TYPE=Release)",
    )

    args = parser.parse_args()

    if args.E:
        return cmd_command_mode(args.E)

    if args.command == "build":
        return cmd_build(args)
    elif args.command == "test":
        return cmd_test(args)
    elif args.command == "run":
        return cmd_run(args)
    else:
        # Default: configure only
        return cmd_configure(args)


if __name__ == "__main__":
    sys.exit(main())
