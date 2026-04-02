"""Ninja build file generator."""

import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import cast

from .utils import is_truthy, make_relative, strip_generator_expressions, to_posix_path
from .build_context import (
    BuildContext,
)
from termcolor import colored

from .ninja_syntax import Writer
from .parser import Command
from .configurator import process_commands


def _infer_compiler_id(compiler: str) -> str:
    """Infer CMake-style compiler ID from a compiler command."""
    parts = shlex.split(compiler) if compiler else []
    if not parts:
        return "Unknown"
    tool = parts[0]
    if Path(tool).name.lower() in ("ccache", "sccache") and len(parts) > 1:
        tool = parts[1]
    base = Path(tool).name.lower()

    if base in ("clang", "clang++", "clang-cl") or "clang" in base:
        return "Clang"
    if base in ("gcc", "g++") or base.startswith("gcc-") or base.startswith("g++-"):
        return "GNU"
    if base in ("cl", "cl.exe"):
        return "MSVC"
    if base in ("icx", "icpx", "dpcpp"):
        return "IntelLLVM"
    if base in ("icc", "icpc"):
        return "Intel"

    # Fallback for generic compiler driver names like cc/c++.
    try:
        out = subprocess.check_output(
            parts + ["--version"],
            stderr=subprocess.STDOUT,
            text=True,
        ).lower()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "Unknown"

    if "clang" in out:
        return "Clang"
    if "gcc" in out or "gnu" in out:
        return "GNU"
    if "microsoft" in out or "msvc" in out:
        return "MSVC"
    if "intel" in out and ("llvm" in out or "oneapi" in out):
        return "IntelLLVM"
    if "intel" in out:
        return "Intel"

    return "Unknown"


def _infer_compiler_version(compiler: str) -> str:
    """Infer compiler version (major.minor.patch) from a compiler command."""
    parts = shlex.split(compiler) if compiler else []
    if not parts:
        return ""
    tool = parts[0]
    if Path(tool).name.lower() in ("ccache", "sccache") and len(parts) > 1:
        tool = parts[1]
    cmd = [tool] + parts[1:] + ["--version"]
    try:
        out = subprocess.check_output(
            cmd,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""

    # Extract first semver-like token.
    match = re.search(r"\b(\d+)\.(\d+)(?:\.(\d+))?\b", out)
    if not match:
        return ""
    major = match.group(1)
    minor = match.group(2)
    patch = match.group(3) or "0"
    return f"{major}.{minor}.{patch}"


def _detect_host_system_processor() -> str:
    """Detect host CPU architecture string for CMAKE_HOST_SYSTEM_PROCESSOR."""
    machine = platform.machine().strip()
    if machine:
        return machine
    processor = platform.processor().strip()
    if processor:
        return processor
    return "unknown"


def is_header(filename: str) -> bool:
    """Check if a filename refers to a header file."""
    header_extensions = (".h", ".hpp", ".hxx", ".hh", ".inc", ".inl")
    return filename.lower().endswith(header_extensions)


def is_rc(filename: str) -> bool:
    """Check if a filename refers to a Windows resource script."""
    return filename.lower().endswith(".rc")


def is_manifest(filename: str) -> bool:
    """Check if a filename refers to a Windows manifest file."""
    return filename.lower().endswith(".manifest")


def is_compilable_source(filename: str) -> bool:
    """Check if a filename looks like a compilable C/C++ source file."""
    source_extensions = (
        ".c",
        ".cc",
        ".cpp",
        ".cxx",
        ".c++",
        ".C",
        ".m",
        ".mm",
        ".M",
        ".s",
        ".S",
    )
    return filename.endswith(source_extensions)


def _rc_manifest_deps(ctx: BuildContext, rc_path: str) -> list[str]:
    """Extract manifest file paths referenced by RT_MANIFEST in .rc file."""
    deps: list[str] = []
    abs_path = ctx.source_dir / rc_path
    if not abs_path.exists():
        return deps
    try:
        content = abs_path.read_text(encoding="utf-8", errors="replace")
        # Match RT_MANIFEST "filename" or RT_MANIFEST 'filename'
        for match in re.finditer(r"RT_MANIFEST\s+[\"']([^\"']+)[\"']", content, re.I):
            manifest_ref = match.group(1)
            rc_dir = Path(rc_path).parent
            if rc_dir and rc_dir != Path("."):
                manifest_path = (rc_dir / manifest_ref).as_posix()
            else:
                manifest_path = manifest_ref
            deps.append(manifest_path)
    except (OSError, UnicodeDecodeError):
        pass
    return deps


def compile_feature_to_flag(feature: str) -> str | None:
    """Translate a CMake compile feature to a compiler flag."""
    # Map cxx_std_XX features to -std=c++XX flags
    if feature.startswith("cxx_std_"):
        std_version = feature[8:]  # Extract "11", "14", "17", "20", "23", etc.
        return f"-std=c++{std_version}"
    # Map c_std_XX features to -std=cXX flags
    if feature.startswith("c_std_"):
        std_version = feature[6:]
        return f"-std=c{std_version}"
    # Other features could be added here
    return None


def _is_windows_clangxx(cxx: str) -> bool:
    if platform.system() != "Windows":
        return False
    parts = shlex.split(cxx) if cxx else []
    tool = parts[0] if parts else cxx
    name = Path(tool).name.lower()
    return name in ("clang++", "clang++.exe")


def _normalize_windows_clang_cxx_std(flag: str, enabled: bool) -> str:
    if not enabled:
        return flag
    return re.sub(r"(?<!\S)-std=c\+\+11(?=\s|$)", "-std=c++14", flag)


def _std_level(lang: str, token: str) -> int:
    known = {
        "cxx": {
            "98": 98,
            "03": 103,
            "11": 111,
            "14": 114,
            "17": 117,
            "20": 120,
            "23": 123,
            "26": 126,
            "2a": 123,
            "2b": 126,
        },
        "c": {
            "90": 90,
            "99": 99,
            "11": 111,
            "17": 117,
            "23": 123,
        },
    }
    token_lower = token.lower()
    if token_lower in known.get(lang, {}):
        return known[lang][token_lower]
    digits = "".join(ch for ch in token_lower if ch.isdigit())
    if digits:
        try:
            return int(digits)
        except ValueError:
            return -1
    return -1


def _keep_highest_std_flag(flags: list[str], lang: str) -> list[str]:
    """Keep only the highest -std=... flag for the given language."""
    if lang == "cxx":
        std_re = re.compile(r"^-std=(?:gnu\+\+|c\+\+)(\S+)$")
    else:
        std_re = re.compile(r"^-std=(?:gnu|c)(?!\+\+)(\S+)$")

    best_idx = -1
    best_rank = -1
    filtered: list[str] = []

    for flag in flags:
        match = std_re.match(flag)
        if match:
            rank = _std_level(lang, match.group(1))
            if rank >= best_rank:
                best_rank = rank
                best_idx = len(filtered)
            filtered.append(flag)
        else:
            filtered.append(flag)

    if best_idx == -1:
        return filtered

    kept: list[str] = []
    std_seen = 0
    for idx, flag in enumerate(filtered):
        if std_re.match(flag):
            if idx == best_idx:
                kept.append(flag)
            std_seen += 1
            continue
        kept.append(flag)
    return kept


def _format_compile_definition_flag(definition: str) -> str:
    """Format a compile definition as a compiler -D flag."""
    normalized = strip_generator_expressions(definition)
    escaped = re.sub(r'(?<!\\)"', r'\\"', normalized)
    return f"-D{escaped}"


def framework_link_flags(lib_path: str) -> list[str] | None:
    """Return macOS framework link flags if lib_path refers to a framework."""
    if platform.system() != "Darwin":
        return None
    if ".framework" not in lib_path:
        return None
    idx = lib_path.find(".framework")
    framework_path = lib_path[: idx + len(".framework")]
    framework_name = Path(framework_path).stem
    framework_dir = str(Path(framework_path).parent)
    flags = []
    if framework_dir:
        flags.append(f"-F{framework_dir}")
    flags.extend(["-framework", framework_name])
    return flags


def _ninja_flag_path(path: str, source_dir: Path) -> str:
    """Format paths for Ninja flags and relativize paths under source_dir."""
    path = make_relative(path, source_dir)
    if len(path) >= 3 and path[1] == ":" and path[2] == "\\":
        head, sep, tail = path.rpartition("\\")
        if sep:
            return f"{head}/{tail}"
    return path


def handle_add_subdirectory(
    ctx: BuildContext,
    cmd: Command,
    args: list[str],
    trace: bool,
    strict: bool,
) -> None:
    """Handle add_subdirectory() command."""
    if args:
        sub_dir_name = args[0]
        sub_source_dir = ctx.current_source_dir / sub_dir_name
        if not sub_source_dir.exists():
            # Try relative to the root source dir as well?
            # CMake usually expects it relative to current source dir.
            pass

        sub_cmakelists = sub_source_dir / "CMakeLists.txt"
        if sub_cmakelists.exists():
            from .parser import parse_file

            ctx.record_cmake_file(sub_cmakelists)
            sub_commands = parse_file(sub_cmakelists)

            # Save current state
            saved_current_source_dir = ctx.current_source_dir
            saved_current_list_file = ctx.current_list_file
            saved_parent_directory = ctx.parent_directory
            saved_vars = ctx.variables.copy()
            saved_parent_scope_vars = ctx.parent_scope_vars
            ctx.parent_scope_vars = {}

            # Update current_source_dir for the subdirectory
            ctx.current_source_dir = sub_source_dir
            ctx.current_list_file = sub_cmakelists
            ctx.parent_directory = str(saved_current_source_dir)
            ctx.variables["CMAKE_CURRENT_SOURCE_DIR"] = str(sub_source_dir)
            ctx.variables["CMAKE_CURRENT_LIST_FILE"] = str(sub_cmakelists)
            ctx.variables["CMAKE_CURRENT_LIST_DIR"] = str(sub_cmakelists.parent)
            # For now, CMAKE_CURRENT_BINARY_DIR is the same as CMAKE_BINARY_DIR
            # since we don't support separate binary dirs for subdirectories yet
            ctx.variables["CMAKE_CURRENT_BINARY_DIR"] = str(ctx.build_dir)

            try:
                process_commands(sub_commands, ctx, trace, strict)
            finally:
                # Apply PARENT_SCOPE changes
                parent_scope_updates = ctx.parent_scope_vars
                ctx.parent_scope_vars = saved_parent_scope_vars

                # Restore state
                ctx.current_source_dir = saved_current_source_dir
                ctx.current_list_file = saved_current_list_file
                ctx.parent_directory = saved_parent_directory
                ctx.variables = saved_vars
                for var, val in parent_scope_updates.items():
                    if val is None:
                        ctx.variables.pop(var, None)
                    else:
                        ctx.variables[var] = val
                ctx.variables["CMAKE_CURRENT_SOURCE_DIR"] = str(
                    saved_current_source_dir
                )
                ctx.variables["CMAKE_CURRENT_LIST_FILE"] = str(saved_current_list_file)
                ctx.variables["CMAKE_CURRENT_LIST_DIR"] = str(
                    saved_current_list_file.parent
                )
                ctx.variables["CMAKE_CURRENT_BINARY_DIR"] = str(ctx.build_dir)
        elif strict:
            ctx.print_error(
                f'add_subdirectory given source "{sub_dir_name}" which does not exist.',
                cmd.line,
            )
            sys.exit(1)


def generate_ninja(
    ctx: BuildContext, output_path: Path, builddir: str, strict: bool = False
) -> None:
    """Generate ninja build file."""
    # Use compilers from context (set via CMAKE_C_COMPILER/CMAKE_CXX_COMPILER or defaults)
    cc = ctx.c_compiler
    cxx = ctx.cxx_compiler
    windows_clangxx = _is_windows_clangxx(cxx)

    # Detect extensions
    exe_ext = ".exe" if platform.system() == "Windows" else ""
    lib_ext = ".lib" if platform.system() == "Windows" else ".a"
    shared_lib_ext = (
        ".dll"
        if platform.system() == "Windows"
        else ".dylib"
        if platform.system() == "Darwin"
        else ".so"
    )
    module_lib_ext = ".dll" if platform.system() == "Windows" else ".so"

    # Determine build type flags
    build_type = ctx.variables.get("CMAKE_BUILD_TYPE", "Debug").upper()
    build_type_flags = ""
    if build_type == "DEBUG":
        build_type_flags = "-g -O0"
    elif build_type == "RELEASE":
        build_type_flags = "-O3 -DNDEBUG"
    elif build_type == "RELWITHDEBINFO":
        build_type_flags = "-O2 -g -DNDEBUG"
    elif build_type == "MINSIZEREL":
        build_type_flags = "-Os -DNDEBUG"

    # Interprocedural optimization flags (LTO), including config-specific override.
    ipo_enabled = False
    ipo_config_var = f"CMAKE_INTERPROCEDURAL_OPTIMIZATION_{build_type}"
    if ipo_config_var in ctx.variables:
        ipo_enabled = is_truthy(ctx.variables[ipo_config_var])
    elif "CMAKE_INTERPROCEDURAL_OPTIMIZATION" in ctx.variables:
        ipo_enabled = is_truthy(ctx.variables["CMAKE_INTERPROCEDURAL_OPTIMIZATION"])
    ipo_flags = ""
    if ipo_enabled:
        c_id = ctx.variables.get("CMAKE_C_COMPILER_ID", "")
        cxx_id = ctx.variables.get("CMAKE_CXX_COMPILER_ID", "")
        # GCC supports parallel LTO partitioning with -flto=auto.
        if c_id == "GNU" or cxx_id == "GNU":
            ipo_flags = "-flto=auto"
        else:
            ipo_flags = "-flto"

    with open(output_path, "w") as f:
        n = Writer(f)

        output_origins: dict[str, tuple[Path | None, int]] = {}
        warning_label = colored("warning:", "magenta", attrs=["bold"])
        error_label = colored("error:", "red", attrs=["bold"])

        def format_origin(path: Path | None, line: int) -> str:
            if path is None:
                return "<unknown>"
            rel = make_relative(str(path), ctx.source_dir)
            return f"{rel}:{line}" if line > 0 else rel

        def register_output(
            output: str, origin_file: Path | None, origin_line: int
        ) -> None:
            if output in output_origins:
                first_file, first_line = output_origins[output]
                loc = format_origin(origin_file, origin_line)
                first_loc = format_origin(first_file, first_line)
                label = error_label if strict else warning_label
                print(
                    f"{loc}: {label} multiple rules generate {output}; first defined at {first_loc}",
                    file=sys.stderr,
                )
                if strict:
                    raise SystemExit(1)
            else:
                output_origins[output] = (origin_file, origin_line)

        n.comment("Generated by cja")
        n.newline()

        # Variables
        n.variable("builddir", builddir)
        n.variable("cc", cc)
        n.variable("cxx", cxx)
        default_ar = "llvm-ar" if platform.system() == "Windows" else "ar"
        n.variable("ar", default_ar)
        n.newline()

        cmake_deps: list[str] = []
        for cmake_path in sorted(ctx.cmake_files, key=lambda p: str(p)):
            if cmake_path.name == "CMakeLists.txt" or cmake_path.suffix == ".cmake":
                cmake_deps.append(make_relative(str(cmake_path), ctx.source_dir))

        if cmake_deps:

            def format_define(name: str, value: str) -> str:
                if value == "":
                    return f"-D{name}="
                return f"-D{name}={value}"

            cja_cmd = ["cja"]
            absolute_cja_cmd = shutil.which(cja_cmd[0])
            if absolute_cja_cmd is None:
                # If cja is not in PATH, use the current Python executable to run it as a module
                cja_cmd = [sys.executable, "-m", "cja"]
            elif os.getenv("VIRTUAL_ENV") is not None:
                # The venv might not be active when the user runs ninja (e.g. the IDE runs it)
                cja_cmd = [absolute_cja_cmd]
            if platform.system() == "Windows":
                cja_cmd[0] = to_posix_path(cja_cmd[0])
            reconfigure_cmd_parts = cja_cmd + ["--regenerate-during-build"]
            if builddir != "build":
                reconfigure_cmd_parts += ["-B", "$builddir"]
            for var_name in sorted(ctx.cli_variables):
                reconfigure_cmd_parts.append(
                    format_define(var_name, ctx.cli_variables[var_name])
                )

            def quote_part(part: str) -> str:
                if part == "$builddir":
                    return part
                return shlex.quote(part)

            reconfigure_cmd = " ".join(
                quote_part(part) for part in reconfigure_cmd_parts
            )

            n.rule(
                "reconfigure",
                command=reconfigure_cmd,
                generator=True,
                pool="console",
                description="\x1b[35mRe-running cja\x1b[0m",
            )
            n.newline()

            output_name = make_relative(str(output_path), ctx.source_dir)
            n.build(output_name, "reconfigure", cmake_deps)
            n.newline()

        # Compile rules - include build type flags
        base_cflags = f"-fdiagnostics-color {build_type_flags} {ipo_flags}".strip()
        c_flags = ctx.variables.get("CMAKE_C_FLAGS", "")
        c_flags_config = ctx.variables.get(f"CMAKE_C_FLAGS_{build_type}", "")
        if c_flags_config:
            c_flags = f"{c_flags} {c_flags_config}".strip()
        cxx_flags = ctx.variables.get("CMAKE_CXX_FLAGS", "")
        cxx_flags_config = ctx.variables.get(f"CMAKE_CXX_FLAGS_{build_type}", "")
        if cxx_flags_config:
            cxx_flags = f"{cxx_flags} {cxx_flags_config}".strip()
        cxx_flags = _normalize_windows_clang_cxx_std(cxx_flags, windows_clangxx)
        linker_flags_parts = [
            ctx.variables.get("CMAKE_EXE_LINKER_FLAGS", ""),
            ctx.variables.get("CMAKE_LINKER_FLAGS", ""),
            ipo_flags,
        ]
        linker_flags = " ".join(p for p in linker_flags_parts if p).strip()
        n.variable("ldflags", linker_flags)

        n.rule(
            "cc",
            command=f"$cc -MMD -MF $out.d {base_cflags} {c_flags} $cflags -c $in -o $out".replace(
                "  ", " "
            ).strip(),
            depfile="$out.d",
            description="\x1b[32mCompiling $in\x1b[0m",
        )
        n.newline()

        n.rule(
            "cxx",
            command=f"$cxx -MMD -MF $out.d {base_cflags} {cxx_flags} $cflags -c $in -o $out".replace(
                "  ", " "
            ).strip(),
            depfile="$out.d",
            description="\x1b[32mCompiling $in\x1b[0m",
        )
        n.newline()

        # Archive rule for static libraries
        # We must delete the old archive before creating a new one because
        # ar rcs only adds/replaces members but never removes them.
        if platform.system() == "Windows":
            # On Windows, shell metacharacters (&, |, <, >, ^) cause ninja to
            # wrap the command with cmd.exe, which corrupts pipe handles
            # ("ReadFile: The handle is invalid"). Use a Python one-liner to
            # avoid all shell metacharacters so ninja uses CreateProcess directly.
            ar_command = (
                'python -c "import os,subprocess,sys;'
                "o=sys.argv[1];os.path.exists(o) and os.remove(o);"
                'sys.exit(subprocess.call(sys.argv[2:]))"'
                " $out $ar rcs $out $in"
            )
        else:
            ar_command = "rm -f $out && $ar rcs $out $in"
        n.rule(
            "ar",
            command=ar_command,
            description="\x1b[32;1mArchiving $out\x1b[0m",
            # TODO: CMake shows "Linking C static library" or "Linking C++ static library" instead.
            # "static" is redundant info here, but we should also distinguish C vs C++.
        )
        n.newline()

        # Link rules
        n.rule(
            "link",
            command="$cc -fdiagnostics-color $in -o $out $ldflags $libs",
            description="\x1b[32;1mLinking C executable $out\x1b[0m",
        )
        n.newline()

        n.rule(
            "link_cxx",
            command="$cxx -fdiagnostics-color $in -o $out $ldflags $libs",
            description="\x1b[32;1mLinking C++ executable $out\x1b[0m",
        )
        n.newline()

        shared_link_flag = "-dynamiclib" if platform.system() == "Darwin" else "-shared"
        n.rule(
            "solink",
            command=f"$cc -fdiagnostics-color {shared_link_flag} $in -o $out $ldflags $libs",
            description="\x1b[32;1mLinking C shared library $out\x1b[0m",
        )
        n.newline()

        n.rule(
            "solink_cxx",
            command=f"$cxx -fdiagnostics-color {shared_link_flag} $in -o $out $ldflags $libs",
            description="\x1b[32;1mLinking C++ shared library $out\x1b[0m",
        )
        n.newline()

        # Windows resource compilation (llvm-rc, clang-only, no mt.exe)
        if platform.system() == "Windows":
            default_rc = "llvm-rc"
            n.variable("rc", default_rc)
            n.rule(
                "rc",
                command="$rc /FO $out $in",
                description="\x1b[32mCompiling resources $in\x1b[0m",
            )
            n.newline()

        # Emit clang-tidy rule if any target uses CXX_CLANG_TIDY or C_CLANG_TIDY
        has_clang_tidy = any(
            "CXX_CLANG_TIDY" in t.properties or "C_CLANG_TIDY" in t.properties
            for t in (*ctx.libraries, *ctx.executables)
        )
        if has_clang_tidy:
            src_prefix = str(ctx.source_dir.resolve()) + "/"
            n.rule(
                "clang_tidy",
                command=f"$clang_tidy_cmd $in -- $cflags 2>/dev/null >$out.log; rv=$$?; sed 's|{src_prefix}||g' $out.log; rm -f $out.log; [ $$rv -eq 0 ] && touch $out || exit $$rv",
                description="\x1b[35mAnalyzing $in\x1b[0m",
            )
            n.newline()

        # Track library and executable outputs for linking and testing
        lib_outputs: dict[str, str] = {}
        exe_outputs: dict[str, str] = {}
        object_lib_objects: dict[str, list[str]] = {}
        custom_command_outputs: set[str] = set()

        # Generate custom command rule
        n.rule(
            "custom_command",
            command="$cmd",
        )
        n.newline()

        shell_operators = (
            ">",
            ">>",
            "2>",
            "2>&1",
            "<",
            "|",
            "&",
            "&&",
            "||",
            ";",
        )

        # Generate custom commands
        for custom_cmd in ctx.custom_commands:
            outputs = []
            for o in custom_cmd.outputs:
                if not Path(o).is_absolute():
                    prefixed_o = f"$builddir/{o}"
                    outputs.append(prefixed_o)
                    custom_command_outputs.add(o)
                else:
                    outputs.append(o)

            # Process multiple commands
            cmd_parts: list[str] = []
            for command in custom_cmd.commands:
                if custom_cmd.verbatim:
                    parts = []
                    for arg in command:
                        if arg in shell_operators:
                            parts.append(str(arg))
                        else:
                            parts.append(shlex.quote(str(arg)))
                    cmd_parts.append(" ".join(parts))
                else:
                    cmd_parts.append(" ".join(str(c) for c in command))

            cmd_str = " && ".join(cmd_parts)

            depends = [
                f"$builddir/{d}"
                if d in custom_command_outputs and not Path(d).is_absolute()
                else d
                for d in custom_cmd.depends
            ]
            main_dep = custom_cmd.main_dependency
            if main_dep:
                if (
                    main_dep in custom_command_outputs
                    and not Path(main_dep).is_absolute()
                ):
                    main_dep = f"$builddir/{main_dep}"
                depends.insert(0, main_dep)

            working_dir = custom_cmd.working_directory
            if working_dir:
                cmd_str = f"cd {to_posix_path(working_dir)} && {cmd_str}"

            n.build(
                outputs,
                "custom_command",
                depends,
                variables={"cmd": cmd_str},
            )
            for out in outputs:
                register_output(out, custom_cmd.defined_file, custom_cmd.defined_line)
            n.newline()

        # Generate custom targets (phony targets)
        custom_target_all: list[str] = []
        for ct in ctx.custom_targets:
            ct_depends = [
                f"$builddir/{d}"
                if d in custom_command_outputs and not Path(d).is_absolute()
                else d
                for d in ct.depends
            ]

            if ct.commands:
                # Custom target with commands: use custom_command rule
                ct_cmd_parts: list[str] = []
                for command in ct.commands:
                    if ct.verbatim:
                        parts = []
                        for arg in command:
                            if arg in shell_operators:
                                parts.append(str(arg))
                            else:
                                parts.append(shlex.quote(str(arg)))
                        ct_cmd_parts.append(" ".join(parts))
                    else:
                        ct_cmd_parts.append(" ".join(str(c) for c in command))

                ct_cmd_str = " && ".join(ct_cmd_parts)
                if ct.working_directory:
                    ct_cmd_str = f"cd {ct.working_directory} && {ct_cmd_str}"

                # Use a stamp file so ninja can track when the target last ran
                stamp = f"$builddir/{ct.name}.stamp"
                n.build(
                    [stamp],
                    "custom_command",
                    ct_depends,
                    variables={"cmd": f"{ct_cmd_str} && touch {stamp}"},
                )
                n.build([ct.name], "phony", [stamp])
            else:
                # No commands: purely a phony dependency aggregator
                n.build([ct.name], "phony", ct_depends)

            if ct.all:
                custom_target_all.append(ct.name)
            n.newline()

        # Helper to expand link libraries recursively
        def expand_link_libraries(
            initial: list[str], follow_private_of_static: bool
        ) -> list[str]:
            expanded: list[str] = []
            seen: set[str] = set()
            queue = list(initial)
            while queue:
                name = queue.pop(0)
                if name in seen:
                    continue
                seen.add(name)
                expanded.append(name)
                lib = ctx.get_library(name)
                if lib:
                    # For static libraries, even private dependencies propagate to the consumer
                    # but only when we are expanding for linking, not for compile flags
                    if follow_private_of_static and lib.lib_type == "STATIC":
                        deps = list(
                            dict.fromkeys(
                                lib.link_libraries + lib.public_link_libraries
                            )
                        )
                    else:
                        deps = lib.public_link_libraries
                    for dep in deps:
                        if dep not in seen:
                            queue.append(dep)
            return expanded

        def _collect_directory_property_chain(
            target_dir: Path, prop_name: str
        ) -> list[str]:
            try:
                current = target_dir.resolve()
            except FileNotFoundError:
                current = target_dir
            try:
                root = ctx.source_dir.resolve()
            except FileNotFoundError:
                root = ctx.source_dir

            chain: list[str] = []
            path = current
            while True:
                chain.append(str(path))
                if path == root or path.parent == path:
                    break
                path = path.parent

            values: list[str] = []
            for d in reversed(chain):
                props = ctx.directory_properties.get(d)
                if not props:
                    continue
                raw = props.get(prop_name, "")
                if raw:
                    values.extend([p for p in raw.split(";") if p])
            return values

        # Generate build statements for libraries
        for lib in ctx.libraries:
            if lib.is_alias:
                continue
            if lib.lib_type == "INTERFACE":
                # Interface libraries are usage requirements only.
                continue
            objects: list[str] = []
            uses_cxx = False

            # Collect compile flags from global options, compile definitions, compile features, include dirs, and linked libraries
            target_dir = (
                lib.defined_file.parent
                if lib.defined_file is not None
                else ctx.source_dir
            )
            lib_compile_flags: list[str] = _collect_directory_property_chain(
                target_dir, "COMPILE_OPTIONS"
            )
            for definition in _collect_directory_property_chain(
                target_dir, "COMPILE_DEFINITIONS"
            ):
                lib_compile_flags.append(_format_compile_definition_flag(definition))
            for definition in lib.compile_definitions:
                lib_compile_flags.append(_format_compile_definition_flag(definition))
            for option in lib.compile_options:
                opt = strip_generator_expressions(option)
                if opt:
                    lib_compile_flags.append(opt)
            for feature in lib.compile_features:
                flag = compile_feature_to_flag(feature)
                if flag:
                    lib_compile_flags.append(flag)
            for inc_dir in lib.include_directories:
                inc = strip_generator_expressions(inc_dir)
                lib_compile_flags.append(f"-I{_ninja_flag_path(inc, ctx.source_dir)}")

            # Propagate flags from dependencies
            # For compilation, we only follow public dependencies
            expanded_lib_link_libraries = expand_link_libraries(
                lib.link_libraries, follow_private_of_static=False
            )
            for dep_name in expanded_lib_link_libraries:
                dep_lib = ctx.get_library(dep_name)
                if dep_lib:
                    for feature in dep_lib.public_compile_features:
                        flag = compile_feature_to_flag(feature)
                        if flag and flag not in lib_compile_flags:
                            lib_compile_flags.append(flag)
                    for inc_dir in dep_lib.public_include_directories:
                        inc = strip_generator_expressions(inc_dir)
                        inc_flag = f"-I{_ninja_flag_path(inc, ctx.source_dir)}"
                        if inc_flag not in lib_compile_flags:
                            lib_compile_flags.append(inc_flag)
                    for definition in dep_lib.public_compile_definitions:
                        def_flag = _format_compile_definition_flag(definition)
                        if def_flag not in lib_compile_flags:
                            lib_compile_flags.append(def_flag)
                    for option in dep_lib.public_compile_options:
                        opt = strip_generator_expressions(option)
                        if opt and opt not in lib_compile_flags:
                            lib_compile_flags.append(opt)
                if dep_name in ctx.imported_targets:
                    imported = ctx.imported_targets[dep_name]
                    if imported.cflags:
                        lib_compile_flags.append(imported.cflags)

            # Filter out headers, .rc, and .manifest files from compileable sources
            compileable_sources: list[str] = [
                s
                for s in lib.sources
                if is_compilable_source(s)
                and not is_header(s)
                and not is_rc(s)
                and not is_manifest(s)
            ]
            # CMake tolerates duplicate source entries on a target. Keep first occurrence.
            compileable_sources = list(dict.fromkeys(compileable_sources))

            cxx_clang_tidy = lib.properties.get("CXX_CLANG_TIDY")
            c_clang_tidy = lib.properties.get("C_CLANG_TIDY")

            for source in compileable_sources:
                actual_source = source
                if source in custom_command_outputs:
                    actual_source = f"$builddir/{source}"

                source_rel = Path(source)
                obj_subdir = source_rel.parent.as_posix()
                obj_basename = f"{lib.name}_{source_rel.stem}.o"
                if obj_subdir and obj_subdir != ".":
                    obj_name = f"$builddir/{obj_subdir}/{obj_basename}"
                else:
                    obj_name = f"$builddir/{obj_basename}"
                register_output(obj_name, lib.defined_file, lib.defined_line)
                objects.append(obj_name)

                # Determine if C or C++
                is_cxx = source.endswith((".cpp", ".cxx", ".cc", ".C", ".mm", ".MM"))
                if is_cxx:
                    rule = "cxx"
                    uses_cxx = True
                else:
                    rule = "cc"

                # Check for source file properties
                abs_source = str(ctx.source_dir / source)
                file_props = ctx.source_file_properties.get(abs_source)

                source_compile_flags = list(lib_compile_flags)
                source_depends = []

                if file_props:
                    for definition in file_props.compile_definitions:
                        source_compile_flags.append(
                            _format_compile_definition_flag(definition)
                        )
                    for inc_dir in file_props.include_directories:
                        source_compile_flags.append(
                            f"-I{_ninja_flag_path(inc_dir, ctx.source_dir)}"
                        )
                    for d in file_props.object_depends:
                        if d in custom_command_outputs:
                            source_depends.append(f"$builddir/{d}")
                        else:
                            source_depends.append(d)

                if rule == "cc":
                    source_compile_flags = [
                        flag
                        for flag in source_compile_flags
                        if not flag.startswith("-std=c++")
                    ]
                    source_compile_flags = _keep_highest_std_flag(
                        source_compile_flags, "c"
                    )
                else:
                    source_compile_flags = [
                        flag
                        for flag in source_compile_flags
                        if not (
                            flag.startswith("-std=c")
                            and not flag.startswith("-std=c++")
                        )
                    ]
                    source_compile_flags = [
                        _normalize_windows_clang_cxx_std(flag, windows_clangxx)
                        for flag in source_compile_flags
                    ]
                    source_compile_flags = _keep_highest_std_flag(
                        source_compile_flags, "cxx"
                    )

                source_vars: dict[str, str | list[str] | None] | None = None
                if source_compile_flags:
                    source_vars = cast(
                        dict[str, str | list[str] | None],
                        {"cflags": " ".join(source_compile_flags)},
                    )

                # Generate clang-tidy validation node if applicable
                tidy_cmd = cxx_clang_tidy if is_cxx else c_clang_tidy
                tidy_stamp: str | None = None
                if tidy_cmd:
                    tidy_args = tidy_cmd.replace(";", " ")
                    tidy_stamp = f"{obj_name}.tidy"
                    tidy_vars: dict[str, str | list[str] | None] = {
                        "clang_tidy_cmd": tidy_args,
                    }
                    if source_compile_flags:
                        tidy_vars["cflags"] = " ".join(source_compile_flags)
                    n.build(
                        tidy_stamp,
                        "clang_tidy",
                        actual_source,
                        variables=cast(dict[str, str | list[str] | None], tidy_vars),
                    )

                n.build(
                    obj_name,
                    rule,
                    actual_source,
                    implicit=source_depends,
                    variables=source_vars,
                    validation=tidy_stamp,
                )

            if lib.lib_type == "OBJECT":
                # Object libraries don't produce an archive, just track objects
                object_lib_objects[lib.name] = objects
                n.newline()
            elif lib.lib_type == "STATIC":
                # Create static library archive
                lib_name = f"$builddir/lib{lib.name}{lib_ext}"
                register_output(lib_name, lib.defined_file, lib.defined_line)
                n.build(lib_name, "ar", objects)
                n.newline()
                lib_outputs[lib.name] = lib_name
            elif lib.lib_type in ("SHARED", "MODULE"):
                # Create shared/module library output so aliases can resolve to real artifacts.
                if lib.lib_type == "SHARED":
                    lib_name = f"$builddir/lib{lib.name}{shared_lib_ext}"
                else:
                    lib_name = f"$builddir/lib{lib.name}{module_lib_ext}"

                register_output(lib_name, lib.defined_file, lib.defined_line)
                link_rule = "solink_cxx" if uses_cxx else "solink"
                n.build(lib_name, link_rule, objects)
                n.newline()
                lib_outputs[lib.name] = lib_name

        # Second pass for aliases to map them to original outputs
        for lib in ctx.libraries:
            if lib.is_alias and lib.alias_for in lib_outputs:
                lib_outputs[lib.name] = lib_outputs[lib.alias_for]

        # Collect default targets (libraries that produce real output files)
        default_targets: list[str] = list(lib_outputs.values())
        default_targets.extend(custom_target_all)

        # Generate build statements for executables

        for exe in ctx.executables:
            objects: list[str] = []
            uses_cxx = False
            # For compile flags, we only follow public dependencies
            expanded_compile_libraries = expand_link_libraries(
                exe.link_libraries, follow_private_of_static=False
            )
            # For linking, static libraries propagate their private dependencies
            expanded_link_libraries = expand_link_libraries(
                exe.link_libraries, follow_private_of_static=True
            )

            # Collect cflags from global options, compile definitions, compile features, include dirs, linked libraries, and imported targets
            target_dir = (
                exe.defined_file.parent
                if exe.defined_file is not None
                else ctx.source_dir
            )
            compile_flags: list[str] = _collect_directory_property_chain(
                target_dir, "COMPILE_OPTIONS"
            )
            for definition in _collect_directory_property_chain(
                target_dir, "COMPILE_DEFINITIONS"
            ):
                compile_flags.append(_format_compile_definition_flag(definition))
            for definition in exe.compile_definitions:
                compile_flags.append(_format_compile_definition_flag(definition))
            for option in exe.compile_options:
                opt = strip_generator_expressions(option)
                if opt:
                    compile_flags.append(opt)
            for feature in exe.compile_features:
                flag = compile_feature_to_flag(feature)
                if flag:
                    compile_flags.append(flag)
            for inc_dir in exe.include_directories:
                inc = strip_generator_expressions(inc_dir)
                compile_flags.append(f"-I{_ninja_flag_path(inc, ctx.source_dir)}")

            for lib_name in expanded_compile_libraries:
                # Check for public compile features from linked libraries
                linked_lib = ctx.get_library(lib_name)

                if linked_lib:
                    for feature in linked_lib.public_compile_features:
                        flag = compile_feature_to_flag(feature)
                        if flag and flag not in compile_flags:
                            compile_flags.append(flag)
                    # Check for public include directories from linked libraries
                    for inc_dir in linked_lib.public_include_directories:
                        inc = strip_generator_expressions(inc_dir)
                        inc_flag = f"-I{_ninja_flag_path(inc, ctx.source_dir)}"
                        if inc_flag not in compile_flags:
                            compile_flags.append(inc_flag)
                    # Check for public compile definitions from linked libraries
                    for definition in linked_lib.public_compile_definitions:
                        def_flag = _format_compile_definition_flag(definition)
                        if def_flag not in compile_flags:
                            compile_flags.append(def_flag)
                    for option in linked_lib.public_compile_options:
                        opt = strip_generator_expressions(option)
                        if opt and opt not in compile_flags:
                            compile_flags.append(opt)
                # Check for cflags from imported targets
                if lib_name in ctx.imported_targets:
                    imported = ctx.imported_targets[lib_name]
                    if imported.cflags:
                        compile_flags.append(imported.cflags)
                    elif lib_name.startswith("GTest::"):
                        gtest_includes = ctx.variables.get("GTEST_INCLUDE_DIRS", "")
                        if gtest_includes:
                            for inc_dir in gtest_includes.split(";"):
                                if inc_dir:
                                    compile_flags.append(
                                        f"-I{_ninja_flag_path(inc_dir, ctx.source_dir)}"
                                    )

            # Filter out headers, .rc, and .manifest files from compileable sources
            compileable_sources: list[str] = [
                s
                for s in exe.sources
                if is_compilable_source(s)
                and not is_header(s)
                and not is_rc(s)
                and not is_manifest(s)
            ]
            # CMake tolerates duplicate source entries on a target. Keep first occurrence.
            compileable_sources = list(dict.fromkeys(compileable_sources))
            rc_sources: list[str] = [s for s in exe.sources if is_rc(s)]
            manifest_sources: list[str] = [s for s in exe.sources if is_manifest(s)]

            cxx_clang_tidy = exe.properties.get("CXX_CLANG_TIDY")
            c_clang_tidy = exe.properties.get("C_CLANG_TIDY")

            for source in compileable_sources:
                actual_source = source
                if source in custom_command_outputs:
                    actual_source = f"$builddir/{source}"

                source_rel = Path(source)
                obj_subdir = source_rel.parent.as_posix()
                obj_basename = f"{exe.name}_{source_rel.stem}.o"
                if obj_subdir and obj_subdir != ".":
                    obj_name = f"$builddir/{obj_subdir}/{obj_basename}"
                else:
                    obj_name = f"$builddir/{obj_basename}"
                register_output(obj_name, exe.defined_file, exe.defined_line)
                objects.append(obj_name)

                # Determine if C or C++
                is_cxx = source.endswith((".cpp", ".cxx", ".cc", ".C", ".mm", ".MM"))
                if is_cxx:
                    rule = "cxx"
                    uses_cxx = True
                else:
                    rule = "cc"

                # Check for source file properties
                abs_source = str(ctx.source_dir / source)
                file_props = ctx.source_file_properties.get(abs_source)

                source_compile_flags = list(compile_flags)
                source_depends = []

                if file_props:
                    for definition in file_props.compile_definitions:
                        source_compile_flags.append(
                            _format_compile_definition_flag(definition)
                        )
                    for inc_dir in file_props.include_directories:
                        source_compile_flags.append(
                            f"-I{_ninja_flag_path(inc_dir, ctx.source_dir)}"
                        )
                    for d in file_props.object_depends:
                        if d in custom_command_outputs:
                            source_depends.append(f"$builddir/{d}")
                        else:
                            source_depends.append(d)

                if rule == "cc":
                    source_compile_flags = [
                        flag
                        for flag in source_compile_flags
                        if not flag.startswith("-std=c++")
                    ]
                    source_compile_flags = _keep_highest_std_flag(
                        source_compile_flags, "c"
                    )
                else:
                    source_compile_flags = [
                        flag
                        for flag in source_compile_flags
                        if not (
                            flag.startswith("-std=c")
                            and not flag.startswith("-std=c++")
                        )
                    ]
                    source_compile_flags = [
                        _normalize_windows_clang_cxx_std(flag, windows_clangxx)
                        for flag in source_compile_flags
                    ]
                    source_compile_flags = _keep_highest_std_flag(
                        source_compile_flags, "cxx"
                    )

                source_vars: dict[str, str | list[str] | None] | None = None
                if source_compile_flags:
                    source_vars = cast(
                        dict[str, str | list[str] | None],
                        {"cflags": " ".join(source_compile_flags)},
                    )

                # Generate clang-tidy validation node if applicable
                tidy_cmd = cxx_clang_tidy if is_cxx else c_clang_tidy
                tidy_stamp: str | None = None
                if tidy_cmd:
                    tidy_args = tidy_cmd.replace(";", " ")
                    tidy_stamp = f"{obj_name}.tidy"
                    tidy_vars: dict[str, str | list[str] | None] = {
                        "clang_tidy_cmd": tidy_args,
                    }
                    if source_compile_flags:
                        tidy_vars["cflags"] = " ".join(source_compile_flags)
                    n.build(
                        tidy_stamp,
                        "clang_tidy",
                        actual_source,
                        variables=cast(dict[str, str | list[str] | None], tidy_vars),
                    )

                n.build(
                    obj_name,
                    rule,
                    actual_source,
                    implicit=source_depends,
                    variables=source_vars,
                    validation=tidy_stamp,
                )

            # Add linked libraries to inputs
            link_inputs = objects.copy()
            link_flags: list[str] = []

            # Propagate link directories from dependencies
            for lib_name in expanded_link_libraries:
                linked_lib = ctx.get_library(lib_name)
                if linked_lib:
                    for link_dir in linked_lib.public_link_directories:
                        if link_dir not in exe.link_directories:
                            exe.link_directories.append(link_dir)

            for link_dir in exe.link_directories:
                link_flags.append(f"-L{_ninja_flag_path(link_dir, ctx.source_dir)}")
            for lib_name in expanded_link_libraries:
                linked_lib = ctx.get_library(lib_name)
                if linked_lib and linked_lib.lib_type == "INTERFACE":
                    # Interface libraries contribute usage requirements only.
                    continue
                if lib_name in object_lib_objects:
                    # Object library: add object files directly
                    link_inputs.extend(object_lib_objects[lib_name])
                elif lib_name in lib_outputs:
                    # Static library: add archive
                    link_inputs.append(lib_outputs[lib_name])
                elif lib_name in ctx.imported_targets:
                    # Imported target (e.g., Threads::Threads): add link flags
                    imported = ctx.imported_targets[lib_name]
                    if imported.libs:
                        link_flags.append(imported.libs)
                    if lib_name == "GTest::gtest_main":
                        main_libs = ctx.variables.get("GTEST_MAIN_LIBRARIES", "")
                        gtest_libs = ctx.variables.get("GTEST_LIBRARIES", "")
                        if main_libs:
                            link_flags.append(main_libs.replace(";", " "))
                        if gtest_libs:
                            link_flags.append(gtest_libs.replace(";", " "))
                    elif lib_name == "GTest::gtest":
                        gtest_libs = ctx.variables.get("GTEST_LIBRARIES", "")
                        if gtest_libs:
                            link_flags.append(gtest_libs.replace(";", " "))
                else:
                    # Generic library name or path
                    if (
                        lib_name.startswith("-")
                        or lib_name.startswith("$")
                        or "/" in lib_name
                        or lib_name.endswith(
                            (".a", ".so", ".dylib", ".lib", ".dll", ".o", ".obj")
                        )
                        or ".so." in lib_name
                    ):
                        framework_flags = framework_link_flags(lib_name)
                        if framework_flags:
                            link_flags.extend(framework_flags)
                        else:
                            link_flags.append(lib_name)
                    else:
                        link_flags.append(f"-l{lib_name}")

            # On Windows, compile .rc files to .res and add to link inputs
            if rc_sources and platform.system() == "Windows":
                for rc_source in rc_sources:
                    actual_rc = rc_source
                    if rc_source in custom_command_outputs:
                        actual_rc = f"$builddir/{rc_source}"
                    rc_rel = Path(rc_source)
                    res_name = f"$builddir/{exe.name}_{rc_rel.stem}.res"
                    register_output(res_name, exe.defined_file, exe.defined_line)
                    rc_deps = _rc_manifest_deps(ctx, rc_source)
                    n.build(
                        res_name,
                        "rc",
                        actual_rc,
                        implicit=rc_deps if rc_deps else None,
                    )
                    link_inputs.append(res_name)

            # On Windows, .manifest as source: auto-generate .rc and use llvm-rc workflow
            if manifest_sources and platform.system() == "Windows":
                for manifest in manifest_sources:
                    manifest_rel = Path(manifest)
                    rc_stem = f"{exe.name}_{manifest_rel.stem}"
                    rc_name = f"{rc_stem}.rc"
                    res_name = f"$builddir/{rc_stem}.res"
                    rc_path = ctx.build_dir / rc_name
                    # Path from build dir to manifest (llvm-rc resolves relative to .rc)
                    rc_manifest_path = Path("..") / manifest
                    rc_content = (
                        "#ifndef RT_MANIFEST\n#define RT_MANIFEST 24\n#endif\n"
                        f'1 RT_MANIFEST "{rc_manifest_path.as_posix()}"\n'
                    )
                    rc_path.parent.mkdir(parents=True, exist_ok=True)
                    rc_path.write_text(rc_content, encoding="utf-8")
                    register_output(res_name, exe.defined_file, exe.defined_line)
                    n.build(
                        res_name,
                        "rc",
                        f"$builddir/{rc_name}",
                        implicit=manifest,
                    )
                    link_inputs.append(res_name)

            # Link
            exe_name = f"$builddir/{exe.name}{exe_ext}"
            register_output(exe_name, exe.defined_file, exe.defined_line)
            link_rule = "link_cxx" if uses_cxx else "link"
            variables: dict[str, str | list[str] | None] = {}
            if link_flags:
                variables["libs"] = " ".join(link_flags)
            n.build(
                exe_name,
                link_rule,
                link_inputs,
                variables=variables if variables else None,
            )
            n.newline()

            exe_outputs[exe.name] = exe_name
            default_targets.append(exe_name)

        # Generate test runner
        if ctx.tests:
            n.rule(
                "test_run",
                command="$cmd",
                description="\x1b[1;34mRunning $name\x1b[0m",
                pool="console",
            )
            n.newline()

            test_targets: list[str] = []
            for test in ctx.tests:
                # Resolve target in command: if COMMAND specifies an
                # executable target created by add_executable(), it will
                # automatically be replaced by the location of the executable
                # created at build time.
                cmd = list(test.command)
                depends = []

                # Check if WORKING_DIRECTORY is the build dir (the default)
                is_builddir = not test.working_directory
                if test.working_directory:
                    try:
                        build_dir = ctx.build_dir.resolve()
                        wd_path = Path(test.working_directory).resolve()
                        is_builddir = wd_path == build_dir
                    except (OSError, RuntimeError, ValueError):
                        pass

                if cmd[0] in exe_outputs:
                    target_exe = exe_outputs[cmd[0]]
                    if is_builddir and target_exe.startswith("$builddir/"):
                        cmd[0] = "./" + target_exe[len("$builddir/") :]
                    else:
                        cmd[0] = target_exe
                    depends.append(target_exe)

                cmd_str = " ".join(cmd)

                # Determine cd prefix for the working directory
                if is_builddir:
                    cmd_str = f"cd $builddir && {cmd_str}"
                elif test.working_directory:
                    try:
                        source_dir = ctx.source_dir.resolve()
                        wd_path = Path(test.working_directory).resolve()
                        if wd_path == source_dir:
                            # Source dir itself: no cd needed
                            pass
                        elif wd_path.is_relative_to(source_dir):
                            rel = wd_path.relative_to(source_dir)
                            cmd_str = f"cd {to_posix_path(rel)} && {cmd_str}"
                        else:
                            cmd_str = f"cd {to_posix_path(test.working_directory)} && {cmd_str}"
                    except (OSError, RuntimeError, ValueError):
                        cmd_str = (
                            f"cd {to_posix_path(test.working_directory)} && {cmd_str}"
                        )

                test_target = f"test_{test.name}"
                register_output(test_target, None, 0)
                test_variables: dict[str, str | list[str] | None] = {
                    "cmd": cmd_str,
                    "name": test.name,
                }
                n.build(
                    test_target,
                    "test_run",
                    implicit=depends,
                    variables=test_variables,
                )
                test_targets.append(test_target)

            n.newline()
            n.build("test", "phony", test_targets)
            n.newline()

        # Generate install runner
        if ctx.install_targets:
            n.rule(
                "install_file",
                command="mkdir -p $out_dir && cp $in $out",
                description="Installing $out",
            )
            n.newline()

            install_files: list[str] = []
            for install in ctx.install_targets:
                destination = install.destination
                try:
                    source_dir = ctx.source_dir.resolve()
                    destination_path = Path(destination).resolve()
                    if destination_path.is_relative_to(source_dir):
                        destination = str(destination_path.relative_to(source_dir))
                except (OSError, RuntimeError, ValueError):
                    pass

                for target in install.targets:
                    src = None
                    if target in exe_outputs:
                        src = exe_outputs[target]
                    elif target in lib_outputs:
                        src = lib_outputs[target]

                    if src:
                        dest = (
                            f"{destination}/{Path(src).name.replace('$builddir/', '')}"
                        )
                        register_output(dest, None, 0)
                        n.build(
                            dest,
                            "install_file",
                            src,
                            variables={"out_dir": destination},
                        )
                        install_files.append(dest)

            n.newline()
            n.build("install", "phony", install_files)
            n.newline()

        # Write cja.json with run executable info
        if ctx.executables:
            run_target = ctx.executables[0].name

            root_dir = str(ctx.source_dir)
            if root_dir in ctx.directory_properties:
                startup_proj = ctx.directory_properties[root_dir].get(
                    "VS_STARTUP_PROJECT"
                )
                if startup_proj:
                    run_target = startup_proj

            if run_target in exe_outputs:
                exe_path = exe_outputs[run_target].replace("$builddir", builddir)
                cja_json = {"run_executable": exe_path}
                ctx.build_dir.mkdir(parents=True, exist_ok=True)
                cja_json_path = ctx.build_dir / "cja.json"
                cja_json_path.write_text(json.dumps(cja_json) + "\n")

        # "all" phony target (matches CMake behavior)
        if default_targets:
            n.build("all", "phony", default_targets)
            n.newline()
            n.default(["all"])


def configure(
    source_dir: Path,
    build_dir: str,
    variables: dict[str, str] | None = None,
    trace: bool = False,
    strict: bool = False,
    regenerate_during_build: bool = False,
    quiet: bool = False,
) -> BuildContext:
    """Configure a CMake project and generate build.ninja.

    Args:
        source_dir: Path to source directory containing CMakeLists.txt
        build_dir: Relative path for build directory (e.g., "build")
        variables: Optional dict of variables to set (e.g., from -D flags)
        trace: If True, print each command as it's processed
        strict: If True, error on unsupported commands instead of ignoring them
        regenerate_during_build: If True, we were triggered during build
        quiet: If True, suppress warnings and status output
    """
    source_dir = source_dir.resolve()
    cmake_file = source_dir / "CMakeLists.txt"
    if not cmake_file.exists():
        raise FileNotFoundError(f"CMakeLists.txt not found in {source_dir}")

    from .parser import parse_file

    ctx = BuildContext(
        source_dir=source_dir,
        build_dir=source_dir / build_dir,
    )
    ctx.quiet = quiet
    ctx.record_cmake_file(cmake_file)

    commands = parse_file(cmake_file)

    # Create build directory early (needed for variables that reference it)
    ctx.build_dir.mkdir(parents=True, exist_ok=True)

    # Set variables from command line (-D flags) first
    # These are cache variables that won't be overridden by set()
    if variables:
        ctx.variables.update(variables)
        ctx.cache_variables.update(variables.keys())
        ctx.cli_variables = dict(variables)

    # Set up standard CMake variables
    ctx.variables["CMAKE_SOURCE_DIR"] = str(ctx.source_dir)
    ctx.variables["CMAKE_BINARY_DIR"] = str(ctx.build_dir)
    ctx.variables["CMAKE_CURRENT_SOURCE_DIR"] = str(ctx.source_dir)
    ctx.variables["CMAKE_CURRENT_BINARY_DIR"] = str(ctx.build_dir)
    ctx.variables["CMAKE_CURRENT_LIST_FILE"] = str(ctx.current_list_file)
    ctx.variables["CMAKE_CURRENT_LIST_DIR"] = str(ctx.current_list_file.parent)
    ctx.variables["CMAKE_MODULE_PATH"] = ""
    ctx.variables.setdefault("CMAKE_BUILD_TYPE", "Debug")
    ctx.variables["CMAKE_FIND_PACKAGE_REDIRECTS_DIR"] = str(
        ctx.build_dir / "CMakeFiles" / "pkgRedirects"
    )
    ctx.variables.setdefault(
        "CMAKE_INSTALL_PREFIX", to_posix_path(str(ctx.build_dir / "install"))
    )
    ctx.variables["CMAKE_HOST_SYSTEM_PROCESSOR"] = _detect_host_system_processor()
    host_system = platform.system()
    ctx.variables["CMAKE_HOST_WIN32"] = "TRUE" if host_system == "Windows" else "FALSE"

    if host_system == "Darwin":
        ctx.variables["CMAKE_SYSTEM_NAME"] = "Darwin"
        ctx.variables["UNIX"] = "TRUE"
        ctx.variables["APPLE"] = "TRUE"
    elif host_system == "Windows":
        ctx.variables["CMAKE_SYSTEM_NAME"] = "Windows"
        ctx.variables["WIN32"] = "TRUE"
    else:
        ctx.variables["CMAKE_SYSTEM_NAME"] = "Linux"
        ctx.variables["UNIX"] = "TRUE"

    # Set up compilers from variables if provided
    if "CMAKE_C_COMPILER" in ctx.variables:
        ctx.c_compiler = ctx.variables["CMAKE_C_COMPILER"]
    if "CMAKE_CXX_COMPILER" in ctx.variables:
        ctx.cxx_compiler = ctx.variables["CMAKE_CXX_COMPILER"]
    ctx.variables["CMAKE_C_COMPILER"] = ctx.c_compiler
    ctx.variables["CMAKE_CXX_COMPILER"] = ctx.cxx_compiler
    ctx.variables["CMAKE_C_COMPILER_ID"] = _infer_compiler_id(ctx.c_compiler)
    ctx.variables["CMAKE_CXX_COMPILER_ID"] = _infer_compiler_id(ctx.cxx_compiler)
    ctx.variables["CMAKE_C_COMPILER_VERSION"] = _infer_compiler_version(ctx.c_compiler)
    ctx.variables["CMAKE_CXX_COMPILER_VERSION"] = _infer_compiler_version(
        ctx.cxx_compiler
    )

    process_commands(commands, ctx, trace, strict)

    # Generate ninja manifest in source directory (named after build dir)
    output_path = source_dir / f"{build_dir}.ninja"
    manifest_existed = output_path.exists()
    generate_ninja(ctx, output_path, build_dir, strict=strict)

    # Generate compilation database
    try:
        compdb = subprocess.check_output(
            ["ninja", "-f", str(output_path), "-t", "compdb"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
        (ctx.build_dir / "compile_commands.json").write_text(compdb)
    except (subprocess.CalledProcessError, FileNotFoundError):
        # Ignore errors if ninja is not found or fails
        pass

    # Don't cause unnecessary rebuilds when we the users runs cja explicitly:
    if not regenerate_during_build and manifest_existed:
        restat_cmd = [
            "ninja",
            "-t",
            "restat",
            f"--builddir={build_dir}",
            f"{build_dir}.ninja",
        ]
        try:
            subprocess.check_output(restat_cmd, stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError as e:
            if not quiet:
                print(
                    f"{colored('warning:', 'magenta', attrs=['bold'])} `{' '.join(restat_cmd)}` failed with exit code {e.returncode}:\n{e.output.decode().rstrip()}"
                )

    if not quiet:
        print(f"{colored('Configured', 'green', attrs=['bold'])} {build_dir}.ninja")
    return ctx
