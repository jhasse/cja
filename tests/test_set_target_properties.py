"""Tests for set_target_properties command."""

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
