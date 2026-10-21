"""Tests for the language server (`cja lsp`)."""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from cja.lsp.document import (
    TOKEN_MODIFIERS,
    TOKEN_TYPES,
    LineIndex,
    document_symbols,
    folding_ranges,
    parse,
    semantic_tokens,
)
from cja.lsp.server import changed_lines_edit, parse_configure_output
from cja.lsp.workspace import Workspace, normalize


def decode_tokens(text: str, workspace: Workspace | None = None) -> list[tuple[str, str]]:
    """Return (text, type[+modifiers]) for each semantic token."""
    parsed = parse(text)
    functions = workspace.functions() if workspace else {}
    targets = workspace.targets() if workspace else set()
    data = semantic_tokens(parsed, functions, targets)
    lines = parsed.text.split("\n")
    result: list[tuple[str, str]] = []
    line = char = 0
    for i in range(0, len(data), 5):
        delta_line, delta_char, length, token_type, modifiers = data[i : i + 5]
        line += delta_line
        char = delta_char if delta_line else char + delta_char
        names = [TOKEN_TYPES[token_type]] + [
            m for bit, m in enumerate(TOKEN_MODIFIERS) if modifiers >> bit & 1
        ]
        result.append((lines[line][char : char + length], "+".join(names)))
    return result


def messages(text: str) -> list[str]:
    return [d.message for d in parse(text).diagnostics]


def test_syntax_diagnostics() -> None:
    assert messages("set(a b)\n") == []
    assert messages('set(a "b)\n') == ["Unterminated quoted argument"]
    assert messages("set(a b\n") == ["Missing ')' for set("]
    assert messages("set a\n") == ["Expected '(' after set"]
    assert messages("if(a)\nendforeach()\n") == [
        "endforeach() without foreach()",
        "if() without endif()",
    ]
    assert messages("else()\n") == ["else() without if()"]
    assert messages("function(f)\nif(a)\nendfunction()\n") == ["if() without endif()"]


def test_semantic_tokens() -> None:
    tokens = decode_tokens(
        """\
# comment
function(greet name)
  if(name STREQUAL "World" AND NOT DEFINED SILENT)
    message(STATUS "Hello ${name}! ${GREETING}")
  endif()
endfunction()
set(GREETING Hi CACHE STRING "")
greet(World ON 42)
"""
    )
    assert tokens == [
        ("# comment", "comment"),
        ("function", "keyword"),
        ("greet", "function+declaration"),
        ("name", "parameter+declaration"),
        ("if", "keyword"),
        ("name", "parameter"),
        ("STREQUAL", "keyword"),
        ('"World"', "string"),
        ("AND", "keyword"),
        ("NOT", "keyword"),
        ("DEFINED", "keyword"),
        ("SILENT", "variable"),
        ("message", "function+defaultLibrary"),
        ("STATUS", "keyword"),
        ('"Hello ', "string"),
        ("${name}", "parameter"),
        ("! ", "string"),
        ("${GREETING}", "variable"),
        ('"', "string"),
        ("endif", "keyword"),
        ("endfunction", "keyword"),
        ("set", "function+defaultLibrary"),
        ("GREETING", "variable+declaration"),
        ("CACHE", "keyword"),
        ("STRING", "keyword"),
        ('""', "string"),
        ("greet", "function"),
        ("ON", "enumMember"),
        ("42", "number"),
    ]


def test_semantic_tokens_multiline_and_unicode() -> None:
    tokens = decode_tokens('message("ä ${X}\nb")\nset([[x\ny]])\n')
    assert ('"ä ', "string") in tokens
    assert ("${X}", "variable") in tokens
    assert ('b"', "string") in tokens
    assert ("[[x", "string") in tokens
    assert ("y]]", "string") in tokens


def test_line_index_utf16() -> None:
    index = LineIndex("a😀b\nc")
    assert index.position(2) == {"line": 0, "character": 3}
    assert index.offset({"line": 0, "character": 3}) == 2
    assert index.position(4) == {"line": 1, "character": 0}
    assert index.offset({"line": 5, "character": 0}) == 5


def make_project(root: Path) -> Workspace:
    (root / "cmake").mkdir()
    (root / "sub").mkdir()
    (root / "build").mkdir()
    (root / "CMakeLists.txt").write_text(
        """\
project(demo)
include(cmake/helpers.cmake)
set(SOURCES main.c)
add_executable(app ${SOURCES})
add_subdirectory(sub)
target_link_libraries(app PRIVATE mylib)
my_helper(app)
"""
    )
    (root / "cmake" / "helpers.cmake").write_text(
        """\
# Does helpful things.
function(my_helper target)
  message(STATUS "${target} ${SOURCES}")
endfunction()
"""
    )
    (root / "sub" / "CMakeLists.txt").write_text(
        "add_library(mylib lib.c)\nlist(APPEND SOURCES lib.c)\n"
    )
    # Build directories aren't indexed
    (root / "build" / "CMakeLists.txt").write_text("function(my_helper)\nendfunction()\n")
    workspace = Workspace()
    workspace.scan(root)
    return workspace


def position_of(workspace: Workspace, path: Path, needle: str, delta: int = 0) -> int:
    parsed = workspace.get(path)
    assert parsed is not None
    return parsed.text.index(needle) + delta


def describe(workspace: Workspace, locations: Any, root: Path) -> list[tuple[str, str]]:
    result = []
    for location in locations:
        parsed = workspace.get(location.path)
        assert parsed is not None
        text = parsed.text[location.start : location.end]
        # Workspace paths are normalized (lower-cased on Windows): restore the real spelling
        actual = next(p for p in root.rglob("*") if normalize(p) == location.path)
        result.append((actual.relative_to(root).as_posix(), text))
    return result


def test_definitions(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    workspace = make_project(root)
    top = root / "CMakeLists.txt"
    helpers = root / "cmake" / "helpers.cmake"

    def definition(path: Path, needle: str, delta: int = 1) -> list[tuple[str, str]]:
        offset = position_of(workspace, path, needle, delta)
        return describe(workspace, workspace.definitions(path, offset), root)

    assert definition(top, "my_helper(app") == [("cmake/helpers.cmake", "my_helper")]
    assert definition(top, "SOURCES}") == [
        ("CMakeLists.txt", "SOURCES"),
        ("sub/CMakeLists.txt", "SOURCES"),
    ]
    assert definition(top, "mylib") == [("sub/CMakeLists.txt", "mylib")]
    assert definition(top, "app ${") == [("CMakeLists.txt", "app")]
    assert definition(top, "cmake/helpers") == [("cmake/helpers.cmake", "")]
    assert definition(top, "sub)") == [("sub/CMakeLists.txt", "")]
    assert definition(helpers, "target}") == [("cmake/helpers.cmake", "target")]


def test_references_and_hover(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    workspace = make_project(root)
    top = root / "CMakeLists.txt"
    helpers = root / "cmake" / "helpers.cmake"

    offset = position_of(workspace, top, "app ${", 1)
    refs = describe(workspace, workspace.references(top, offset, True), root)
    assert sorted(refs) == [
        ("CMakeLists.txt", "app"),
        ("CMakeLists.txt", "app"),
        ("CMakeLists.txt", "app"),
    ]
    offset = position_of(workspace, helpers, "SOURCES", 1)
    refs = describe(workspace, workspace.references(helpers, offset, False), root)
    assert sorted(refs) == [
        ("CMakeLists.txt", "SOURCES"),
        ("cmake/helpers.cmake", "SOURCES"),
    ]

    hover = workspace.hover(top, position_of(workspace, top, "my_helper(app", 1))
    assert hover is not None
    assert "function(my_helper target)" in hover
    assert "Does helpful things." in hover
    hover = workspace.hover(top, position_of(workspace, top, "add_executable", 1))
    assert hover is not None
    assert "https://cmake.org/cmake/help/latest/command/add_executable.html" in hover
    hover = workspace.hover(helpers, position_of(workspace, helpers, "target}", 1))
    assert hover == "parameter of `function(my_helper)`"


def test_completion(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    workspace = make_project(root)
    top = root / "CMakeLists.txt"
    text = (top.read_text()) + "target_link_libraries(app P)\nmy_\nmessage(${SO"
    workspace.update(top, text)

    def labels(offset: int) -> list[str]:
        return [item["label"] for item in workspace.completions(top, offset)]

    in_call = labels(text.index("P)\n") + 1)
    assert "PRIVATE" in in_call
    assert "mylib" in in_call
    at_start = labels(text.index("my_\n") + 3)
    assert "my_helper" in at_start
    assert "FetchContent_Declare" in at_start
    assert "SOURCES" in labels(len(text))


def test_folding_and_symbols() -> None:
    parsed = parse(
        """\
# a
# b
function(f)
  set(x
      1)
endfunction()
add_library(lib STATIC a.c)
"""
    )
    assert sorted(folding_ranges(parsed), key=lambda r: r["startLine"]) == [
        {"startLine": 0, "endLine": 1, "kind": "comment"},
        {"startLine": 2, "endLine": 4},
        {"startLine": 3, "endLine": 4},
    ]
    symbols = document_symbols(parsed)
    assert [(s["name"], s["detail"]) for s in symbols] == [
        ("f", "function"),
        ("lib", "library"),
    ]
    assert symbols[0]["range"]["end"] == {"line": 5, "character": 13}


def test_changed_lines_edit() -> None:
    assert changed_lines_edit("a\nb\n", "a\nb\n") == []
    assert changed_lines_edit("a\nB( x )\nc\n", "a\nb(x)\nc\n") == [
        {
            "range": {"start": {"line": 1, "character": 0}, "end": {"line": 2, "character": 0}},
            "newText": "b(x)\n",
        }
    ]
    # Lines can be added or removed; CRLF is kept
    assert changed_lines_edit("a\r\nx(\r\n)\r\nb\r\n", "a\r\nx()\r\nb\r\n") == [
        {
            "range": {"start": {"line": 1, "character": 0}, "end": {"line": 3, "character": 0}},
            "newText": "x()\r\n",
        }
    ]
    assert changed_lines_edit("x(\na)", "x(a)\n") == [
        {
            "range": {"start": {"line": 0, "character": 0}, "end": {"line": 1, "character": 2}},
            "newText": "x(a)\n",
        }
    ]


def test_parse_configure_output(tmp_path: Path) -> None:
    stderr = (
        "sub/CMakeLists.txt:3: \x1b[1mwarning:\x1b[0m careful\n"
        "  more details\n"
        "CMakeLists.txt:1: error: unsupported argument to include_directories(): SYSTEM\n"
    )
    diagnostics = parse_configure_output(stderr, 1, tmp_path)
    sub = diagnostics[tmp_path / "sub" / "CMakeLists.txt"]
    assert [(d["range"]["start"]["line"], d["severity"], d["message"]) for d in sub] == [
        (2, 2, "careful\nmore details")
    ]
    assert diagnostics[tmp_path / "CMakeLists.txt"][0]["severity"] == 1

    diagnostics = parse_configure_output("Traceback ...\nKeyError: 'x'\n", 1, tmp_path)
    [crash] = diagnostics[tmp_path / "CMakeLists.txt"]
    assert crash["message"] == "Configuring failed: KeyError: 'x'"


class Client:
    def __init__(self, cwd: Path) -> None:
        self.process = subprocess.Popen(
            [sys.executable, "-m", "cja", "lsp", "--stdio"],
            cwd=cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
        )
        self.next_id = 0
        self.notifications: list[dict[str, Any]] = []

    def send(self, message: dict[str, Any]) -> None:
        assert self.process.stdin is not None
        body = json.dumps({"jsonrpc": "2.0", **message}).encode()
        self.process.stdin.write(f"Content-Length: {len(body)}\r\n\r\n".encode() + body)
        self.process.stdin.flush()

    def receive(self) -> dict[str, Any]:
        assert self.process.stdout is not None
        length = 0
        while line := self.process.stdout.readline().strip():
            name, _, value = line.decode().partition(":")
            if name.lower() == "content-length":
                length = int(value)
        return json.loads(self.process.stdout.read(length))

    def request(self, method: str, params: Any = None) -> Any:
        self.next_id += 1
        self.send({"id": self.next_id, "method": method, "params": params})
        while True:
            message = self.receive()
            if message.get("id") == self.next_id:
                return message.get("result", message.get("error"))
            self.notifications.append(message)

    def notify(self, method: str, params: Any = None) -> None:
        self.send({"method": method, "params": params})


def test_server_session(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    make_project(root)
    top = root / "CMakeLists.txt"
    uri = top.as_uri()
    client = Client(tmp_path)

    capabilities = client.request("initialize", {"rootUri": root.as_uri(), "capabilities": {}})
    assert capabilities["capabilities"]["semanticTokensProvider"]["legend"]["tokenTypes"]
    client.notify("initialized", {})
    client.notify(
        "textDocument/didOpen",
        {"textDocument": {"uri": uri, "languageId": "cmake", "version": 1, "text": "SET(a"}},
    )
    tokens = client.request("textDocument/semanticTokens/full", {"textDocument": {"uri": uri}})
    assert tokens["data"][:5] == [0, 0, 3, TOKEN_TYPES.index("function"), 2]
    [published] = [n for n in client.notifications if n["method"].endswith("Diagnostics")]
    assert published["params"]["diagnostics"][0]["message"] == "Missing ')' for SET("

    text = top.read_text().replace("project(demo)", "PROJECT( demo )")
    client.notify(
        "textDocument/didChange",
        {"textDocument": {"uri": uri, "version": 2}, "contentChanges": [{"text": text}]},
    )
    edits = client.request(
        "textDocument/formatting",
        {"textDocument": {"uri": uri}, "options": {"tabSize": 2, "insertSpaces": True}},
    )
    assert edits[0]["newText"].startswith("project(demo)\n")
    # Only the selected statement is formatted
    client.notify(
        "textDocument/didChange",
        {
            "textDocument": {"uri": uri, "version": 3},
            "contentChanges": [{"text": text.replace("set(SOURCES", "SET( SOURCES")}],
        },
    )
    edits = client.request(
        "textDocument/rangeFormatting",
        {
            "textDocument": {"uri": uri},
            "range": {"start": {"line": 2, "character": 0}, "end": {"line": 3, "character": 0}},
            "options": {"tabSize": 2, "insertSpaces": True},
        },
    )
    assert edits == [
        {
            "range": {"start": {"line": 2, "character": 0}, "end": {"line": 3, "character": 0}},
            "newText": "set(SOURCES main.c)\n",
        }
    ]
    location = client.request(
        "textDocument/definition",
        {"textDocument": {"uri": uri}, "position": {"line": 6, "character": 2}},
    )
    assert location[0]["uri"] == normalize(root / "cmake" / "helpers.cmake").as_uri()
    assert client.request("unknown/method")["code"] == -32601

    assert client.request("shutdown") is None
    client.notify("exit")
    assert client.process.wait(timeout=10) == 0
