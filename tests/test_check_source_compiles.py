"""Tests for check_c_source_compiles / check_cxx_source_compiles commands.

The source body is passed as a bracket argument ([==[...]==]), matching how
CMake projects invoke these checks, so semicolons in the code are not treated
as list separators.
"""

import platform
from pathlib import Path

from cja.generator import BuildContext, process_commands
from cja.parser import parse


def test_check_c_source_compiles_success() -> None:
    content = (
        "check_c_source_compiles([==[\n"
        "int main(void) { return 0; }\n"
        "]==] HAVE_OK)\n"
    )
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    process_commands(parse(content), ctx)

    assert ctx.variables["HAVE_OK"] == "1"


def test_check_c_source_compiles_failure() -> None:
    content = (
        "check_c_source_compiles([==[\n"
        "this is not valid C code;\n"
        "]==] HAVE_BAD)\n"
    )
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    process_commands(parse(content), ctx)

    assert ctx.variables["HAVE_BAD"] == ""


def test_check_cxx_source_compiles_success() -> None:
    content = (
        "check_cxx_source_compiles([==[\n"
        "#include <vector>\n"
        "int main() { std::vector<int> v; return 0; }\n"
        "]==] HAVE_CXX)\n"
    )
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    process_commands(parse(content), ctx)

    assert ctx.variables["HAVE_CXX"] == "1"


def test_check_c_source_compiles_fail_regex() -> None:
    # FAIL_REGEX marks a compile that emits a warning as a failure even though
    # compilation itself succeeds.
    content = (
        "check_c_source_compiles([==[\n"
        "int main(void) {\n"
        "#warning intentional\n"
        "  return 0;\n"
        "}\n"
        "]==] HAVE_WARN FAIL_REGEX intentional)\n"
    )
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.variables["CMAKE_REQUIRED_FLAGS"] = "-Wall"
    process_commands(parse(content), ctx)

    assert ctx.variables["HAVE_WARN"] == ""


def test_check_c_source_compiles_honors_required_libraries() -> None:
    # CMAKE_REQUIRED_LIBRARIES participate in the link step.
    if platform.system() == "Windows":
        content = (
            "check_c_source_compiles([==[\n"
            "#include <winsock2.h>\n"
            "int main(void) { WSADATA d; return WSAStartup(MAKEWORD(2, 2), &d); }\n"
            "]==] HAVE_SQRT)\n"
        )
        required_libraries = "ws2_32.lib"
    else:
        content = (
            "check_c_source_compiles([==[\n"
            "#include <math.h>\n"
            "int main(void) { return (int)sqrt(4.0) - 2; }\n"
            "]==] HAVE_SQRT)\n"
        )
        required_libraries = "-lm"
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.variables["CMAKE_REQUIRED_LIBRARIES"] = required_libraries
    process_commands(parse(content), ctx)

    assert ctx.variables["HAVE_SQRT"] == "1"
