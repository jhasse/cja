"""Formatter for CMake files (``cja format``).

The layout algorithm follows cmake-format: the arguments of each command are
grouped into positional and keyword groups, and every group tries a series of
increasingly vertical layouts until one fits. There is no configuration file;
indentation, column limit, blank lines and line endings are read from the
nearest ``.clang-format``, everything else uses cmake-format's defaults.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from .format_specs import SHELL, SPECS_LOWER, CmdSpec, PSpec, Shell, spec

# ---------------------------------------------------------------------------
# Style (.clang-format)
# ---------------------------------------------------------------------------


@dataclass
class Style:
    """Formatting options. The first block is read from .clang-format."""

    line_width: int = 80
    indent_width: int = 2
    tab_width: int = 8
    use_tab: str = "Never"
    max_empty_lines: int = 1
    line_ending: str = "DeriveLF"
    disable: bool = False

    # cmake-format defaults, not configurable.
    max_subgroups_hwrap: int = 2
    max_pargs_hwrap: int = 6
    max_rows_cmdline: int = 2
    min_prefix_chars: int = 4
    max_prefix_chars: int = 10
    max_lines_hwrap: int = 2

    # Lowercase the names of known commands (cmake-format's "canonical").
    canonical_case: bool = True
    # Treat UPPERCASE words as keywords in calls to unknown commands.
    guess_keywords: bool = True


# Defaults of the predefined clang-format styles that matter to us.
_BASE_STYLES: dict[str, dict[str, str]] = {
    "llvm": {},
    "google": {},
    "chromium": {},
    "mozilla": {},
    "webkit": {"ColumnLimit": "0", "IndentWidth": "4"},
    "microsoft": {"ColumnLimit": "120", "IndentWidth": "4"},
    "gnu": {"ColumnLimit": "79"},
}


def parse_clang_format(text: str) -> list[dict[str, str]]:
    """Parse the top-level scalar keys of each YAML document in a .clang-format.

    Nested mappings and lists are skipped; none of the keys we use need them.
    """
    docs: list[dict[str, str]] = [{}]
    for raw_line in text.splitlines():
        if raw_line.startswith("---"):
            if docs[-1]:
                docs.append({})
            continue
        if raw_line.startswith("..."):
            break
        if not raw_line or raw_line[0] in " \t#-":
            continue
        key, sep, value = raw_line.partition(":")
        if not sep:
            continue
        value = value.strip()
        if value.startswith(("'", '"')):
            quote = value[0]
            end = value.find(quote, 1)
            value = value[1:end] if end != -1 else value[1:]
        else:
            value = value.split(" #", 1)[0].strip()
        docs[-1][key.strip()] = value
    return [d for d in docs if d] or [{}]


def _select_document(docs: list[dict[str, str]]) -> dict[str, str]:
    """Pick the section that applies to CMake files.

    clang-format has no CMake language, so prefer the section without a
    ``Language`` key (applies to all languages), then the C++ one.
    """
    for doc in docs:
        if "Language" not in doc:
            return doc
    for doc in docs:
        if doc.get("Language") == "Cpp":
            return doc
    return docs[0]


def _apply_clang_format(style: Style, options: dict[str, str]) -> None:
    def as_int(key: str) -> int | None:
        try:
            return int(options[key])
        except (KeyError, ValueError):
            return None

    if (value := as_int("ColumnLimit")) is not None:
        style.line_width = value if value > 0 else sys.maxsize
    if (value := as_int("IndentWidth")) is not None and value > 0:
        style.indent_width = value
    if (value := as_int("TabWidth")) is not None and value > 0:
        style.tab_width = value
    if (value := as_int("MaxEmptyLinesToKeep")) is not None and value >= 0:
        style.max_empty_lines = value
    if "UseTab" in options:
        use_tab = options["UseTab"]
        style.use_tab = {"true": "Always", "false": "Never"}.get(
            use_tab.lower(), use_tab
        )
    if "LineEnding" in options:
        style.line_ending = options["LineEnding"]
    elif "UseCRLF" in options or "DeriveLineEnding" in options:
        crlf = options.get("UseCRLF", "false").lower() == "true"
        derive = options.get("DeriveLineEnding", "true").lower() == "true"
        style.line_ending = ("Derive" if derive else "") + ("CRLF" if crlf else "LF")
    if "DisableFormat" in options:
        style.disable = options["DisableFormat"].lower() == "true"


def _style_from_file(path: Path) -> Style:
    try:
        options = _select_document(parse_clang_format(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeDecodeError):
        return Style()
    based_on = options.get("BasedOnStyle", "LLVM")
    if based_on.lower() == "inheritparentconfig":
        style = find_style(path.parent.parent)
    else:
        style = Style()
        _apply_clang_format(style, _BASE_STYLES.get(based_on.lower(), {}))
    _apply_clang_format(style, options)
    return style


def find_style(directory: Path) -> Style:
    """Return the style from the nearest .clang-format in directory or above."""
    directory = directory.resolve()
    for d in (directory, *directory.parents):
        for name in (".clang-format", "_clang-format"):
            candidate = d / name
            if candidate.is_file():
                return _style_from_file(candidate)
    return Style()


# ---------------------------------------------------------------------------
# Lexer
# ---------------------------------------------------------------------------

NEWLINE = "newline"
SPACE = "space"
COMMENT = "comment"
BRACKET_COMMENT = "bracket_comment"
LPAREN = "lparen"
RPAREN = "rparen"
QUOTED = "quoted"
BRACKET = "bracket"
UNQUOTED = "unquoted"

_BRACKET_OPEN = re.compile(r"\[(=*)\[")


@dataclass
class Token:
    kind: str
    text: str
    line: int
    col: int
    start: int
    end: int


def lex(src: str, filename: str, tab_width: int = 8) -> list[Token]:
    """Split CMake source (with \\n line endings) into tokens, losslessly.

    The column of comments is visual (tabs expanded), as it's used to detect
    aligned comment lines.
    """
    tokens: list[Token] = []
    n = len(src)
    i = 0
    line = 1
    line_start = 0

    while i < n:
        start = i
        start_line = line
        col = i - line_start
        c = src[i]
        if c == "\n":
            kind = NEWLINE
            i += 1
        elif c in " \t" or (c == "\\" and src.startswith("\\\n", i)):
            kind = SPACE
            while i < n and (src[i] in " \t" or src.startswith("\\\n", i)):
                i += 2 if src[i] == "\\" else 1
        elif c == "#":
            m = _BRACKET_OPEN.match(src, i + 1)
            if m:
                close = src.find("]" + m.group(1) + "]", m.end())
                i = n if close == -1 else close + len(m.group(1)) + 2
                kind = BRACKET_COMMENT
            else:
                end = src.find("\n", i)
                i = n if end == -1 else end
                kind = COMMENT
                col = len(src[line_start:start].expandtabs(tab_width))
        elif c == "(":
            kind = LPAREN
            i += 1
        elif c == ")":
            kind = RPAREN
            i += 1
        elif c == '"':
            i += 1
            while i < n and src[i] != '"':
                i += 2 if src[i] == "\\" else 1
            if i >= n:
                raise SyntaxError(
                    "Unterminated quoted argument", (filename, start_line, col + 1, "")
                )
            i += 1
            kind = QUOTED
        elif (m := _BRACKET_OPEN.match(src, i)) and (
            close := src.find("]" + m.group(1) + "]", m.end())
        ) != -1:
            i = close + len(m.group(1)) + 2
            kind = BRACKET
        else:
            kind = UNQUOTED
            genex_depth = 0
            while i < n:
                ch = src[i]
                if src.startswith("$<", i):
                    genex_depth += 1
                    i += 2
                elif ch == ">" and genex_depth > 0:
                    genex_depth -= 1
                    i += 1
                elif ch == "\\" and i + 1 < n:
                    i += 2
                elif ch == '"':
                    # Legacy unquoted argument such as -DFOO="a b"
                    end = src.find('"', i + 1)
                    while end != -1 and src[end - 1] == "\\":
                        end = src.find('"', end + 1)
                    if end == -1 or "\n" in src[i:end]:
                        i += 1
                    else:
                        i = end + 1
                elif ch in "()#" or (ch in " \t\n" and genex_depth == 0):
                    # Like cja's parser, whitespace inside $<...> doesn't split
                    break
                else:
                    i += 1
            # An unterminated $<...> stopped by a comment or parenthesis
            while genex_depth and src[i - 1] in " \t\n" and src[i - 2] != "\\":
                i -= 1
        text = src[start:i]
        newlines = text.count("\n")
        if newlines:
            line += newlines
            line_start = start + text.rfind("\n") + 1
        tokens.append(Token(kind, text, start_line, col, start, i))
    return tokens


# ---------------------------------------------------------------------------
# Body-level structure
# ---------------------------------------------------------------------------


@dataclass
class Statement:
    name: Token
    args: list[Token]
    blank_before: int
    trailing: list[str] | None = None
    # Inside a "cmake-format: off" region: only tracked for indentation.
    disabled: bool = False


@dataclass
class CommentBlock:
    text: str
    blank_before: int


@dataclass
class RawText:
    lines: list[str]
    blank_before: int = 0


BodyItem = Statement | CommentBlock | RawText

_SWITCH = re.compile(
    r"#\s*(?:cmake-format|cmf|clang-format)\s*:?\s*(on|off)\b", re.IGNORECASE
)


def _switch(token: Token) -> str | None:
    if token.kind != COMMENT:
        return None
    m = _SWITCH.match(token.text)
    return m.group(1).lower() if m else None


def parse_body(tokens: list[Token], src: str, filename: str) -> list[BodyItem]:
    """Split the token stream into statements, comments and blank lines."""
    items: list[BodyItem] = []
    newlines = 0
    disabled_from: Token | None = None
    i = 0
    n = len(tokens)

    def blank() -> int:
        return max(0, newlines - 1) if items else 0

    while i < n:
        tok = tokens[i]
        if tok.kind == NEWLINE:
            newlines += 1
            i += 1
        elif tok.kind == SPACE:
            i += 1
        elif tok.kind in (COMMENT, BRACKET_COMMENT):
            last = items[-1] if items else None
            switch = _switch(tok)
            if disabled_from is not None and switch != "on":
                pass  # copied verbatim with the rest of the disabled region
            elif (
                isinstance(last, Statement)
                and newlines == 0
                and last.trailing is None
                and switch is None
            ):
                last.trailing = [tok.text.rstrip()]
                # Following comment lines aligned with this one continue it.
                j = i + 1
                while (
                    j + 1 < n
                    and tokens[j].kind == NEWLINE
                    and (k := j + 1 + (tokens[j + 1].kind == SPACE)) < n
                    and tokens[k].kind == COMMENT
                    and tokens[k].col == tok.col
                    and _switch(tokens[k]) is None
                ):
                    last.trailing.append(tokens[k].text.rstrip())
                    i = j = k
                    j += 1
            elif switch == "off" and disabled_from is None:
                items.append(CommentBlock(tok.text.rstrip(), blank()))
                disabled_from = tok
            elif switch == "on" and disabled_from is not None:
                first = src.find("\n", disabled_from.end) + 1
                end = src.rfind("\n", 0, tok.start) + 1
                raw = src[first:end] if 0 < first <= end else ""
                items.append(RawText(raw.split("\n")[:-1]))
                items.append(CommentBlock(tok.text.rstrip(), 0))
                disabled_from = None
            else:
                text = tok.text.rstrip() if tok.kind == COMMENT else tok.text
                items.append(CommentBlock(text, blank()))
            newlines = 0
            i += 1
        elif tok.kind == UNQUOTED:
            i += 1
            while i < n and tokens[i].kind in (SPACE, NEWLINE):
                i += 1
            if i >= n or tokens[i].kind != LPAREN:
                if re.fullmatch(r"@\w+@", tok.text):
                    # @PACKAGE_INIT@ and friends in configure_file() templates
                    items.append(RawText([tok.text], blank()))
                    newlines = 0
                    continue
                raise SyntaxError(
                    f"Expected '(' after command '{tok.text}'",
                    (filename, tok.line, tok.col + 1, ""),
                )
            i += 1
            depth = 1
            args: list[Token] = []
            while i < n:
                t = tokens[i]
                if t.kind == LPAREN:
                    depth += 1
                elif t.kind == RPAREN:
                    depth -= 1
                    if depth == 0:
                        break
                if t.kind != SPACE:
                    args.append(t)
                i += 1
            if i >= n:
                raise SyntaxError(
                    f"Expected ')' for command '{tok.text}'",
                    (filename, tok.line, tok.col + 1, ""),
                )
            i += 1
            items.append(
                Statement(tok, args, blank(), disabled=disabled_from is not None)
            )
            newlines = 0
        else:
            raise SyntaxError(
                f"Unexpected '{tok.text.splitlines()[0]}'",
                (filename, tok.line, tok.col + 1, ""),
            )

    if disabled_from is not None:
        first = src.find("\n", disabled_from.end) + 1
        raw = src[first:] if first > 0 else ""
        items.append(RawText(raw.rstrip("\n").split("\n") if raw.strip("\n") else []))
    return items


# ---------------------------------------------------------------------------
# Argument atoms
# ---------------------------------------------------------------------------


@dataclass
class Atom:
    """An argument, parenthesis or comment inside a command invocation."""

    kind: str
    text: str
    col: int = 0
    # Comment lines on the same line after this argument or ")"
    trailing: list[str] | None = None

    @property
    def word(self) -> str | None:
        """Uppercase spelling if this can be a keyword, ")" for parentheses."""
        if self.kind == UNQUOTED:
            return self.text.upper()
        if self.kind == RPAREN:
            return ")"
        return None


def make_atoms(tokens: list[Token]) -> list[Atom]:
    atoms: list[Atom] = []
    newline_seen = True
    last_comment: Token | None = None
    for tok in tokens:
        if tok.kind == NEWLINE:
            if newline_seen:
                last_comment = None
            newline_seen = True
            continue
        if tok.kind == COMMENT:
            prev = atoms[-1] if atoms else None
            text = tok.text.rstrip()
            if prev is not None and prev.kind != COMMENT and not newline_seen:
                if prev.trailing is None:
                    prev.trailing = []
                prev.trailing.append(text)
                last_comment = tok
            elif (
                prev is not None
                and prev.trailing is not None
                and last_comment is not None
                and last_comment.col == tok.col
            ):
                # Continuation of an aligned trailing comment
                prev.trailing.append(text)
                last_comment = tok
            else:
                atoms.append(Atom(COMMENT, text, tok.col))
                last_comment = None
            newline_seen = False
            continue
        atoms.append(Atom(tok.kind, tok.text, tok.col))
        newline_seen = False
        last_comment = None
    return atoms


class Stream:
    def __init__(self, atoms: list[Atom]) -> None:
        self.atoms = atoms
        self.pos = 0

    def __bool__(self) -> bool:
        return self.pos < len(self.atoms)

    def peek(self) -> Atom:
        return self.atoms[self.pos]

    def pop(self) -> Atom:
        atom = self.atoms[self.pos]
        self.pos += 1
        return atom

    def next_semantic(self) -> Atom | None:
        for atom in self.atoms[self.pos :]:
            if atom.kind not in (COMMENT, BRACKET_COMMENT):
                return atom
        return None


# ---------------------------------------------------------------------------
# Layout tree
# ---------------------------------------------------------------------------

Cursor = tuple[int, int]


class Canvas:
    """Collects text placed at (row, column) positions."""

    def __init__(self) -> None:
        self.rows: dict[int, list[tuple[int, str]]] = {}
        # Rows starting with the continuation of a multi-line token
        self.raw_rows: set[int] = set()

    def put(self, cursor: Cursor, text: str) -> None:
        row, col = cursor
        parts = text.split("\n")
        self.rows.setdefault(row, []).append((col, parts[0]))
        for k, part in enumerate(parts[1:], 1):
            self.rows.setdefault(row + k, []).append((0, part))
            self.raw_rows.add(row + k)

    def lines(self) -> list[tuple[str, bool]]:
        result: list[tuple[str, bool]] = []
        for row in range(max(self.rows) + 1 if self.rows else 0):
            line = ""
            for col, text in sorted(self.rows.get(row, []), key=lambda p: p[0]):
                if col > len(line):
                    line += " " * (col - len(line))
                line += text
            result.append((line, row in self.raw_rows))
        return result


class Node:
    """Layout node. Mirrors cmake-format's layout passes."""

    passes: tuple[tuple[int, bool], ...] = ((0, False),)

    def __init__(self) -> None:
        self.pos: Cursor = (0, 0)
        self.colextent = 0
        self.valid = True
        self.wrap = False
        self.statement_terminal = False

    def has_terminal_comment(self) -> bool:
        return False

    def reflow(self, style: Style, cursor: Cursor, parent_passno: int = 0) -> Cursor:
        self.pos = cursor
        out = cursor
        for passno, wrap in self.passes:
            if passno > parent_passno:
                break
            self.wrap = wrap
            self.valid = True
            out = self._reflow(style, cursor, passno)
            self.valid = self.valid and self._validate(
                style, cursor, (out[0], self.colextent)
            )
            if self.valid:
                break
        return out

    def _reflow(self, style: Style, cursor: Cursor, passno: int) -> Cursor:
        raise NotImplementedError

    def _validate(self, style: Style, start: Cursor, end: Cursor) -> bool:
        if end[1] > style.line_width:
            return False
        return self.wrap or end[0] - start[0] <= style.max_lines_hwrap

    def write(self, canvas: Canvas) -> None:
        raise NotImplementedError


class Comment(Node):
    """Comment lines inside a command invocation.

    Comments are kept verbatim and do not count towards the line width.
    """

    def __init__(
        self, lines: list[str], bracket: bool = False, standalone: bool = False
    ) -> None:
        super().__init__()
        self.lines = lines
        self.bracket = bracket
        # Was on a line of its own; it never moves onto a line with code.
        self.standalone = standalone and not bracket

    def _reflow(self, style: Style, cursor: Cursor, passno: int) -> Cursor:
        self.colextent = cursor[1]
        if self.bracket:
            parts = self.lines[0].split("\n")
            if len(parts) == 1:
                return (cursor[0], cursor[1] + len(parts[0]))
            return (cursor[0] + len(parts) - 1, len(parts[-1]))
        return (cursor[0] + len(self.lines) - 1, cursor[1])

    def _validate(self, style: Style, start: Cursor, end: Cursor) -> bool:
        return True

    def write(self, canvas: Canvas) -> None:
        if self.bracket:
            canvas.put(self.pos, self.lines[0])
        else:
            for k, line in enumerate(self.lines):
                canvas.put((self.pos[0] + k, self.pos[1]), line)


def is_line_comment(node: Node) -> bool:
    return isinstance(node, Comment) and not node.bracket


def is_standalone_comment(node: Node) -> bool:
    return isinstance(node, Comment) and node.standalone


def starts_with_standalone_comment(node: Node | None) -> bool:
    while isinstance(node, (PargGroup, ArgGroup)) and node.children:
        node = node.children[0]
    return node is not None and is_standalone_comment(node)


class Scalar(Node):
    """A single argument, keyword or parenthesis, with its trailing comment."""

    def __init__(self, text: str, trailing: list[str] | None = None) -> None:
        super().__init__()
        self.text = text
        self.comment = Comment(trailing) if trailing else None

    def has_terminal_comment(self) -> bool:
        return self.comment is not None

    def _reflow(self, style: Style, cursor: Cursor, passno: int) -> Cursor:
        lines = self.text.split("\n")
        row = cursor[0] + len(lines) - 1
        col = (cursor[1] if len(lines) == 1 else 0) + len(lines[-1])
        self.colextent = max([cursor[1] + len(lines[0])] + [len(x) for x in lines[1:]])
        if self.comment is not None:
            out = self.comment.reflow(style, (row, col + 1), passno)
            self.valid = self.valid and self.comment.valid
            return out
        return (row, col)

    def write(self, canvas: Canvas) -> None:
        canvas.put(self.pos, self.text)
        if self.comment is not None:
            self.comment.write(canvas)


class PargGroup(Node):
    """A group of positional arguments (and flags)."""

    passes = ((0, False), (1, False), (2, False), (3, False), (4, True))

    def __init__(self, cmdline: bool = False) -> None:
        super().__init__()
        self.children: list[Node] = []
        self.cmdline = cmdline

    def has_terminal_comment(self) -> bool:
        if not self.children:
            return False
        last = self.children[-1]
        return isinstance(last, Comment) or last.has_terminal_comment()

    def _reflow(self, style: Style, cursor: Cursor, passno: int) -> Cursor:
        self.colextent = cursor[1]
        column = cursor
        numpargs = sum(1 for c in self.children if not isinstance(c, Comment))
        if self.cmdline:
            self.wrap = False

        rowcount = 0
        prev: Node | None = None
        for idx, child in enumerate(self.children):
            at_column = True
            if prev is None:
                rowcount = 1
            elif (
                is_line_comment(prev)
                or prev.has_terminal_comment()
                or self.wrap
                or is_standalone_comment(child)
            ):
                column = (cursor[0] + 1, column[1])
                cursor = column
                rowcount += 1
            else:
                at_column = False
                cursor = (cursor[0], cursor[1] + 1)

            if self.statement_terminal and idx == len(self.children) - 1:
                child.statement_terminal = True

            input_cursor = cursor
            cursor = child.reflow(style, input_cursor, passno)

            if not at_column and not self.wrap:
                needs_wrap = child.colextent > style.line_width
                if self.statement_terminal and cursor[1] + 1 > style.line_width:
                    needs_wrap = True
                if isinstance(prev, Scalar) and isinstance(child, Comment):
                    needs_wrap = True
                if needs_wrap:
                    rowcount += 1
                    column = (input_cursor[0] + 1, column[1])
                    cursor = child.reflow(style, column, passno)

            self.valid = self.valid and child.valid
            self.colextent = max(self.colextent, child.colextent)
            prev = child

        if self.cmdline:
            self.valid = self.valid and rowcount <= style.max_rows_cmdline
        elif numpargs > style.max_pargs_hwrap:
            self.valid = self.valid and self.wrap
        return cursor

    def write(self, canvas: Canvas) -> None:
        for child in self.children:
            child.write(canvas)


class ArgGroup(Node):
    """A sequence of positional, keyword and parenthesized groups."""

    passes = ((0, False), (1, False), (2, False), (3, False), (4, True), (5, True))

    def __init__(self) -> None:
        super().__init__()
        self.children: list[Node] = []

    def has_terminal_comment(self) -> bool:
        if not self.children:
            return False
        last = self.children[-1]
        return isinstance(last, Comment) or last.has_terminal_comment()

    def _reflow(self, style: Style, cursor: Cursor, passno: int) -> Cursor:
        self.colextent = cursor[1]
        column = cursor
        numgroups = sum(1 for c in self.children if not isinstance(c, Comment))

        prev: Node | None = None
        for idx, child in enumerate(self.children):
            if prev is None:
                first_in_row = True
            elif (
                is_line_comment(prev)
                or prev.has_terminal_comment()
                or self.wrap
                or is_standalone_comment(child)
            ):
                column = (column[0] + 1, column[1])
                cursor = column
                first_in_row = True
            else:
                cursor = (cursor[0], cursor[1] + 1)
                first_in_row = False

            if self.statement_terminal and idx == len(self.children) - 1:
                child.statement_terminal = True

            start = cursor
            cursor = child.reflow(style, cursor, passno)
            if not first_in_row and not self.wrap:
                needs_wrap = (
                    (child.statement_terminal and cursor[1] + 1 > style.line_width)
                    or child.colextent > style.line_width
                    or cursor[0] - start[0] > 1
                )
                if needs_wrap:
                    column = (column[0] + 1, column[1])
                    cursor = child.reflow(style, column, passno)

            self.valid = self.valid and child.valid
            self.colextent = max(self.colextent, child.colextent)
            column = (cursor[0], column[1])
            prev = child

        if numgroups > style.max_subgroups_hwrap:
            self.valid = self.valid and self.wrap
        return cursor

    def write(self, canvas: Canvas) -> None:
        for child in self.children:
            child.write(canvas)


class KwargGroup(Node):
    """A keyword followed by its arguments."""

    passes = ((0, False), (1, False), (2, False), (3, False), (4, False), (5, True))

    def __init__(self, keyword: Scalar, body: Node | None) -> None:
        super().__init__()
        self.keyword = keyword
        self.body = body

    def has_terminal_comment(self) -> bool:
        if self.body is None:
            return self.keyword.has_terminal_comment()
        return self.body.has_terminal_comment()

    def _validate(self, style: Style, start: Cursor, end: Cursor) -> bool:
        if end[1] > style.line_width:
            return False
        return not (
            not self.wrap
            and end[0] - start[0] > 1
            and len(self.keyword.text) > style.max_prefix_chars
        )

    def _reflow(self, style: Style, cursor: Cursor, passno: int) -> Cursor:
        start = cursor
        if len(self.keyword.text) <= style.min_prefix_chars:
            self.wrap = False
        cursor = self.keyword.reflow(style, cursor, passno)
        self.valid = self.valid and self.keyword.valid
        self.colextent = self.keyword.colextent
        if self.body is None:
            return cursor

        if (
            self.wrap
            or self.keyword.has_terminal_comment()
            or starts_with_standalone_comment(self.body)
        ):
            column = (cursor[0] + 1, start[1] + style.indent_width)
        else:
            column = (cursor[0], cursor[1] + 1)
        if self.statement_terminal:
            self.body.statement_terminal = True
        cursor = self.body.reflow(style, column, passno)
        self.valid = self.valid and self.body.valid
        self.colextent = max(self.colextent, self.body.colextent)
        return cursor

    def write(self, canvas: Canvas) -> None:
        self.keyword.write(canvas)
        if self.body is not None:
            self.body.write(canvas)


class ParenGroup(Node):
    """A parenthesized sub-expression, e.g. in if() conditions."""

    passes = ((0, False), (1, False), (2, False), (3, False), (4, False), (5, True))

    def __init__(self, lparen: Scalar, body: ArgGroup, rparen: Scalar | None) -> None:
        super().__init__()
        self.lparen = lparen
        self.body = body
        self.rparen = rparen

    def has_terminal_comment(self) -> bool:
        return self.rparen is not None and self.rparen.has_terminal_comment()

    def _reflow(self, style: Style, cursor: Cursor, passno: int) -> Cursor:
        self.colextent = cursor[1]
        column = cursor
        children: list[Node] = [self.lparen, self.body]
        if self.rparen is not None:
            children.append(self.rparen)
        prev: Node | None = None
        for idx, child in enumerate(children):
            if prev is None:
                pass
            elif prev is self.lparen:
                if starts_with_standalone_comment(child):
                    cursor = (cursor[0] + 1, column[1] + 1)
            elif is_line_comment(prev) or prev.has_terminal_comment() or self.wrap:
                cursor = (cursor[0] + 1, column[1])
            elif child is not self.rparen:
                cursor = (cursor[0], cursor[1] + 1)

            if self.statement_terminal and idx == len(children) - 1:
                child.statement_terminal = True

            cursor = child.reflow(style, cursor, passno)
            if not self.wrap:
                needs_wrap = (
                    (child.statement_terminal and cursor[1] + 1 > style.line_width)
                    or child.colextent > style.line_width
                    or not child.valid
                )
                if needs_wrap:
                    column = (column[0] + 1, column[1])
                    cursor = child.reflow(style, column, passno)

            self.valid = self.valid and child.valid
            self.colextent = max(self.colextent, child.colextent)
            column = (cursor[0], column[1])
            prev = child
        return cursor

    def write(self, canvas: Canvas) -> None:
        self.lparen.write(canvas)
        self.body.write(canvas)
        if self.rparen is not None:
            self.rparen.write(canvas)


class StatementNode(Node):
    """A complete command invocation."""

    passes = ((0, False), (1, True), (2, True), (3, True), (4, True), (5, True))

    def __init__(self, name: str, args: ArgGroup, trailing: list[str] | None) -> None:
        super().__init__()
        self.name = name
        self.args = args
        self.trailing = Comment(trailing) if trailing else None
        self.rparen_pos: Cursor = (0, 0)

    def reflow(self, style: Style, cursor: Cursor, parent_passno: int = 0) -> Cursor:
        return super().reflow(style, cursor, self.passes[-1][0])

    def _validate(self, style: Style, start: Cursor, end: Cursor) -> bool:
        if end[1] > style.line_width:
            return False
        return not (
            not self.wrap
            and end[0] - start[0] > 1
            and len(self.name) + 1 > style.max_prefix_chars
        )

    def _reflow(self, style: Style, cursor: Cursor, passno: int) -> Cursor:
        start = cursor
        if len(self.name) + 1 <= style.min_prefix_chars:
            self.wrap = False
        if starts_with_standalone_comment(self.args):
            self.wrap = True
        cursor = (cursor[0], cursor[1] + len(self.name) + 1)
        self.colextent = cursor[1]

        if self.wrap:
            cursor = (start[0] + 1, start[1] + style.indent_width)
        self.args.statement_terminal = True
        cursor = self.args.reflow(style, cursor, passno)
        self.valid = self.valid and self.args.valid
        self.colextent = max(self.colextent, self.args.colextent)

        dangle = False
        if cursor[1] >= style.line_width:
            dangle = True
            if not self.wrap:
                self.valid = False
        elif self.args.has_terminal_comment():
            dangle = True
        if dangle:
            cursor = (cursor[0] + 1, start[1])

        self.rparen_pos = cursor
        cursor = (cursor[0], cursor[1] + 1)
        self.colextent = max(self.colextent, cursor[1])
        if self.trailing is not None:
            cursor = self.trailing.reflow(style, (cursor[0], cursor[1] + 1), passno)
        return cursor

    def write(self, canvas: Canvas) -> None:
        canvas.put(self.pos, self.name + "(")
        self.args.write(canvas)
        canvas.put(self.rparen_pos, ")")
        if self.trailing is not None:
            self.trailing.write(canvas)


# ---------------------------------------------------------------------------
# Argument parsers (atoms -> layout tree)
# ---------------------------------------------------------------------------

Breakstack = list[frozenset[str]]
PAREN_BREAKER = frozenset({")"})


def should_break(atom: Atom, breakstack: Breakstack) -> bool:
    word = atom.word
    return word is not None and any(word in breaker for breaker in breakstack)


def is_comment(atom: Atom) -> bool:
    return atom.kind in (COMMENT, BRACKET_COMMENT)


def comment_node(atom: Atom) -> Comment:
    return Comment([atom.text], bracket=atom.kind == BRACKET_COMMENT, standalone=True)


def scalar(atom: Atom) -> Scalar:
    return Scalar(atom.text, atom.trailing)


def comment_belongs_up(ts: Stream, breakstack: Breakstack) -> bool:
    """A comment right before a token that ends this group goes to the parent."""
    nxt = ts.next_semantic()
    return nxt is not None and should_break(nxt, breakstack)


def pargs_full(nargs: int | str, consumed: int) -> bool:
    if isinstance(nargs, int):
        return consumed >= nargs
    return nargs == "?" and consumed >= 1


def parse_paren_group(ts: Stream) -> ParenGroup:
    lparen = scalar(ts.pop())
    body = parse_conditional(ts, [PAREN_BREAKER])
    rparen = scalar(ts.pop()) if ts and ts.peek().kind == RPAREN else None
    return ParenGroup(lparen, body, rparen)


def parse_positional(
    ts: Stream, nargs: int | str, breakstack: Breakstack, cmdline: bool = False
) -> PargGroup:
    group = PargGroup(cmdline)
    consumed = 0
    while ts:
        if pargs_full(nargs, consumed):
            break
        atom = ts.peek()
        if should_break(atom, breakstack) and (
            not isinstance(nargs, int) or atom.kind == RPAREN
        ):
            break
        if atom.kind == RPAREN:
            break
        if atom.kind == LPAREN:
            group.children.append(parse_paren_group(ts))
            continue
        if is_comment(atom):
            if comment_belongs_up(ts, breakstack):
                break
            group.children.append(comment_node(ts.pop()))
            continue
        group.children.append(scalar(ts.pop()))
        consumed += 1
    return group


KwargParser = Callable[[Stream, Breakstack], "Node | None"]


def parse_kwarg(ts: Stream, value: Any, breakstack: Breakstack) -> KwargGroup:
    keyword_atom = ts.pop()
    keyword = Scalar(keyword_atom.text)
    start = ts.pos
    body: Node | None
    if isinstance(value, CmdSpec):
        body = parse_standard(ts, value, breakstack)
    elif isinstance(value, Shell):
        shell_spec = spec(
            [PSpec("+", legacy=True, cmdline=True)],
            kwargs=dict.fromkeys(value.kwargs, "*"),
        )
        body = parse_standard(ts, shell_spec, breakstack)
    elif callable(value):
        body = cast(KwargParser, value)(ts, breakstack)
    else:
        body = parse_positional(ts, value, breakstack)
    if ts.pos == start:
        body = None
    if keyword_atom.trailing:
        # A comment after the keyword becomes the first line of its arguments.
        if isinstance(body, (PargGroup, ArgGroup)):
            body.children.insert(0, Comment(keyword_atom.trailing))
        else:
            keyword.comment = Comment(keyword_atom.trailing)
    return KwargGroup(keyword, body)


def parse_standard(ts: Stream, cmd: CmdSpec, breakstack: Breakstack) -> ArgGroup:
    """Positional groups, keyword groups and flags (cmake-format's standard parser)."""
    pargspecs = list(cmd.pargs)
    tree = ArgGroup()
    default = PSpec("*")
    if (
        len(pargspecs) == 1
        and pargspecs[0].legacy
        and not isinstance(pargspecs[0].nargs, int)
    ):
        default = pargspecs.pop(0)

    all_flags = set(default.flags)
    for pspec in pargspecs:
        all_flags.update(pspec.flags)
    kwarg_breakstack = [*breakstack, frozenset(cmd.kwargs) | all_flags]

    while ts:
        atom = ts.peek()
        if is_comment(atom):
            if comment_belongs_up(ts, breakstack):
                break
            tree.children.append(comment_node(ts.pop()))
            continue
        if should_break(atom, breakstack):
            pspec = pargspecs[0] if pargspecs else default
            if not isinstance(pspec.nargs, int) or pspec.nargs == 0:
                break
        start = ts.pos
        word = atom.word
        if word is not None and word in cmd.kwargs:
            tree.children.append(parse_kwarg(ts, cmd.kwargs[word], kwarg_breakstack))
        else:
            pspec = pargspecs.pop(0) if pargspecs else default
            other_flags = {
                f for s in pargspecs for f in s.flags if f not in pspec.flags
            }
            group = parse_positional(
                ts,
                pspec.nargs,
                [*breakstack, frozenset(cmd.kwargs) | other_flags],
                pspec.cmdline,
            )
            if ts.pos > start:
                tree.children.append(group)
        if ts.pos == start:
            if atom.kind == RPAREN:
                break
            # Never stall: take the token as a positional argument.
            group = PargGroup()
            group.children.append(scalar(ts.pop()))
            tree.children.append(group)
    return tree


CONDITIONAL_FLAGS = frozenset(
    {
        "COMMAND",
        "DEFINED",
        "EQUAL",
        "EXISTS",
        "GREATER",
        "GREATER_EQUAL",
        "IN_LIST",
        "IS_ABSOLUTE",
        "IS_DIRECTORY",
        "IS_NEWER_THAN",
        "IS_SYMLINK",
        "LESS",
        "LESS_EQUAL",
        "MATCHES",
        "NOT",
        "POLICY",
        "STREQUAL",
        "STRGREATER",
        "STRGREATER_EQUAL",
        "STRLESS",
        "STRLESS_EQUAL",
        "TARGET",
        "TEST",
        "VERSION_EQUAL",
        "VERSION_GREATER",
        "VERSION_GREATER_EQUAL",
        "VERSION_LESS",
        "VERSION_LESS_EQUAL",
    }
)
_AND_OR = frozenset({"AND", "OR"})


def parse_conditional(ts: Stream, breakstack: Breakstack) -> ArgGroup:
    """Arguments of if(), elseif() and while(): AND/OR act as keywords."""
    tree = ArgGroup()
    child_breakstack = [*breakstack, _AND_OR]
    while ts:
        atom = ts.peek()
        if should_break(atom, breakstack) or atom.kind == RPAREN:
            break
        if is_comment(atom):
            tree.children.append(comment_node(ts.pop()))
        elif atom.kind == LPAREN:
            tree.children.append(parse_paren_group(ts))
        elif atom.word in _AND_OR:
            tree.children.append(parse_kwarg(ts, parse_conditional, child_breakstack))
        else:
            tree.children.append(parse_positional(ts, "+", child_breakstack))
    return tree


def parse_set(ts: Stream, breakstack: Breakstack) -> ArgGroup:
    """set(<variable> <value>... [CACHE <type> <docstring> [FORCE]] [PARENT_SCOPE])"""
    tree = ArgGroup()
    kwarg_breakstack = [*breakstack, frozenset({"CACHE", "PARENT_SCOPE"})]
    positional_breakstack = [*breakstack, frozenset({"CACHE"})]
    varname = ts.next_semantic()
    # Values of *_COMMAND variables are command lines, like COMMAND arguments.
    cmdline = varname is not None and varname.text.upper().endswith("_COMMAND")
    if ts:
        tree.children.append(parse_positional(ts, 1, positional_breakstack))
    while ts:
        atom = ts.peek()
        if should_break(atom, breakstack):
            break
        if is_comment(atom):
            tree.children.append(comment_node(ts.pop()))
        elif atom.word == "CACHE":
            tree.children.append(parse_kwarg(ts, "2+", kwarg_breakstack))
        elif atom.word == "PARENT_SCOPE":
            tree.children.append(parse_positional(ts, "+", positional_breakstack))
        else:
            tree.children.append(parse_positional(ts, "+", kwarg_breakstack, cmdline))
    return tree


def _parse_add_target(
    ts: Stream, breakstack: Breakstack, flags: frozenset[str]
) -> ArgGroup:
    """<name> [flags...] <source>..."""
    words = {a.word for a in ts.atoms}
    if words & {"IMPORTED", "ALIAS"}:
        return parse_standard(
            ts,
            spec("+", flags=tuple(flags | {"IMPORTED", "ALIAS", "GLOBAL"})),
            breakstack,
        )
    tree = ArgGroup()
    name = PargGroup()
    sources = PargGroup()
    while ts:
        atom = ts.peek()
        if is_comment(atom):
            target = sources if sources.children else name
            target.children.append(comment_node(ts.pop()))
        elif not name.children or (not sources.children and atom.word in flags):
            name.children.append(scalar(ts.pop()))
        else:
            sources.children.append(scalar(ts.pop()))
    tree.children.append(name)
    if sources.children:
        tree.children.append(sources)
    return tree


def parse_add_executable(ts: Stream, breakstack: Breakstack) -> ArgGroup:
    return _parse_add_target(
        ts, breakstack, frozenset({"WIN32", "MACOSX_BUNDLE", "EXCLUDE_FROM_ALL"})
    )


def parse_add_library(ts: Stream, breakstack: Breakstack) -> ArgGroup:
    return _parse_add_target(
        ts,
        breakstack,
        frozenset(
            {
                "STATIC",
                "SHARED",
                "MODULE",
                "OBJECT",
                "INTERFACE",
                "UNKNOWN",
                "EXCLUDE_FROM_ALL",
            }
        ),
    )


def parse_foreach(ts: Stream, breakstack: Breakstack) -> ArgGroup:
    semantic = [a for a in ts.atoms if not is_comment(a)]
    second = semantic[1].word if len(semantic) > 1 else None
    if second == "RANGE":
        return parse_standard(ts, spec(1, kwargs={"RANGE": "+"}), breakstack)
    tree = ArgGroup()
    if second == "IN":
        tree.children.append(parse_positional(ts, 2, breakstack))
        kwargs = spec(kwargs={"LISTS": "*", "ITEMS": "*", "ZIP_LISTS": "*"})
        tree.children.extend(parse_standard(ts, kwargs, breakstack).children)
        return tree
    tree.children.append(parse_positional(ts, 1, breakstack))
    if ts:
        tree.children.append(parse_positional(ts, "+", breakstack))
    return tree


_LIST_FORMS: dict[str, CmdSpec] = {
    "LENGTH": spec(3, flags=("LENGTH",)),
    "GET": spec("4+", flags=("GET",)),
    "JOIN": spec(4, flags=("JOIN",)),
    "SUBLIST": spec(5, flags=("SUBLIST",)),
    "FIND": spec(4, flags=("FIND",)),
    "APPEND": spec("2+", flags=("APPEND",)),
    "FILTER": spec(5, flags=("FILTER", "INCLUDE", "EXCLUDE", "REGEX")),
    "INSERT": spec("4+", flags=("INSERT",)),
    "POP_BACK": spec("2+", flags=("POP_BACK",)),
    "POP_FRONT": spec("2+", flags=("POP_FRONT",)),
    "PREPEND": spec("2+", flags=("PREPEND",)),
    "REMOVE_ITEM": spec("3+", flags=("REMOVE_ITEM",)),
    "REMOVE_AT": spec("3+", flags=("REMOVE_AT",)),
    "REMOVE_DUPLICATES": spec(2, flags=("REMOVE_DUPLICATES",)),
    "TRANSFORM": spec(
        2,
        flags=("TRANSFORM",),
        kwargs={
            "APPEND": spec(1),
            "PREPEND": spec(1),
            "TOLOWER": 0,
            "TOUPPER": 0,
            "STRIP": 0,
            "GENEX_STRIP": 0,
            "REPLACE": spec(2),
            "AT": spec("+"),
            "FOR": spec("2+"),
            "REGEX": spec(1),
            "OUTPUT_VARIABLE": spec(1),
        },
    ),
    "REVERSE": spec(2, flags=("REVERSE",)),
    "SORT": spec(
        2,
        flags=("SORT",),
        kwargs={
            "COMPARE": spec(1, flags=("STRING", "FILE_BASENAME", "NATURAL")),
            "CASE": spec(1, flags=("SENSITIVE", "INSENSITIVE")),
            "ORDER": spec(1, flags=("ASCENDING", "DESCENDING")),
        },
    ),
}


def parse_list(ts: Stream, breakstack: Breakstack) -> ArgGroup:
    first = ts.next_semantic()
    form = _LIST_FORMS.get(first.word or "") if first is not None else None
    return parse_standard(ts, form or spec("*"), breakstack)


_PATTERN = spec("+", flags=("EXCLUDE",), kwargs={"PERMISSIONS": "+"})

_FILE_COPY = spec(
    "*",
    flags=(
        "INSTALL",
        "NO_SOURCE_PERMISSIONS",
        "USE_SOURCE_PERMISSIONS",
        "FILES_MATCHING",
        "FOLLOW_SYMLINK_CHAIN",
    ),
    kwargs={
        "COPY": "*",
        "DESTINATION": 1,
        "FILE_PERMISSIONS": "+",
        "DIRECTORY_PERMISSIONS": "+",
        "PATTERN": _PATTERN,
        "REGEX": _PATTERN,
    },
)
_FILE_TRANSFER = spec(
    3,
    flags=("DOWNLOAD", "UPLOAD", "SHOW_PROGRESS"),
    kwargs=dict.fromkeys(
        (
            "EXPECTED_HASH",
            "EXPECTED_MD5",
            "HTTPHEADER",
            "INACTIVITY_TIMEOUT",
            "LOG",
            "NETRC",
            "NETRC_FILE",
            "RANGE_END",
            "RANGE_START",
            "STATUS",
            "TIMEOUT",
            "TLS_CAINFO",
            "TLS_VERIFY",
            "TLS_VERSION",
            "USERPWD",
        ),
        1,
    ),
)
_FILE_HASHES = (
    "MD5",
    "SHA1",
    "SHA224",
    "SHA256",
    "SHA384",
    "SHA512",
    "SHA3_224",
    "SHA3_256",
    "SHA3_384",
    "SHA3_512",
)
_FILE_FORMS: dict[str, CmdSpec] = {
    "READ": spec("*", flags=("READ", "HEX"), kwargs={"OFFSET": 1, "LIMIT": 1}),
    "STRINGS": spec(
        "*",
        flags=("STRINGS", "NEWLINE_CONSUME", "NO_HEX_CONVERSION"),
        kwargs=dict.fromkeys(
            (
                "LENGTH_MAXIMUM",
                "LENGTH_MINIMUM",
                "LIMIT_COUNT",
                "LIMIT_INPUT",
                "LIMIT_OUTPUT",
                "REGEX",
                "ENCODING",
            ),
            1,
        ),
    ),
    "TIMESTAMP": spec("+", flags=("TIMESTAMP", "UTC")),
    "TOUCH": spec("+", flags=("TOUCH",)),
    "TOUCH_NOCREATE": spec("+", flags=("TOUCH_NOCREATE",)),
    "GENERATE": spec(
        1,
        flags=("GENERATE", "NO_SOURCE_PERMISSIONS", "USE_SOURCE_PERMISSIONS"),
        kwargs={
            "OUTPUT": 1,
            "INPUT": 1,
            "CONTENT": "+",
            "CONDITION": parse_conditional,
            "TARGET": 1,
            "FILE_PERMISSIONS": "+",
            "NEWLINE_STYLE": 1,
        },
    ),
    "GLOB": spec(
        "+",
        flags=("GLOB", "GLOB_RECURSE", "CONFIGURE_DEPENDS", "FOLLOW_SYMLINKS"),
        kwargs={"LIST_DIRECTORIES": 1, "RELATIVE": 1},
    ),
    "RENAME": spec(3, flags=("RENAME", "NO_REPLACE"), kwargs={"RESULT": 1}),
    "COPY_FILE": spec(
        3,
        flags=("COPY_FILE", "ONLY_IF_DIFFERENT", "INPUT_MAY_BE_RECENT"),
        kwargs={"RESULT": 1},
    ),
    "REMOVE": spec("+", flags=("REMOVE",)),
    "REMOVE_RECURSE": spec("+", flags=("REMOVE_RECURSE",)),
    "MAKE_DIRECTORY": spec("+", flags=("MAKE_DIRECTORY",), kwargs={"RESULT": 1}),
    "COPY": _FILE_COPY,
    "INSTALL": _FILE_COPY,
    "SIZE": spec(3, flags=("SIZE",)),
    "READ_SYMLINK": spec(3, flags=("READ_SYMLINK",)),
    "CREATE_LINK": spec(
        "+", flags=("CREATE_LINK", "COPY_ON_ERROR", "SYMBOLIC"), kwargs={"RESULT": 1}
    ),
    "REAL_PATH": spec(
        "+", flags=("REAL_PATH", "EXPAND_TILDE"), kwargs={"BASE_DIRECTORY": 1}
    ),
    "RELATIVE_PATH": spec(4, flags=("RELATIVE_PATH",)),
    "TO_CMAKE_PATH": spec(3, flags=("TO_CMAKE_PATH",)),
    "TO_CMAKE_PATH_LIST": spec(3, flags=("TO_CMAKE_PATH_LIST",)),
    "TO_NATIVE_PATH": spec(3, flags=("TO_NATIVE_PATH",)),
    "TO_NATIVE_PATH_LIST": spec(3, flags=("TO_NATIVE_PATH_LIST",)),
    "DOWNLOAD": _FILE_TRANSFER,
    "UPLOAD": _FILE_TRANSFER,
    "LOCK": spec(
        "+",
        flags=("LOCK", "DIRECTORY", "RELEASE"),
        kwargs={"GUARD": 1, "RESULT_VARIABLE": 1, "TIMEOUT": 1},
    ),
    "CHMOD": spec(
        "+",
        flags=("CHMOD", "CHMOD_RECURSE"),
        kwargs={
            "PERMISSIONS": "+",
            "FILE_PERMISSIONS": "+",
            "DIRECTORY_PERMISSIONS": "+",
        },
    ),
    "CONFIGURE": spec(
        "*",
        flags=("CONFIGURE", "ESCAPE_QUOTES", "@ONLY"),
        kwargs={"OUTPUT": 1, "CONTENT": "+", "NEWLINE_STYLE": 1},
    ),
} | {name: spec(3, flags=_FILE_HASHES) for name in _FILE_HASHES}
_FILE_FORMS["GLOB_RECURSE"] = _FILE_FORMS["GLOB"]
_FILE_FORMS["CHMOD_RECURSE"] = _FILE_FORMS["CHMOD"]


def parse_file(ts: Stream, breakstack: Breakstack) -> ArgGroup:
    first = ts.next_semantic()
    form = first.word if first is not None else None
    if form in ("WRITE", "APPEND"):
        # file(WRITE <filename> <content>...)
        tree = ArgGroup()
        tree.children.append(parse_positional(ts, 2, breakstack))
        if ts:
            tree.children.append(parse_positional(ts, "+", breakstack))
        return tree
    return parse_standard(ts, _FILE_FORMS.get(form or "") or spec("*"), breakstack)


_INSTALL_TARGET_KINDS = frozenset(
    {
        "ARCHIVE",
        "BUNDLE",
        "CXX_MODULES_BMI",
        "FILE_SET",
        "FRAMEWORK",
        "LIBRARY",
        "OBJECTS",
        "PRIVATE_HEADER",
        "PUBLIC_HEADER",
        "RESOURCE",
        "RUNTIME",
    }
)
_INSTALL_TARGET_KWARGS: dict[str, Any] = {
    "TARGETS": "+",
    "EXPORT": 1,
    "INCLUDES": spec("+", flags=("DESTINATION",)),
    "DESTINATION": 1,
    "PERMISSIONS": "+",
    "CONFIGURATIONS": "+",
    "COMPONENT": 1,
    "NAMELINK_COMPONENT": 1,
    "RUNTIME_DEPENDENCIES": "*",
    "RUNTIME_DEPENDENCY_SET": 1,
}
_INSTALL_TARGET_FLAGS = frozenset(
    {"OPTIONAL", "EXCLUDE_FROM_ALL", "NAMELINK_ONLY", "NAMELINK_SKIP"}
)

_INSTALL_SPEC = spec(
    "*",
    flags=(
        "ALL_COMPONENTS",
        "EXCLUDE_FROM_ALL",
        "EXPORT_LINK_INTERFACE_LIBRARIES",
        "EXPORT_PACKAGE_DEPENDENCIES",
        "FILES_MATCHING",
        "MESSAGE_NEVER",
        "OPTIONAL",
        "USE_SOURCE_PERMISSIONS",
    ),
    kwargs={
        "CODE": "+",
        "COMPONENT": 1,
        "CONFIGURATIONS": "+",
        "CXX_MODULES_DIRECTORY": 1,
        "DESTINATION": 1,
        "DIRECTORY": "+",
        "DIRECTORY_PERMISSIONS": "+",
        "EXPORT": 1,
        "EXPORT_ANDROID_MK": 1,
        "FILE": 1,
        "FILE_PERMISSIONS": "+",
        "FILES": "+",
        "IMPORTED_RUNTIME_ARTIFACTS": "+",
        "NAMESPACE": 1,
        "PATTERN": _PATTERN,
        "PERMISSIONS": "+",
        "PROGRAMS": "+",
        "REGEX": _PATTERN,
        "RENAME": 1,
        "SCRIPT": "+",
        "TYPE": 1,
    },
)


def parse_install_targets(ts: Stream, breakstack: Breakstack) -> ArgGroup:
    tree = ArgGroup()
    kinds_breakstack = [*breakstack, _INSTALL_TARGET_KINDS | {"INCLUDES"}]
    kwarg_breakstack = [
        *breakstack,
        frozenset(_INSTALL_TARGET_KWARGS)
        | _INSTALL_TARGET_KINDS
        | _INSTALL_TARGET_FLAGS,
    ]
    positional_breakstack = [
        *breakstack,
        frozenset(_INSTALL_TARGET_KWARGS) | _INSTALL_TARGET_KINDS,
    ]
    while ts:
        atom = ts.peek()
        if should_break(atom, breakstack):
            break
        start = ts.pos
        word = atom.word
        if is_comment(atom):
            tree.children.append(comment_node(ts.pop()))
        elif word in _INSTALL_TARGET_KINDS:
            tree.children.append(
                parse_kwarg(ts, parse_install_targets, kinds_breakstack)
            )
        elif word is not None and word in _INSTALL_TARGET_KWARGS:
            tree.children.append(
                parse_kwarg(ts, _INSTALL_TARGET_KWARGS[word], kwarg_breakstack)
            )
        else:
            tree.children.append(parse_positional(ts, "+", positional_breakstack))
        if ts.pos == start:
            break
    return tree


def parse_install(ts: Stream, breakstack: Breakstack) -> ArgGroup:
    first = ts.next_semantic()
    if first is not None and first.word == "TARGETS":
        return parse_install_targets(ts, breakstack)
    return parse_standard(ts, _INSTALL_SPEC, breakstack)


_CUSTOM_COMMAND_SPEC = spec(
    "*",
    flags=(
        "APPEND",
        "CODEGEN",
        "COMMAND_EXPAND_LISTS",
        "DEPENDS_EXPLICIT_ONLY",
        "POST_BUILD",
        "PRE_BUILD",
        "PRE_LINK",
        "USES_TERMINAL",
        "VERBATIM",
    ),
    kwargs={
        "BYPRODUCTS": "*",
        "COMMAND": SHELL,
        "COMMENT": "*",
        "DEPENDS": "*",
        "DEPFILE": 1,
        "IMPLICIT_DEPENDS": "+",
        "JOB_POOL": 1,
        "JOB_SERVER_AWARE": 1,
        "MAIN_DEPENDENCY": 1,
        "OUTPUT": "+",
        "TARGET": 1,
        "WORKING_DIRECTORY": 1,
    },
)


def parse_add_custom_command(ts: Stream, breakstack: Breakstack) -> ArgGroup:
    return parse_standard(ts, _CUSTOM_COMMAND_SPEC, breakstack)


_CUSTOM_TARGET_KWARGS: dict[str, Any] = {
    "BYPRODUCTS": "+",
    "COMMAND": SHELL,
    "COMMENT": 1,
    "DEPENDS": "+",
    "JOB_POOL": 1,
    "JOB_SERVER_AWARE": 1,
    "SOURCES": "+",
    "WORKING_DIRECTORY": 1,
}
_CUSTOM_TARGET_FLAGS = frozenset({"VERBATIM", "USES_TERMINAL", "COMMAND_EXPAND_LISTS"})


def parse_add_custom_target(ts: Stream, breakstack: Breakstack) -> ArgGroup:
    """add_custom_target(Name [ALL] [command1 [args1...]] [COMMAND ...] ...)"""
    tree = ArgGroup()
    child_breakstack = [
        *breakstack,
        frozenset(_CUSTOM_TARGET_KWARGS) | _CUSTOM_TARGET_FLAGS,
    ]
    state = "name"
    while ts:
        atom = ts.peek()
        if should_break(atom, breakstack):
            break
        if is_comment(atom):
            tree.children.append(comment_node(ts.pop()))
            continue
        start = ts.pos
        word = atom.word
        if state == "name":
            semantic = [a for a in ts.atoms[ts.pos + 1 :] if not is_comment(a)]
            nargs = 2 if semantic and semantic[0].word == "ALL" else 1
            tree.children.append(parse_positional(ts, nargs, child_breakstack))
            state = "first-command"
        elif (
            state == "first-command"
            and word not in _CUSTOM_TARGET_KWARGS
            and word not in _CUSTOM_TARGET_FLAGS
        ):
            tree.children.append(parse_positional(ts, "+", child_breakstack))
            state = "kwargs"
        elif word in _CUSTOM_TARGET_FLAGS:
            group = PargGroup()
            while ts and ts.peek().word in _CUSTOM_TARGET_FLAGS:
                group.children.append(scalar(ts.pop()))
            tree.children.append(group)
            state = "kwargs"
        elif word is not None and word in _CUSTOM_TARGET_KWARGS:
            tree.children.append(
                parse_kwarg(ts, _CUSTOM_TARGET_KWARGS[word], child_breakstack)
            )
            state = "kwargs"
        else:
            tree.children.append(parse_positional(ts, "+", child_breakstack))
        if ts.pos == start:
            group = PargGroup()
            group.children.append(scalar(ts.pop()))
            tree.children.append(group)
    return tree


def _parse_pairs(ts: Stream, breakstack: Breakstack) -> ArgGroup:
    """Property name/value pairs, one PargGroup per pair."""
    tree = ArgGroup()
    group: PargGroup | None = None
    while ts:
        atom = ts.peek()
        if should_break(atom, breakstack):
            break
        if is_comment(atom):
            tree.children.append(comment_node(ts.pop()))
            continue
        if group is None:
            group = PargGroup()
            tree.children.append(group)
        group.children.append(scalar(ts.pop()))
        if len(group.children) == 2:
            group = None
    return tree


def parse_set_target_properties(ts: Stream, breakstack: Breakstack) -> ArgGroup:
    return parse_standard(
        ts, spec("+", kwargs={"PROPERTIES": _parse_pairs}), breakstack
    )


def parse_set_source_files_properties(ts: Stream, breakstack: Breakstack) -> ArgGroup:
    return parse_standard(
        ts,
        spec(
            "*",
            kwargs={
                "DIRECTORY": "*",
                "TARGET_DIRECTORY": "*",
                "PROPERTIES": _parse_pairs,
            },
        ),
        breakstack,
    )


def parse_if(ts: Stream, breakstack: Breakstack) -> ArgGroup:
    return parse_conditional(ts, breakstack)


CUSTOM_PARSERS: dict[str, Callable[[Stream, Breakstack], ArgGroup]] = {
    "add_custom_command": parse_add_custom_command,
    "add_custom_target": parse_add_custom_target,
    "add_executable": parse_add_executable,
    "add_library": parse_add_library,
    "else": parse_if,
    "elseif": parse_if,
    "endif": parse_if,
    "endwhile": parse_if,
    "file": parse_file,
    "foreach": parse_foreach,
    "if": parse_if,
    "install": parse_install,
    "list": parse_list,
    "set": parse_set,
    "set_source_files_properties": parse_set_source_files_properties,
    "set_target_properties": parse_set_target_properties,
    "while": parse_if,
}

# Builtin commands without a dedicated signature; only used for casing.
OTHER_BUILTINS = frozenset(
    [
        "build_command",
        "build_name",
        "cmake_file_api",
        "create_test_sourcelist",
        "ctest_build",
        "ctest_configure",
        "ctest_coverage",
        "ctest_empty_binary_directory",
        "ctest_memcheck",
        "ctest_read_custom_files",
        "ctest_run_script",
        "ctest_sleep",
        "ctest_start",
        "ctest_submit",
        "ctest_test",
        "ctest_update",
        "ctest_upload",
        "exec_program",
        "export_library_dependencies",
        "fltk_wrap_ui",
        "include_external_msproject",
        "include_regular_expression",
        "install_files",
        "install_programs",
        "install_targets",
        "load_cache",
        "load_command",
        "make_directory",
        "output_required_files",
        "qt_wrap_cpp",
        "qt_wrap_ui",
        "remove",
        "subdir_depends",
        "subdirs",
        "use_mangled_mesa",
        "utility_source",
        "variable_requires",
        "write_file",
    ]
)

# Values that are never treated as keywords when guessing.
_VALUE_WORDS = frozenset(
    {
        "ON",
        "OFF",
        "TRUE",
        "FALSE",
        "YES",
        "NO",
        "Y",
        "N",
        "AND",
        "OR",
        "NOT",
        "IGNORE",
        "NOTFOUND",
    }
)
_GUESSABLE_KEYWORD = re.compile(r"[A-Z][A-Z0-9_]+")


def _guessed_spec(atoms: list[Atom]) -> CmdSpec:
    """Treat UPPERCASE words as keywords for commands we don't know."""
    keywords = {
        atom.text
        for atom in atoms
        if atom.kind == UNQUOTED
        and _GUESSABLE_KEYWORD.fullmatch(atom.text)
        and atom.text not in _VALUE_WORDS
    }
    return spec("*", kwargs=dict.fromkeys(keywords, "*"))


def build_statement(stmt: Statement, style: Style) -> StatementNode:
    lower = stmt.name.text.lower()
    ts = Stream(make_atoms(stmt.args))
    cmd_spec = SPECS_LOWER.get(lower)
    if lower in CUSTOM_PARSERS:
        args = CUSTOM_PARSERS[lower](ts, [])
    elif cmd_spec is not None:
        args = parse_standard(ts, cmd_spec, [])
    elif style.guess_keywords:
        args = parse_standard(ts, _guessed_spec(ts.atoms), [])
    else:
        args = parse_standard(ts, spec("*"), [])

    name = stmt.name.text
    if style.canonical_case:
        if cmd_spec is not None and cmd_spec.spelling:
            name = cmd_spec.spelling
        elif cmd_spec is not None or lower in CUSTOM_PARSERS or lower in OTHER_BUILTINS:
            name = lower
    return StatementNode(name, args, stmt.trailing)


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

_BLOCK_OPENERS = frozenset({"if", "foreach", "while", "function", "macro", "block"})
_BLOCK_MIDDLE = frozenset({"elseif", "else"})
_BLOCK_CLOSERS = frozenset(
    {"endif", "endforeach", "endwhile", "endfunction", "endmacro", "endblock"}
)


def _leading_whitespace(columns: int, indent: int, style: Style) -> str:
    if style.use_tab == "Never":
        return " " * columns
    if style.use_tab == "ForIndentation":
        indent = min(indent, columns)
        tabs, rest = divmod(indent, style.tab_width)
        return "\t" * tabs + " " * (rest + columns - indent)
    tabs, rest = divmod(columns, style.tab_width)
    return "\t" * tabs + " " * rest


def _indent_lines(
    lines: list[tuple[str, bool]], indent: int, style: Style
) -> list[str]:
    result: list[str] = []
    for line, raw in lines:
        if raw or not line:
            result.append(line)
            continue
        stripped = line.lstrip(" ")
        result.append(
            _leading_whitespace(len(line) - len(stripped), indent, style) + stripped
        )
    return result


def format_statement(stmt: Statement, indent: int, style: Style) -> list[str]:
    node = build_statement(stmt, style)
    node.reflow(style, (0, indent))
    canvas = Canvas()
    node.write(canvas)
    return _indent_lines(canvas.lines(), indent, style)


def format_source(
    source: str, style: Style | None = None, filename: str = "<stdin>"
) -> str:
    """Format CMake source code and return the result."""
    if style is None:
        style = Style()
    if style.disable:
        return source

    bom = "﻿" if source.startswith("﻿") else ""
    text = source.removeprefix("﻿")
    crlf = text.count("\r\n")
    text = text.replace("\r\n", "\n")
    if style.line_ending in ("LF", "CRLF"):
        eol = "\r\n" if style.line_ending == "CRLF" else "\n"
    else:
        lf = text.count("\n") - crlf
        if crlf == lf:
            eol = "\r\n" if style.line_ending == "DeriveCRLF" else "\n"
        else:
            eol = "\r\n" if crlf > lf else "\n"

    items = parse_body(lex(text, filename, style.tab_width), text, filename)

    out: list[str] = []
    depth = 0
    for item in items:
        if out:
            out.extend([""] * min(item.blank_before, style.max_empty_lines))
        if isinstance(item, RawText):
            out.extend(item.lines)
            continue
        if isinstance(item, CommentBlock):
            indent = depth * style.indent_width
            canvas = Canvas()
            canvas.put((0, indent), item.text)
            out.extend(_indent_lines(canvas.lines(), indent, style))
            continue

        lower = item.name.text.lower()
        if lower in _BLOCK_CLOSERS or lower in _BLOCK_MIDDLE:
            depth = max(0, depth - 1)
        if not item.disabled:
            out.extend(format_statement(item, depth * style.indent_width, style))
        if lower in _BLOCK_OPENERS or lower in _BLOCK_MIDDLE:
            depth += 1

    if not out:
        return bom
    return bom + eol.join(out) + eol


def decode(data: bytes) -> tuple[str, str]:
    """Decode file contents, returning (text, encoding)."""
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        # Some upstream CMake files contain non-UTF8 bytes in comments.
        return data.decode("latin-1"), "latin-1"
