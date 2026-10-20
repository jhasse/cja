"""Language server for CMake files (``cja lsp``).

Speaks the Language Server Protocol over stdin/stdout and provides semantic
highlighting, diagnostics, go-to-definition, references, hover, completion,
document symbols, folding and formatting.
"""

from .server import serve

__all__ = ["serve"]
