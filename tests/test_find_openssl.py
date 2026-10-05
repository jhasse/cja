"""Tests for find_package(OpenSSL) using the bundled FindOpenSSL.cmake."""

import re
import sys
from pathlib import Path

import pytest

from cja.generator import configure

OPENSSL3_HEADER = """\
#ifndef OPENSSL_OPENSSLV_H
# define OPENSSL_OPENSSLV_H
# define OPENSSL_VERSION_MAJOR  3
# define OPENSSL_VERSION_MINOR  0
# define OPENSSL_VERSION_PATCH  13
# define OPENSSL_VERSION_STR "3.0.13"
# define OPENSSL_VERSION_NUMBER \\
    ( (OPENSSL_VERSION_MAJOR<<28) \\
      |(OPENSSL_VERSION_MINOR<<20) \\
      |(OPENSSL_VERSION_PATCH<<4) \\
      |_OPENSSL_VERSION_PRE_RELEASE )
#endif
"""

OPENSSL1_HEADER = """\
#ifndef HEADER_OPENSSLV_H
# define HEADER_OPENSSLV_H
# define OPENSSL_VERSION_NUMBER  0x1010108fL
# define OPENSSL_VERSION_TEXT    "OpenSSL 1.1.1h  22 Sep 2020"
#endif
"""


def _make_prefix(root: Path, header: str = OPENSSL3_HEADER) -> Path:
    prefix = root / "openssl root"
    (prefix / "include" / "openssl").mkdir(parents=True)
    (prefix / "include" / "openssl" / "ssl.h").write_text("/* ssl */\n")
    (prefix / "include" / "openssl" / "opensslv.h").write_text(header)
    (prefix / "lib").mkdir()
    for name in ("libssl.a", "libcrypto.a"):
        (prefix / "lib" / name).write_bytes(b"!<arch>\n")
    return prefix


def _project(root: Path, cmake_body: str) -> Path:
    source = root / "proj"
    source.mkdir()
    (source / "main.c").write_text("int main(void) { return 0; }\n")
    (source / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.10)\n"
        "project(ossl C)\n"
        "set(OPENSSL_USE_STATIC_LIBS ON)\n"
        f"{cmake_body}\n"
    )
    return source


def test_find_openssl_basic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prefix = _make_prefix(tmp_path)
    source = _project(
        tmp_path,
        "find_package(OpenSSL REQUIRED)\n"
        "add_executable(app main.c)\n"
        "target_link_libraries(app PRIVATE OpenSSL::SSL OpenSSL::Crypto)\n",
    )
    monkeypatch.chdir(source)

    ctx = configure(
        source,
        "build",
        variables={"OPENSSL_ROOT_DIR": prefix.as_posix()},
        quiet=True,
    )

    assert ctx.variables["OpenSSL_FOUND"] == "TRUE"
    assert ctx.variables["OPENSSL_FOUND"] == "TRUE"
    assert ctx.variables["OPENSSL_VERSION"] == "3.0.13"
    assert Path(ctx.variables["OPENSSL_INCLUDE_DIR"]) == prefix / "include"
    assert "OpenSSL::SSL" in ctx.imported_targets
    assert "OpenSSL::Crypto" in ctx.imported_targets

    # Undo ninja's `$`-newline line wrapping to look at the logical lines.
    ninja = re.sub(r" \$\n\s*", " ", (source / "build.ninja").read_text())
    posix_prefix = prefix.as_posix()
    # The prefix contains a space, so each path must stay a single quoted
    # argument (the quote wraps the whole `-I<dir>` token / library path).
    assert f"-I{posix_prefix}/include" in ninja
    assert f"{posix_prefix}/lib/libssl.a" in ninja
    assert f"{posix_prefix}/lib/libcrypto.a" in ninja
    quote = '"' if sys.platform == "win32" else "'"
    assert f"{quote}-I{posix_prefix}/include{quote}" in ninja
    assert f"{quote}{posix_prefix}/lib/libssl.a{quote}" in ninja


def test_find_openssl_result_variables_with_spaces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prefix = _make_prefix(tmp_path)
    source = _project(
        tmp_path,
        "find_package(OpenSSL REQUIRED)\n"
        "add_executable(app main.c)\n"
        "target_include_directories(app PRIVATE ${OPENSSL_INCLUDE_DIR})\n"
        "target_link_libraries(app PRIVATE ${OPENSSL_LIBRARIES})\n",
    )
    monkeypatch.chdir(source)

    # Native separators, like a root taken from $ENV{ProgramFiles} on Windows.
    ctx = configure(
        source, "build", variables={"OPENSSL_ROOT_DIR": str(prefix)}, quiet=True
    )

    posix_prefix = prefix.as_posix()
    # Like CMake, find_* results use forward slashes.
    assert ctx.variables["OPENSSL_INCLUDE_DIR"] == f"{posix_prefix}/include"

    ninja = re.sub(r" \$\n\s*", " ", (source / "build.ninja").read_text())
    quote = '"' if sys.platform == "win32" else "'"
    assert f"{quote}-I{posix_prefix}/include{quote}" in ninja
    assert f"{quote}{posix_prefix}/lib/libssl.a{quote}" in ninja
    assert f"{quote}{posix_prefix}/lib/libcrypto.a{quote}" in ninja


def test_find_openssl_ssl_target_propagates_crypto(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prefix = _make_prefix(tmp_path)
    source = _project(
        tmp_path,
        "find_package(OpenSSL REQUIRED)\n"
        "add_executable(app main.c)\n"
        "target_link_libraries(app PRIVATE OpenSSL::SSL)\n",
    )
    monkeypatch.chdir(source)

    ctx = configure(
        source,
        "build",
        variables={"OPENSSL_ROOT_DIR": prefix.as_posix()},
        quiet=True,
    )

    ssl = ctx.imported_targets["OpenSSL::SSL"]
    assert "libssl.a" in ssl.libs
    assert "libcrypto.a" in ssl.libs
    ninja = (source / "build.ninja").read_text()
    assert "libcrypto.a" in ninja


def test_find_openssl_legacy_hex_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prefix = _make_prefix(tmp_path, OPENSSL1_HEADER)
    source = _project(tmp_path, "find_package(OpenSSL REQUIRED)\n")
    monkeypatch.chdir(source)

    ctx = configure(
        source,
        "build",
        variables={"OPENSSL_ROOT_DIR": prefix.as_posix()},
        quiet=True,
    )

    assert ctx.variables["OpenSSL_FOUND"] == "TRUE"
    assert ctx.variables["OPENSSL_VERSION"] == "1.1.1h"


def test_find_openssl_version_satisfied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prefix = _make_prefix(tmp_path)
    source = _project(tmp_path, "find_package(OpenSSL 3.0 REQUIRED)\n")
    monkeypatch.chdir(source)

    ctx = configure(
        source,
        "build",
        variables={"OPENSSL_ROOT_DIR": prefix.as_posix()},
        quiet=True,
    )

    assert ctx.variables["OpenSSL_FOUND"] == "TRUE"


def test_find_openssl_version_too_old(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prefix = _make_prefix(tmp_path)
    source = _project(tmp_path, "find_package(OpenSSL 99.0 REQUIRED)\n")
    monkeypatch.chdir(source)

    with pytest.raises(SystemExit):
        configure(
            source,
            "build",
            variables={"OPENSSL_ROOT_DIR": prefix.as_posix()},
            quiet=True,
        )


def test_find_openssl_version_too_old_optional(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prefix = _make_prefix(tmp_path)
    source = _project(tmp_path, "find_package(OpenSSL 99.0)\n")
    monkeypatch.chdir(source)

    ctx = configure(
        source,
        "build",
        variables={"OPENSSL_ROOT_DIR": prefix.as_posix()},
        quiet=True,
    )

    assert ctx.variables["OpenSSL_FOUND"] == "FALSE"
    assert ctx.variables["OPENSSL_FOUND"] == "FALSE"


def test_find_openssl_version_range(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prefix = _make_prefix(tmp_path)
    source = _project(tmp_path, "find_package(OpenSSL 1.1...<3.0)\n")
    monkeypatch.chdir(source)

    ctx = configure(
        source,
        "build",
        variables={"OPENSSL_ROOT_DIR": prefix.as_posix()},
        quiet=True,
    )

    assert ctx.variables["OpenSSL_FOUND"] == "FALSE"


def _prefix_without_libs(root: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    prefix = _make_prefix(root)
    for lib in (prefix / "lib").iterdir():
        lib.unlink()
    # FindOpenSSL passes pkg-config's libdir as a HINT; keep a system OpenSSL
    # (e.g. Homebrew's on macOS) from satisfying the library search.
    empty = root / "empty pkgconfig"
    empty.mkdir()
    monkeypatch.setenv("PKG_CONFIG_LIBDIR", str(empty))
    monkeypatch.delenv("PKG_CONFIG_PATH", raising=False)
    return prefix


def test_find_openssl_missing_libraries_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prefix = _prefix_without_libs(tmp_path, monkeypatch)
    source = _project(tmp_path, "find_package(OpenSSL REQUIRED)\n")
    monkeypatch.chdir(source)

    with pytest.raises(SystemExit):
        configure(
            source,
            "build",
            variables={"OPENSSL_ROOT_DIR": prefix.as_posix()},
            quiet=True,
        )


def test_find_openssl_missing_libraries_optional(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prefix = _prefix_without_libs(tmp_path, monkeypatch)
    source = _project(tmp_path, "find_package(OpenSSL)\n")
    monkeypatch.chdir(source)

    ctx = configure(
        source,
        "build",
        variables={"OPENSSL_ROOT_DIR": prefix.as_posix()},
        quiet=True,
    )

    assert ctx.variables["OpenSSL_FOUND"] == "FALSE"
    assert ctx.variables["OPENSSL_FOUND"] == "FALSE"
    assert "OpenSSL::SSL" not in ctx.imported_targets
