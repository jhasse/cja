"""Tests for find_package command."""

import subprocess
import sys
from pathlib import Path

import pytest

from cja.generator import BuildContext, process_commands
from cja.parser import Command


def has_pkg_config_gtest() -> bool:
    """Check if pkg-config can find gtest."""
    try:
        result = subprocess.run(
            ["pkg-config", "--exists", "gtest"],
            capture_output=True,
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


def has_pkg_config_webp() -> bool:
    """Check if pkg-config can find WebP."""
    try:
        for candidate in ("libwebp", "webp"):
            result = subprocess.run(
                ["pkg-config", "--exists", candidate],
                capture_output=True,
            )
            if result.returncode == 0:
                return True
        return False
    except FileNotFoundError:
        return False


@pytest.mark.skipif(not has_pkg_config_gtest(), reason="gtest not found via pkg-config")
def test_find_package_gtest_found() -> None:
    """Test find_package(GTest) when gtest is available."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="find_package", args=["GTest"], line=1)]
    process_commands(commands, ctx)

    assert ctx.variables["GTest_FOUND"] == "TRUE"
    assert ctx.variables["GTEST_FOUND"] == "TRUE"
    assert "GTEST_LIBRARIES" in ctx.variables


def test_find_package_unknown() -> None:
    """Test find_package with unknown package."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="find_package", args=["UnknownPackage123"], line=1)]
    process_commands(commands, ctx)

    assert ctx.variables["UnknownPackage123_FOUND"] == "FALSE"


def test_find_package_unknown_required() -> None:
    """Test find_package with REQUIRED for unknown package."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="find_package", args=["UnknownPackage123", "REQUIRED"], line=1)
    ]

    with pytest.raises(SystemExit) as exc_info:
        process_commands(commands, ctx)
    assert exc_info.value.code == 1


def test_find_package_gtest_with_if() -> None:
    """Test find_package(GTest) used in if condition."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="find_package", args=["GTest"], line=1),
        Command(name="if", args=["GTest_FOUND"], line=2),
        Command(name="set", args=["RESULT", "found"], line=3),
        Command(name="else", args=[], line=4),
        Command(name="set", args=["RESULT", "not_found"], line=5),
        Command(name="endif", args=[], line=6),
    ]
    process_commands(commands, ctx)

    # Result depends on whether gtest is installed
    if has_pkg_config_gtest():
        assert ctx.variables["RESULT"] == "found"
    else:
        assert ctx.variables["RESULT"] == "not_found"


def test_find_package_gtest_alias_imported_targets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test find_package(GTest) creates modern and legacy imported target names."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))

    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        if cmd == ["pkg-config", "--exists", "gtest"]:
            return subprocess.CompletedProcess(cmd, 0)
        if cmd == ["pkg-config", "--cflags", "gtest"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="-I/usr/include")
        if cmd == ["pkg-config", "--libs", "gtest"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="-lgtest")
        if cmd == ["pkg-config", "--libs", "gtest_main"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="-lgtest_main")
        return subprocess.CompletedProcess(cmd, 1)

    monkeypatch.setattr("cja.generator.subprocess.run", fake_run)

    commands = [Command(name="find_package", args=["GTest"], line=1)]
    process_commands(commands, ctx)

    assert "GTest::gtest" in ctx.imported_targets
    assert "GTest::GTest" in ctx.imported_targets
    assert ctx.imported_targets["GTest::gtest"] == ctx.imported_targets["GTest::GTest"]

    assert "GTest::gtest_main" in ctx.imported_targets
    assert "GTest::Main" in ctx.imported_targets
    assert (
        ctx.imported_targets["GTest::gtest_main"]
        == ctx.imported_targets["GTest::Main"]
    )


def test_find_package_gtest_fallback_filesystem(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test find_package(GTest) falls back to filesystem probing."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))

    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        if cmd == ["pkg-config", "--exists", "gtest"]:
            return subprocess.CompletedProcess(cmd, 1)
        return subprocess.CompletedProcess(cmd, 1)

    monkeypatch.setattr("cja.generator.subprocess.run", fake_run)
    monkeypatch.setattr(
        "cja.find_package._find_gtest_via_filesystem",
        lambda _hint: (
            True,
            "-I/usr/include",
            "/usr/lib/libgtest.a",
            "/usr/lib/libgtest_main.a",
        ),
    )

    commands = [Command(name="find_package", args=["GTest"], line=1)]
    process_commands(commands, ctx)

    assert ctx.variables["GTest_FOUND"] == "TRUE"
    assert ctx.variables["GTEST_FOUND"] == "TRUE"
    assert ctx.variables["GTEST_INCLUDE_DIR"] == "/usr/include"
    assert ctx.variables["GTEST_LIBRARIES"] == "/usr/lib/libgtest.a"
    assert ctx.variables["GTEST_MAIN_LIBRARIES"] == "/usr/lib/libgtest_main.a"
    assert "GTest::gtest" in ctx.imported_targets
    assert "GTest::gtest_main" in ctx.imported_targets


def test_find_package_gtest_required_failure_when_fallback_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test required GTest still fails when pkg-config and fallback miss."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))

    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        if cmd == ["pkg-config", "--exists", "gtest"]:
            return subprocess.CompletedProcess(cmd, 1)
        return subprocess.CompletedProcess(cmd, 1)

    monkeypatch.setattr("cja.generator.subprocess.run", fake_run)
    monkeypatch.setattr(
        "cja.find_package._find_gtest_via_filesystem",
        lambda _hint: (False, "", "", ""),
    )

    commands = [Command(name="find_package", args=["GTest", "REQUIRED"], line=1)]
    with pytest.raises(SystemExit) as exc_info:
        process_commands(commands, ctx)
    assert exc_info.value.code == 1


def test_find_package_threads() -> None:
    """Test find_package(Threads) sets variables and imported target."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="find_package", args=["Threads"], line=1)]
    process_commands(commands, ctx)

    assert ctx.variables["Threads_FOUND"] == "TRUE"
    assert ctx.variables["CMAKE_THREAD_LIBS_INIT"] == "-pthread"
    assert "Threads::Threads" in ctx.imported_targets
    assert ctx.imported_targets["Threads::Threads"].libs == "-pthread"


def test_find_package_threads_link() -> None:
    """Test that linking against Threads::Threads adds -pthread."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="find_package", args=["Threads"], line=1),
        Command(name="add_executable", args=["myapp", "main.c"], line=2),
        Command(
            name="target_link_libraries", args=["myapp", "Threads::Threads"], line=3
        ),
    ]
    process_commands(commands, ctx)

    exe = ctx.get_executable("myapp")
    assert exe is not None
    assert "Threads::Threads" in exe.link_libraries


@pytest.mark.skipif(not has_pkg_config_gtest(), reason="gtest not found via pkg-config")
def test_find_package_gtest_imported_target() -> None:
    """Test find_package(GTest) creates GTest::gtest imported target with cflags."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="find_package", args=["GTest"], line=1)]
    process_commands(commands, ctx)

    assert "GTest::gtest" in ctx.imported_targets
    target = ctx.imported_targets["GTest::gtest"]
    # Should have libs (link flags)
    assert target.libs
    # cflags may or may not be set depending on pkg-config output


@pytest.mark.skipif(not has_pkg_config_webp(), reason="WebP not found via pkg-config")
def test_find_package_webp_found() -> None:
    """Test find_package(WebP) when webp is available."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="find_package", args=["WebP"], line=1)]
    process_commands(commands, ctx)

    assert ctx.variables["WebP_FOUND"] == "TRUE"
    assert ctx.variables["WEBP_FOUND"] == "TRUE"
    assert "WEBP_LIBRARIES" in ctx.variables
    assert "WebP::webp" in ctx.imported_targets


def test_find_package_python_interpreter() -> None:
    """Test find_package(Python COMPONENTS Interpreter)."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="find_package",
            args=["Python", "COMPONENTS", "Interpreter"],
            line=1,
        )
    ]
    process_commands(commands, ctx)

    assert ctx.variables["Python_FOUND"] == "TRUE"
    assert ctx.variables["Python_Interpreter_FOUND"] == "TRUE"
    assert ctx.variables["Python_EXECUTABLE"] == sys.executable
    assert "Python::Interpreter" in ctx.imported_targets


def test_find_package_python3_interpreter() -> None:
    """Test find_package(Python3 COMPONENTS Interpreter)."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="find_package",
            args=["Python3", "COMPONENTS", "Interpreter"],
            line=1,
        )
    ]
    process_commands(commands, ctx)

    assert ctx.variables["Python3_FOUND"] == "TRUE"
    assert ctx.variables["Python3_Interpreter_FOUND"] == "TRUE"
    assert ctx.variables["Python3_EXECUTABLE"] == sys.executable
    assert "Python3::Interpreter" in ctx.imported_targets


def test_find_package_boost_found_via_pkg_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test find_package(Boost) when boost is available via pkg-config."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))

    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        if cmd == ["pkg-config", "--exists", "boost"]:
            return subprocess.CompletedProcess(cmd, 0)
        if cmd == ["pkg-config", "--cflags", "boost"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="-I/usr/include/boost")
        if cmd == ["pkg-config", "--libs", "boost"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="-lboost_headers")
        if cmd == ["pkg-config", "--modversion", "boost"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="1.84.0")
        return subprocess.CompletedProcess(cmd, 1)

    monkeypatch.setattr("cja.generator.subprocess.run", fake_run)

    commands = [Command(name="find_package", args=["Boost"], line=1)]
    process_commands(commands, ctx)

    assert ctx.variables["Boost_FOUND"] == "TRUE"
    assert ctx.variables["BOOST_FOUND"] == "TRUE"
    assert ctx.variables["Boost_VERSION"] == "1.84.0"
    assert "Boost::headers" in ctx.imported_targets
    assert "Boost::boost" in ctx.imported_targets


def test_find_package_boost_required_component_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test find_package(Boost REQUIRED COMPONENTS filesystem) failure."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))

    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        if cmd == ["pkg-config", "--exists", "boost"]:
            return subprocess.CompletedProcess(cmd, 0)
        if cmd == ["pkg-config", "--cflags", "boost"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="-I/usr/include/boost")
        if cmd == ["pkg-config", "--libs", "boost"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="")
        if cmd == ["pkg-config", "--modversion", "boost"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="1.84.0")
        if cmd == ["pkg-config", "--exists", "boost_filesystem"]:
            return subprocess.CompletedProcess(cmd, 1)
        return subprocess.CompletedProcess(cmd, 1)

    monkeypatch.setattr("cja.generator.subprocess.run", fake_run)

    commands = [
        Command(
            name="find_package",
            args=["Boost", "REQUIRED", "COMPONENTS", "filesystem"],
            line=1,
        )
    ]
    with pytest.raises(SystemExit) as exc_info:
        process_commands(commands, ctx)
    assert exc_info.value.code == 1


def test_find_package_png_found_via_pkg_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test find_package(PNG) when png is available via pkg-config."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))

    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        if cmd == ["pkg-config", "--exists", "libpng"]:
            return subprocess.CompletedProcess(cmd, 0)
        if cmd == ["pkg-config", "--cflags", "libpng"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="-I/usr/include/libpng16")
        if cmd == ["pkg-config", "--libs", "libpng"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="-lpng16")
        if cmd == ["pkg-config", "--modversion", "libpng"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="1.6.43")
        return subprocess.CompletedProcess(cmd, 1)

    monkeypatch.setattr("cja.generator.subprocess.run", fake_run)

    commands = [Command(name="find_package", args=["PNG"], line=1)]
    process_commands(commands, ctx)

    assert ctx.variables["PNG_FOUND"] == "TRUE"
    assert ctx.variables["PNG_LIBRARIES"] == "-lpng16"
    assert ctx.variables["PNG_LIBRARY"] == "-lpng16"
    assert ctx.variables["PNG_INCLUDE_DIRS"] == "/usr/include/libpng16"
    assert ctx.variables["PNG_INCLUDE_DIR"] == "/usr/include/libpng16"
    assert ctx.variables["PNG_PNG_INCLUDE_DIR"] == "/usr/include/libpng16"
    assert ctx.variables["PNG_VERSION"] == "1.6.43"
    assert ctx.variables["PNG_VERSION_STRING"] == "1.6.43"
    assert "PNG::PNG" in ctx.imported_targets


def test_find_package_png_required_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test find_package(PNG REQUIRED) failure when pkg-config can't find png."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))

    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        if cmd == ["pkg-config", "--exists", "libpng"]:
            return subprocess.CompletedProcess(cmd, 1)
        if cmd == ["pkg-config", "--exists", "png"]:
            return subprocess.CompletedProcess(cmd, 1)
        return subprocess.CompletedProcess(cmd, 1)

    monkeypatch.setattr("cja.generator.subprocess.run", fake_run)

    commands = [Command(name="find_package", args=["PNG", "REQUIRED"], line=1)]
    with pytest.raises(SystemExit) as exc_info:
        process_commands(commands, ctx)
    assert exc_info.value.code == 1
