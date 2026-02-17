from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Library:
    """A library target."""

    name: str
    sources: list[str]
    lib_type: str = "STATIC"  # STATIC, SHARED, or OBJECT
    defined_file: Path | None = None
    defined_line: int = 0
    compile_features: list[str] = field(default_factory=list)  # PRIVATE features
    public_compile_features: list[str] = field(default_factory=list)  # PUBLIC features
    include_directories: list[str] = field(default_factory=list)  # PRIVATE includes
    public_include_directories: list[str] = field(
        default_factory=list
    )  # PUBLIC includes
    compile_definitions: list[str] = field(default_factory=list)  # PRIVATE definitions
    public_compile_definitions: list[str] = field(
        default_factory=list
    )  # PUBLIC definitions
    compile_options: list[str] = field(default_factory=list)  # PRIVATE options
    public_compile_options: list[str] = field(default_factory=list)  # PUBLIC options
    link_directories: list[str] = field(
        default_factory=list
    )  # PRIVATE link directories
    public_link_directories: list[str] = field(
        default_factory=list
    )  # PUBLIC link directories
    link_libraries: list[str] = field(default_factory=list)
    public_link_libraries: list[str] = field(default_factory=list)
    properties: dict[str, str] = field(default_factory=dict)
    is_alias: bool = False
    alias_for: str | None = None


@dataclass
class Executable:
    """An executable target."""

    name: str
    sources: list[str]
    defined_file: Path | None = None
    defined_line: int = 0
    link_libraries: list[str] = field(default_factory=list)
    compile_features: list[str] = field(default_factory=list)
    include_directories: list[str] = field(default_factory=list)
    compile_definitions: list[str] = field(default_factory=list)
    compile_options: list[str] = field(default_factory=list)
    link_directories: list[str] = field(default_factory=list)
    properties: dict[str, str] = field(default_factory=dict)


@dataclass
class ImportedTarget:
    """An imported target (e.g., from find_package)."""

    cflags: str = ""  # Compile flags (e.g., -I/path/to/include)
    libs: str = ""  # Link flags (e.g., -lgtest -pthread)


@dataclass
class InstallTarget:
    """An installation target."""

    targets: list[str]
    destination: str
