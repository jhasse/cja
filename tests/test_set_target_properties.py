"""Tests for set_target_properties command."""

import platform
from pathlib import Path

from cja.generator import configure


def _assert_win32_gui_flag(ninja_content: str, *, msvc: bool) -> None:
    if msvc:
        assert "/SUBSYSTEM:WINDOWS" in ninja_content
        assert "/SUBSYSTEM:CONSOLE" not in ninja_content
        assert "-mwindows" not in ninja_content
    else:
        assert "-mwindows" in ninja_content


def _assert_win32_console_flag(ninja_content: str) -> None:
    assert "/SUBSYSTEM:CONSOLE" in ninja_content
    assert "/SUBSYSTEM:WINDOWS" not in ninja_content
    assert "-mwindows" not in ninja_content


def _assert_no_subsystem_flag(ninja_content: str) -> None:
    assert "-mwindows" not in ninja_content
    assert "/SUBSYSTEM:WINDOWS" not in ninja_content
    assert "/SUBSYSTEM:CONSOLE" not in ninja_content


def test_set_target_properties_interface_include_directories(tmp_path: Path) -> None:
    """Test set_target_properties(PROPERTIES INTERFACE_INCLUDE_DIRECTORIES ...)."""
    source_dir = tmp_path / "src"
    source_dir.mkdir()

    (source_dir / "CMakeLists.txt").write_text(
        "project(test_props)\n"
        "add_library(mylib STATIC mylib.c)\n"
        'set_target_properties(mylib PROPERTIES INTERFACE_INCLUDE_DIRECTORIES "${CMAKE_CURRENT_SOURCE_DIR}/include")\n'
        "add_executable(main main.c)\n"
        "target_link_libraries(main mylib)"
    )
    (source_dir / "mylib.c").write_text("int mylib_func() { return 0; }")
    (source_dir / "main.c").write_text("int main() { return 0; }")
    (source_dir / "include").mkdir()

    ctx = configure(source_dir, "build")

    lib = ctx.get_library("mylib")
    assert lib is not None
    assert any(str(source_dir / "include") in d for d in lib.public_include_directories)

    # Check that executable 'main' has the include directory from 'mylib'
    exe = ctx.get_executable("main")
    assert exe is not None
    # In cja, public_include_directories from linked libs should be added to exe.include_directories
    # during processing or ninja generation.

    # Let's verify build.ninja content
    ninja_file = source_dir / "build.ninja"
    content = ninja_file.read_text()
    assert "-Iinclude" in content


def test_set_target_properties_win32_executable_config_genex(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """WIN32_EXECUTABLE $<CONFIG:Release> should select WINDOWS vs CONSOLE by config."""
    monkeypatch.setattr("cja.generator.platform.system", lambda: "Windows")

    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "CMakeLists.txt").write_text(
        "project(test_win32)\n"
        "add_executable(foo main.c)\n"
        "set_target_properties(foo PROPERTIES WIN32_EXECUTABLE $<CONFIG:Release>)\n"
    )
    (source_dir / "main.c").write_text("int main() { return 0; }")

    configure(
        source_dir,
        "build",
        variables={"CMAKE_BUILD_TYPE": "Release", "MSVC_VERSION": "1930"},
    )
    _assert_win32_gui_flag((source_dir / "build.ninja").read_text(), msvc=True)

    exe = configure(
        source_dir,
        "build-debug",
        variables={"CMAKE_BUILD_TYPE": "Debug", "MSVC_VERSION": "1930"},
    ).get_executable("foo")
    assert exe is not None
    assert exe.properties["WIN32_EXECUTABLE"] == "$<CONFIG:Release>"
    _assert_win32_console_flag((source_dir / "build-debug.ninja").read_text())


def test_set_target_properties_win32_executable_msvc_flag(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """MSVC-style clang should get /SUBSYSTEM:WINDOWS, not -mwindows."""
    monkeypatch.setattr("cja.generator.platform.system", lambda: "Windows")

    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "CMakeLists.txt").write_text(
        "project(test_win32)\n"
        "add_executable(foo main.c)\n"
        "set_target_properties(foo PROPERTIES WIN32_EXECUTABLE ON)\n"
    )
    (source_dir / "main.c").write_text("int main() { return 0; }")

    configure(
        source_dir,
        "build",
        variables={"MSVC_VERSION": "1930"},
    )
    _assert_win32_gui_flag((source_dir / "build.ninja").read_text(), msvc=True)


def test_msvc_console_subsystem_default(tmp_path: Path, monkeypatch) -> None:
    """MSVC-style clang console apps must set /SUBSYSTEM:CONSOLE (LNK4031)."""
    monkeypatch.setattr("cja.generator.platform.system", lambda: "Windows")

    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "CMakeLists.txt").write_text(
        "project(test_console)\n"
        "add_executable(foo main.c)\n"
    )
    (source_dir / "main.c").write_text("int main() { return 0; }")

    configure(source_dir, "build", variables={"MSVC_VERSION": "1930"})
    _assert_win32_console_flag((source_dir / "build.ninja").read_text())


def test_set_target_properties_win32_executable_gnu_flag(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """MinGW-style toolchains should keep -mwindows."""
    monkeypatch.setattr("cja.generator.platform.system", lambda: "Windows")
    # Prevent configure from auto-detecting MSVC_VERSION from the host clang.
    monkeypatch.setattr("cja.generator._infer_msvc_version", lambda _cc: "")

    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "CMakeLists.txt").write_text(
        "project(test_win32)\n"
        "add_executable(foo main.c)\n"
        "set_target_properties(foo PROPERTIES WIN32_EXECUTABLE ON)\n"
    )
    (source_dir / "main.c").write_text("int main() { return 0; }")

    configure(source_dir, "build")
    _assert_win32_gui_flag((source_dir / "build.ninja").read_text(), msvc=False)


def test_add_executable_win32_keyword(tmp_path: Path, monkeypatch) -> None:
    """add_executable(... WIN32 ...) should set WIN32_EXECUTABLE and emit a GUI flag."""
    monkeypatch.setattr("cja.generator.platform.system", lambda: "Windows")

    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "CMakeLists.txt").write_text(
        "project(test_win32)\n"
        "add_executable(foo WIN32 main.c)\n"
    )
    (source_dir / "main.c").write_text("int main() { return 0; }")

    ctx = configure(source_dir, "build")
    exe = ctx.get_executable("foo")
    assert exe is not None
    assert exe.properties["WIN32_EXECUTABLE"] == "TRUE"
    assert exe.sources == ["main.c"]
    content = (source_dir / "build.ninja").read_text()
    assert "-mwindows" in content or "/SUBSYSTEM:WINDOWS" in content


def test_win32_executable_ignored_on_non_windows(tmp_path: Path, monkeypatch) -> None:
    """WIN32_EXECUTABLE must not emit a subsystem flag off Windows."""
    monkeypatch.setattr("cja.generator.platform.system", lambda: "Linux")

    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "CMakeLists.txt").write_text(
        "project(test_win32)\n"
        "add_executable(foo main.c)\n"
        "set_target_properties(foo PROPERTIES WIN32_EXECUTABLE ON)\n"
    )
    (source_dir / "main.c").write_text("int main() { return 0; }")

    configure(source_dir, "build")
    _assert_no_subsystem_flag((source_dir / "build.ninja").read_text())


def test_set_target_properties_usage_requirements(tmp_path: Path) -> None:
    """Properties like INCLUDE_DIRECTORIES replace what the target_*() commands set."""
    (tmp_path / "CMakeLists.txt").write_text(
        "project(test_props C)\n"
        "add_library(mylib STATIC mylib.c)\n"
        "target_compile_definitions(mylib PUBLIC OLD_DEF)\n"
        "set_target_properties(mylib PROPERTIES\n"
        "  INTERFACE_COMPILE_DEFINITIONS USE_MYLIB\n"
        "  COMPILE_DEFINITIONS BUILDING_MYLIB\n"
        '  INTERFACE_LINK_LIBRARIES "m")\n'
        "add_executable(main main.c)\n"
        "set_property(TARGET main PROPERTY INCLUDE_DIRECTORIES inc)\n"
        "set_property(TARGET main APPEND PROPERTY INCLUDE_DIRECTORIES inc2)\n"
        "set_property(TARGET main PROPERTY LINK_LIBRARIES mylib)\n"
        "get_target_property(main_inc main INCLUDE_DIRECTORIES)\n"
        "get_target_property(mylib_defs mylib COMPILE_DEFINITIONS)\n"
        "get_target_property(main_opts main COMPILE_OPTIONS)\n"
        "get_property(main_opts_set TARGET main PROPERTY COMPILE_OPTIONS SET)\n"
        "get_property(mylib_type TARGET mylib PROPERTY TYPE)\n"
    )
    (tmp_path / "mylib.c").write_text("int mylib_func(void) { return 0; }\n")
    (tmp_path / "main.c").write_text("int main(void) { return 0; }\n")

    ctx = configure(tmp_path, "build")

    assert [Path(d) for d in ctx.variables["main_inc"].split(";")] == [
        (tmp_path / "inc").resolve(),
        (tmp_path / "inc2").resolve(),
    ]
    assert ctx.variables["mylib_defs"] == "BUILDING_MYLIB"
    assert ctx.variables["main_opts"] == "main_opts-NOTFOUND"
    assert ctx.variables["main_opts_set"] == "0"
    assert ctx.variables["mylib_type"] == "STATIC_LIBRARY"
    lib = ctx.get_library("mylib")
    assert lib is not None
    assert lib.public_link_libraries == ["m"]
    content = (tmp_path / "build.ninja").read_text()
    assert "OLD_DEF" not in content
    assert "USE_MYLIB" in content
    assert "BUILDING_MYLIB" in content
    assert "inc2" in content


def test_compile_flags_and_link_flags(tmp_path: Path) -> None:
    """The legacy COMPILE_FLAGS and LINK_FLAGS strings, on targets and sources."""
    (tmp_path / "CMakeLists.txt").write_text(
        "project(test_props C)\n"
        "add_executable(app main.c other.c)\n"
        'set_target_properties(app PROPERTIES COMPILE_FLAGS "-DAPP_A -DAPP_B"'
        " LINK_FLAGS --app-link-flag)\n"
        "set_source_files_properties(main.c PROPERTIES COMPILE_OPTIONS"
        ' "-DSRC_A;-DSRC_B" COMPILE_FLAGS -DSRC_C)\n'
        "set_property(SOURCE other.c APPEND_STRING PROPERTY COMPILE_FLAGS -DOTHER)\n"
    )
    (tmp_path / "main.c").write_text("int main(void) { return 0; }\n")
    (tmp_path / "other.c").write_text("int other(void) { return 0; }\n")

    configure(tmp_path, "build")

    lines = (tmp_path / "build.ninja").read_text().splitlines()
    main_flags = lines[next(i for i, l in enumerate(lines) if "main.c" in l) + 1]
    other_flags = lines[next(i for i, l in enumerate(lines) if "other.c" in l) + 1]
    for flag in ("-DAPP_A", "-DAPP_B", "-DSRC_A", "-DSRC_B", "-DSRC_C"):
        assert flag in main_flags
    assert "-DOTHER" in other_flags
    assert "-DSRC_C" not in other_flags
    assert any("libs" in line and "--app-link-flag" in line for line in lines)


def test_output_name_and_directory(tmp_path: Path) -> None:
    """OUTPUT_NAME, PREFIX, SUFFIX, <CONFIG>_POSTFIX and *_OUTPUT_DIRECTORY."""
    exe_ext = ".exe" if platform.system() == "Windows" else ""
    (tmp_path / "sub").mkdir()
    (tmp_path / "CMakeLists.txt").write_text(
        "project(test_props C)\n"
        "set(CMAKE_BUILD_TYPE Debug)\n"
        "set(CMAKE_DEBUG_POSTFIX _d)\n"
        "add_subdirectory(sub)\n"
        "add_executable(app main.c)\n"
        "set_target_properties(app PROPERTIES RUNTIME_OUTPUT_DIRECTORY bin"
        " OUTPUT_NAME myapp DEBUG_POSTFIX -dbg)\n"
        "add_executable(app2 main.c)\n"
        "set(CMAKE_ARCHIVE_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/archive)\n"
        "add_library(st STATIC a.c)\n"
        'set_target_properties(st PROPERTIES PREFIX "" SUFFIX .lib OUTPUT_NAME static)\n'
        "add_test(NAME t COMMAND app)\n"
    )
    (tmp_path / "sub" / "CMakeLists.txt").write_text(
        "add_executable(subexe ../main.c)\n"
        "set_target_properties(subexe PROPERTIES RUNTIME_OUTPUT_DIRECTORY out)\n"
    )
    (tmp_path / "main.c").write_text("int main(void) { return 0; }\n")
    (tmp_path / "a.c").write_text("int a(void) { return 0; }\n")

    configure(tmp_path, "build")

    content = (tmp_path / "build.ninja").read_text()
    for output in (
        f"$builddir/bin/myapp-dbg{exe_ext}",
        f"$builddir/app2{exe_ext}",
        "$builddir/archive/static_d.lib",
        f"$builddir/sub/out/subexe{exe_ext}",
    ):
        assert f"build {output}:" in content
    assert f"bin/myapp-dbg{exe_ext}" in content.split("rule test_run", 1)[1]


def test_visibility_extensions_and_linker_language(tmp_path: Path) -> None:
    (tmp_path / "CMakeLists.txt").write_text(
        "project(test_props C CXX)\n"
        "set(CMAKE_CXX_VISIBILITY_PRESET hidden)\n"
        "add_library(foo SHARED foo.c bar.cpp)\n"
        "set_target_properties(foo PROPERTIES C_VISIBILITY_PRESET protected"
        " VISIBILITY_INLINES_HIDDEN ON CXX_STANDARD 17 CXX_EXTENSIONS ON)\n"
        "add_executable(app main.c)\n"
        "set_target_properties(app PROPERTIES LINKER_LANGUAGE CXX)\n"
    )
    for name in ("foo.c", "bar.cpp", "main.c"):
        (tmp_path / name).write_text("int main(void) { return 0; }\n")

    configure(tmp_path, "build")

    lines = (tmp_path / "build.ninja").read_text().splitlines()
    c_flags = lines[next(i for i, l in enumerate(lines) if "foo.c" in l) + 1]
    cxx_flags = lines[next(i for i, l in enumerate(lines) if "bar.cpp" in l) + 1]
    assert "-std=gnu++17" in cxx_flags
    if platform.system() != "Windows":
        assert "-fvisibility=protected" in c_flags
        assert "-fvisibility-inlines-hidden" not in c_flags
        assert "-fvisibility=hidden" in cxx_flags
        assert "-fvisibility-inlines-hidden" in cxx_flags
    app_link = next(
        l for l in lines if l.startswith(("build $builddir/app:", "build $builddir/app.exe:"))
    )
    assert ": link_cxx " in app_link
