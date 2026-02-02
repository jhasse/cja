from dataclasses import dataclass, field


@dataclass
class Library:
    """A library target."""

    name: str
    sources: list[str]
    lib_type: str = "STATIC"  # STATIC, SHARED, or OBJECT
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
    link_directories: list[str] = field(
        default_factory=list
    )  # PRIVATE link directories
    public_link_directories: list[str] = field(
        default_factory=list
    )  # PUBLIC link directories


@dataclass
class Executable:
    """An executable target."""

    name: str
    sources: list[str]
    link_libraries: list[str] = field(default_factory=list)
    compile_features: list[str] = field(default_factory=list)
    include_directories: list[str] = field(default_factory=list)
    compile_definitions: list[str] = field(default_factory=list)
    link_directories: list[str] = field(default_factory=list)


@dataclass
class ImportedTarget:
    """An imported target (e.g., from find_package)."""

    cflags: str = ""  # Compile flags (e.g., -I/path/to/include)
    libs: str = ""  # Link flags (e.g., -lgtest -pthread)
