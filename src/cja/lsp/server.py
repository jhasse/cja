"""The language server behind ``cja lsp``.

Requests and notifications are handled one after another on the main thread.
Only the optional configure run (diagnostics from actually configuring the
project) happens in a background thread.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import IO, Any
from urllib.parse import unquote, urlparse

from ..format import find_style, format_source
from .document import (
    TOKEN_MODIFIERS,
    TOKEN_TYPES,
    LineIndex,
    document_symbols,
    folding_ranges,
    semantic_tokens,
)
from .protocol import (
    INTERNAL_ERROR,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    SERVER_NOT_INITIALIZED,
    Connection,
    read_message,
)
from .workspace import Location, Workspace, is_cmake_file, normalize

CONFIGURE_COMMAND = "cja.configure"

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_LOCATED = re.compile(r"^(?P<file>.+?):(?P<line>\d+): (?P<severity>error|warning): (?P<message>.*)$")
_UNLOCATED = re.compile(r"^(?P<severity>error|warning): (?P<message>.*)$")


def uri_to_path(uri: str) -> Path:
    parsed = urlparse(uri)
    path = unquote(parsed.path)
    if os.name == "nt" and re.match(r"/[A-Za-z]:", path):
        path = path[1:]
    return normalize(Path(path))


def path_to_uri(path: Path) -> str:
    return path.as_uri()


class Server:
    def __init__(self, connection: Connection) -> None:
        self.connection = connection
        self.workspace = Workspace()
        # Text of the documents open in the client
        self.documents: dict[Path, str] = {}
        self.initialized = False
        self.shutdown_requested = False
        # Workspace folders, scanned once the client sent "initialized"
        self.pending_roots: list[Path] = []
        self.options: dict[str, Any] = {
            "configureOnSave": False,
            "buildDir": "build",
            "strict": True,
            "configureArgs": [],
        }
        self.refresh_tokens = False
        # Diagnostics from the last configure run, by file
        self.configure_diagnostics: dict[Path, list[dict[str, Any]]] = {}
        self._lock = threading.RLock()
        self._configure_state = threading.Lock()
        self._configure_running = False
        self._configure_pending = False
        self._symbols: tuple[dict[str, str], set[str]] = ({}, set())

        self.requests: dict[str, Callable[[Any], Any]] = {
            "initialize": self.initialize,
            "shutdown": self.shutdown,
            "textDocument/semanticTokens/full": self.semantic_tokens,
            "textDocument/definition": self.definition,
            "textDocument/references": self.references,
            "textDocument/hover": self.hover,
            "textDocument/completion": self.completion,
            "textDocument/documentSymbol": self.document_symbol,
            "textDocument/foldingRange": self.folding_range,
            "textDocument/formatting": self.formatting,
            "workspace/executeCommand": self.execute_command,
        }
        self.notifications: dict[str, Callable[[Any], None]] = {
            "initialized": self.on_initialized,
            "textDocument/didOpen": self.did_open,
            "textDocument/didChange": self.did_change,
            "textDocument/didSave": self.did_save,
            "textDocument/didClose": self.did_close,
            "workspace/didChangeWatchedFiles": self.did_change_watched_files,
            "workspace/didChangeConfiguration": self.did_change_configuration,
            "workspace/didChangeWorkspaceFolders": self.did_change_workspace_folders,
        }

    # -- Dispatch -----------------------------------------------------------

    def handle(self, message: dict[str, Any]) -> int | None:
        """Handle one message; return the exit code after "exit"."""
        method = message.get("method")
        params = message.get("params")
        if method is None:
            return None  # A response to one of our requests
        if method == "exit":
            return 0 if self.shutdown_requested else 1
        request_id = message.get("id")
        with self._lock:
            if request_id is None:
                handler = self.notifications.get(method)
                if handler is not None and (self.initialized or method == "initialized"):
                    try:
                        handler(params)
                    except Exception:  # noqa: BLE001 - keep serving after bugs
                        traceback.print_exc()
                return None
            if not self.initialized and method != "initialize":
                self.connection.respond_error(
                    request_id, SERVER_NOT_INITIALIZED, "Server not initialized"
                )
                return None
            if self.shutdown_requested:
                self.connection.respond_error(request_id, INVALID_REQUEST, "Shut down")
                return None
            request = self.requests.get(method)
            if request is None:
                self.connection.respond_error(
                    request_id, METHOD_NOT_FOUND, f"Unknown method {method}"
                )
                return None
            try:
                result = request(params)
            except Exception as e:  # noqa: BLE001 - reported to the client
                traceback.print_exc()
                self.connection.respond_error(request_id, INTERNAL_ERROR, str(e))
                return None
            self.connection.respond(request_id, result)
        return None

    # -- Lifecycle ----------------------------------------------------------

    def initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        self.initialized = True
        capabilities = params.get("capabilities") or {}
        workspace_capabilities = capabilities.get("workspace") or {}
        self.refresh_tokens = bool(
            (workspace_capabilities.get("semanticTokens") or {}).get("refreshSupport")
        )
        self._update_options(params.get("initializationOptions"))
        folders = params.get("workspaceFolders") or []
        self.pending_roots = [uri_to_path(f["uri"]) for f in folders]
        if not self.pending_roots and params.get("rootUri"):
            self.pending_roots = [uri_to_path(params["rootUri"])]
        elif not self.pending_roots and params.get("rootPath"):
            self.pending_roots = [normalize(Path(params["rootPath"]))]
        return {
            "capabilities": {
                "positionEncoding": "utf-16",
                "textDocumentSync": {
                    "openClose": True,
                    "change": 1,  # Full
                    "save": {"includeText": False},
                },
                "semanticTokensProvider": {
                    "legend": {
                        "tokenTypes": TOKEN_TYPES,
                        "tokenModifiers": TOKEN_MODIFIERS,
                    },
                    "full": True,
                },
                "definitionProvider": True,
                "referencesProvider": True,
                "hoverProvider": True,
                "completionProvider": {"triggerCharacters": ["{"]},
                "documentSymbolProvider": True,
                "foldingRangeProvider": True,
                "documentFormattingProvider": True,
                "executeCommandProvider": {"commands": [CONFIGURE_COMMAND]},
                "workspace": {
                    "workspaceFolders": {"supported": True, "changeNotifications": True}
                },
            },
            "serverInfo": {"name": "cja"},
        }

    def on_initialized(self, params: Any) -> None:
        for root in self.pending_roots:
            self.workspace.scan(root)
        self._symbols = (self.workspace.functions(), self.workspace.targets())

    def shutdown(self, params: Any) -> None:
        self.shutdown_requested = True

    def _update_options(self, options: Any) -> None:
        if isinstance(options, dict):
            options = options.get("cja", options)
            if isinstance(options, dict):
                self.options.update(
                    {k: v for k, v in options.items() if k in self.options}
                )

    # -- Document sync ------------------------------------------------------

    def did_open(self, params: dict[str, Any]) -> None:
        document = params["textDocument"]
        path = uri_to_path(document["uri"])
        self.documents[path] = document["text"]
        self._update(path, document["text"])

    def did_change(self, params: dict[str, Any]) -> None:
        path = uri_to_path(params["textDocument"]["uri"])
        changes = params["contentChanges"]
        if changes:
            # Full sync: the last change is the whole document
            text = changes[-1]["text"]
            self.documents[path] = text
            self._update(path, text)

    def did_save(self, params: dict[str, Any]) -> None:
        if self.options.get("configureOnSave"):
            self.request_configure()

    def did_close(self, params: dict[str, Any]) -> None:
        path = uri_to_path(params["textDocument"]["uri"])
        self.documents.pop(path, None)
        if path.exists():
            self.workspace.load(path)
        else:
            self.workspace.files.pop(path, None)
        self._symbols_changed()
        self.publish(path)

    def did_change_watched_files(self, params: dict[str, Any]) -> None:
        for change in params.get("changes", []):
            path = uri_to_path(change["uri"])
            if path in self.documents or not is_cmake_file(path):
                continue
            if change.get("type") == 3:  # Deleted
                self.workspace.files.pop(path, None)
            else:
                self.workspace.load(path)
        self._symbols_changed()

    def did_change_configuration(self, params: dict[str, Any]) -> None:
        self._update_options(params.get("settings"))

    def did_change_workspace_folders(self, params: dict[str, Any]) -> None:
        event = params.get("event") or {}
        for folder in event.get("removed", []):
            root = uri_to_path(folder["uri"])
            if root in self.workspace.roots:
                self.workspace.roots.remove(root)
            for path in [p for p in self.workspace.files if p.is_relative_to(root)]:
                if path not in self.documents:
                    del self.workspace.files[path]
        for folder in event.get("added", []):
            self.workspace.scan(uri_to_path(folder["uri"]))
        self._symbols_changed()

    def _update(self, path: Path, text: str) -> None:
        self.workspace.update(path, text)
        self._symbols_changed()
        self.publish(path)

    def _symbols_changed(self) -> None:
        """Ask the client to re-highlight if commands or targets changed."""
        symbols = (self.workspace.functions(), self.workspace.targets())
        if symbols != self._symbols:
            self._symbols = symbols
            if self.refresh_tokens:
                self.connection.request("workspace/semanticTokens/refresh", None)

    # -- Diagnostics --------------------------------------------------------

    def publish(self, path: Path) -> None:
        diagnostics = list(self.configure_diagnostics.get(path, []))
        parsed = self.workspace.files.get(path)
        if path in self.documents and parsed is not None:
            diagnostics += [
                {
                    "range": parsed.index.range(d.start, d.end),
                    "severity": d.severity,
                    "source": "cja",
                    "message": d.message,
                }
                for d in parsed.diagnostics
            ]
        self.connection.notify(
            "textDocument/publishDiagnostics",
            {"uri": path_to_uri(path), "diagnostics": diagnostics},
        )

    def execute_command(self, params: dict[str, Any]) -> None:
        if params.get("command") == CONFIGURE_COMMAND:
            self.request_configure()

    def request_configure(self) -> None:
        """Configure the project in the background, or again after the current run."""
        with self._configure_state:
            if self._configure_running:
                self._configure_pending = True
                return
            self._configure_running = True
        threading.Thread(target=self._configure_loop, daemon=True).start()

    def _configure_loop(self) -> None:
        while True:
            try:
                diagnostics = self.run_configure()
            except Exception:  # noqa: BLE001 - keep the thread's state consistent
                traceback.print_exc()
                diagnostics = None
            if diagnostics is not None:
                with self._lock:
                    previous = set(self.configure_diagnostics)
                    self.configure_diagnostics = diagnostics
                    for path in previous | set(diagnostics):
                        self.publish(path)
            with self._configure_state:
                if not self._configure_pending:
                    self._configure_running = False
                    return
                self._configure_pending = False

    def run_configure(self) -> dict[Path, list[dict[str, Any]]] | None:
        """Configure the project with cja and turn its messages into diagnostics."""
        with self._lock:
            roots = list(self.workspace.roots)
            options = dict(self.options)
        root = next((r for r in roots if (r / "CMakeLists.txt").is_file()), None)
        if root is None:
            return None
        command = [sys.executable, "-m", "cja", "-B", str(options["buildDir"])]
        if options.get("strict"):
            command.append("--strict")
        command += [str(arg) for arg in options.get("configureArgs") or []]
        env = {**os.environ, "NO_COLOR": "1", "ANSI_COLORS_DISABLED": "1"}
        result = subprocess.run(
            command,
            cwd=root,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            check=False,
        )
        return parse_configure_output(result.stderr, result.returncode, root)

    # -- Language features --------------------------------------------------

    def _document(self, params: dict[str, Any]) -> tuple[Path, int]:
        path = uri_to_path(params["textDocument"]["uri"])
        parsed = self.workspace.get(path)
        offset = parsed.index.offset(params["position"]) if parsed else 0
        return path, offset

    def _locations(self, locations: list[Location]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for location in locations:
            parsed = self.workspace.get(location.path)
            if parsed is None:
                continue
            result.append(
                {
                    "uri": path_to_uri(location.path),
                    "range": parsed.index.range(location.start, location.end),
                }
            )
        return result

    def semantic_tokens(self, params: dict[str, Any]) -> dict[str, Any]:
        parsed = self.workspace.get(uri_to_path(params["textDocument"]["uri"]))
        if parsed is None:
            return {"data": []}
        functions, targets = self._symbols
        return {"data": semantic_tokens(parsed, functions, targets)}

    def definition(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        path, offset = self._document(params)
        return self._locations(self.workspace.definitions(path, offset))

    def references(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        path, offset = self._document(params)
        include = bool((params.get("context") or {}).get("includeDeclaration"))
        return self._locations(self.workspace.references(path, offset, include))

    def hover(self, params: dict[str, Any]) -> dict[str, Any] | None:
        path, offset = self._document(params)
        text = self.workspace.hover(path, offset)
        if text is None:
            return None
        return {"contents": {"kind": "markdown", "value": text}}

    def completion(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        path, offset = self._document(params)
        return self.workspace.completions(path, offset)

    def document_symbol(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        parsed = self.workspace.get(uri_to_path(params["textDocument"]["uri"]))
        return document_symbols(parsed) if parsed else []

    def folding_range(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        parsed = self.workspace.get(uri_to_path(params["textDocument"]["uri"]))
        return folding_ranges(parsed) if parsed else []

    def formatting(self, params: dict[str, Any]) -> list[dict[str, Any]] | None:
        path = uri_to_path(params["textDocument"]["uri"])
        text = self.documents.get(path)
        if text is None:
            return None
        try:
            formatted = format_source(text, find_style(path.parent), str(path))
        except SyntaxError:
            return None
        if formatted == text:
            return []
        index = LineIndex(text.replace("\r\n", "\n"))
        return [{"range": index.range(0, len(index.text)), "newText": formatted}]


def parse_configure_output(
    stderr: str, returncode: int, root: Path
) -> dict[Path, list[dict[str, Any]]]:
    """Turn the errors and warnings printed by a configure run into diagnostics."""
    diagnostics: dict[Path, list[dict[str, Any]]] = {}
    top = normalize(root / "CMakeLists.txt")
    last: dict[str, Any] | None = None
    lines = [_ANSI.sub("", line) for line in stderr.splitlines()]
    for line in lines:
        located = _LOCATED.match(line)
        unlocated = None if located else _UNLOCATED.match(line)
        match = located or unlocated
        if match is None:
            if last is not None and line.strip():
                last["message"] += "\n" + line.strip()
            continue
        path, line_number = top, 0
        if located:
            path = normalize(root / located["file"])
            line_number = int(located["line"]) - 1
        last = {
            "range": {
                "start": {"line": line_number, "character": 0},
                "end": {"line": line_number + 1, "character": 0},
            },
            "severity": 1 if match["severity"] == "error" else 2,
            "source": "cja configure",
            "message": match["message"],
        }
        diagnostics.setdefault(path, []).append(last)
    has_error = any(d["severity"] == 1 for ds in diagnostics.values() for d in ds)
    if returncode != 0 and not has_error:
        message = next((line for line in reversed(lines) if line.strip()), "")
        diagnostics.setdefault(top, []).append(
            {
                "range": {
                    "start": {"line": 0, "character": 0},
                    "end": {"line": 1, "character": 0},
                },
                "severity": 1,
                "source": "cja configure",
                "message": f"Configuring failed: {message}" if message else "Configuring failed",
            }
        )
    return diagnostics


def serve(input_stream: IO[bytes], output_stream: IO[bytes]) -> int:
    """Run the language server until the client sends "exit"."""
    connection = Connection(output_stream)
    server = Server(connection)
    while True:
        try:
            message = read_message(input_stream)
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as e:
            connection.respond_error(None, PARSE_ERROR, str(e))
            continue
        if message is None:
            return 0 if server.shutdown_requested else 1
        exit_code = server.handle(message)
        if exit_code is not None:
            return exit_code
