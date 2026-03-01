"""Built-in find_package() handlers."""

import os
from pathlib import Path
import re
import shutil
import shlex
import subprocess
import sys

from termcolor import colored

from .build_context import BuildContext
from .parser import Command
from .targets import ImportedTarget


def _unique_existing_dirs(candidates: list[Path]) -> list[Path]:
    """Return candidate directories that exist, preserving order."""
    result: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = str(candidate)
        if normalized in seen:
            continue
        seen.add(normalized)
        if candidate.exists() and candidate.is_dir():
            result.append(candidate)
    return result


def _find_first_library(lib_dirs: list[Path], names: list[str]) -> str:
    """Find the first library file matching any provided name."""
    for lib_dir in lib_dirs:
        for name in names:
            candidate = lib_dir / name
            if candidate.exists() and candidate.is_file():
                return str(candidate)
    return ""


def _find_gtest_via_filesystem(gtest_root_hint: str) -> tuple[bool, str, str, str]:
    """Find GTest via filesystem probing when pkg-config is unavailable."""
    root_hints: list[Path] = []
    if gtest_root_hint:
        root_hints.append(Path(gtest_root_hint))
    env_root = os.environ.get("GTEST_ROOT", "")
    if env_root:
        root_hints.append(Path(env_root))

    include_dir_candidates = [
        *(root / "include" for root in root_hints),
        Path("/usr/include"),
        Path("/usr/local/include"),
        Path("/opt/homebrew/include"),
        Path("/opt/local/include"),
    ]

    lib_dir_candidates = [
        *(root / "lib" for root in root_hints),
        *(root / "lib64" for root in root_hints),
        Path("/usr/lib"),
        Path("/usr/lib64"),
        Path("/usr/local/lib"),
        Path("/usr/local/lib64"),
        Path("/lib"),
        Path("/lib64"),
        Path("/opt/homebrew/lib"),
        Path("/opt/local/lib"),
    ]

    for base in (Path("/usr/lib"), Path("/lib")):
        if base.exists() and base.is_dir():
            lib_dir_candidates.extend(path for path in base.iterdir() if path.is_dir())

    include_dirs = _unique_existing_dirs(include_dir_candidates)
    lib_dirs = _unique_existing_dirs(lib_dir_candidates)

    include_dir = ""
    for candidate in include_dirs:
        if (candidate / "gtest/gtest.h").exists():
            include_dir = str(candidate)
            break

    gtest_lib = _find_first_library(
        lib_dirs,
        ["libgtest.so", "libgtest.a", "libgtest.dylib", "gtest.lib"],
    )
    gtest_main_lib = _find_first_library(
        lib_dirs,
        [
            "libgtest_main.so",
            "libgtest_main.a",
            "libgtest_main.dylib",
            "gtest_main.lib",
        ],
    )

    found = bool(include_dir and gtest_lib)
    cflags = f"-I{include_dir}" if include_dir else ""
    return found, cflags, gtest_lib, gtest_main_lib


def handle_builtin_find_package(
    ctx: BuildContext,
    cmd: Command,
    args: list[str],
    package_name: str,
    required: bool,
    quiet: bool,
) -> bool:
    """Handle built-in find_package implementations.

    Returns True if package_name is handled here, False to fall back
    to Find<Package>.cmake module discovery.
    """
    if package_name == "GTest":
        found = False
        gtest_cflags = ""
        gtest_libs = ""
        gtest_main_libs = ""
        try:
            result = subprocess.run(
                ["pkg-config", "--exists", "gtest"],
                capture_output=True,
            )
            if result.returncode == 0:
                found = True
                cflags_result = subprocess.run(
                    ["pkg-config", "--cflags", "gtest"],
                    capture_output=True,
                    text=True,
                )
                libs_result = subprocess.run(
                    ["pkg-config", "--libs", "gtest"],
                    capture_output=True,
                    text=True,
                )
                gtest_cflags = cflags_result.stdout.strip()
                gtest_libs = libs_result.stdout.strip()
                main_result = subprocess.run(
                    ["pkg-config", "--libs", "gtest_main"],
                    capture_output=True,
                    text=True,
                )
                if main_result.returncode == 0:
                    gtest_main_libs = main_result.stdout.strip()
        except FileNotFoundError:
            pass

        if not found:
            found, gtest_cflags, gtest_libs, gtest_main_libs = _find_gtest_via_filesystem(
                ctx.variables.get("GTEST_ROOT", "")
            )

        if found:
            ctx.variables["GTEST_INCLUDE_DIRS"] = gtest_cflags
            ctx.variables["GTEST_LIBRARIES"] = gtest_libs
            if gtest_cflags.startswith("-I"):
                ctx.variables["GTEST_INCLUDE_DIR"] = gtest_cflags[2:]

            gtest_target = ImportedTarget(
                cflags=gtest_cflags,
                libs=gtest_libs,
            )
            ctx.imported_targets["GTest::gtest"] = gtest_target
            ctx.imported_targets["GTest::GTest"] = gtest_target

            if gtest_main_libs:
                ctx.variables["GTEST_MAIN_LIBRARIES"] = gtest_main_libs
                ctx.variables["GTEST_BOTH_LIBRARIES"] = (
                    gtest_libs + " " + gtest_main_libs
                )
                gtest_main_target = ImportedTarget(
                    cflags=gtest_cflags,
                    libs=gtest_main_libs,
                )
                ctx.imported_targets["GTest::gtest_main"] = gtest_main_target
                ctx.imported_targets["GTest::Main"] = gtest_main_target

        if found:
            ctx.variables["GTest_FOUND"] = "TRUE"
            ctx.variables["GTEST_FOUND"] = "TRUE"
            if not quiet:
                print(f"{colored('✓', 'green')} {package_name}")
        else:
            ctx.variables["GTest_FOUND"] = "FALSE"
            ctx.variables["GTEST_FOUND"] = "FALSE"
            if required:
                ctx.print_error("could not find package: GTest", cmd.line)
                raise SystemExit(1)
            if not quiet:
                print(f"{colored('✗', 'red')} {package_name}")
        return True

    if package_name == "Threads":
        ctx.variables["Threads_FOUND"] = "TRUE"
        ctx.variables["CMAKE_THREAD_LIBS_INIT"] = "-pthread"
        ctx.variables["CMAKE_USE_PTHREADS_INIT"] = "TRUE"
        ctx.imported_targets["Threads::Threads"] = ImportedTarget(libs="-pthread")
        if not quiet:
            print(f"{colored('✓', 'green')} {package_name}")
        return True

    if package_name in ("Python", "Python3"):
        components: list[str] = []
        i = 1
        while i < len(args):
            token = args[i]
            if token in ("COMPONENTS", "OPTIONAL_COMPONENTS"):
                i += 1
                while i < len(args) and args[i] not in (
                    "REQUIRED",
                    "QUIET",
                    "COMPONENTS",
                    "OPTIONAL_COMPONENTS",
                    "EXACT",
                    "MODULE",
                    "CONFIG",
                    "NO_MODULE",
                ):
                    components.append(args[i])
                    i += 1
                continue
            i += 1

        requested_components = set(components)
        needs_interpreter = (
            not requested_components or "Interpreter" in requested_components
        )
        interpreter_path = sys.executable if needs_interpreter else ""
        interpreter_found = bool(interpreter_path)
        unsupported_components = requested_components - {"Interpreter"}
        found = interpreter_found and not unsupported_components

        ctx.variables[f"{package_name}_FOUND"] = "TRUE" if found else "FALSE"
        if needs_interpreter:
            ctx.variables[f"{package_name}_Interpreter_FOUND"] = (
                "TRUE" if interpreter_found else "FALSE"
            )
            if interpreter_found:
                ctx.variables[f"{package_name}_EXECUTABLE"] = interpreter_path
                ctx.imported_targets[f"{package_name}::Interpreter"] = ImportedTarget()

        if required and not found:
            ctx.print_error(f"could not find package: {package_name}", cmd.line)
            raise SystemExit(1)
        if not quiet:
            if found:
                print(f"{colored('?', 'green')} {package_name}")
            else:
                print(f"{colored('?', 'red')} {package_name}")
        return True

    if package_name == "PkgConfig":
        pkg_config_executable = shutil.which("pkg-config")
        if pkg_config_executable is None:
            pkg_config_executable = shutil.which("pkgconf")

        if pkg_config_executable is not None:
            found = True
            ctx.variables["PkgConfig_FOUND"] = "TRUE"
            ctx.variables["PKG_CONFIG_EXECUTABLE"] = pkg_config_executable
        else:
            found = False
            ctx.variables["PkgConfig_FOUND"] = "FALSE"

        if required and not found:
            ctx.print_error("could not find package: PkgConfig", cmd.line)
            raise SystemExit(1)

        if not quiet:
            if found:
                print(f"{colored('✓', 'green')} {package_name}")
            else:
                print(f"{colored('✗', 'red')} {package_name}")
        return True

    if package_name == "Fontconfig":
        found = False
        try:
            result = subprocess.run(
                ["pkg-config", "--exists", "fontconfig"],
                capture_output=True,
            )
            if result.returncode == 0:
                found = True
                cflags_result = subprocess.run(
                    ["pkg-config", "--cflags", "fontconfig"],
                    capture_output=True,
                    text=True,
                )
                libs_result = subprocess.run(
                    ["pkg-config", "--libs", "fontconfig"],
                    capture_output=True,
                    text=True,
                )
                version_result = subprocess.run(
                    ["pkg-config", "--modversion", "fontconfig"],
                    capture_output=True,
                    text=True,
                )

                fc_cflags = cflags_result.stdout.strip()
                fc_libs = libs_result.stdout.strip()
                fc_version = version_result.stdout.strip()

                include_dirs = []
                for entry in shlex.split(fc_cflags):
                    if entry.startswith("-I"):
                        include_dirs.append(entry[2:])

                ctx.variables["Fontconfig_FOUND"] = "TRUE"
                ctx.variables["FONTCONFIG_FOUND"] = "TRUE"
                if include_dirs:
                    ctx.variables["Fontconfig_INCLUDE_DIR"] = include_dirs[0]
                    ctx.variables["Fontconfig_INCLUDE_DIRS"] = ";".join(include_dirs)
                ctx.variables["Fontconfig_LIBRARIES"] = fc_libs
                if fc_version:
                    ctx.variables["Fontconfig_VERSION"] = fc_version
                ctx.variables["Fontconfig_COMPILE_OPTIONS"] = fc_cflags

                ctx.imported_targets["Fontconfig::Fontconfig"] = ImportedTarget(
                    cflags=fc_cflags,
                    libs=fc_libs,
                )
        except FileNotFoundError:
            pass

        if found:
            if not quiet:
                print(f"{colored('✓', 'green')} {package_name}")
        else:
            ctx.variables["Fontconfig_FOUND"] = "FALSE"
            ctx.variables["FONTCONFIG_FOUND"] = "FALSE"
            if required:
                ctx.print_error("could not find package: Fontconfig", cmd.line)
                raise SystemExit(1)
            if not quiet:
                print(f"{colored('✗', 'red')} {package_name}")
        return True

    if package_name == "WebP":
        found = False
        pkg_name = None
        try:
            for candidate in ("libwebp", "webp"):
                result = subprocess.run(
                    ["pkg-config", "--exists", candidate],
                    capture_output=True,
                )
                if result.returncode == 0:
                    found = True
                    pkg_name = candidate
                    break
        except FileNotFoundError:
            found = False

        if found and pkg_name:
            cflags_result = subprocess.run(
                ["pkg-config", "--cflags", pkg_name],
                capture_output=True,
                text=True,
            )
            libs_result = subprocess.run(
                ["pkg-config", "--libs", pkg_name],
                capture_output=True,
                text=True,
            )
            version_result = subprocess.run(
                ["pkg-config", "--modversion", pkg_name],
                capture_output=True,
                text=True,
            )

            webp_cflags = cflags_result.stdout.strip()
            webp_libs = libs_result.stdout.strip()
            webp_version = version_result.stdout.strip()

            include_dirs = []
            for entry in shlex.split(webp_cflags):
                if entry.startswith("-I"):
                    include_dirs.append(entry[2:])

            ctx.variables["WebP_FOUND"] = "TRUE"
            ctx.variables["WEBP_FOUND"] = "TRUE"
            ctx.variables["WEBP_INCLUDE_DIRS"] = ";".join(include_dirs)
            if include_dirs:
                ctx.variables["WEBP_INCLUDE_DIR"] = include_dirs[0]
            ctx.variables["WEBP_LIBRARIES"] = webp_libs
            if webp_version:
                ctx.variables["WEBP_VERSION"] = webp_version

            ctx.imported_targets["WebP::webp"] = ImportedTarget(
                cflags=webp_cflags,
                libs=webp_libs,
            )
            if not quiet:
                print(f"{colored('✓', 'green')} {package_name}")
        else:
            ctx.variables["WebP_FOUND"] = "FALSE"
            ctx.variables["WEBP_FOUND"] = "FALSE"
            if required:
                ctx.print_error("could not find package: WebP", cmd.line)
                raise SystemExit(1)
            if not quiet:
                print(f"{colored('✗', 'red')} {package_name}")
        return True

    if package_name == "Boost":
        keywords = {
            "REQUIRED",
            "QUIET",
            "COMPONENTS",
            "OPTIONAL_COMPONENTS",
            "EXACT",
            "MODULE",
            "CONFIG",
            "NO_MODULE",
        }
        required_components: list[str] = []
        optional_components: list[str] = []
        i = 1
        while i < len(args):
            token = args[i]
            if token == "COMPONENTS":
                i += 1
                while i < len(args) and args[i] not in keywords:
                    required_components.append(args[i])
                    i += 1
                continue
            if token == "OPTIONAL_COMPONENTS":
                i += 1
                while i < len(args) and args[i] not in keywords:
                    optional_components.append(args[i])
                    i += 1
                continue
            i += 1

        found = False
        boost_cflags = ""
        boost_libs = ""
        boost_version = ""
        include_dirs: list[str] = []
        missing_required_components: list[str] = []

        pkg_base = None
        try:
            for candidate in ("boost", "boost_headers"):
                result = subprocess.run(
                    ["pkg-config", "--exists", candidate],
                    capture_output=True,
                )
                if result.returncode == 0:
                    pkg_base = candidate
                    break
        except FileNotFoundError:
            pkg_base = None

        if pkg_base:
            cflags_result = subprocess.run(
                ["pkg-config", "--cflags", pkg_base],
                capture_output=True,
                text=True,
            )
            libs_result = subprocess.run(
                ["pkg-config", "--libs", pkg_base],
                capture_output=True,
                text=True,
            )
            version_result = subprocess.run(
                ["pkg-config", "--modversion", pkg_base],
                capture_output=True,
                text=True,
            )
            boost_cflags = cflags_result.stdout.strip()
            boost_libs = libs_result.stdout.strip()
            boost_version = version_result.stdout.strip()
            found = True

        if not found:
            for include_root in (
                "/usr/include",
                "/usr/local/include",
                "/opt/homebrew/include",
            ):
                version_header = Path(include_root) / "boost/version.hpp"
                if version_header.exists():
                    include_dirs = [include_root]
                    boost_cflags = f"-I{include_root}"
                    found = True
                    break

        if boost_cflags:
            for entry in shlex.split(boost_cflags):
                if entry.startswith("-I"):
                    include_dirs.append(entry[2:])

        if found and not boost_version and include_dirs:
            version_header = Path(include_dirs[0]) / "boost/version.hpp"
            if version_header.exists():
                try:
                    header_text = version_header.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    header_text = version_header.read_text(encoding="latin-1")
                version_match = re.search(
                    r'#define\s+BOOST_LIB_VERSION\s+"([^"]+)"',
                    header_text,
                )
                if version_match:
                    boost_version = version_match.group(1).replace("_", ".")

        component_libs: list[str] = []
        for component in required_components + optional_components:
            pkg_component = f"boost_{component.lower()}"
            component_found = False
            component_cflags = ""
            component_link_flags = ""
            try:
                result = subprocess.run(
                    ["pkg-config", "--exists", pkg_component],
                    capture_output=True,
                )
                component_found = result.returncode == 0
            except FileNotFoundError:
                component_found = False

            var_name = f"Boost_{component}_FOUND"
            upper_var_name = f"Boost_{component.upper()}_FOUND"
            if component_found:
                cflags_result = subprocess.run(
                    ["pkg-config", "--cflags", pkg_component],
                    capture_output=True,
                    text=True,
                )
                libs_result = subprocess.run(
                    ["pkg-config", "--libs", pkg_component],
                    capture_output=True,
                    text=True,
                )
                component_cflags = cflags_result.stdout.strip()
                component_link_flags = libs_result.stdout.strip()
                if component_link_flags:
                    component_libs.append(component_link_flags)
                ctx.imported_targets[f"Boost::{component}"] = ImportedTarget(
                    cflags=component_cflags,
                    libs=component_link_flags,
                )
                ctx.variables[var_name] = "TRUE"
                ctx.variables[upper_var_name] = "TRUE"
            else:
                ctx.variables[var_name] = "FALSE"
                ctx.variables[upper_var_name] = "FALSE"
                if component in required_components:
                    missing_required_components.append(component)

        found = found and not missing_required_components
        ctx.variables["Boost_FOUND"] = "TRUE" if found else "FALSE"
        ctx.variables["BOOST_FOUND"] = "TRUE" if found else "FALSE"

        if include_dirs:
            unique_include_dirs = list(dict.fromkeys(include_dirs))
            ctx.variables["Boost_INCLUDE_DIRS"] = ";".join(unique_include_dirs)
            ctx.variables["BOOST_INCLUDE_DIRS"] = ";".join(unique_include_dirs)
            ctx.variables["Boost_INCLUDE_DIR"] = unique_include_dirs[0]
            ctx.variables["BOOST_INCLUDE_DIR"] = unique_include_dirs[0]

        all_libs = " ".join(value for value in [boost_libs, *component_libs] if value)
        if all_libs:
            ctx.variables["Boost_LIBRARIES"] = all_libs
            ctx.variables["BOOST_LIBRARIES"] = all_libs
        if boost_version:
            ctx.variables["Boost_VERSION"] = boost_version
            ctx.variables["BOOST_VERSION"] = boost_version

        if found:
            ctx.imported_targets["Boost::headers"] = ImportedTarget(cflags=boost_cflags)
            ctx.imported_targets["Boost::boost"] = ImportedTarget(cflags=boost_cflags)

        if required and not found:
            ctx.print_error("could not find package: Boost", cmd.line)
            raise SystemExit(1)
        if not quiet:
            if found:
                print(f"{colored('✓', 'green')} {package_name}")
            else:
                print(f"{colored('✗', 'red')} {package_name}")
        return True

    if package_name == "PNG":
        found = False
        pkg_name = None
        png_cflags = ""
        png_libs = ""
        png_version = ""
        include_dirs: list[str] = []

        try:
            for candidate in ("libpng", "png"):
                result = subprocess.run(
                    ["pkg-config", "--exists", candidate],
                    capture_output=True,
                )
                if result.returncode == 0:
                    pkg_name = candidate
                    found = True
                    break
        except FileNotFoundError:
            found = False

        if found and pkg_name:
            cflags_result = subprocess.run(
                ["pkg-config", "--cflags", pkg_name],
                capture_output=True,
                text=True,
            )
            libs_result = subprocess.run(
                ["pkg-config", "--libs", pkg_name],
                capture_output=True,
                text=True,
            )
            version_result = subprocess.run(
                ["pkg-config", "--modversion", pkg_name],
                capture_output=True,
                text=True,
            )

            png_cflags = cflags_result.stdout.strip()
            png_libs = libs_result.stdout.strip()
            png_version = version_result.stdout.strip()

            for entry in shlex.split(png_cflags):
                if entry.startswith("-I"):
                    include_dirs.append(entry[2:])

            unique_include_dirs = list(dict.fromkeys(include_dirs))

            ctx.variables["PNG_FOUND"] = "TRUE"
            ctx.variables["PNG_LIBRARIES"] = png_libs
            ctx.variables["PNG_LIBRARY"] = png_libs
            ctx.variables["PNG_INCLUDE_DIRS"] = ";".join(unique_include_dirs)
            if unique_include_dirs:
                ctx.variables["PNG_INCLUDE_DIR"] = unique_include_dirs[0]
                ctx.variables["PNG_PNG_INCLUDE_DIR"] = unique_include_dirs[0]
            if png_version:
                ctx.variables["PNG_VERSION"] = png_version
                ctx.variables["PNG_VERSION_STRING"] = png_version

            ctx.imported_targets["PNG::PNG"] = ImportedTarget(
                cflags=png_cflags,
                libs=png_libs,
            )
            if not quiet:
                print(f"{colored('✓', 'green')} {package_name}")
        else:
            ctx.variables["PNG_FOUND"] = "FALSE"
            if required:
                ctx.print_error("could not find package: PNG", cmd.line)
                raise SystemExit(1)
            if not quiet:
                print(f"{colored('✗', 'red')} {package_name}")
        return True

    return False
