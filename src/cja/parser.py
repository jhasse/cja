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
    # UTF-8 BOM appears in some upstream CMakeLists.txt files (e.g. Box2D).
    # Treat it as a file marker, not part of the first command token.
    if content.startswith("\ufeff"):
        content = content[1:]

    tokens: list[tuple[str, int]] = []
    i = 0
    line = 1

    while i < len(content):
        # Line continuation: backslash-newline is removed but still advances line count
        if content[i] == "\\" and i + 1 < len(content) and content[i + 1] == "\n":
            i += 2
            line += 1
            continue
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
            i += 1
            # Check for bracket comment: #[[...]] or #[==[...]==]
            if i < len(content) and content[i] == "[":
                bracket_start = i
                i += 1
                while i < len(content) and content[i] == "=":
                    i += 1
                if i < len(content) and content[i] == "[":
                    # It is a bracket comment
                    num_equals = i - bracket_start - 1
                    i += 1
                    closing = "]" + "=" * num_equals + "]"
                    closing_idx = content.find(closing, i)
                    if closing_idx != -1:
                        comment_content = content[i:closing_idx]
                        line += comment_content.count("\n")
                        i = closing_idx + len(closing)
                    else:
                        # Unterminated bracket comment
                        i = len(content)
                    continue

            # Regular line comment
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
                    if content[i + 1] == "\n":
                        i += 2
                        line += 1
                    elif content[i + 1] in ('"', "\\", "n", "t", "r"):
                        i += 2
                    else:
                        i += 2
                else:
                    if content[i] == "\n":
                        line += 1
                    i += 1
            i += 1  # Skip closing quote
            raw_val = content[start:i]
            # Unescape
            val = ""
            j = 1
            while j < len(raw_val) - 1:
                if raw_val[j] == "\\":
                    if raw_val[j + 1] == "n":
                        val += "\n"
                    elif raw_val[j + 1] == "t":
                        val += "\t"
                    elif raw_val[j + 1] == "r":
                        val += "\r"
                    elif raw_val[j + 1] == "$":
                        # Preserve escaped variable markers (\${...}) so they
                        # can remain literal during variable expansion.
                        val += "\\$"
                    elif raw_val[j + 1] == "\n":
                        pass  # Line continuation
                    else:
                        val += raw_val[j + 1]
                    j += 2
                else:
                    val += raw_val[j]
                    j += 1
            tokens.append(('"' + val + '"', line))
            continue

        # Unquoted token (identifier or value)
        start = i
        genex_depth = 0
        while i < len(content):
            if content.startswith("$<", i):
                genex_depth += 1
                i += 2
                continue
            if content[i] == ">" and genex_depth > 0:
                genex_depth -= 1
                i += 1
                continue
            if genex_depth == 0 and content[i] in " \t\n()#":
                break
            if content[i] == "\\" and i + 1 < len(content) and content[i + 1] == "\n":
                i += 2
                line += 1
            else:
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

        # Collect arguments until the matching closing paren
        args: list[str] = []
        is_quoted: list[bool] = []
        depth = 1
        while i < len(tokens):
            token, token_line = tokens[i]
            if token == "(":
                depth += 1
            elif token == ")":
                depth -= 1
                if depth == 0:
                    break

            arg = token
            quoted = False
            # Strip quotes from quoted strings
            if arg.startswith('"') and arg.endswith('"'):
                arg = arg[1:-1]
                quoted = True
            args.append(arg)
            is_quoted.append(quoted)
            i += 1

        if i >= len(tokens) or tokens[i][0] != ")":
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
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        # Some upstream CMake files contain non-UTF8 bytes in comments.
        # CMake parses them fine, so fall back to a permissive decoding.
        content = path.read_text(encoding="latin-1")
    return parse(content, filename=str(path))
