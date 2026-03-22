"""Built-in find_package() handlers."""

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

        lib_search_dirs = _unique_existing_dirs(
            [
                Path("/usr/lib"),
                Path("/usr/lib64"),
                Path("/usr/local/lib"),
                Path("/opt/homebrew/lib"),
            ]
        )
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
            else:
                # Fallback: search for the library file directly
                lib_name = f"libboost_{component.lower()}.so"
                for lib_dir in lib_search_dirs:
                    if (lib_dir / lib_name).exists():
                        component_found = True
                        component_cflags = boost_cflags
                        component_link_flags = f"-lboost_{component.lower()}"
                        break

            var_name = f"Boost_{component}_FOUND"
            upper_var_name = f"Boost_{component.upper()}_FOUND"
            if component_found:
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

    if package_name == "Qt5":
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

        all_components = required_components + optional_components
        if not all_components:
            all_components = ["Core"]

        found = False
        missing_required: list[str] = []

        for component in all_components:
            pkg_name = f"Qt5{component}"
            component_found = False
            try:
                result = subprocess.run(
                    ["pkg-config", "--exists", pkg_name],
                    capture_output=True,
                )
                component_found = result.returncode == 0
            except FileNotFoundError:
                component_found = False

            if component_found:
                found = True
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

                comp_cflags = cflags_result.stdout.strip()
                comp_libs = libs_result.stdout.strip()
                comp_version = version_result.stdout.strip()

                ctx.variables[f"Qt5{component}_FOUND"] = "TRUE"
                if comp_version:
                    ctx.variables[f"Qt5{component}_VERSION"] = comp_version
                    ctx.variables["Qt5_VERSION"] = comp_version

                ctx.imported_targets[f"Qt5::{component}"] = ImportedTarget(
                    cflags=comp_cflags,
                    libs=comp_libs,
                )
            else:
                ctx.variables[f"Qt5{component}_FOUND"] = "FALSE"
                if component in required_components:
                    missing_required.append(component)

        found = found and not missing_required
        ctx.variables["Qt5_FOUND"] = "TRUE" if found else "FALSE"

        if found:
            if not quiet:
                print(f"{colored('✓', 'green')} {package_name}")
        else:
            ctx.variables["Qt5_FOUND"] = "FALSE"
            if required:
                ctx.print_error("could not find package: Qt5", cmd.line)
                raise SystemExit(1)
            if not quiet:
                print(f"{colored('✗', 'red')} {package_name}")
        return True

    return False
