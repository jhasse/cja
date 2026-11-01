import operator
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .parser import Command
from .utils import (
    UNDEFINED_VAR_SENTINEL,
    cmake_regex_to_python,
    compare_versions,
    is_constant_truthy,
    is_truthy,
)


@dataclass
class FetchContentInfo:
    """Information for FetchContent_Declare."""

    name: str
    args: list[str]


@dataclass
class FunctionDef:
    """A CMake function definition."""

    name: str
    params: list[str]
    body: list  # list[Command] - forward reference
    defining_file: Path


@dataclass
class MacroDef:
    """A CMake macro definition."""

    name: str
    params: list[str]
    body: list  # list[Command] - forward reference


@dataclass
class SourceFileProperties:
    """Properties for a source file."""

    object_depends: list[str] = field(default_factory=list)
    include_directories: list[str] = field(default_factory=list)
    compile_definitions: list[str] = field(default_factory=list)
    compile_options: list[str] = field(default_factory=list)
    compile_flags: str = ""  # Legacy COMPILE_FLAGS, a command-line string
    skip_precompile_headers: bool = False


@dataclass
class Test:
    """A test definition."""

    name: str
    command: list[str]
    working_directory: str | None = None
    properties: dict[str, str] = field(default_factory=dict)


# EQUAL, LESS, ... compare numbers, STREQUAL, STRLESS, ... strings and
# VERSION_EQUAL, VERSION_LESS, ... versions.
_COMPARISONS: dict[str, Callable[[Any, Any], bool]] = {
    "EQUAL": operator.eq,
    "LESS": operator.lt,
    "LESS_EQUAL": operator.le,
    "GREATER": operator.gt,
    "GREATER_EQUAL": operator.ge,
}
_BINARY_OPERATORS = {
    "MATCHES",
    "IN_LIST",
    *_COMPARISONS,
    *(f"STR{op}" for op in _COMPARISONS),
    *(f"VERSION_{op}" for op in _COMPARISONS),
}

# The longest prefixes sscanf("%lg") reads as a number.
_SPECIAL_NUMBER_RE = re.compile(
    r"[+-]?(?:inf(?:i(?:n(?:i(?:ty?)?)?)?)?|nan)", re.IGNORECASE
)
_HEX_NUMBER_RE = re.compile(
    r"[+-]?0[xX](?P<mantissa>[0-9a-fA-F]*\.?[0-9a-fA-F]*)(?:[pP](?P<exp>[+-]?[0-9]*))?"
)
_DECIMAL_NUMBER_RE = re.compile(
    r"[+-]?(?P<mantissa>[0-9]*\.?[0-9]*)(?:[eE](?P<exp>[+-]?[0-9]*))?"
)


def _parse_number(value: str) -> float | None:
    """Parse a number like sscanf("%lg"), which CMake uses.

    It reads as much as could still become a number and ignores the rest, so
    "3abc" is 3, but fails if what it read isn't a number, like "1e" or "0x".
    """
    text = value.lstrip(" \t\n\v\f\r")
    special = _SPECIAL_NUMBER_RE.match(text)
    if special:
        word = special.group().lstrip("+-").lower()
        return float(special.group()) if word in ("inf", "infinity", "nan") else None
    hex_number = _HEX_NUMBER_RE.match(text)
    match = hex_number or _DECIMAL_NUMBER_RE.match(text)
    assert match  # The decimal pattern also matches nothing
    exponent = match.group("exp")
    if not match.group("mantissa").strip(".") or (
        exponent is not None and not exponent.lstrip("+-")
    ):
        return None
    return float.fromhex(match.group()) if hex_number else float(match.group())


def evaluate_condition(
    args: list[str],
    variables: dict[str, str],
    target_exists: Callable[[str], bool] | None = None,
) -> bool:
    """Evaluate a CMake if() condition."""
    if not args:
        return False

    i = 0

    def is_defined(name: str) -> bool:
        m = re.fullmatch(r"ENV\{\s*(\w+)\s*\}", name)
        if m:
            return m.group(1) in os.environ
        m = re.fullmatch(r"CACHE\{\s*(\w+)\s*\}", name)
        if m:
            return m.group(1) in variables and variables.get(m.group(1)) != UNDEFINED_VAR_SENTINEL
        return name in variables and variables.get(name) != UNDEFINED_VAR_SENTINEL

    def resolve(name: str) -> str:
        if name in variables:
            val = variables[name]
            if val == UNDEFINED_VAR_SENTINEL:
                return ""
            return val
        return name

    def parse_or() -> bool:
        nonlocal i
        left = parse_and()
        while i < len(args) and args[i] == "OR":
            i += 1
            right = parse_and()
            left = left or right
        return left

    def parse_and() -> bool:
        nonlocal i
        left = parse_not()
        while i < len(args) and args[i] == "AND":
            i += 1
            right = parse_not()
            left = left and right
        return left

    def parse_not() -> bool:
        nonlocal i
        if i < len(args) and args[i] == "NOT":
            i += 1
            return not parse_not()
        return parse_atom()

    def parse_atom() -> bool:
        nonlocal i
        if i >= len(args):
            return False

        if args[i] == "(":
            i += 1
            res = parse_or()
            if i < len(args) and args[i] == ")":
                i += 1
            return res

        # Handle other unary operators
        if args[i] in ("DEFINED", "EXISTS", "COMMAND", "TARGET"):
            op = args[i]
            i += 1
            if i < len(args):
                val = args[i]
                i += 1
                if op == "DEFINED":
                    return is_defined(val)
                if op == "EXISTS":
                    return Path(val).exists()
                if op == "COMMAND":
                    # For now, just return False as we don't track all commands yet
                    return False
                if op == "TARGET":
                    return target_exists(val) if target_exists else False
            return False

        # Handle binary operators/comparisons
        left = args[i]
        i += 1
        if i < len(args) and args[i] in _BINARY_OPERATORS:
            op = args[i]
            i += 1
            if i < len(args):
                right = args[i]
                i += 1

                left_val = resolve(left)
                right_val = resolve(right)

                if op in _COMPARISONS:
                    left_num = _parse_number(left_val)
                    right_num = _parse_number(right_val)
                    if left_num is None or right_num is None:
                        return False
                    return _COMPARISONS[op](left_num, right_num)
                if op.startswith("STR"):
                    return _COMPARISONS[op[3:]](left_val, right_val)
                if op.startswith("VERSION_"):
                    compare = _COMPARISONS[op[8:]]
                    return compare(compare_versions(left_val, right_val), 0)
                if op == "IN_LIST":
                    # The right side always names a list variable.
                    items = variables.get(right)
                    if items is None or items == UNDEFINED_VAR_SENTINEL:
                        return False
                    return left_val in items.split(";")
                if op == "MATCHES":
                    match = re.search(cmake_regex_to_python(right_val), left_val)
                    if match:
                        variables["CMAKE_MATCH_0"] = match.group(0)
                        for idx, group in enumerate(match.groups(), start=1):
                            variables[f"CMAKE_MATCH_{idx}"] = group
                        return True
                    return False
            return False

        # Single value
        if left in variables:
            return is_truthy(resolve(left))
        return is_constant_truthy(left)

    return parse_or()


def find_else_or_elseif(
    commands: list[Command], start: int, end: int
) -> list[tuple[str, int, list[str]]]:
    """Find elseif/else blocks between if and endif, returns list of (type, index, args)."""
    blocks: list[tuple[str, int, list[str]]] = []
    depth = 0
    i = start + 1
    while i < end:
        if commands[i].name == "if":
            depth += 1
        elif commands[i].name == "endif":
            depth -= 1
        elif depth == 0:
            if commands[i].name == "elseif":
                blocks.append(("elseif", i, commands[i].args))
            elif commands[i].name == "else":
                blocks.append(("else", i, []))
        i += 1
    return blocks
