"""Command-line interface for cja."""

import argparse
import importlib.metadata
import json
import shutil
import subprocess
import sys
from pathlib import Path

from termcolor import colored

from . import __version__
from .format import decode, find_style, format_source
from .generator import configure, run_script, verify_globs


def _get_version() -> str:
    """Get cja package version."""
    try:
        return importlib.metadata.version("cja")
    except importlib.metadata.PackageNotFoundError:
        return __version__


def parse_define(value: str) -> tuple[str, str]:
    """Parse a -D argument into (name, value) tuple."""
    if "=" in value:
        name, val = value.split("=", 1)
        return (name, val)
    else:
        # -DFOO without value means FOO=ON
        return (value, "ON")


def _build_dir_and_variables(args: argparse.Namespace) -> tuple[str, dict[str, str]]:
    """Return the build directory and variables from -B, -D and --release."""
    if args.release:
        build_dir = "build-release"
        variables: dict[str, str] = {"CMAKE_BUILD_TYPE": "Release"}
    else:
        build_dir = "build"
        variables = {}
    # -B and -D win over --release
    if args.build_dir is not None:
        build_dir = args.build_dir
    for define in args.defines:
        name, value = parse_define(define)
        variables[name] = value
    return build_dir, variables


def _configure_for_subcommand(args: argparse.Namespace) -> tuple[str, int]:
    """Configure for build/test/run if needed; return (build_dir, exit code).

    Only configures when the ninja file is missing (from then on ninja
    regenerates it itself) or when -D asks for different variables.
    """
    build_dir, variables = _build_dir_and_variables(args)
    ninja_file = Path(f"{build_dir}.ninja")
    cja_json_path = Path(build_dir) / "cja.json"
    configured = ninja_file.exists() and (
        args.command != "run" or cja_json_path.exists()
    )
    if configured and not args.defines:
        return build_dir, 0
    try:
        configure(Path("."), build_dir, variables=variables if variables else None)
    except FileNotFoundError as e:
        error_label = colored("error:", "red", attrs=["bold"])
        print(f"{error_label} {e}", file=sys.stderr)
        return build_dir, 1
    except SyntaxError as e:
        if e.filename and e.lineno:
            rel_file = e.filename
            try:
                p = Path(e.filename)
                if p.is_absolute():
                    rel_file = str(p.relative_to(Path.cwd()))
            except ValueError:
                pass
            error_label = colored("error:", "red", attrs=["bold"])
            print(f"{rel_file}:{e.lineno}: {error_label} {e.msg}", file=sys.stderr)
        else:
            error_label = colored("error:", "red", attrs=["bold"])
            print(f"{error_label} Parse error: {e}", file=sys.stderr)
        return build_dir, 1
    except RuntimeError as e:
        error_label = colored("error:", "red", attrs=["bold"])
        print(f"{error_label} {e}", file=sys.stderr)
        return build_dir, 1
    return build_dir, 0


def cmd_configure(args: argparse.Namespace) -> int:
    """Run the configure command."""
    source_dir = Path(".")
    build_dir, variables = _build_dir_and_variables(args)

    try:
        configure(
            source_dir,
            build_dir,
            variables=variables if variables else None,
            trace=args.trace,
            strict=args.strict,
            regenerate_during_build=args.regenerate_during_build,
            quiet=args.quiet or args.regenerate_during_build,
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
                    rel_file = str(p.relative_to(Path.cwd()))
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
    return _run_ninja(args, target="test-parallel" if args.parallel else "test")


def cmd_run(args: argparse.Namespace) -> int:
    """Build and run the first executable."""
    build_dir, status = _configure_for_subcommand(args)
    if status != 0:
        return status

    ninja_file = Path(f"{build_dir}.ninja")
    cja_json_path = Path(build_dir) / "cja.json"

    if not cja_json_path.exists():
        error_label = colored("error:", "red", attrs=["bold"])
        print(f"{error_label} No executable target to run", file=sys.stderr)
        return 1

    cja_config = json.loads(cja_json_path.read_text())
    exe_path = cja_config["run_executable"]

    # Build just the executable
    ninja_cmd = ["ninja", "-f", str(ninja_file), exe_path]
    sys.stdout.flush()
    sys.stderr.flush()
    result = subprocess.run(ninja_cmd, check=False)
    if result.returncode != 0:
        return result.returncode

    # Run the executable directly, passing through any extra arguments
    exe_cmd = [str(Path(exe_path))]
    if hasattr(args, "ninja_args"):
        exe_cmd.extend(args.ninja_args)
    sys.stdout.flush()
    sys.stderr.flush()
    result = subprocess.run(exe_cmd, check=False)
    return result.returncode


def cmd_script(
    script_path: str,
    script_args: list[str],
    defines: list[str],
    trace: bool,
    strict: bool,
) -> int:
    """Run a CMake script file (cmake -P mode)."""
    variables: dict[str, str] = {}
    for define in defines:
        name, value = parse_define(define)
        variables[name] = value

    try:
        run_script(
            Path(script_path),
            variables=variables if variables else None,
            script_args=script_args,
            trace=trace,
            strict=strict,
        )
        return 0
    except FileNotFoundError as e:
        error_label = colored("error:", "red", attrs=["bold"])
        print(f"{error_label} {e}", file=sys.stderr)
        return 1
    except SyntaxError as e:
        error_label = colored("error:", "red", attrs=["bold"])
        if e.filename and e.lineno:
            print(f"{e.filename}:{e.lineno}: {error_label} {e.msg}", file=sys.stderr)
        else:
            print(f"{error_label} Parse error: {e}", file=sys.stderr)
        return 1
    except RuntimeError as e:
        error_label = colored("error:", "red", attrs=["bold"])
        print(f"{error_label} {e}", file=sys.stderr)
        return 1
    except SystemExit as e:
        return int(e.code) if isinstance(e.code, int) else 1


def parse_line_range(value: str) -> tuple[int, int]:
    """Parse START:END for cja format --lines."""
    start, sep, end = value.partition(":")
    try:
        first, last = int(start), int(end)
    except ValueError:
        first = last = 0
    if not sep or first < 1 or last < first:
        raise argparse.ArgumentTypeError(
            f"invalid line range '{value}' (expected START:END with 1 <= START <= END)"
        )
    return first, last


def cmd_lsp() -> int:
    """Run the language server on stdin/stdout."""
    from .lsp import serve

    output = sys.stdout.buffer
    # Anything printed by accident must not end up in the protocol stream.
    sys.stdout = sys.stderr
    return serve(sys.stdin.buffer, output)


def cmd_format(args: argparse.Namespace) -> int:
    """Format CMake files like clang-format / cmake-format."""
    error_label = colored("error:", "red", attrs=["bold"])
    files: list[str] = args.files or ["-"]
    if args.in_place and "-" in files:
        print(f"{error_label} -i cannot be used when reading from stdin", file=sys.stderr)
        return 1
    if args.lines and len(files) > 1:
        print(f"{error_label} --lines can only be used with one file", file=sys.stderr)
        return 1

    status = 0
    for name in files:
        if name == "-":
            path = Path(args.assume_filename or "CMakeLists.txt")
            source, encoding = decode(sys.stdin.buffer.read())
            name = "<stdin>"
        else:
            path = Path(name)
            try:
                source, encoding = decode(path.read_bytes())
            except OSError as e:
                print(f"{error_label} {name}: {e.strerror}", file=sys.stderr)
                status = 1
                continue

        try:
            formatted = format_source(
                source, find_style(path.parent), name, args.lines
            )
        except SyntaxError as e:
            print(f"{e.filename}:{e.lineno}: {error_label} {e.msg}", file=sys.stderr)
            status = 1
            continue

        if args.check:
            if formatted != source:
                print(f"{name}: would reformat", file=sys.stderr)
                status = 1
        elif args.in_place:
            if formatted != source:
                path.write_bytes(formatted.encode(encoding))
        else:
            sys.stdout.buffer.write(formatted.encode(encoding))
    sys.stdout.flush()
    return status


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
    elif cmd == "touch":
        for f in cmd_args:
            p = Path(f)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.touch()
        return 0
    elif cmd in ("copy", "copy_if_different"):
        if len(cmd_args) < 2:
            error_label = colored("error:", "red", attrs=["bold"])
            print(f"{error_label} -E {cmd} requires at least 2 arguments", file=sys.stderr)
            return 1
        *sources, dest = cmd_args
        dest_path = Path(dest)
        for src in sources:
            src_path = Path(src)
            if dest_path.is_dir():
                target = dest_path / src_path.name
            else:
                target = dest_path
            if (
                cmd == "copy_if_different"
                and target.exists()
                and target.read_bytes() == src_path.read_bytes()
            ):
                continue
            shutil.copy2(str(src_path), str(target))
        return 0
    else:
        error_label = colored("error:", "red", attrs=["bold"])
        print(f"{error_label} Unknown command -E {cmd}", file=sys.stderr)
        return 1


def _run_ninja(args: argparse.Namespace, target: str | None) -> int:
    """Internal helper to run ninja with configuration if needed."""
    build_dir, status = _configure_for_subcommand(args)
    if status != 0:
        return status

    ninja_file = Path(f"{build_dir}.ninja")

    # Run ninja
    ninja_cmd = ["ninja", "-f", str(ninja_file)]
    if target:
        ninja_cmd.append(target)
    if hasattr(args, "ninja_args"):
        ninja_cmd.extend(args.ninja_args)
    sys.stdout.flush()
    sys.stderr.flush()
    result = subprocess.run(ninja_cmd, check=False)
    return result.returncode


def main() -> int:
    """Main entry point for cja CLI."""
    parser = argparse.ArgumentParser(
        prog="cja",
        description="A CMake reimplementation in Python with Ninja generator",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {_get_version()}",
    )

    subparsers = parser.add_subparsers(dest="command")

    # Configure command (default behavior, also works without subcommand)
    parser.add_argument(
        "-B",
        "--build-dir",
        dest="build_dir",
        help="Relative path for build directory "
        "(default: build, or build-release with --release)",
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
        help="Error on unsupported commands and arguments instead of ignoring them",
    )

    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress warnings and status output",
    )

    parser.add_argument(
        "--release",
        action="store_true",
        help="Configure in release mode (CMAKE_BUILD_TYPE=Release)",
    )

    parser.add_argument(
        "-E",
        nargs="+",
        metavar="command",
        help="CMake-like command mode (e.g., -E make_directory dir...)",
    )

    # Registered only so it appears in --help; the actual value is extracted
    # from sys.argv before argparse runs so that trailing script arguments are
    # not interpreted as subcommands or options.
    parser.add_argument(
        "-P",
        dest="_script",
        metavar="SCRIPT [ARG...]",
        help="Run a CMake script file (script mode)",
    )

    parser.add_argument(
        "--regenerate-during-build",
        action="store_true",
        help=argparse.SUPPRESS,
    )

    parser.add_argument(
        "--verify-globs",
        nargs=2,
        metavar=("MANIFEST", "STAMP"),
        help=argparse.SUPPRESS,
    )

    def add_configure_arguments(subparser: argparse.ArgumentParser, mode: str) -> None:
        # default=SUPPRESS so `cja --release build` keeps the parent flag
        subparser.add_argument(
            "--release",
            action="store_true",
            default=argparse.SUPPRESS,
            help=f"{mode} in release mode (CMAKE_BUILD_TYPE=Release)",
        )
        subparser.add_argument(
            "-B",
            "--build-dir",
            dest="build_dir",
            default=argparse.SUPPRESS,
            help="Relative path for build directory "
            "(default: build, or build-release with --release)",
        )
        # Own dest, merged in main(), so `cja -DA=1 build -DB=2` keeps both
        subparser.add_argument(
            "-D",
            dest="subcommand_defines",
            action="append",
            default=argparse.SUPPRESS,
            metavar="VAR=VALUE",
            help="Set a CMake variable and reconfigure (can be used multiple times)",
        )

    # Build subcommand
    build_parser = subparsers.add_parser(
        "build", help="Configure and build the project"
    )
    add_configure_arguments(build_parser, "Build")

    # Test subcommand
    test_parser = subparsers.add_parser("test", help="Configure and run tests")
    add_configure_arguments(test_parser, "Run tests")
    test_parser.add_argument(
        "--parallel",
        action="store_true",
        help="Run tests in parallel instead of one after another",
    )

    # Run subcommand
    run_parser = subparsers.add_parser(
        "run", help="Configure, build and run the first executable"
    )
    add_configure_arguments(run_parser, "Run")

    # Format subcommand
    format_parser = subparsers.add_parser(
        "format",
        help="Format CMake files",
        description="Format CMake files. Indentation, column limit, blank lines and "
        "line endings are taken from the nearest .clang-format file. The nearest "
        ".cmake-format.json overrides them.",
    )
    format_parser.add_argument(
        "files",
        nargs="*",
        metavar="FILE",
        help="Files to format (default: read from stdin)",
    )
    format_parser.add_argument(
        "-i",
        "--in-place",
        action="store_true",
        help="Edit files in place instead of printing to stdout",
    )
    format_parser.add_argument(
        "--check",
        action="store_true",
        help="Don't write anything; exit with 1 if a file isn't formatted",
    )
    format_parser.add_argument(
        "--assume-filename",
        metavar="PATH",
        help="Path used to find .clang-format and .cmake-format.json when reading "
        "from stdin",
    )
    format_parser.add_argument(
        "--lines",
        action="append",
        type=parse_line_range,
        metavar="START:END",
        help="Only format statements that touch these lines (1-based, inclusive). "
        "Can be given multiple times",
    )

    # Language server subcommand
    lsp_parser = subparsers.add_parser(
        "lsp",
        help="Run a language server for CMake files",
        description="Run a Language Server Protocol server for CMake files on "
        "stdin/stdout, for editors like VS Code.",
    )
    lsp_parser.add_argument(
        "--stdio",
        action="store_true",
        help="Communicate over stdin/stdout (the default and only transport)",
    )
    # Passed by vscode-languageclient; the server exits when stdin is closed.
    lsp_parser.add_argument("--clientProcessId", help=argparse.SUPPRESS)

    # Extract -P SCRIPT [ARGS...] before argparse so trailing positional script
    # arguments are not parsed as subcommands.
    argv = sys.argv[1:]
    script_path: str | None = None
    script_args: list[str] = []
    if "-P" in argv:
        p_idx = argv.index("-P")
        if p_idx + 1 >= len(argv):
            error_label = colored("error:", "red", attrs=["bold"])
            print(f"{error_label} -P requires a script path", file=sys.stderr)
            return 1
        script_path = argv[p_idx + 1]
        script_args = argv[p_idx + 2 :]
        argv = argv[:p_idx]

    args, ninja_args = parser.parse_known_args(argv)
    args.defines += getattr(args, "subcommand_defines", [])
    if hasattr(args, "command") and args.command in ("build", "test", "run"):
        args.ninja_args = ninja_args
    elif args.command == "format" and ninja_args:
        format_parser.error(f"unrecognized arguments: {' '.join(ninja_args)}")
    elif args.command == "lsp" and ninja_args:
        lsp_parser.error(f"unrecognized arguments: {' '.join(ninja_args)}")

    try:
        if args.E:
            return cmd_command_mode(args.E)

        if args.verify_globs:
            manifest, stamp = args.verify_globs
            return verify_globs(Path(manifest), Path(stamp))

        if script_path is not None:
            return cmd_script(
                script_path,
                script_args,
                args.defines,
                args.trace,
                args.strict,
            )

        if args.command == "build":
            return cmd_build(args)
        elif args.command == "test":
            return cmd_test(args)
        elif args.command == "run":
            return cmd_run(args)
        elif args.command == "format":
            return cmd_format(args)
        elif args.command == "lsp":
            return cmd_lsp()
        else:
            # Default: configure only
            return cmd_configure(args)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
