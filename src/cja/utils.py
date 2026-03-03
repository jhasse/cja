from pathlib import Path
import re


_DRIVE_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")
_UNC_PATH_RE = re.compile(r"^[\\/]{2}[^\\/]+[\\/][^\\/]+")
UNDEFINED_VAR_SENTINEL = "__CJA_UNDEFINED_VAR__"


def to_posix_path(path: str | Path) -> str:
    """Normalize path separators to forward slashes."""
    return str(path).replace("\\", "/")


def is_cmake_absolute_path(path_str: str) -> bool:
    """Return True for CMake-style absolute paths across platforms."""
    if not path_str:
        return False
    if path_str.startswith("/"):
        return True
    return bool(_DRIVE_PATH_RE.match(path_str) or _UNC_PATH_RE.match(path_str))


def resolve_cmake_path(path_str: str, base_dir: Path) -> str:
    """Resolve a CMake path while preserving native absolute path formatting."""
    if is_cmake_absolute_path(path_str):
        if path_str.startswith("/"):
            return path_str.replace("\\", "/")
        return str(Path(path_str))
    resolved = base_dir / path_str
    base_str = str(base_dir)
    if base_str.startswith("\\") and not _DRIVE_PATH_RE.match(base_str):
        return to_posix_path(resolved)
    return str(resolved)


def make_relative(path_str: str, root: Path) -> str:
    """Convert an absolute path to a relative path if it's under the root directory."""
    try:
        path = Path(path_str)
        path_abs = path.resolve() if path.is_absolute() else path
        root_abs = root.resolve() if root.is_absolute() else root.resolve()
        if path_abs.is_absolute() and path_abs.is_relative_to(root_abs):
            return to_posix_path(path_abs.relative_to(root_abs))
    except ValueError:
        pass
    except OSError:
        pass
    if not Path(path_str).is_absolute():
        return to_posix_path(path_str)
    return path_str


def is_truthy(value: str) -> bool:
    """Check if a CMake value is considered true."""
    if not value:
        return False
    # CMake considers these values false
    false_values = ("0", "OFF", "NO", "FALSE", "N", "IGNORE", "NOTFOUND", "")
    upper = value.upper()
    if upper in false_values or upper.endswith("-NOTFOUND"):
        return False
    # Numbers other than 0 are true
    try:
        return float(value) != 0
    except ValueError:
        pass
    # These are explicitly true
    if upper in ("1", "ON", "YES", "TRUE", "Y"):
        return True
    # For anything else, it's true if it's not a false constant
    # (This is used for variable values)
    return True


def is_constant_truthy(value: str) -> bool:
    """Check if a literal constant is truthy."""
    upper = value.upper()
    if upper in ("1", "ON", "YES", "TRUE", "Y"):
        return True
    try:
        return float(value) != 0
    except ValueError:
        pass
    return False


def strip_generator_expressions(
    value: str, variables: dict[str, str] | None = None
) -> str:
    """Strip or evaluate common CMake generator expressions."""
    variables = variables or {}

    def split_top_level(text: str, sep: str, maxsplit: int = -1) -> list[str]:
        parts: list[str] = []
        depth = 0
        i = 0
        start = 0
        splits = 0
        while i < len(text):
            if text.startswith("$<", i):
                depth += 1
                i += 2
                continue
            if text[i] == ">" and depth > 0:
                depth -= 1
                i += 1
                continue
            if text[i] == sep and depth == 0 and (maxsplit < 0 or splits < maxsplit):
                parts.append(text[start:i])
                start = i + 1
                splits += 1
            i += 1
        parts.append(text[start:])
        return parts

    def version_tuple(v: str) -> tuple[int, ...]:
        try:
            return tuple(int(x) for x in re.split(r"[^0-9]", v) if x)
        except ValueError:
            return (0,)

    def find_genex_end(text: str, start: int) -> int:
        depth = 1
        i = start + 2
        while i < len(text):
            if text.startswith("$<", i):
                depth += 1
                i += 2
                continue
            if text[i] == ">":
                depth -= 1
                if depth == 0:
                    return i
            i += 1
        return -1

    def eval_genex_content(content: str) -> str:
        if content.startswith("BUILD_INTERFACE:"):
            return expand_text(content[len("BUILD_INTERFACE:") :])
        if content.startswith("INSTALL_INTERFACE:"):
            return ""
        if content.startswith("BOOL:"):
            arg = expand_text(content[len("BOOL:") :])
            return "1" if is_truthy(arg) else "0"
        if content.startswith("NOT:"):
            arg = expand_text(content[len("NOT:") :])
            return "0" if is_truthy(arg) else "1"
        if content.startswith("AND:"):
            args = split_top_level(content[len("AND:") :], ",")
            return "1" if all(is_truthy(expand_text(a)) for a in args) else "0"
        if content.startswith("OR:"):
            args = split_top_level(content[len("OR:") :], ",")
            return "1" if any(is_truthy(expand_text(a)) for a in args) else "0"
        if content.startswith("STREQUAL:"):
            args = split_top_level(content[len("STREQUAL:") :], ",", maxsplit=1)
            if len(args) == 2:
                return "1" if expand_text(args[0]) == expand_text(args[1]) else "0"
            return "0"
        if content.startswith("VERSION_LESS:"):
            args = split_top_level(content[len("VERSION_LESS:") :], ",", maxsplit=1)
            if len(args) == 2:
                return (
                    "1"
                    if version_tuple(expand_text(args[0]))
                    < version_tuple(expand_text(args[1]))
                    else "0"
                )
            return "0"
        if content == "CXX_COMPILER_ID":
            return variables.get("CMAKE_CXX_COMPILER_ID", "")
        if content == "C_COMPILER_ID":
            return variables.get("CMAKE_C_COMPILER_ID", "")
        if content == "CXX_COMPILER_VERSION":
            return variables.get("CMAKE_CXX_COMPILER_VERSION", "")
        if content == "C_COMPILER_VERSION":
            return variables.get("CMAKE_C_COMPILER_VERSION", "")
        if content.startswith("CXX_COMPILER_ID:"):
            args = [a for a in split_top_level(content[len("CXX_COMPILER_ID:") :], ",") if a]
            current = variables.get("CMAKE_CXX_COMPILER_ID", "")
            return "1" if current and current in args else "0"
        if content.startswith("C_COMPILER_ID:"):
            args = [a for a in split_top_level(content[len("C_COMPILER_ID:") :], ",") if a]
            current = variables.get("CMAKE_C_COMPILER_ID", "")
            return "1" if current and current in args else "0"
        if content.startswith("TARGET_PROPERTY:"):
            # No property lookup support in generator expressions yet.
            return ""

        # Generic conditional form: $<condition:string>
        cond_parts = split_top_level(content, ":", maxsplit=1)
        if len(cond_parts) == 2:
            condition = expand_text(cond_parts[0])
            if is_truthy(condition):
                return expand_text(cond_parts[1])
            return ""
        return ""

    def expand_text(text: str) -> str:
        out: list[str] = []
        i = 0
        while i < len(text):
            start = text.find("$<", i)
            if start == -1:
                out.append(text[i:])
                break
            out.append(text[i:start])
            end = find_genex_end(text, start)
            if end == -1:
                out.append(text[start:])
                break
            out.append(eval_genex_content(text[start + 2 : end]))
            i = end + 1
        return "".join(out)

    result = expand_text(value)
    if "\n" in result:
        result = " ".join(result.split())
    return result
