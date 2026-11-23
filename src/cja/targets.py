from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Library:
    """A library target."""

    name: str
    sources: list[str]
    lib_type: str = "STATIC"  # STATIC, SHARED, OBJECT, MODULE, or INTERFACE
    # INTERFACE/PUBLIC sources, compiled into every target that uses this library
    interface_sources: list[str] = field(default_factory=list)
    defined_file: Path | None = None
    defined_line: int = 0
    # The directory the target was created in (its CMAKE_CURRENT_SOURCE_DIR)
    source_dir: Path | None = None
    binary_dir: str = ""
    compile_features: list[str] = field(default_factory=list)  # PRIVATE features
    public_compile_features: list[str] = field(default_factory=list)  # PUBLIC features
    include_directories: list[str] = field(default_factory=list)  # PRIVATE includes
    public_include_directories: list[str] = field(
        default_factory=list
    )  # PUBLIC includes
    # Which of the include directories are system ones (-isystem), i.e. its
    # SYSTEM_INCLUDE_DIRECTORIES and INTERFACE_SYSTEM_INCLUDE_DIRECTORIES
    system_include_directories: list[str] = field(default_factory=list)
    public_system_include_directories: list[str] = field(default_factory=list)
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
    link_options: list[str] = field(default_factory=list)  # PRIVATE link options
    public_link_options: list[str] = field(default_factory=list)  # PUBLIC options
    properties: dict[str, str] = field(default_factory=dict)
    is_alias: bool = False
    alias_for: str | None = None
    dependencies: list[str] = field(default_factory=list)
    post_build_commands: list[list[str]] = field(default_factory=list)
    pre_build_commands: list[list[str]] = field(default_factory=list)
    pre_link_commands: list[list[str]] = field(default_factory=list)


@dataclass
class Executable:
    """An executable target."""

    name: str
    sources: list[str]
    defined_file: Path | None = None
    defined_line: int = 0
    # The directory the target was created in (its CMAKE_CURRENT_SOURCE_DIR)
    source_dir: Path | None = None
    binary_dir: str = ""
    directory_depth: int = 0
    link_libraries: list[str] = field(default_factory=list)
    compile_features: list[str] = field(default_factory=list)
    include_directories: list[str] = field(default_factory=list)
    # Which of the include directories are system ones (-isystem)
    system_include_directories: list[str] = field(default_factory=list)
    compile_definitions: list[str] = field(default_factory=list)
    compile_options: list[str] = field(default_factory=list)
    link_directories: list[str] = field(default_factory=list)
    link_options: list[str] = field(default_factory=list)
    properties: dict[str, str] = field(default_factory=dict)
    dependencies: list[str] = field(default_factory=list)
    post_build_commands: list[list[str]] = field(default_factory=list)
    # Files that the POST_BUILD commands may write, kept like the outputs of
    # a custom command
    post_build_byproducts: list[str] = field(default_factory=list)
    pre_build_commands: list[list[str]] = field(default_factory=list)
    pre_link_commands: list[list[str]] = field(default_factory=list)


@dataclass
class ImportedTarget:
    """An imported target (e.g., from find_package)."""

    cflags: str = ""  # Compile flags (e.g., -I/path/to/include)
    libs: str = ""  # Link flags (e.g., -lgtest -pthread)
    compile_features: list[str] = field(default_factory=list)  # INTERFACE ones
    # Imported targets in INTERFACE_LINK_LIBRARIES, resolved when generating
    link_targets: list[str] = field(default_factory=list)
    # Properties as set, for get_target_property() and $<TARGET_PROPERTY:...>
    properties: dict[str, str] = field(default_factory=dict)
    # From add_executable(... IMPORTED): runs in commands instead of linking
    executable: bool = False

    def location(self, build_type: str) -> str | None:
        """The file of an imported executable.

        Like in CMake, that's IMPORTED_LOCATION_<CONFIG> of the build type,
        else IMPORTED_LOCATION, else the one of the first configuration in
        IMPORTED_CONFIGURATIONS.
        """
        configurations = self.properties.get("IMPORTED_CONFIGURATIONS", "")
        suffixes = [f"_{build_type}", "", *(f"_{c}" for c in configurations.split(";"))]
        for suffix in suffixes:
            location = self.properties.get(f"IMPORTED_LOCATION{suffix.upper()}")
            if location:
                return location.replace("\\", "/")
        return None


@dataclass
class InstallTarget:
    """An installation target."""

    targets: list[str]
    destination: str


# Target properties that are stored in fields of Library and Executable instead
# of their ``properties``. Executables only have the non-INTERFACE fields.
TARGET_PROPERTY_FIELDS = {
    "SOURCES": "sources",
    "INTERFACE_SOURCES": "interface_sources",
    "INCLUDE_DIRECTORIES": "include_directories",
    "INTERFACE_INCLUDE_DIRECTORIES": "public_include_directories",
    "COMPILE_DEFINITIONS": "compile_definitions",
    "INTERFACE_COMPILE_DEFINITIONS": "public_compile_definitions",
    "COMPILE_OPTIONS": "compile_options",
    "INTERFACE_COMPILE_OPTIONS": "public_compile_options",
    "COMPILE_FEATURES": "compile_features",
    "INTERFACE_COMPILE_FEATURES": "public_compile_features",
    "LINK_LIBRARIES": "link_libraries",
    "INTERFACE_LINK_LIBRARIES": "public_link_libraries",
    "LINK_OPTIONS": "link_options",
    "INTERFACE_LINK_OPTIONS": "public_link_options",
    "LINK_DIRECTORIES": "link_directories",
    "INTERFACE_LINK_DIRECTORIES": "public_link_directories",
}
