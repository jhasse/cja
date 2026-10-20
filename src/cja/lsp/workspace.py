"""Index of all CMake files in the workspace, for queries across files."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..format import UNQUOTED
from .document import (
    BUILTIN_COMMANDS,
    KNOWN_COMMANDS,
    Definition,
    ParsedFile,
    Statement,
    command_keywords,
    parse,
)

# Find modules and helpers that ship with cja
BUNDLED_MODULES = Path(__file__).resolve().parent.parent / "cmake" / "Modules"

# Directories that are never searched for CMake files
_SKIPPED_DIRS = frozenset({"node_modules", "__pycache__", "CMakeFiles", "_deps"})
MAX_FILES = 10000

# LSP CompletionItemKind values
_COMPLETION_FUNCTION = 3
_COMPLETION_VARIABLE = 6
_COMPLETION_CLASS = 7
_COMPLETION_KEYWORD = 14

_TARGET_ARGUMENT_COMMANDS = frozenset(
    {
        "add_dependencies",
        "get_target_property",
        "install",
        "set_target_properties",
        "target_compile_definitions",
        "target_compile_features",
        "target_compile_options",
        "target_include_directories",
        "target_link_directories",
        "target_link_libraries",
        "target_link_options",
        "target_precompile_headers",
        "target_sources",
    }
)


def normalize(path: Path) -> Path:
    """Make paths comparable (Windows paths are case-insensitive)."""
    return Path(os.path.normcase(os.path.abspath(path)))


def is_cmake_file(path: Path) -> bool:
    return path.name == "CMakeLists.txt" or path.suffix == ".cmake"


@dataclass
class Location:
    path: Path
    start: int
    end: int


@dataclass
class Symbol:
    # "command", "variable", "target" or "file"
    kind: str
    name: str
    # Visible parameter or loop variable the name refers to
    scoped: Definition | None = None


class Workspace:
    def __init__(self) -> None:
        self.roots: list[Path] = []
        self.files: dict[Path, ParsedFile] = {}

    def scan(self, root: Path) -> None:
        """Index the CMake files below root."""
        root = normalize(root)
        if root not in self.roots:
            self.roots.append(root)
        for dirpath, dirnames, filenames in os.walk(root):
            # Build directories (configured by CMake or cja) and hidden ones
            dirnames[:] = [
                d
                for d in dirnames
                if not d.startswith((".", "build"))
                and d not in _SKIPPED_DIRS
                and not (Path(dirpath) / d / "CMakeCache.txt").exists()
            ]
            for filename in filenames:
                path = normalize(Path(dirpath) / filename)
                if is_cmake_file(path) and path not in self.files:
                    if len(self.files) >= MAX_FILES:
                        return
                    self.load(path)

    def load(self, path: Path) -> ParsedFile | None:
        """Parse a file from disk."""
        path = normalize(path)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            self.files.pop(path, None)
            return None
        return self.update(path, text)

    def update(self, path: Path, text: str) -> ParsedFile:
        path = normalize(path)
        parsed = parse(text)
        self.files[path] = parsed
        return parsed

    def get(self, path: Path) -> ParsedFile | None:
        path = normalize(path)
        return self.files.get(path) or self.load(path)

    def functions(self) -> dict[str, str]:
        """Return the user-defined commands: lowercase name -> function/macro."""
        return {
            d.name.lower(): d.kind
            for parsed in self.files.values()
            for d in parsed.definitions
            if d.kind in ("function", "macro")
        }

    def targets(self) -> set[str]:
        return {
            d.name
            for parsed in self.files.values()
            for d in parsed.definitions
            if d.kind == "target"
        }

    def _ordered_files(self, first: Path) -> list[tuple[Path, ParsedFile]]:
        """All files, starting with ``first``."""
        first = normalize(first)
        files = sorted(self.files.items(), key=lambda item: str(item[0]))
        return sorted(files, key=lambda item: item[0] != first)

    def symbol_at(self, path: Path, offset: int) -> Symbol | None:
        path = normalize(path)
        parsed = self.get(path)
        if parsed is None:
            return None
        for ref in parsed.references:
            if ref.start <= offset <= ref.end:
                return self._symbol(parsed, ref.kind, ref.name, offset)
        for d in parsed.definitions:
            if d.start <= offset <= d.end and not d.implicit:
                kind = {"function": "command", "macro": "command", "target": "target"}
                return self._symbol(parsed, kind.get(d.kind, "variable"), d.name, offset)
        stmt = parsed.statement_at(offset)
        if stmt is None:
            return None
        for idx, arg in enumerate(stmt.args):
            if arg.start <= offset <= arg.end:
                if idx == 0 and stmt.lower in ("include", "add_subdirectory"):
                    return Symbol("file", arg.value)
                if arg.kind == UNQUOTED and arg.value in self.targets():
                    return Symbol("target", arg.value)
        return None

    def _symbol(self, parsed: ParsedFile, kind: str, name: str, offset: int) -> Symbol:
        scoped = None
        if kind == "variable":
            scoped = next(
                (d for d in reversed(parsed.scopes_at(offset)) if d.name == name), None
            )
        return Symbol(kind, name, scoped)

    def definitions(self, path: Path, offset: int) -> list[Location]:
        path = normalize(path)
        symbol = self.symbol_at(path, offset)
        if symbol is None:
            return []
        if symbol.kind == "file":
            target = self._resolve_file(path, symbol.name, self.get(path), offset)
            return [Location(target, 0, 0)] if target else []
        if symbol.scoped is not None:
            return [Location(path, symbol.scoped.start, symbol.scoped.end)]
        return [
            Location(file, d.start, d.end)
            for file, d in self._matching_definitions(path, symbol)
        ]

    def _matching_definitions(
        self, path: Path, symbol: Symbol
    ) -> list[tuple[Path, Definition]]:
        matches: list[tuple[Path, Definition]] = []
        for file, parsed in self._ordered_files(path):
            for d in parsed.definitions:
                if symbol.kind == "command":
                    found = d.kind in ("function", "macro") and (
                        d.name.lower() == symbol.name.lower()
                    )
                elif symbol.kind == "target":
                    found = d.kind == "target" and d.name == symbol.name
                else:
                    # Parameters and loop variables aren't visible elsewhere
                    found = (
                        d.kind == "variable" and d.scope is None and d.name == symbol.name
                    )
                if found:
                    matches.append((file, d))
        return matches

    def _resolve_file(
        self, path: Path, name: str, parsed: ParsedFile | None, offset: int
    ) -> Path | None:
        """Resolve the argument of include() or add_subdirectory()."""
        stmt = parsed.statement_at(offset) if parsed else None
        if stmt is None or "${" in name:
            return None
        base = path.parent
        if stmt.lower == "add_subdirectory":
            candidate = base / name / "CMakeLists.txt"
            return candidate if candidate.is_file() else None
        if "/" in name or name.endswith(".cmake"):
            candidate = base / name
            return candidate if candidate.is_file() else None
        # A module: look in the workspace, then in cja's bundled modules
        filename = f"{name}.cmake"
        for file in sorted(self.files, key=str):
            if file.name == filename:
                return file
        bundled = BUNDLED_MODULES / filename
        return bundled if bundled.is_file() else None

    def references(
        self, path: Path, offset: int, include_declaration: bool
    ) -> list[Location]:
        path = normalize(path)
        symbol = self.symbol_at(path, offset)
        if symbol is None or symbol.kind == "file":
            return []
        locations: dict[tuple[Path, int], Location] = {}

        def add(file: Path, start: int, end: int) -> None:
            locations.setdefault((file, start), Location(file, start, end))

        if symbol.scoped is not None:
            scope = symbol.scoped.scope or (0, 0)
            parsed = self.files[path]
            if include_declaration:
                add(path, symbol.scoped.start, symbol.scoped.end)
            for ref in parsed.references:
                if (
                    ref.kind == "variable"
                    and ref.name == symbol.name
                    and scope[0] <= ref.start <= scope[1]
                ):
                    add(path, ref.start, ref.end)
            return list(locations.values())

        if include_declaration:
            for file, d in self._matching_definitions(path, symbol):
                if not d.implicit:
                    add(file, d.start, d.end)
        for file, parsed in self._ordered_files(path):
            if symbol.kind == "target":
                for stmt in parsed.statements:
                    for arg in stmt.args:
                        if arg.kind == UNQUOTED and arg.value == symbol.name:
                            add(file, arg.start, arg.end)
                continue
            for ref in parsed.references:
                if ref.kind != symbol.kind:
                    continue
                if symbol.kind == "command":
                    same = ref.name == symbol.name.lower()
                else:
                    same = ref.name == symbol.name and not any(
                        d.name == ref.name for d in parsed.scopes_at(ref.start)
                    )
                if same:
                    add(file, ref.start, ref.end)
        if not include_declaration:
            declarations = {
                (file, d.start) for file, d in self._matching_definitions(path, symbol)
            }
            for key in declarations:
                locations.pop(key, None)
        return list(locations.values())

    def hover(self, path: Path, offset: int) -> str | None:
        """Return Markdown describing the symbol at the offset."""
        path = normalize(path)
        symbol = self.symbol_at(path, offset)
        if symbol is None or symbol.kind == "file":
            return None
        if symbol.scoped is not None:
            d = symbol.scoped
            owner = d.statement.args[0].value if d.statement.args else ""
            role = "parameter" if d.kind == "parameter" else "loop variable"
            return f"{role} of `{d.statement.lower}({owner})`"
        matches = self._matching_definitions(path, symbol)
        if symbol.kind == "command" and not matches:
            lower = symbol.name.lower()
            spelling = KNOWN_COMMANDS.get(lower)
            if spelling is None:
                return None
            text = f"**{spelling}**"
            if lower in BUILTIN_COMMANDS:
                url = f"https://cmake.org/cmake/help/latest/command/{lower}.html"
                text += f" — [CMake documentation]({url})"
            keywords = command_keywords(lower)
            if keywords:
                text += "\n\nKeywords: " + ", ".join(f"`{k}`" for k in sorted(keywords))
            return text
        if not matches:
            return None
        parts: list[str] = []
        for file, d in matches[:5]:
            parsed = self.files[file]
            code = _statement_text(parsed, d.statement)
            line = parsed.index.line_of(d.start) + 1
            parts.append(f"```cmake\n{code}\n```\n{_display_path(file, self.roots)}:{line}")
            if symbol.kind == "command":
                comment = _leading_comment(parsed, d.statement)
                if comment:
                    parts[-1] = f"{parts[-1]}\n\n{comment}"
        if len(matches) > 5:
            parts.append(f"… and {len(matches) - 5} more")
        return "\n\n---\n\n".join(parts)

    def completions(self, path: Path, offset: int) -> list[dict[str, Any]]:
        path = normalize(path)
        parsed = self.get(path)
        if parsed is None:
            return []
        line_start = parsed.index.starts[parsed.index.line_of(offset)]
        before = parsed.text[line_start:offset]
        if re.search(r"\$\{[A-Za-z0-9_./+-]*$", before):
            names: dict[str, Definition] = {}
            for _, other in self._ordered_files(path):
                for d in other.definitions:
                    if d.kind == "variable" and d.scope is None:
                        names.setdefault(d.name, d)
            for d in parsed.scopes_at(offset):
                names[d.name] = d
            return [
                {"label": name, "kind": _COMPLETION_VARIABLE, "detail": d.statement.lower}
                for name, d in sorted(names.items())
            ]
        stmt = parsed.statement_at(offset)
        if stmt is not None and stmt.open < offset and (
            stmt.close is None or offset < stmt.close
        ):
            return self._argument_completions(stmt)
        if not re.fullmatch(r"\s*[A-Za-z_0-9]*", before):
            return []
        items: dict[str, dict[str, Any]] = {}
        for lower, spelling in sorted(KNOWN_COMMANDS.items()):
            items[lower] = {"label": spelling, "kind": _COMPLETION_FUNCTION, "detail": "CMake"}
        for file, other in self._ordered_files(path):
            for d in other.definitions:
                if d.kind in ("function", "macro"):
                    items.setdefault(
                        d.name.lower(),
                        {
                            "label": d.name,
                            "kind": _COMPLETION_FUNCTION,
                            "detail": f"{d.kind} in {_display_path(file, self.roots)}",
                        },
                    )
        return list(items.values())

    def _argument_completions(self, stmt: Statement) -> list[dict[str, Any]]:
        items = [
            {"label": keyword, "kind": _COMPLETION_KEYWORD}
            for keyword in sorted(command_keywords(stmt.lower) or ())
        ]
        if stmt.lower in _TARGET_ARGUMENT_COMMANDS:
            items += [
                {"label": target, "kind": _COMPLETION_CLASS, "detail": "target"}
                for target in sorted(self.targets())
            ]
        return items


def _statement_text(parsed: ParsedFile, stmt: Statement) -> str:
    """The source of a statement, shortened to a few lines."""
    lines = parsed.text[stmt.start : stmt.end].splitlines()
    if len(lines) > 6:
        lines = [*lines[:5], "  ..."]
    return "\n".join(lines)


def _leading_comment(parsed: ParsedFile, stmt: Statement) -> str:
    """Return the comment lines directly above a statement."""
    index = parsed.index
    # Comments on lines of their own
    by_line = {
        index.line_of(c.start): c
        for c in parsed.comments
        if not parsed.text[index.starts[index.line_of(c.start)] : c.start].strip()
    }
    line = index.line_of(stmt.start)
    lines: list[str] = []
    while line - 1 in by_line:
        line -= 1
        lines.append(by_line[line].text.lstrip("#").strip())
    return "\n".join(reversed(lines))


def _display_path(path: Path, roots: list[Path]) -> str:
    for root in roots:
        if path.is_relative_to(root):
            return path.relative_to(root).as_posix()
    return path.as_posix()
