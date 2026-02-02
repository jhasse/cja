"""Tests for if/elseif/else/endif commands."""

from pathlib import Path

import pytest

from cninja.build_context import BuildContext
from cninja.generator import process_commands
from cninja.syntax import evaluate_condition
from cninja.parser import Command


class TestEvaluateCondition:
    """Tests for the evaluate_condition function."""

    def test_defined_true(self) -> None:
        variables = {"MY_VAR": "value"}
        assert evaluate_condition(["DEFINED", "MY_VAR"], variables) is True

    def test_defined_false(self) -> None:
        variables: dict[str, str] = {}
        assert evaluate_condition(["DEFINED", "MY_VAR"], variables) is False

    def test_not_defined(self) -> None:
        variables: dict[str, str] = {}
        assert evaluate_condition(["NOT", "DEFINED", "MY_VAR"], variables) is True

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

    def test_cpm_nested_source_condition(self, capsys: pytest.CaptureFixture[str]) -> None:
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
