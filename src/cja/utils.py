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
        if path.is_absolute() and path.is_relative_to(root):
            return to_posix_path(path.relative_to(root))
    except ValueError:
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


def strip_generator_expressions(value: str) -> str:
    """Strip or evaluate simple CMake generator expressions."""
    # Handle $<BUILD_INTERFACE:xxx>
    value = re.sub(r"\$<BUILD_INTERFACE:([^>]+)>", r"\1", value)
    # Handle $<INSTALL_INTERFACE:xxx> -> empty
    value = re.sub(r"\$<INSTALL_INTERFACE:[^>]*>", "", value)
    # Handle $<TARGET_FILE:target> -> target (we'll fix this later if needed)

    # Handle nested expressions by repeatedly stripping the innermost ones
    while "$<" in value:
        new_value = re.sub(r"\$<[^<>]+>", "", value)
        if new_value == value:
            break
        value = new_value
    return value
