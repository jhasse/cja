"""JSON-RPC 2.0 over stdio with the Content-Length framing of the LSP."""

from __future__ import annotations

import json
import threading
from typing import IO, Any

# JSON-RPC error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INTERNAL_ERROR = -32603
SERVER_NOT_INITIALIZED = -32002


def read_message(stream: IO[bytes]) -> Any | None:
    """Read one message, or return None at the end of the stream."""
    length: int | None = None
    while True:
        line = stream.readline()
        if not line:
            return None
        line = line.strip()
        if not line:
            break
        name, _, value = line.decode("ascii").partition(":")
        if name.strip().lower() == "content-length":
            length = int(value.strip())
    if length is None:
        raise ValueError("Missing Content-Length header")
    body = stream.read(length)
    if len(body) < length:
        return None
    return json.loads(body.decode("utf-8"))


class Connection:
    """Writes messages to the client; safe to use from several threads."""

    def __init__(self, output: IO[bytes]) -> None:
        self._output = output
        self._lock = threading.Lock()
        self._next_id = 0

    def _write(self, message: dict[str, Any]) -> None:
        body = json.dumps(message, separators=(",", ":")).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        with self._lock:
            self._output.write(header + body)
            self._output.flush()

    def respond(self, request_id: Any, result: Any) -> None:
        self._write({"jsonrpc": "2.0", "id": request_id, "result": result})

    def respond_error(self, request_id: Any, code: int, message: str) -> None:
        self._write(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": code, "message": message},
            }
        )

    def notify(self, method: str, params: Any) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params})

    def request(self, method: str, params: Any) -> None:
        """Send a request to the client; its response is ignored."""
        with self._lock:
            self._next_id += 1
            request_id = f"cja-{self._next_id}"
        self._write(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        )
