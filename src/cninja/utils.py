from pathlib import Path


def make_relative(path_str: str, root: Path) -> str:
    """Convert an absolute path to a relative path if it's under the root directory."""
    try:
        path = Path(path_str)
        if path.is_absolute() and path.is_relative_to(root):
            return str(path.relative_to(root))
    except ValueError:
        pass
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
