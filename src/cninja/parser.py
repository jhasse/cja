"""CMake file parser."""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Command:
    """A CMake command with its name and arguments."""

    name: str
    args: list[str]
    is_quoted: list[bool] = field(default_factory=list)
    line: int = 0


def tokenize(content: str) -> list[tuple[str, int]]:
    """Tokenize CMake content into tokens with line numbers."""
    tokens: list[tuple[str, int]] = []
    i = 0
    line = 1

    while i < len(content):
        # Skip whitespace
        if content[i] in " \t":
            i += 1
            continue

        # Track newlines
        if content[i] == "\n":
            line += 1
            i += 1
            continue

        # Skip comments
        if content[i] == "#":
            while i < len(content) and content[i] != "\n":
                i += 1
            continue

        # Parentheses
        if content[i] in "()":
            tokens.append((content[i], line))
            i += 1
            continue

        # Quoted string
        if content[i] == '"':
            start = i
            i += 1
            while i < len(content) and content[i] != '"':
                if content[i] == "\\" and i + 1 < len(content):
                    i += 2
                else:
                    if content[i] == "\n":
                        line += 1
                    i += 1
            i += 1  # Skip closing quote
            tokens.append((content[start:i], line))
            continue

        # Unquoted token (identifier or value)
        start = i
        while i < len(content) and content[i] not in " \t\n()#":
            i += 1
        if i > start:
            tokens.append((content[start:i], line))

    return tokens


def parse(content: str, filename: str = "CMakeLists.txt") -> list[Command]:
    """Parse CMake content into a list of commands."""
    tokens = tokenize(content)
    commands: list[Command] = []
    i = 0

    lines = content.splitlines()

    while i < len(tokens):
        # Expect command name
        if i >= len(tokens):
            break

        name, line = tokens[i]
        i += 1

        # Expect opening paren
        if i >= len(tokens) or tokens[i][0] != "(":
            raise SyntaxError(
                f"Expected '(' after command '{name}'",
                (filename, line, 0, lines[line - 1] if line <= len(lines) else ""),
            )
        i += 1

        # Collect arguments until closing paren
        args: list[str] = []
        is_quoted: list[bool] = []
        while i < len(tokens) and tokens[i][0] != ")":
            arg = tokens[i][0]
            quoted = False
            # Strip quotes from quoted strings
            if arg.startswith('"') and arg.endswith('"'):
                arg = arg[1:-1]
                quoted = True
            args.append(arg)
            is_quoted.append(quoted)
            i += 1

        if i >= len(tokens):
            raise SyntaxError(
                f"Expected ')' for command '{name}'",
                (filename, line, 0, lines[line - 1] if line <= len(lines) else ""),
            )
        i += 1  # Skip closing paren

        commands.append(
            Command(name=name.lower(), args=args, is_quoted=is_quoted, line=line)
        )

    return commands


def parse_file(path: Path) -> list[Command]:
    """Parse a CMakeLists.txt file."""
    content = path.read_text()
    return parse(content, filename=str(path))
