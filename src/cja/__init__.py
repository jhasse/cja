"""cja - A CMake reimplementation in Python with Ninja generator."""

__version__ = "0.1.0"

from .generator import configure
from .parser import parse, parse_file

__all__ = ["configure", "parse", "parse_file"]
