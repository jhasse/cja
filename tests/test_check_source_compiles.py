"""Tests for check_c_source_compiles / check_cxx_source_compiles commands.

The source body is passed as a bracket argument ([==[...]==]), matching how
CMake projects invoke these checks, so semicolons in the code are not treated
as list separators.
"""

import platform
import subprocess
from pathlib import Path

from cja import configurator
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
            "]==] HAVE_REQUIRED_LIB)\n"
        )
        required_libraries = "ws2_32.lib"
    else:
        content = (
            "check_c_source_compiles([==[\n"
            "#include <math.h>\n"
            "int main(void) { return (int)sqrt(4.0) - 2; }\n"
            "]==] HAVE_REQUIRED_LIB)\n"
        )
        required_libraries = "-lm"
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.variables["CMAKE_REQUIRED_LIBRARIES"] = required_libraries
    process_commands(parse(content), ctx)

    assert ctx.variables["HAVE_REQUIRED_LIB"] == "1"


def test_check_c_source_compiles_translates_dot_lib_for_gnu_on_windows(
    monkeypatch,
) -> None:
    calls: list[list[str]] = []

    def fake_run(
        cmd: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(configurator.sys, "platform", "win32")
    monkeypatch.setattr(configurator.subprocess, "run", fake_run)

    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.c_compiler = "clang"
    ctx.variables["CMAKE_REQUIRED_LIBRARIES"] = "ws2_32.lib"

    assert configurator._check_source_compiles(
        ctx, "int main(void) { return 0; }", "C", []
    )
    assert calls
    assert "-lws2_32" in calls[0]


def test_check_source_runs() -> None:
    content = (
        "check_c_source_runs([==[\n"
        "int main(void) { return 0; }\n"
        "]==] C_RUNS)\n"
        "check_c_source_runs([==[\n"
        "int main(void) { return 1; }\n"
        "]==] C_FAILS)\n"
        "check_c_source_runs([==[\n"
        "this is not valid C code;\n"
        "]==] C_BAD)\n"
        "check_cxx_source_runs([==[\n"
        "#include <vector>\n"
        "int main() { return std::vector<int>(3).size() == 3 ? 0 : 1; }\n"
        "]==] CXX_RUNS)\n"
    )
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    process_commands(parse(content), ctx)

    assert ctx.variables["C_RUNS"] == "1"
    assert ctx.variables["C_FAILS"] == ""
    assert ctx.variables["C_BAD"] == ""
    assert ctx.variables["CXX_RUNS"] == "1"


def test_check_source_compiles_required_link_options(monkeypatch) -> None:
    """CMAKE_REQUIRED_LINK_OPTIONS are link options with LINKER: and SHELL:."""
    calls: list[list[str]] = []

    def fake_run(
        cmd: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(configurator.subprocess, "run", fake_run)

    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.variables["CMAKE_REQUIRED_LINK_OPTIONS"] = "LINKER:-z,now;SHELL:-a  b;-c d"

    assert configurator._check_source_compiles(
        ctx, "int main(void) { return 0; }", "C", []
    )
    assert calls[0][-4:] == ["-Wl,-z,now", "-a", "b", "-c d"]


def test_check_source_code_is_evaluated_twice() -> None:
    """In CMake these checks are macros, which evaluate escape sequences and
    variable references in the code again."""
    content = (
        'set(RET "return 0;")\n'
        "check_c_source_runs([==[\n"
        'int main(void) { return sizeof("\\\\\\\\") == 2 ? 0 : 1; }\n'
        "]==] ESCAPES)\n"
        "check_c_source_compiles([==[\n"
        "int main(void) { ${RET} }\n"
        "]==] VARIABLE)\n"
        "check_cxx_source_compiles([==[\n"
        "int main() { \\${RET} }\n"
        "]==] ESCAPED_VARIABLE)\n"
    )
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    process_commands(parse(content), ctx)

    assert ctx.variables["ESCAPES"] == "1"
    assert ctx.variables["VARIABLE"] == "1"
    assert ctx.variables["ESCAPED_VARIABLE"] == ""


def test_check_objc_source_compiles(monkeypatch) -> None:
    """Objective-C(++) checks compile .m/.mm files with the C/C++ compiler."""
    calls: list[list[str]] = []

    def fake_run(
        cmd: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(configurator.subprocess, "run", fake_run)

    content = (
        "include(CheckOBJCSourceCompiles)\n"
        "include(CheckOBJCXXSourceCompiles)\n"
        "check_objc_source_compiles([==[\n"
        "#import <Foundation/Foundation.h>\n"
        "int main(void) { return 0; }\n"
        "]==] HAVE_OBJC)\n"
        "check_objcxx_source_compiles([==[\n"
        "#import <Foundation/Foundation.h>\n"
        "int main() { return 0; }\n"
        "]==] HAVE_OBJCXX)\n"
    )
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.c_compiler = "my-cc"
    ctx.cxx_compiler = "my-c++"
    process_commands(parse(content), ctx, strict=True)

    assert ctx.variables["HAVE_OBJC"] == "1"
    assert ctx.variables["HAVE_OBJCXX"] == "1"
    assert [(cmd[0], Path(cmd[-1]).suffix) for cmd in calls] == [
        ("my-cc", ".m"),
        ("my-c++", ".mm"),
    ]


def test_check_source_compiles_required_imported_target(monkeypatch) -> None:
    """An imported target in CMAKE_REQUIRED_LIBRARIES stands for its include
    directories and libraries, including those of the targets it links."""
    calls: list[list[str]] = []

    def fake_run(
        cmd: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(configurator.subprocess, "run", fake_run)

    content = (
        "add_library(Dep::dep UNKNOWN IMPORTED)\n"
        "set_target_properties(Dep::dep PROPERTIES\n"
        "  IMPORTED_LOCATION /opt/dep/lib/libdep.a)\n"
        "add_library(Foo::foo UNKNOWN IMPORTED)\n"
        "set_target_properties(Foo::foo PROPERTIES\n"
        "  IMPORTED_LOCATION /opt/foo/lib/libfoo.a\n"
        "  INTERFACE_INCLUDE_DIRECTORIES /opt/foo/include\n"
        "  INTERFACE_LINK_LIBRARIES Dep::dep)\n"
        "set(CMAKE_REQUIRED_LIBRARIES Foo::foo m)\n"
        "check_c_source_compiles([==[\n"
        "int main(void) { return 0; }\n"
        "]==] HAVE_FOO)\n"
    )
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    process_commands(parse(content), ctx, strict=True)

    assert ctx.variables["HAVE_FOO"] == "1"
    assert "-I/opt/foo/include" in calls[0]
    assert calls[0][-3:] == ["/opt/foo/lib/libfoo.a", "/opt/dep/lib/libdep.a", "-lm"]
