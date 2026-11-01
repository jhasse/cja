"""Tests for if/elseif/else/endif commands."""

import os
import platform
from pathlib import Path

import pytest

from cja.build_context import BuildContext
from cja.generator import configure, process_commands
from cja.parser import Command, parse
from cja.syntax import evaluate_condition


class TestEvaluateCondition:
    """Tests for the evaluate_condition function."""

    def test_defined_true(self) -> None:
        variables = {"MY_VAR": "value"}
        assert evaluate_condition(["DEFINED", "MY_VAR"], variables) is True

    def test_defined_false(self) -> None:
        variables: dict[str, str] = {}
        assert evaluate_condition(["DEFINED", "MY_VAR"], variables) is False

    def test_defined_env_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MY_TEST_ENV_VAR", "hello")
        assert evaluate_condition(["DEFINED", "ENV{MY_TEST_ENV_VAR}"], {}) is True

    def test_defined_env_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MY_TEST_ENV_VAR", raising=False)
        assert evaluate_condition(["DEFINED", "ENV{MY_TEST_ENV_VAR}"], {}) is False

    def test_not_defined(self) -> None:
        variables: dict[str, str] = {}
        assert evaluate_condition(["NOT", "DEFINED", "MY_VAR"], variables) is True

    def test_target_operator_true(self) -> None:
        variables: dict[str, str] = {}
        assert (
            evaluate_condition(
                ["TARGET", "fmt::fmt"],
                variables,
                target_exists=lambda n: n == "fmt::fmt",
            )
            is True
        )

    def test_target_operator_false(self) -> None:
        variables: dict[str, str] = {}
        assert (
            evaluate_condition(
                ["TARGET", "fmt::fmt"], variables, target_exists=lambda _: False
            )
            is False
        )

    def test_truthy_variable(self) -> None:
        variables = {"MY_VAR": "yes"}
        assert evaluate_condition(["MY_VAR"], variables) is True

    def test_falsy_variable(self) -> None:
        variables = {"MY_VAR": "OFF"}
        assert evaluate_condition(["MY_VAR"], variables) is False

    def test_notfound_variable(self) -> None:
        variables = {"MY_VAR": "MY_VAR-NOTFOUND"}
        assert evaluate_condition(["MY_VAR"], variables) is False

    def test_undefined_variable(self) -> None:
        """Test that undefined variables evaluate to false (e.g. if(WIN32) when WIN32 not set)."""
        variables: dict[str, str] = {}
        assert evaluate_condition(["WIN32"], variables) is False
        assert evaluate_condition(["UNDEFINED_VAR"], variables) is False

    def test_strequal_true(self) -> None:
        variables = {"X": "hello"}
        assert evaluate_condition(["X", "STREQUAL", "hello"], variables) is True

    def test_strequal_false(self) -> None:
        variables = {"X": "hello"}
        assert evaluate_condition(["X", "STREQUAL", "world"], variables) is False

    def test_equal_true(self) -> None:
        variables = {"X": "42"}
        assert evaluate_condition(["X", "EQUAL", "42"], variables) is True

    def test_less_true(self) -> None:
        variables = {"X": "5"}
        assert evaluate_condition(["X", "LESS", "10"], variables) is True

    def test_greater_true(self) -> None:
        variables = {"X": "10"}
        assert evaluate_condition(["X", "GREATER", "5"], variables) is True

    def test_matches(self) -> None:
        variables = {"X": "hello world"}
        assert evaluate_condition(["X", "MATCHES", "wor.*"], variables) is True
        assert variables["CMAKE_MATCH_0"] == "world"

    def test_cmake_matches_sets_group(self) -> None:
        variables = {"url": "http://example.com/libogg-1.3.5.tar.gz"}
        assert (
            evaluate_condition(
                [
                    "url",
                    "MATCHES",
                    r"[/\?]([a-zA-Z0-9_.-]+)\.(tar|tar\.gz|tar\.bz2|zip|ZIP)(\?|/|$)",
                ],
                variables,
            )
            is True
        )
        assert variables["CMAKE_MATCH_1"] == "libogg-1.3.5"

    def test_in_list(self) -> None:
        variables = {"L": "a;c_std_99;;b", "ITEM": "b"}
        assert evaluate_condition(["c_std_99", "IN_LIST", "L"], variables) is True
        assert evaluate_condition(["ITEM", "IN_LIST", "L"], variables) is True
        assert evaluate_condition(["", "IN_LIST", "L"], variables) is True
        assert evaluate_condition(["c", "IN_LIST", "L"], variables) is False
        assert evaluate_condition(["NOT", "c", "IN_LIST", "L"], variables) is True

    def test_in_list_undefined_list(self) -> None:
        assert evaluate_condition(["a", "IN_LIST", "L"], {}) is False

    @pytest.mark.parametrize(
        ("condition", "expected"),
        [
            ("5 GREATER_EQUAL 3", True),
            ("3 GREATER_EQUAL 3", True),
            ("4 LESS_EQUAL 3", False),
            ("5 GREATER_EQUAL 3 AND 2 LESS_EQUAL 1", False),
            ("abc STRLESS_EQUAL abc", True),
            ("abc STRGREATER_EQUAL abd", False),
            ("3.28 VERSION_LESS_EQUAL 3.28.0", True),
            ("2.0 VERSION_GREATER_EQUAL 1.0", True),
            ("1.2 VERSION_GREATER_EQUAL 1.10", False),
        ],
    )
    def test_equal_variants(self, condition: str, expected: bool) -> None:
        assert evaluate_condition(condition.split(), {}) is expected

    @pytest.mark.parametrize(
        ("condition", "expected"),
        [
            ("1.5 LESS 2", True),
            ("3 EQUAL 3.0", True),
            ("3abc EQUAL 3", True),
            ("1e2 EQUAL 100", True),
            ("0x10 EQUAL 16", True),
            ("1e EQUAL 1", False),
            ("0x EQUAL 0", False),
            ("x EQUAL 0", False),
            ("nan EQUAL nan", False),
        ],
    )
    def test_numbers_parse_like_sscanf(self, condition: str, expected: bool) -> None:
        assert evaluate_condition(condition.split(), {}) is expected

    @pytest.mark.parametrize(
        ("condition", "expected"),
        [
            ("1.0 VERSION_EQUAL 1", True),
            ("1.2.3-rc1 VERSION_EQUAL 1.2.3", True),
            ("1.02 VERSION_EQUAL 1.2", True),
            ("1.10 VERSION_GREATER 1.9", True),
            ("v1.2 VERSION_EQUAL 0", True),
            ("1..2 VERSION_EQUAL 1.0.2", True),
            ("1.2 VERSION_LESS 1.2.1", True),
        ],
    )
    def test_versions_compare_like_cmake(self, condition: str, expected: bool) -> None:
        assert evaluate_condition(condition.split(), {}) is expected


class TestIfCommand:
    """Tests for if/elseif/else/endif processing."""

    def test_if_true(self, capsys: pytest.CaptureFixture[str]) -> None:
        ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
        ctx.variables["MY_VAR"] = "yes"
        commands = [
            Command(name="if", args=["MY_VAR"], line=1),
            Command(name="message", args=["STATUS", "in if"], line=2),
            Command(name="endif", args=[], line=3),
        ]
        process_commands(commands, ctx)
        assert "in if" in capsys.readouterr().out

    def test_if_false(self, capsys: pytest.CaptureFixture[str]) -> None:
        ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
        ctx.variables["MY_VAR"] = "OFF"
        commands = [
            Command(name="if", args=["MY_VAR"], line=1),
            Command(name="message", args=["STATUS", "in if"], line=2),
            Command(name="endif", args=[], line=3),
        ]
        process_commands(commands, ctx)
        assert capsys.readouterr().out == ""

    def test_if_else(self, capsys: pytest.CaptureFixture[str]) -> None:
        ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
        commands = [
            Command(name="if", args=["DEFINED", "UNDEFINED_VAR"], line=1),
            Command(name="message", args=["STATUS", "defined"], line=2),
            Command(name="else", args=[], line=3),
            Command(name="message", args=["STATUS", "not defined"], line=4),
            Command(name="endif", args=[], line=5),
        ]
        process_commands(commands, ctx)
        assert "not defined" in capsys.readouterr().out

    def test_if_elseif_else(self, capsys: pytest.CaptureFixture[str]) -> None:
        ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
        ctx.variables["X"] = "2"
        commands = [
            Command(name="if", args=["X", "STREQUAL", "1"], line=1),
            Command(name="message", args=["STATUS", "X is 1"], line=2),
            Command(name="elseif", args=["X", "STREQUAL", "2"], line=3),
            Command(name="message", args=["STATUS", "X is 2"], line=4),
            Command(name="else", args=[], line=5),
            Command(name="message", args=["STATUS", "X is other"], line=6),
            Command(name="endif", args=[], line=7),
        ]
        process_commands(commands, ctx)
        assert "X is 2" in capsys.readouterr().out

    def test_nested_variable_expansion_in_condition(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
        commands = [
            Command(name="set", args=["NAME", "foo"], line=1),
            Command(name="set", args=["CPM_foo_SOURCE", "srcdir"], line=2),
            Command(
                name="if",
                args=["NOT", "${CPM_${NAME}_SOURCE}", "STREQUAL", ""],
                line=3,
            ),
            Command(name="message", args=["STATUS", "has source"], line=4),
            Command(name="endif", args=[], line=5),
        ]
        process_commands(commands, ctx)
        assert "has source" in capsys.readouterr().out

    def test_cpm_nested_source_condition(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
        commands = [
            Command(name="set", args=["CPM_ARGS_NAME", "libogg"], line=1),
            Command(name="set", args=["CPM_ARGS_FORCE", "FALSE"], line=2),
            Command(name="set", args=["CPM_libogg_SOURCE", "srcdir"], line=3),
            Command(
                name="if",
                args=[
                    "NOT",
                    "CPM_ARGS_FORCE",
                    "AND",
                    "NOT",
                    "${CPM_${CPM_ARGS_NAME}_SOURCE}",
                    "STREQUAL",
                    "",
                ],
                line=4,
            ),
            Command(name="message", args=["STATUS", "cpm source set"], line=5),
            Command(name="endif", args=[], line=6),
        ]
        process_commands(commands, ctx)
        assert "cpm source set" in capsys.readouterr().out

    def test_nested_if(self, capsys: pytest.CaptureFixture[str]) -> None:
        ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
        ctx.variables["A"] = "yes"
        ctx.variables["B"] = "yes"
        commands = [
            Command(name="if", args=["A"], line=1),
            Command(name="if", args=["B"], line=2),
            Command(name="message", args=["STATUS", "A and B"], line=3),
            Command(name="endif", args=[], line=4),
            Command(name="endif", args=[], line=5),
        ]
        process_commands(commands, ctx)
        assert "A and B" in capsys.readouterr().out

    def test_set_inside_if(self) -> None:
        ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
        ctx.variables["COND"] = "yes"
        commands = [
            Command(name="if", args=["COND"], line=1),
            Command(name="set", args=["RESULT", "from_if"], line=2),
            Command(name="endif", args=[], line=3),
        ]
        process_commands(commands, ctx)
        assert ctx.variables["RESULT"] == "from_if"

    def test_if_target_operator_with_imported_target(self) -> None:
        ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
        commands = [
            Command(name="find_package", args=["Threads"], line=1),
            Command(name="if", args=["NOT", "TARGET", "Threads::Threads"], line=2),
            Command(name="set", args=["BAD", "1"], line=3),
            Command(name="endif", args=[], line=4),
        ]
        process_commands(commands, ctx, strict=True)
        assert "BAD" not in ctx.variables


class TestEnvVariable:
    """Tests for $ENV{VAR} expansion and if(DEFINED ENV{VAR})."""

    def test_env_expansion(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CJA_TEST_VAR", "world")
        source_dir = tmp_path / "src"
        source_dir.mkdir()
        (source_dir / "CMakeLists.txt").write_text("set(VAL $ENV{CJA_TEST_VAR})\n")
        ctx = configure(source_dir, "build", quiet=True)
        assert ctx.variables["VAL"] == "world"

    def test_if_defined_env_true(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CJA_TEST_VAR", "1")
        source_dir = tmp_path / "src"
        source_dir.mkdir()
        (source_dir / "CMakeLists.txt").write_text(
            "if(DEFINED ENV{CJA_TEST_VAR})\n"
            '  set(RESULT "yes")\n'
            "else()\n"
            '  set(RESULT "no")\n'
            "endif()\n"
        )
        ctx = configure(source_dir, "build", quiet=True)
        assert ctx.variables["RESULT"] == "yes"

    def test_if_defined_env_false(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("CJA_TEST_VAR", raising=False)
        source_dir = tmp_path / "src"
        source_dir.mkdir()
        (source_dir / "CMakeLists.txt").write_text(
            "if(DEFINED ENV{CJA_TEST_VAR})\n"
            '  set(RESULT "yes")\n'
            "else()\n"
            '  set(RESULT "no")\n'
            "endif()\n"
        )
        ctx = configure(source_dir, "build", quiet=True)
        assert ctx.variables["RESULT"] == "no"


def _run(content: str) -> BuildContext:
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    process_commands(parse(content), ctx)
    return ctx


class TestExistenceOperators:
    """Tests for if(COMMAND), if(POLICY) and if(TEST)."""

    def test_command(self) -> None:
        ctx = _run(
            "function(my_func)\nendfunction()\n"
            "macro(my_macro)\nendmacro()\n"
            "foreach(name message TARGET_SOURCES My_Func my_macro check_ipo_supported nope)\n"
            "  if(COMMAND ${name})\n"
            "    list(APPEND FOUND ${name})\n"
            "  endif()\n"
            "endforeach()\n"
        )
        assert ctx.variables["FOUND"] == "message;TARGET_SOURCES;My_Func;my_macro"

    def test_policy(self) -> None:
        variables: dict[str, str] = {}
        assert evaluate_condition(["POLICY", "CMP0000"], variables) is True
        assert evaluate_condition(["POLICY", "CMP0155"], variables) is True
        assert evaluate_condition(["POLICY", "CMP0156"], variables) is False
        assert evaluate_condition(["POLICY", "CMP155"], variables) is False
        assert evaluate_condition(["POLICY", "cmp0001"], variables) is False

    def test_test(self) -> None:
        ctx = _run(
            "add_test(NAME my_test COMMAND true)\n"
            "if(TEST my_test)\n  set(HAS_MY_TEST yes)\nendif()\n"
            "if(TEST other)\n  set(HAS_OTHER yes)\nendif()\n"
        )
        assert ctx.variables["HAS_MY_TEST"] == "yes"
        assert "HAS_OTHER" not in ctx.variables


class TestPathOperators:
    """Tests for the file and path operators of if()."""

    def test_file_tests(self, tmp_path: Path) -> None:
        (tmp_path / "dir").mkdir()
        (tmp_path / "file").write_text("")
        d, f = str(tmp_path / "dir"), str(tmp_path / "file")
        assert evaluate_condition(["IS_DIRECTORY", d], {}) is True
        assert evaluate_condition(["IS_DIRECTORY", f], {}) is False
        assert evaluate_condition(["IS_SYMLINK", f], {}) is False
        assert evaluate_condition(["IS_READABLE", f], {}) is True
        assert evaluate_condition(["IS_WRITABLE", f], {}) is True
        assert evaluate_condition(["IS_EXECUTABLE", d], {}) is True
        for op in ("EXISTS", "IS_DIRECTORY", "IS_READABLE"):
            assert evaluate_condition([op, ""], {}) is False

    @pytest.mark.skipif(platform.system() == "Windows", reason="needs symlinks")
    def test_is_symlink(self, tmp_path: Path) -> None:
        (tmp_path / "file").write_text("")
        (tmp_path / "link").symlink_to(tmp_path / "file")
        link = str(tmp_path / "link")
        assert evaluate_condition(["IS_SYMLINK", link], {}) is True
        assert evaluate_condition(["EXISTS", link], {}) is True

    def test_is_newer_than(self, tmp_path: Path) -> None:
        old, new = tmp_path / "old", tmp_path / "new"
        old.write_text("")
        new.write_text("")
        os.utime(old, ns=(1_000_000_000, 1_000_000_000))
        missing = str(tmp_path / "missing")
        assert evaluate_condition([str(new), "IS_NEWER_THAN", str(old)], {}) is True
        assert evaluate_condition([str(old), "IS_NEWER_THAN", str(new)], {}) is False
        assert evaluate_condition([str(old), "IS_NEWER_THAN", str(old)], {}) is True
        assert evaluate_condition([str(old), "IS_NEWER_THAN", missing], {}) is True

    @pytest.mark.skipif(platform.system() == "Windows", reason="POSIX path rules")
    @pytest.mark.parametrize(
        ("condition", "expected"),
        [
            ("IS_ABSOLUTE /x", True),
            ("IS_ABSOLUTE ~/x", True),
            ("IS_ABSOLUTE x", False),
            ("IS_ABSOLUTE C:/x", False),
            ("/a//b/c PATH_EQUAL /a/b/c", True),
            ("/a/b/ PATH_EQUAL /a/b", False),
            ("/a/b// PATH_EQUAL /a/b/", True),
            ("a PATH_EQUAL ./a", False),
            ("/ PATH_EQUAL //", True),
            ("a\\b PATH_EQUAL a/b", False),
        ],
    )
    def test_paths(self, condition: str, expected: bool) -> None:
        assert evaluate_condition(condition.split(), {}) is expected


class TestConditionArguments:
    """Tests for how if() expands its arguments."""

    def test_unquoted_list_is_split(self) -> None:
        ctx = _run(
            'set(cond "a;;STREQUAL;a")\n'
            "if(${cond})\n  set(IF_SPLIT yes)\nendif()\n"
            "if(0)\nelseif(${cond})\n  set(ELSEIF_SPLIT yes)\nendif()\n"
            'if("${cond}")\n  set(QUOTED_SPLIT yes)\nendif()\n'
        )
        assert ctx.variables["IF_SPLIT"] == "yes"
        assert ctx.variables["ELSEIF_SPLIT"] == "yes"
        assert "QUOTED_SPLIT" not in ctx.variables

    def test_function_forwarding_its_arguments(self) -> None:
        ctx = _run(
            "function(check out)\n"
            "  if(${ARGN})\n    set(${out} yes PARENT_SCOPE)\n  endif()\n"
            "endfunction()\n"
            "check(RESULT 5 GREATER_EQUAL 3)\n"
        )
        assert ctx.variables["RESULT"] == "yes"

    def test_bracket_argument_is_literal(self) -> None:
        ctx = _run(
            'set(L "x;y")\n'
            'if([[${L}]] STREQUAL "\\${L}")\n  set(LITERAL yes)\nendif()\n'
        )
        assert ctx.variables["LITERAL"] == "yes"
