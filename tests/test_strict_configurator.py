"""Tests for arguments that cja ignores, which --strict turns into errors."""

from pathlib import Path

import pytest

from cja.generator import BuildContext, process_commands
from cja.parser import parse


def configure(tmp_path: Path, source: str, strict: bool = False) -> BuildContext:
    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")
    process_commands(parse(source), ctx, strict=strict)
    return ctx


@pytest.mark.parametrize(
    ("source", "unsupported"),
    [
        (
            "add_custom_command(OUTPUT out.txt COMMAND touch out.txt DEPFILE out.d)",
            "add_custom_command(): DEPFILE",
        ),
        (
            "add_custom_command(OUTPUT out.txt APPEND DEPENDS in.txt)",
            "add_custom_command(): APPEND",
        ),
        (
            'add_custom_command(OUTPUT o COMMAND echo "a;b" COMMAND_EXPAND_LISTS)',
            "add_custom_command(): COMMAND_EXPAND_LISTS",
        ),
        (
            (
                "add_library(lib STATIC a.c)\n"
                "add_custom_command(TARGET lib PRE_LINK COMMAND echo hi)"
            ),
            "add_custom_command(): PRE_LINK",
        ),
        (
            (
                "add_executable(app main.c)\n"
                "add_custom_command(TARGET app POST_BUILD COMMAND echo hi"
                " WORKING_DIRECTORY /tmp BYPRODUCTS out.txt)"
            ),
            "add_custom_command(): WORKING_DIRECTORY, BYPRODUCTS",
        ),
        (
            "add_custom_target(gen COMMAND touch out.txt BYPRODUCTS out.txt)",
            "add_custom_target(): BYPRODUCTS",
        ),
        (
            "execute_process(COMMAND echo a OUTPUT_FILE out.txt)",
            "execute_process(): OUTPUT_FILE",
        ),
        (
            "try_compile(RES ${CMAKE_BINARY_DIR} SOURCES a.c LINK_LIBRARIES m)",
            "try_compile(): LINK_LIBRARIES",
        ),
        (
            "try_compile(RES bin . proj)",
            "try_compile(): PROJECT",
        ),
        (
            "fetchcontent_declare(dep URL https://a/x.zip SOURCE_SUBDIR sub)",
            "fetchcontent_declare(): SOURCE_SUBDIR",
        ),
        (
            "fetchcontent_declare(dep GIT_REPOSITORY u GIT_SUBMODULES ext/a)",
            "fetchcontent_declare(): GIT_SUBMODULES",
        ),
        (
            "fetchcontent_declare(dep URL https://a/x.zip https://b/x.zip)",
            "fetchcontent_declare(): URL",
        ),
        (
            "fetchcontent_populate(dep URL https://a/x.zip)",
            "fetchcontent_populate(): URL",
        ),
        ("include(foo.cmake RESULT_VARIABLE found)", "include(): RESULT_VARIABLE"),
        ("add_subdirectory(sub SYSTEM)", "add_subdirectory(): SYSTEM"),
        (
            "add_test(NAME t COMMAND app CONFIGURATIONS Debug)",
            "add_test(): CONFIGURATIONS",
        ),
        ("return(PROPAGATE x)", "return(): PROPAGATE"),
        (
            "set(A 1)\nset(B 2)\nforeach(a b IN ZIP_LISTS A B)\nendforeach()",
            "foreach(): ZIP_LISTS",
        ),
        (
            (
                "configure_package_config_file(in out INSTALL_DESTINATION lib"
                " INSTALL_PREFIX /opt)"
            ),
            "configure_package_config_file(): INSTALL_PREFIX",
        ),
        (
            "flex_target(lexer lexer.l lexer.c OPTIONS --noline)",
            "flex_target(): OPTIONS",
        ),
        ("bison_target(parser parser.y parser.c VERBOSE)", "bison_target(): VERBOSE"),
        (
            "check_c_source_compiles(\"int main(){}\" HAVE_X SRC_EXT m)",
            "check_c_source_compiles(): SRC_EXT",
        ),
        (
            "find_package(Foo CONFIG PATHS /opt/foo NO_CMAKE_PATH)",
            "find_package(): PATHS, NO_CMAKE_PATH",
        ),
    ],
)
def test_unsupported_args_in_strict_mode(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], source: str, unsupported: str
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        configure(tmp_path, source, strict=True)
    assert exc_info.value.code == 1
    assert unsupported in capsys.readouterr().err


def test_supported_args_in_strict_mode(tmp_path: Path) -> None:
    """Arguments without effect on a Ninja build are accepted."""
    ctx = configure(
        tmp_path,
        """\
project(demo VERSION 1.0 DESCRIPTION "A demo" HOMEPAGE_URL https://example.com
        LANGUAGES C)
add_custom_command(OUTPUT out.txt COMMAND touch out.txt COMMENT "Touching"
                   JOB_POOL console)
add_custom_target(gen ALL DEPENDS out.txt JOB_POOL console SOURCES in.txt)
fetchcontent_declare(dep URL https://a/x.zip GIT_SUBMODULES "" QUIET)
add_executable(app main.c)
add_custom_command(TARGET app POST_BUILD COMMAND echo hi BYPRODUCTS "")
""",
        strict=True,
    )
    assert ctx.variables["PROJECT_DESCRIPTION"] == "A demo"
    assert ctx.variables["demo_DESCRIPTION"] == "A demo"
    assert ctx.variables["CMAKE_PROJECT_HOMEPAGE_URL"] == "https://example.com"
    assert ctx.custom_targets[0].commands == []


def test_keyword_values_are_not_commands(tmp_path: Path) -> None:
    ctx = configure(
        tmp_path,
        """\
add_executable(app main.c)
add_custom_command(TARGET app POST_BUILD COMMAND echo hi WORKING_DIRECTORY /tmp)
add_custom_target(gen COMMAND touch out.txt BYPRODUCTS out.txt JOB_POOL console)
add_test(NAME t COMMAND app --flag CONFIGURATIONS Debug)
""",
    )
    assert ctx.get_executable("app").post_build_commands == [["echo", "hi"]]  # type: ignore[union-attr]
    assert ctx.custom_targets[0].commands == [["touch", "out.txt"]]
    assert ctx.tests[0].command == ["app", "--flag"]


def test_foreach_lists_and_items(tmp_path: Path) -> None:
    ctx = configure(
        tmp_path,
        """\
set(L a b)
set(out "")
foreach(x IN LISTS L ITEMS c LISTS)
  list(APPEND out ${x})
endforeach()
""",
    )
    assert ctx.variables["out"] == "a;b;c;LISTS"


def test_fetchcontent_get_properties_output_variables(tmp_path: Path) -> None:
    ctx = configure(
        tmp_path,
        """\
set(dep_SOURCE_DIR /src/dep)
fetchcontent_getproperties(dep SOURCE_DIR src POPULATED done)
""",
    )
    assert ctx.variables["src"] == "/src/dep"
    assert ctx.variables["done"] == "FALSE"
    assert "dep_BINARY_DIR" not in ctx.variables


def test_set_source_files_properties_directory(tmp_path: Path) -> None:
    ctx = configure(
        tmp_path,
        "set_source_files_properties(a.c DIRECTORY sub PROPERTIES"
        " COMPILE_DEFINITIONS FOO)",
        strict=True,
    )
    assert list(ctx.source_file_properties) == [str(tmp_path / "a.c")]
