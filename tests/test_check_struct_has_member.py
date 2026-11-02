"""Tests for the check_struct_has_member command."""

from pathlib import Path

import pytest

from cja.generator import BuildContext, process_commands
from cja.parser import parse


def _run(content: str) -> BuildContext:
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    process_commands(parse(content), ctx)
    return ctx


def test_check_struct_has_member() -> None:
    ctx = _run(
        'check_struct_has_member("struct tm" tm_sec time.h HAVE_TM_SEC)\n'
        'check_struct_has_member("struct tm" tm_bogus time.h HAVE_TM_BOGUS)\n'
        'check_struct_has_member("struct tm" tm_sec "stddef.h;time.h" HAVE_BOTH)\n'
        "check_struct_has_member(std::tm tm_sec ctime HAVE_STD_TM LANGUAGE CXX)\n"
    )
    assert ctx.variables["HAVE_TM_SEC"] == "1"
    assert ctx.variables["HAVE_TM_BOGUS"] == ""
    assert ctx.variables["HAVE_BOTH"] == "1"
    assert ctx.variables["HAVE_STD_TM"] == "1"


def test_check_struct_has_member_is_c_by_default() -> None:
    ctx = _run("check_struct_has_member(std::tm tm_sec ctime HAVE_STD_TM)\n")
    assert ctx.variables["HAVE_STD_TM"] == ""


@pytest.mark.parametrize("extra", ["LANGUAGE Fortran", "BOGUS", "LANGUAGE CXX BOGUS"])
def test_check_struct_has_member_bad_arguments(extra: str) -> None:
    with pytest.raises(SystemExit):
        _run(f'check_struct_has_member("struct tm" tm_sec time.h HAVE {extra})\n')
