"""Parsing and analysis of a single CMake file for the language server.

Nothing is executed: definitions, references and highlighting are derived
from the syntax alone, using the command signatures of ``cja format``.
"""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass, field
from functools import cached_property
from typing import Any

from ..format import (
    BRACKET,
    BRACKET_COMMENT,
    COMMENT,
    CUSTOM_PARSERS,
    LPAREN,
    NEWLINE,
    OTHER_BUILTINS,
    QUOTED,
    RPAREN,
    SPACE,
    UNQUOTED,
    Token,
    lex,
    parsed_argument_specs,
)
from ..format_specs import SPECS, SPECS_LOWER, CmdSpec, Shell

# Commands built into CMake (cmake --help-command-list), documented at
# https://cmake.org/cmake/help/latest/command/<name>.html
BUILTIN_COMMANDS = frozenset(
    {
        "add_compile_definitions", "add_compile_options", "add_custom_command",
        "add_custom_target", "add_definitions", "add_dependencies", "add_executable",
        "add_library", "add_link_options", "add_subdirectory", "add_test",
        "aux_source_directory", "block", "break", "build_command", "build_name",
        "cmake_file_api", "cmake_host_system_information", "cmake_instrumentation",
        "cmake_language", "cmake_minimum_required", "cmake_parse_arguments",
        "cmake_path", "cmake_pkg_config", "cmake_policy", "configure_file", "continue",
        "create_test_sourcelist", "ctest_build", "ctest_configure", "ctest_coverage",
        "ctest_empty_binary_directory", "ctest_memcheck", "ctest_read_custom_files",
        "ctest_run_script", "ctest_sleep", "ctest_start", "ctest_submit", "ctest_test",
        "ctest_update", "ctest_upload", "define_property", "else", "elseif",
        "enable_language", "enable_testing", "endblock", "endforeach", "endfunction",
        "endif", "endmacro", "endwhile", "exec_program", "execute_process", "export",
        "export_library_dependencies", "file", "find_file", "find_library",
        "find_package", "find_path", "find_program", "fltk_wrap_ui", "foreach",
        "function", "get_cmake_property", "get_directory_property",
        "get_filename_component", "get_property", "get_source_file_property",
        "get_target_property", "get_test_property", "if", "include",
        "include_directories", "include_external_msproject", "include_guard",
        "include_regular_expression", "install", "install_files", "install_programs",
        "install_targets", "link_directories", "link_libraries", "list", "load_cache",
        "load_command", "macro", "make_directory", "mark_as_advanced", "math",
        "message", "option", "output_required_files", "project", "qt_wrap_cpp",
        "qt_wrap_ui", "remove", "remove_definitions", "return", "separate_arguments",
        "set", "set_directory_properties", "set_property",
        "set_source_files_properties", "set_target_properties", "set_tests_properties",
        "site_name", "source_group", "string", "subdir_depends", "subdirs",
        "target_compile_definitions", "target_compile_features",
        "target_compile_options", "target_include_directories",
        "target_link_directories", "target_link_libraries", "target_link_options",
        "target_precompile_headers", "target_sources", "try_compile", "try_run",
        "unset", "use_mangled_mesa", "utility_source", "variable_requires",
        "variable_watch", "while", "write_file",
    }
)

# Lowercase name -> spelling of the commands CMake (and its modules) provide.
KNOWN_COMMANDS: dict[str, str] = {
    **{name: name for name in BUILTIN_COMMANDS},
    **{name: name for name in OTHER_BUILTINS},
    **{name: name for name in CUSTOM_PARSERS},
    **{name.lower(): name for name in SPECS},
}

CONTROL_COMMANDS = frozenset(
    {
        "if",
        "elseif",
        "else",
        "endif",
        "foreach",
        "endforeach",
        "while",
        "endwhile",
        "function",
        "endfunction",
        "macro",
        "endmacro",
        "block",
        "endblock",
        "return",
        "break",
        "continue",
    }
)
BLOCKS = {
    "if": "endif",
    "foreach": "endforeach",
    "while": "endwhile",
    "function": "endfunction",
    "macro": "endmacro",
    "block": "endblock",
}
_BLOCK_OPENERS = {closer: opener for opener, closer in BLOCKS.items()}

CONDITION_OPERATORS = frozenset(
    {
        "NOT",
        "AND",
        "OR",
        "COMMAND",
        "POLICY",
        "TARGET",
        "TEST",
        "DEFINED",
        "EXISTS",
        "IS_NEWER_THAN",
        "IS_DIRECTORY",
        "IS_SYMLINK",
        "IS_ABSOLUTE",
        "IS_READABLE",
        "IS_WRITABLE",
        "IS_EXECUTABLE",
        "MATCHES",
        "LESS",
        "GREATER",
        "EQUAL",
        "LESS_EQUAL",
        "GREATER_EQUAL",
        "STRLESS",
        "STRGREATER",
        "STREQUAL",
        "STRLESS_EQUAL",
        "STRGREATER_EQUAL",
        "VERSION_LESS",
        "VERSION_GREATER",
        "VERSION_EQUAL",
        "VERSION_LESS_EQUAL",
        "VERSION_GREATER_EQUAL",
        "PATH_EQUAL",
        "IN_LIST",
    }
)
_FOREACH_KEYWORDS = frozenset({"IN", "LISTS", "ITEMS", "ZIP_LISTS", "RANGE"})
CONSTANTS = frozenset(
    {"ON", "OFF", "TRUE", "FALSE", "YES", "NO", "Y", "N", "IGNORE", "NOTFOUND"}
)

TOKEN_TYPES = [
    "function",
    "macro",
    "keyword",
    "variable",
    "parameter",
    "string",
    "comment",
    "number",
    "enumMember",
    "class",
]
TOKEN_MODIFIERS = ["declaration", "defaultLibrary"]

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_NUMBER = re.compile(r"-?\d+(\.\d+)*")
_GUESSABLE_KEYWORD = re.compile(r"[A-Z][A-Z0-9_]+")
VARIABLE_REF = re.compile(r"(?<!\\)\$(ENV|CACHE)?\{([A-Za-z0-9_./+-]+)\}")

# Keywords whose value is the name of a variable that receives a result
_OUTPUT_KEYWORDS = frozenset(
    {
        "OUTPUT_VARIABLE",
        "RESULT_VARIABLE",
        "ERROR_VARIABLE",
        "RESULTS_VARIABLE",
        "COMPILE_OUTPUT_VARIABLE",
        "RUN_OUTPUT_VARIABLE",
    }
)
# Commands that set the variable named by their first argument
_FIRST_ARG_OUTPUT = frozenset(
    {
        "set",
        "option",
        "cmake_dependent_option",
        "find_program",
        "find_path",
        "find_file",
        "find_library",
        "get_filename_component",
        "get_property",
        "get_target_property",
        "get_directory_property",
        "get_source_file_property",
        "get_test_property",
        "get_cmake_property",
        "separate_arguments",
        "site_name",
        "try_compile",
        "try_run",
    }
)
# Commands that set the variable named by the argument at this index
_NTH_ARG_OUTPUT = {
    "math": 1,
    "aux_source_directory": 1,
    "check_include_file": 1,
    "check_include_files": 1,
    "check_include_file_cxx": 1,
    "check_function_exists": 1,
    "check_symbol_exists": 2,
    "check_cxx_symbol_exists": 2,
    "check_library_exists": 3,
    "check_c_source_compiles": 1,
    "check_cxx_source_compiles": 1,
    "check_c_source_runs": 1,
    "check_cxx_source_runs": 1,
    "check_c_compiler_flag": 1,
    "check_cxx_compiler_flag": 1,
    "check_compiler_flag": 2,
    "check_linker_flag": 2,
    "check_type_size": 1,
    "check_struct_has_member": 3,
}
# list(<subcommand> ...): index of the output variable, -1 for the last argument
_LIST_OUTPUT = {
    "LENGTH": -1,
    "GET": -1,
    "JOIN": -1,
    "SUBLIST": -1,
    "FIND": -1,
    **dict.fromkeys(
        (
            "APPEND",
            "PREPEND",
            "INSERT",
            "REMOVE_ITEM",
            "REMOVE_AT",
            "REMOVE_DUPLICATES",
            "FILTER",
            "TRANSFORM",
            "SORT",
            "REVERSE",
            "POP_BACK",
            "POP_FRONT",
        ),
        1,
    ),
}
_STRING_OUTPUT = {
    "REPLACE": 3,
    "CONCAT": 1,
    "APPEND": 1,
    "PREPEND": 1,
    "TOLOWER": 2,
    "TOUPPER": 2,
    "LENGTH": 2,
    "STRIP": 2,
    "GENEX_STRIP": 2,
    "MAKE_C_IDENTIFIER": 2,
    "HEX": 2,
    "SUBSTRING": 4,
    "FIND": 3,
    "COMPARE": 4,
    "JOIN": 2,
    "TIMESTAMP": 1,
    "UUID": 1,
    "RANDOM": -1,
    "REPEAT": 3,
    "CONFIGURE": 2,
    "ASCII": -1,
    "JSON": 1,
    **dict.fromkeys(
        ("MD5", "SHA1", "SHA224", "SHA256", "SHA384", "SHA512", "SHA3_256"), 1
    ),
}
_FILE_OUTPUT = {
    "GLOB": 1,
    "GLOB_RECURSE": 1,
    "READ": 2,
    "STRINGS": 2,
    "SIZE": 2,
    "TIMESTAMP": 2,
    "RELATIVE_PATH": 1,
    "TO_CMAKE_PATH": 2,
    "TO_NATIVE_PATH": 2,
    "REAL_PATH": 2,
    "READ_SYMLINK": 2,
    **dict.fromkeys(("MD5", "SHA1", "SHA224", "SHA256", "SHA384", "SHA512"), 2),
}

TARGET_COMMANDS = frozenset({"add_executable", "add_library", "add_custom_target"})


def utf16_len(text: str) -> int:
    return len(text) if text.isascii() else len(text.encode("utf-16-le")) // 2


class LineIndex:
    """Converts between offsets and LSP positions (UTF-16 based)."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.starts = [0] + [m.end() for m in re.finditer("\n", text)]

    def line_of(self, offset: int) -> int:
        return bisect.bisect_right(self.starts, offset) - 1

    def position(self, offset: int) -> dict[str, int]:
        line = self.line_of(offset)
        start = self.starts[line]
        return {"line": line, "character": utf16_len(self.text[start:offset])}

    def range(self, start: int, end: int) -> dict[str, dict[str, int]]:
        return {"start": self.position(start), "end": self.position(end)}

    def offset(self, position: dict[str, int]) -> int:
        line = position["line"]
        if line >= len(self.starts):
            return len(self.text)
        start = self.starts[line]
        end = self.starts[line + 1] - 1 if line + 1 < len(self.starts) else len(self.text)
        units = position["character"]
        offset = start
        while offset < end and units > 0:
            units -= 2 if ord(self.text[offset]) > 0xFFFF else 1
            offset += 1
        return offset


@dataclass
class Arg:
    token: Token
    # The text without quotes or brackets
    value: str

    @property
    def start(self) -> int:
        return self.token.start

    @property
    def end(self) -> int:
        return self.token.end

    @property
    def kind(self) -> str:
        return self.token.kind


@dataclass
class Statement:
    name: Token
    args: list[Arg]
    # Offset of "(" and after ")", or None if the call isn't closed
    open: int
    close: int | None

    @property
    def lower(self) -> str:
        return self.name.text.lower()

    @property
    def start(self) -> int:
        return self.name.start

    @property
    def end(self) -> int:
        if self.close is not None:
            return self.close
        return self.args[-1].end if self.args else self.open + 1


@dataclass
class Definition:
    name: str
    # "function", "macro", "variable", "parameter" or "target"
    kind: str
    start: int
    end: int
    statement: Statement
    # Where a function parameter or loop variable is visible
    scope: tuple[int, int] | None = None
    # Not spelled out at the location, like the <prefix>_<keyword> variables of
    # cmake_parse_arguments()
    implicit: bool = False


@dataclass
class Reference:
    name: str
    # "command" or "variable"
    kind: str
    start: int
    end: int


@dataclass
class Diagnostic:
    start: int
    end: int
    message: str
    # 1 = error, 2 = warning, 3 = information
    severity: int = 1


@dataclass
class Block:
    opener: Statement
    closer: Statement


@dataclass
class ParsedFile:
    text: str
    index: LineIndex
    statements: list[Statement] = field(default_factory=list[Statement])
    comments: list[Token] = field(default_factory=list[Token])
    diagnostics: list[Diagnostic] = field(default_factory=list[Diagnostic])
    blocks: list[Block] = field(default_factory=list[Block])
    definitions: list[Definition] = field(default_factory=list[Definition])
    references: list[Reference] = field(default_factory=list[Reference])
    # Output variable arguments, by (statement index, argument index)
    outputs: set[tuple[int, int]] = field(default_factory=set[tuple[int, int]])
    # Arguments that name variables that are read, like in if()
    variable_args: set[tuple[int, int]] = field(default_factory=set[tuple[int, int]])

    @cached_property
    def command_specs(self) -> dict[str, CmdSpec]:
        """Formatter specs of the functions and macros using cmake_parse_arguments."""
        return parsed_argument_specs(
            (stmt.name, [arg.token for arg in stmt.args]) for stmt in self.statements
        )

    def statement_at(self, offset: int) -> Statement | None:
        """Return the statement whose text contains the offset."""
        for stmt in self.statements:
            if stmt.start <= offset <= stmt.end:
                return stmt
            if stmt.start > offset:
                break
        return None

    def scopes_at(self, offset: int) -> list[Definition]:
        """Return the parameters and loop variables visible at the offset."""
        return [
            d
            for d in self.definitions
            if d.scope is not None and d.scope[0] <= offset <= d.scope[1]
        ]


def _arg_value(token: Token) -> str:
    if token.kind == QUOTED:
        return token.text[1:-1]
    if token.kind == BRACKET:
        equals = token.text.index("[", 1) - 1
        return token.text[equals + 2 : len(token.text) - equals - 2].removeprefix("\n")
    return token.text


def parse(text: str) -> ParsedFile:
    """Parse CMake source (with any line endings) into a ParsedFile."""
    text = text.replace("\r\n", "\n")
    result = ParsedFile(text, LineIndex(text))
    try:
        tokens = lex(text, "")
    except SyntaxError as e:
        line = (e.lineno or 1) - 1
        offset = result.index.starts[min(line, len(result.index.starts) - 1)]
        offset += (e.offset or 1) - 1
        result.diagnostics.append(Diagnostic(offset, len(text), e.msg))
        # Analyze what comes before the error
        tokens = lex(text[:offset], "")

    i = 0
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        if tok.kind in (NEWLINE, SPACE):
            i += 1
        elif tok.kind in (COMMENT, BRACKET_COMMENT):
            result.comments.append(tok)
            i += 1
        elif tok.kind == UNQUOTED and _IDENTIFIER.fullmatch(tok.text):
            j = i + 1
            while j < n and tokens[j].kind == SPACE:
                j += 1
            if j >= n or tokens[j].kind != LPAREN:
                result.diagnostics.append(
                    Diagnostic(tok.start, tok.end, f"Expected '(' after {tok.text}")
                )
                i = _next_line(tokens, i)
                continue
            open_offset = tokens[j].start
            args: list[Arg] = []
            depth = 1
            k = j + 1
            while k < n:
                arg = tokens[k]
                if arg.kind == LPAREN:
                    depth += 1
                elif arg.kind == RPAREN:
                    depth -= 1
                    if depth == 0:
                        break
                elif arg.kind in (COMMENT, BRACKET_COMMENT):
                    result.comments.append(arg)
                elif arg.kind not in (NEWLINE, SPACE):
                    args.append(Arg(arg, _arg_value(arg)))
                k += 1
            if k < n:
                result.statements.append(Statement(tok, args, open_offset, tokens[k].end))
            else:
                if not result.diagnostics:
                    result.diagnostics.append(
                        Diagnostic(tok.start, tok.end, f"Missing ')' for {tok.text}(")
                    )
                result.statements.append(Statement(tok, args, open_offset, None))
            i = k + 1
        else:
            result.diagnostics.append(
                Diagnostic(tok.start, tok.end, f"Expected a command, got {tok.text!r}")
            )
            i = _next_line(tokens, i)

    _match_blocks(result)
    _collect_symbols(result)
    return result


def _next_line(tokens: list[Token], i: int) -> int:
    """Skip the rest of the line after a syntax error."""
    while i < len(tokens) and tokens[i].kind != NEWLINE:
        i += 1
    return i


def _match_blocks(result: ParsedFile) -> None:
    stack: list[Statement] = []
    for stmt in result.statements:
        lower = stmt.lower
        if lower in BLOCKS:
            stack.append(stmt)
        elif lower in ("elseif", "else"):
            if not stack or stack[-1].lower != "if":
                result.diagnostics.append(
                    Diagnostic(stmt.name.start, stmt.name.end, f"{lower}() without if()")
                )
        elif lower in _BLOCK_OPENERS:
            opener = _BLOCK_OPENERS[lower]
            if not any(s.lower == opener for s in stack):
                result.diagnostics.append(
                    Diagnostic(stmt.name.start, stmt.name.end, f"{lower}() without {opener}()")
                )
                continue
            while stack[-1].lower != opener:
                _unclosed(result, stack.pop())
            result.blocks.append(Block(stack.pop(), stmt))
    for stmt in stack:
        _unclosed(result, stmt)


def _unclosed(result: ParsedFile, stmt: Statement) -> None:
    closer = BLOCKS[stmt.lower]
    result.diagnostics.append(
        Diagnostic(stmt.name.start, stmt.name.end, f"{stmt.lower}() without {closer}()")
    )


def _output_indices(stmt: Statement) -> list[int]:
    """Return the indices of arguments that name variables the command sets."""
    lower = stmt.lower
    values = [arg.value for arg in stmt.args]
    if not values:
        return []
    indices: list[int] = []
    if lower in _FIRST_ARG_OUTPUT:
        indices.append(0)
    elif lower in _NTH_ARG_OUTPUT:
        indices.append(_NTH_ARG_OUTPUT[lower])
    elif lower in ("foreach", "list", "string", "file") and len(values) >= 2:
        sub = values[0].upper()
        if lower == "foreach":
            indices.append(0)
        elif lower == "list":
            indices.append(_LIST_OUTPUT.get(sub, -100))
        elif lower == "file":
            indices.append(_FILE_OUTPUT.get(sub, -100))
        elif sub == "REGEX":
            indices.append(3)
        else:
            indices.append(_STRING_OUTPUT.get(sub, -100))
    for idx, value in enumerate(values[:-1]):
        if value in _OUTPUT_KEYWORDS:
            indices.append(idx + 1)
    count = len(values)
    return sorted({i % count for i in indices if -count <= i < count})


def _collect_symbols(result: ParsedFile) -> None:
    """Collect definitions and references of functions, variables and targets."""
    body_end: dict[int, int] = {}
    for block in result.blocks:
        body_end[id(block.opener)] = block.closer.start
    # Literal values of set(), to look up keyword lists of cmake_parse_arguments
    literal_sets: dict[str, list[str]] = {}

    for stmt_idx, stmt in enumerate(result.statements):
        lower = stmt.lower
        args = stmt.args
        result.references.append(
            Reference(lower, "command", stmt.name.start, stmt.name.end)
        )
        if lower in ("function", "macro") and args:
            name = args[0]
            result.definitions.append(
                Definition(name.value, lower, name.start, name.end, stmt)
            )
            scope = (stmt.end, body_end.get(id(stmt), len(result.text)))
            for param in args[1:]:
                result.definitions.append(
                    Definition(param.value, "parameter", param.start, param.end, stmt, scope)
                )
            continue
        if lower in TARGET_COMMANDS and args:
            name = args[0]
            result.definitions.append(
                Definition(name.value, "target", name.start, name.end, stmt)
            )

        for idx in _output_indices(stmt):
            arg = args[idx]
            if arg.kind == UNQUOTED and "${" not in arg.value:
                scope = None
                if lower == "foreach":
                    scope = (stmt.end, body_end.get(id(stmt), len(result.text)))
                result.definitions.append(
                    Definition(arg.value, "variable", arg.start, arg.end, stmt, scope)
                )
                result.outputs.add((stmt_idx, idx))
        if lower == "set" and args and all("${" not in a.value for a in args[1:]):
            literal_sets[args[0].value] = [
                v for a in args[1:] for v in a.value.split(";") if v
            ]
        if lower == "cmake_parse_arguments":
            _parse_arguments_definitions(result, stmt, literal_sets)

        for idx in _variable_name_indices(stmt):
            result.variable_args.add((stmt_idx, idx))
        for idx, arg in enumerate(args):
            if arg.kind == BRACKET:
                continue
            for m in VARIABLE_REF.finditer(arg.token.text):
                if m.group(1) != "ENV":
                    result.references.append(
                        Reference(
                            m.group(2),
                            "variable",
                            arg.start + m.start(2),
                            arg.start + m.end(2),
                        )
                    )
            if (stmt_idx, idx) in result.outputs | result.variable_args:
                result.references.append(
                    Reference(arg.value, "variable", arg.start, arg.end)
                )


def _is_variable_name(arg: Arg) -> bool:
    return (
        arg.kind == UNQUOTED
        and bool(_IDENTIFIER.fullmatch(arg.value))
        and arg.value not in CONDITION_OPERATORS
        and arg.value.upper() not in CONSTANTS
    )


def _variable_name_indices(stmt: Statement) -> list[int]:
    """Return the indices of arguments that name variables which are read."""
    lower = stmt.lower
    args = stmt.args
    if lower in ("if", "elseif", "while"):
        return [i for i, arg in enumerate(args) if _is_variable_name(arg)]
    if lower == "foreach":
        # foreach(<var> IN LISTS <lists>... ITEMS <items>...)
        values = [arg.value for arg in args]
        if "LISTS" not in values:
            return []
        start = values.index("LISTS") + 1
        end = values.index("ITEMS") if "ITEMS" in values[start:] else len(values)
        return [i for i in range(start, end) if _is_variable_name(args[i])]
    if lower == "list" and len(args) >= 2 and _is_variable_name(args[1]):
        return [1]
    return []


def _parse_arguments_definitions(
    result: ParsedFile, stmt: Statement, literal_sets: dict[str, list[str]]
) -> None:
    """Add the <prefix>_<keyword> variables that cmake_parse_arguments() sets."""
    args = stmt.args
    first = 2 if args and args[0].value == "PARSE_ARGV" else 0
    if len(args) < first + 4:
        return
    prefix = args[first]
    keywords: list[str] = ["UNPARSED_ARGUMENTS", "KEYWORDS_MISSING_VALUES"]
    for arg in args[first + 1 : first + 4]:
        value = VARIABLE_REF.sub(
            lambda m: ";".join(literal_sets.get(m.group(2), [])), arg.value
        )
        keywords.extend(v for v in value.split(";") if v)
    for keyword in keywords:
        result.definitions.append(
            Definition(
                f"{prefix.value}_{keyword}",
                "variable",
                prefix.start,
                prefix.end,
                stmt,
                implicit=True,
            )
        )


def _spec_keywords(cmd: CmdSpec) -> set[str]:
    keywords: set[str] = set()
    for pspec in cmd.pargs:
        keywords.update(pspec.flags)
    for keyword, value in cmd.kwargs.items():
        keywords.add(keyword)
        if isinstance(value, CmdSpec):
            keywords |= _spec_keywords(value)
        elif isinstance(value, Shell):
            keywords.update(value.kwargs)
    return keywords


_KEYWORDS: dict[str, frozenset[str]] = {
    name: frozenset(_spec_keywords(cmd)) for name, cmd in SPECS_LOWER.items()
}


def command_keywords(lower: str) -> frozenset[str] | None:
    """Return the keywords of a command, or None if they aren't known."""
    return _KEYWORDS.get(lower)


def semantic_tokens(
    parsed: ParsedFile, functions: dict[str, str], targets: set[str]
) -> list[int]:
    """Return the encoded semantic tokens of a file.

    ``functions`` maps lowercase names of user-defined commands to "function"
    or "macro", ``targets`` are the names of all known targets.
    """
    spans: list[tuple[int, int, str, int]] = []
    declaration = 1 << TOKEN_MODIFIERS.index("declaration")
    default_library = 1 << TOKEN_MODIFIERS.index("defaultLibrary")

    for comment in parsed.comments:
        spans.append((comment.start, comment.end, "comment", 0))

    for stmt_idx, stmt in enumerate(parsed.statements):
        lower = stmt.lower
        name = stmt.name
        if lower in CONTROL_COMMANDS:
            spans.append((name.start, name.end, "keyword", 0))
        elif lower in functions:
            spans.append((name.start, name.end, functions[lower], 0))
        elif lower in KNOWN_COMMANDS:
            spans.append((name.start, name.end, "function", default_library))
        else:
            spans.append((name.start, name.end, "function", 0))

        params = {d.name for d in parsed.scopes_at(stmt.start) if d.kind == "parameter"}
        keywords = command_keywords(lower)
        control_keywords: frozenset[str] = frozenset()
        if lower in ("if", "elseif", "while"):
            control_keywords = CONDITION_OPERATORS
        elif lower == "foreach":
            control_keywords = _FOREACH_KEYWORDS
        for idx, arg in enumerate(stmt.args):
            value = arg.value
            if lower in ("function", "macro"):
                kind = (lower if idx == 0 else "parameter") if arg.kind == UNQUOTED else None
                if kind:
                    spans.append((arg.start, arg.end, kind, declaration))
                    continue
            if arg.kind == BRACKET:
                spans.append((arg.start, arg.end, "string", 0))
                continue
            if (stmt_idx, idx) in parsed.outputs:
                kind = "parameter" if value in params else "variable"
                spans.append((arg.start, arg.end, kind, declaration))
                continue
            if arg.kind == UNQUOTED:
                kind = None
                if value.upper() in CONSTANTS or value.endswith("-NOTFOUND"):
                    kind = "enumMember"
                elif _NUMBER.fullmatch(value):
                    kind = "number"
                elif value in control_keywords:
                    kind = "keyword"
                elif (stmt_idx, idx) in parsed.variable_args:
                    kind = "parameter" if value in params else "variable"
                elif (
                    value in keywords
                    if keywords is not None
                    else _GUESSABLE_KEYWORD.fullmatch(value)
                ):
                    kind = "keyword"
                elif value in targets:
                    kind = "class"
                if kind:
                    spans.append((arg.start, arg.end, kind, 0))
                    continue
            # Variable references, and the rest of a quoted argument as string
            pos = arg.start
            for m in VARIABLE_REF.finditer(arg.token.text):
                ref_start = arg.start + m.start()
                if arg.kind == QUOTED and ref_start > pos:
                    spans.append((pos, ref_start, "string", 0))
                kind = "parameter" if m.group(2) in params else "variable"
                spans.append((ref_start, arg.start + m.end(), kind, 0))
                pos = arg.start + m.end()
            if arg.kind == QUOTED and pos < arg.end:
                spans.append((pos, arg.end, "string", 0))

    return _encode(parsed, sorted(spans))


def _encode(parsed: ParsedFile, spans: list[tuple[int, int, str, int]]) -> list[int]:
    """Encode spans as LSP semantic tokens, split at line ends."""
    data: list[int] = []
    prev_line = 0
    prev_char = 0
    text = parsed.text
    index = parsed.index
    for start, end, kind, modifiers in spans:
        type_index = TOKEN_TYPES.index(kind)
        while start < end:
            line_end = text.find("\n", start, end)
            piece_end = end if line_end == -1 else line_end
            if piece_end > start:
                pos = index.position(start)
                length = utf16_len(text[start:piece_end])
                delta_line = pos["line"] - prev_line
                delta_char = pos["character"] - (prev_char if delta_line == 0 else 0)
                data += [delta_line, delta_char, length, type_index, modifiers]
                prev_line = pos["line"]
                prev_char = pos["character"]
            start = piece_end + 1 if line_end != -1 else end
    return data


def folding_ranges(parsed: ParsedFile) -> list[dict[str, Any]]:
    ranges: list[dict[str, Any]] = []
    index = parsed.index
    for block in parsed.blocks:
        start = index.line_of(block.opener.start)
        end = index.line_of(block.closer.start) - 1
        if end > start:
            ranges.append({"startLine": start, "endLine": end})
    for stmt in parsed.statements:
        start = index.line_of(stmt.start)
        end = index.line_of(stmt.end)
        if end > start and stmt.lower not in BLOCKS:
            ranges.append({"startLine": start, "endLine": end})
    # Runs of line comments
    run: list[int] = []
    for comment in parsed.comments:
        line = index.line_of(comment.start)
        if comment.kind == COMMENT and run and line == run[-1] + 1:
            run.append(line)
            continue
        if len(run) > 1:
            ranges.append({"startLine": run[0], "endLine": run[-1], "kind": "comment"})
        run = [line] if comment.kind == COMMENT else []
    if len(run) > 1:
        ranges.append({"startLine": run[0], "endLine": run[-1], "kind": "comment"})
    return ranges


# LSP SymbolKind values
_SYMBOL_KINDS = {"function": 12, "macro": 12, "target": 5, "option": 17, "project": 4}


def document_symbols(parsed: ParsedFile) -> list[dict[str, Any]]:
    symbols: list[dict[str, Any]] = []
    index = parsed.index
    for stmt in parsed.statements:
        lower = stmt.lower
        if not stmt.args:
            continue
        name = stmt.args[0]
        if lower in ("function", "macro"):
            kind, detail = lower, lower
        elif lower in TARGET_COMMANDS:
            kind = "target"
            detail = lower.removeprefix("add_").replace("_", " ")
        elif lower == "option":
            kind, detail = "option", "option"
        elif lower == "project":
            kind, detail = "project", "project"
        else:
            continue
        end = stmt.end
        if lower in ("function", "macro"):
            end = next(
                (b.closer.end for b in parsed.blocks if b.opener is stmt), stmt.end
            )
        symbols.append(
            {
                "name": name.value,
                "detail": detail,
                "kind": _SYMBOL_KINDS[kind],
                "range": index.range(stmt.start, end),
                "selectionRange": index.range(name.start, name.end),
            }
        )
    return symbols
