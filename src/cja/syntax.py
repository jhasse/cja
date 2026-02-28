from dataclasses import dataclass, field
from pathlib import Path
import re

from .parser import Command
from .utils import UNDEFINED_VAR_SENTINEL, is_constant_truthy, is_truthy


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


@dataclass
class Test:
    """A test definition."""

    name: str
    command: list[str]


def evaluate_condition(args: list[str], variables: dict[str, str]) -> bool:
    """Evaluate a CMake if() condition."""
    if not args:
        return False

    i = 0

    def is_defined(name: str) -> bool:
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
        if args[i] in ("DEFINED", "EXISTS", "COMMAND"):
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
            return False

        # Handle binary operators/comparisons
        left = args[i]
        i += 1
        if i < len(args) and args[i] in (
            "STREQUAL",
            "STRLESS",
            "STRGREATER",
            "EQUAL",
            "LESS",
            "GREATER",
            "MATCHES",
            "VERSION_EQUAL",
            "VERSION_LESS",
            "VERSION_GREATER",
        ):
            op = args[i]
            i += 1
            if i < len(args):
                right = args[i]
                i += 1

                left_val = resolve(left)
                right_val = resolve(right)

                if op == "STREQUAL":
                    return left_val == right_val
                if op == "STRLESS":
                    return left_val < right_val
                if op == "STRGREATER":
                    return left_val > right_val
                if op == "MATCHES":
                    match = re.search(right_val, left_val)
                    if match:
                        variables["CMAKE_MATCH_0"] = match.group(0)
                        for idx, group in enumerate(match.groups(), start=1):
                            variables[f"CMAKE_MATCH_{idx}"] = group
                        return True
                    return False
                if op in ("EQUAL", "LESS", "GREATER"):
                    try:
                        l_num = int(left_val)
                        r_num = int(right_val)
                        if op == "EQUAL":
                            return l_num == r_num
                        if op == "LESS":
                            return l_num < r_num
                        if op == "GREATER":
                            return l_num > r_num
                    except ValueError:
                        return False
                if op.startswith("VERSION_"):
                    # Simple version comparison by splitting on dots
                    def ver_to_tuple(v: str) -> tuple[int, ...]:
                        try:
                            return tuple(int(x) for x in re.split(r"[^0-9]", v) if x)
                        except ValueError:
                            return (0,)

                    l_ver = ver_to_tuple(left_val)
                    r_ver = ver_to_tuple(right_val)
                    if op == "VERSION_EQUAL":
                        return l_ver == r_ver
                    if op == "VERSION_LESS":
                        return l_ver < r_ver
                    if op == "VERSION_GREATER":
                        return l_ver > r_ver
            return False

        # Single value
        if left in variables:
            return is_truthy(resolve(left))
        return is_constant_truthy(left)  # noqa: F821

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
