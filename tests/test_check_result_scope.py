"""Tests that the results of the check_* commands are cache entries."""

from pathlib import Path

import pytest

from cja.generator import BuildContext, process_commands
from cja.parser import parse


@pytest.mark.parametrize(
    "check",
    [
        "check_c_source_compiles([==[int main(void) { return 0; }]==] RESULT)",
        "check_cxx_source_compiles([==[int main() { return 0; }]==] RESULT)",
        "check_symbol_exists(printf stdio.h RESULT)",
        "check_cxx_symbol_exists(printf cstdio RESULT)",
        "check_function_exists(printf RESULT)",
        "check_include_file(stdio.h RESULT)",
        "check_include_files(stdio.h RESULT)",
        "check_c_compiler_flag(-Wall RESULT)",
        "check_cxx_compiler_flag(-Wall RESULT)",
    ],
)
def test_check_result_outlives_function(check: str) -> None:
    """Check results are cache entries, so one made inside a function is seen
    after it returns, like SDL's check_x86_source_compiles() wrapper relies on."""
    content = f"function(wrapper)\n  {check}\nendfunction()\nwrapper()\n"
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    process_commands(parse(content), ctx)

    assert ctx.variables["RESULT"] == "1"
