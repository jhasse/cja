"""Argument signatures of CMake commands, used by ``cja format``.

The formatter groups the arguments of a command into positional groups and
keyword groups (a keyword followed by its arguments). These tables describe
which words act as keywords or flags for the commands it knows about.

``nargs`` follows the cmake-format conventions: an ``int`` is an exact count,
``"?"`` is zero or one, ``"*"`` zero or more, ``"+"`` one or more and ``"N+"``
at least N.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

Nargs = int | str


@dataclass(frozen=True)
class PSpec:
    """Specification of a positional argument group."""

    nargs: Nargs = "*"
    flags: tuple[str, ...] = ()
    # A lone non-exact "legacy" positional spec is reused for every
    # positional group of the command (and its flags don't split groups).
    legacy: bool = False
    # "cmdline" groups (shell commands) are never laid out vertically.
    cmdline: bool = False


@dataclass
class CmdSpec:
    """Specification of a command (or of the arguments after a keyword)."""

    pargs: list[PSpec] = field(default_factory=lambda: [PSpec("*", legacy=True)])
    # Keyword -> nargs (positional group), nested CmdSpec, or custom parser.
    kwargs: dict[str, Any] = field(default_factory=dict)
    spelling: str | None = None


def spec(
    pargs: Nargs | list[Nargs | PSpec] = "*",
    flags: tuple[str, ...] | list[str] = (),
    kwargs: dict[str, Any] | None = None,
    spelling: str | None = None,
) -> CmdSpec:
    """Build a CmdSpec from a compact description."""
    if isinstance(pargs, (int, str)):
        pspecs = [PSpec(pargs, tuple(flags), legacy=True)]
    else:
        assert not flags, "flags must be part of the PSpecs"
        pspecs = [p if isinstance(p, PSpec) else PSpec(p) for p in pargs]
    return CmdSpec(pspecs, dict(kwargs or {}), spelling)


@dataclass(frozen=True)
class Shell:
    """Marker for a ``COMMAND`` keyword whose arguments form a command line."""

    kwargs: tuple[str, ...] = ()


SHELL = Shell()

VISIBILITY = ("PRIVATE", "PUBLIC", "INTERFACE")
FIND_FLAGS = (
    "CMAKE_FIND_ROOT_PATH_BOTH",
    "NO_CACHE",
    "NO_CMAKE_ENVIRONMENT_PATH",
    "NO_CMAKE_FIND_ROOT_PATH",
    "NO_CMAKE_INSTALL_PREFIX",
    "NO_CMAKE_PATH",
    "NO_CMAKE_SYSTEM_PATH",
    "NO_DEFAULT_PATH",
    "NO_PACKAGE_ROOT_PATH",
    "NO_SYSTEM_ENVIRONMENT_PATH",
    "ONLY_CMAKE_FIND_ROOT_PATH",
    "REQUIRED",
    "OPTIONAL",
)
FIND_KWARGS = {
    "DOC": "*",
    "HINTS": "*",
    "NAMES": "*",
    "PATHS": "*",
    "PATH_SUFFIXES": "*",
    "REGISTRY_VIEW": 1,
    "VALIDATOR": 1,
}
FETCH_KWARGS = {
    name: SHELL if name.endswith("_COMMAND") else "*"
    for name in (
        "BINARY_DIR",
        "BUILD_BYPRODUCTS",
        "BUILD_COMMAND",
        "BUILD_IN_SOURCE",
        "CMAKE_ARGS",
        "CMAKE_CACHE_ARGS",
        "CMAKE_CACHE_DEFAULT_ARGS",
        "CMAKE_GENERATOR",
        "CONFIGURE_COMMAND",
        "DEPENDS",
        "DOWNLOAD_COMMAND",
        "DOWNLOAD_DIR",
        "DOWNLOAD_EXTRACT_TIMESTAMP",
        "DOWNLOAD_NAME",
        "DOWNLOAD_NO_EXTRACT",
        "DOWNLOAD_NO_PROGRESS",
        "EXCLUDE_FROM_ALL",
        "FIND_PACKAGE_ARGS",
        "GIT_CONFIG",
        "GIT_PROGRESS",
        "GIT_REMOTE_NAME",
        "GIT_REMOTE_UPDATE_STRATEGY",
        "GIT_REPOSITORY",
        "GIT_SHALLOW",
        "GIT_SUBMODULES",
        "GIT_SUBMODULES_RECURSE",
        "GIT_TAG",
        "HTTP_HEADER",
        "HTTP_PASSWORD",
        "HTTP_USERNAME",
        "INSTALL_COMMAND",
        "INSTALL_DIR",
        "LIST_SEPARATOR",
        "LOG_BUILD",
        "LOG_CONFIGURE",
        "LOG_DOWNLOAD",
        "LOG_INSTALL",
        "LOG_OUTPUT_ON_FAILURE",
        "LOG_UPDATE",
        "OVERRIDE_FIND_PACKAGE",
        "PATCH_COMMAND",
        "PREFIX",
        "SOURCE_DIR",
        "SOURCE_SUBDIR",
        "STAMP_DIR",
        "SVN_REPOSITORY",
        "SVN_REVISION",
        "SYSTEM",
        "TEST_COMMAND",
        "TIMEOUT",
        "TLS_CAINFO",
        "TLS_VERIFY",
        "TMP_DIR",
        "UPDATE_COMMAND",
        "UPDATE_DISCONNECTED",
        "URL",
        "URL_HASH",
        "URL_MD5",
        "USES_TERMINAL_BUILD",
        "USES_TERMINAL_CONFIGURE",
        "USES_TERMINAL_DOWNLOAD",
        "USES_TERMINAL_INSTALL",
        "USES_TERMINAL_UPDATE",
    )
}
CPM_KWARGS = {
    name: "*"
    for name in (
        "BITBUCKET_REPOSITORY",
        "CUSTOM_CACHE_KEY",
        "DOWNLOAD_COMMAND",
        "DOWNLOAD_ONLY",
        "EXCLUDE_FROM_ALL",
        "FIND_PACKAGE_ARGUMENTS",
        "FORCE",
        "GIT_REPOSITORY",
        "GIT_SHALLOW",
        "GIT_TAG",
        "GITHUB_REPOSITORY",
        "GITLAB_REPOSITORY",
        "NAME",
        "OPTIONS",
        "PATCHES",
        "SOURCE_DIR",
        "SOURCE_SUBDIR",
        "SYSTEM",
        "URL",
        "URL_HASH",
        "VERSION",
    )
}

# Commands with a plain signature. Commands that need a dedicated parser
# (if, set, add_library, install, ...) are registered in format.py.
SPECS: dict[str, CmdSpec] = {
    "add_compile_definitions": spec("*"),
    "add_compile_options": spec("*"),
    "add_definitions": spec("*"),
    "add_dependencies": spec("+"),
    "add_link_options": spec("*"),
    "add_subdirectory": spec("+", flags=("EXCLUDE_FROM_ALL", "SYSTEM")),
    "add_test": spec(
        kwargs={
            "COMMAND": SHELL,
            "COMMAND_EXPAND_LISTS": 0,
            "CONFIGURATIONS": "*",
            "NAME": "*",
            "WORKING_DIRECTORY": "*",
        }
    ),
    "aux_source_directory": spec(2),
    "block": spec(kwargs={"SCOPE_FOR": "*", "PROPAGATE": "*"}),
    "break": spec(0),
    "cmake_dependent_option": spec("*"),
    "cmake_host_system_information": spec(kwargs={"QUERY": "*", "RESULT": "*"}),
    "cmake_language": spec(
        "*",
        flags=(
            "CALL",
            "EVAL",
            "DEFER",
            "SET_DEPENDENCY_PROVIDER",
            "GET_MESSAGE_LOG_LEVEL",
        ),
        kwargs={
            "CODE": "*",
            "DIRECTORY": 1,
            "ID": 1,
            "ID_VAR": 1,
            "GET_CALL_IDS": "*",
            "GET_CALL": "*",
            "CANCEL_CALL": "*",
            "SUPPORTED_METHODS": "*",
        },
    ),
    "cmake_minimum_required": spec(flags=("FATAL_ERROR",), kwargs={"VERSION": "*"}),
    "cmake_parse_arguments": spec("*", flags=("PARSE_ARGV",)),
    "cmake_path": spec(
        "*",
        flags=("NORMALIZE", "LAST_ONLY", "APPEND", "APPEND_STRING"),
        kwargs={"OUTPUT_VARIABLE": 1, "BASE_DIRECTORY": 1},
    ),
    "cmake_policy": spec(
        "*", flags=("PUSH", "POP"), kwargs={"VERSION": "*", "SET": 2, "GET": 2}
    ),
    "configure_file": spec(
        "*",
        flags=(
            "@ONLY",
            "COPYONLY",
            "ESCAPE_QUOTES",
            "NO_SOURCE_PERMISSIONS",
            "USE_SOURCE_PERMISSIONS",
        ),
        kwargs={"NEWLINE_STYLE": 1, "FILE_PERMISSIONS": "+"},
    ),
    "continue": spec(0),
    "define_property": spec(
        flags=(
            "CACHED_VARIABLE",
            "DIRECTORY",
            "GLOBAL",
            "INHERITED",
            "SOURCE",
            "TARGET",
            "TEST",
            "VARIABLE",
        ),
        kwargs={
            "BRIEF_DOCS": "*",
            "FULL_DOCS": "*",
            "PROPERTY": "*",
            "INITIALIZE_FROM_VARIABLE": 1,
        },
    ),
    "else": spec("*"),
    "enable_language": spec(flags=("OPTIONAL",)),
    "enable_testing": spec(0),
    "endblock": spec("*"),
    "endforeach": spec("*"),
    "endfunction": spec("*"),
    "endif": spec("*"),
    "endmacro": spec("*"),
    "endwhile": spec("*"),
    "execute_process": spec(
        flags=(
            "ECHO_ERROR_VARIABLE",
            "ECHO_OUTPUT_VARIABLE",
            "ERROR_QUIET",
            "ERROR_STRIP_TRAILING_WHITESPACE",
            "OUTPUT_QUIET",
            "OUTPUT_STRIP_TRAILING_WHITESPACE",
        ),
        kwargs={
            "COMMAND": SHELL,
            "COMMAND_ECHO": 1,
            "COMMAND_ERROR_IS_FATAL": 1,
            "ENCODING": 1,
            "ERROR_FILE": "*",
            "ERROR_VARIABLE": "*",
            "INPUT_FILE": "*",
            "OUTPUT_FILE": "*",
            "OUTPUT_VARIABLE": "*",
            "RESULT_VARIABLE": "*",
            "RESULTS_VARIABLE": "*",
            "TIMEOUT": "*",
            "WORKING_DIRECTORY": "*",
        },
    ),
    "export": spec(
        flags=("APPEND", "EXPORT_LINK_INTERFACE_LIBRARIES"),
        kwargs={
            "ANDROID_MK": 1,
            "EXPORT": 1,
            "FILE": 1,
            "NAMESPACE": 1,
            "PACKAGE": 1,
            "TARGETS": "+",
        },
    ),
    "find_file": spec(flags=FIND_FLAGS, kwargs=FIND_KWARGS),
    "find_library": spec(flags=FIND_FLAGS, kwargs=FIND_KWARGS),
    "find_package": spec(
        "*",
        flags=(
            "CONFIG",
            "EXACT",
            "GLOBAL",
            "MODULE",
            "NO_MODULE",
            "NO_POLICY_SCOPE",
            "QUIET",
            "REQUIRED",
            "BYPASS_PROVIDER",
        )
        + FIND_FLAGS[:-2],
        kwargs={
            "COMPONENTS": "*",
            "OPTIONAL_COMPONENTS": "*",
            "NAMES": "*",
            "CONFIGS": "*",
            "HINTS": "*",
            "PATHS": "*",
            "PATH_SUFFIXES": "*",
            "REGISTRY_VIEW": 1,
        },
    ),
    "find_path": spec(flags=FIND_FLAGS, kwargs=FIND_KWARGS),
    "find_program": spec(flags=FIND_FLAGS, kwargs=FIND_KWARGS),
    "function": spec("1+"),
    "get_cmake_property": spec(2),
    "get_directory_property": spec(kwargs={"DIRECTORY": 1, "DEFINITION": 1}),
    "get_filename_component": spec("*", flags=("CACHE",), kwargs={"BASE_DIR": 1}),
    "get_property": spec(
        flags=("BRIEF_DOCS", "DEFINED", "FULL_DOCS", "GLOBAL", "SET", "VARIABLE"),
        kwargs={
            "CACHE": "*",
            "DIRECTORY": "*",
            "INSTALL": "*",
            "PROPERTY": "*",
            "SOURCE": "*",
            "TARGET": "*",
            "TARGET_DIRECTORY": "*",
            "TEST": "*",
        },
    ),
    "get_source_file_property": spec(
        "*", kwargs={"DIRECTORY": 1, "TARGET_DIRECTORY": 1}
    ),
    "get_target_property": spec("*"),
    "get_test_property": spec("*", kwargs={"DIRECTORY": 1}),
    "include": spec(
        flags=("NO_POLICY_SCOPE", "OPTIONAL"), kwargs={"RESULT_VARIABLE": "*"}
    ),
    "include_directories": spec(flags=("AFTER", "BEFORE", "SYSTEM")),
    "include_guard": spec("?", flags=("DIRECTORY", "GLOBAL")),
    "link_directories": spec(flags=("AFTER", "BEFORE")),
    "link_libraries": spec("*", flags=("debug", "optimized", "general")),
    "macro": spec("1+"),
    "mark_as_advanced": spec(flags=("CLEAR", "FORCE")),
    "math": spec("*", flags=("EXPR",), kwargs={"OUTPUT_FORMAT": 1}),
    "message": spec(
        kwargs={
            name: "*"
            for name in (
                "AUTHOR_WARNING",
                "CHECK_FAIL",
                "CHECK_PASS",
                "CHECK_START",
                "CONFIGURE_LOG",
                "DEBUG",
                "DEPRECATION",
                "FATAL_ERROR",
                "NOTICE",
                "SEND_ERROR",
                "STATUS",
                "TRACE",
                "VERBOSE",
                "WARNING",
            )
        }
    ),
    "option": spec("*"),
    "project": spec(
        kwargs={
            "COMPAT_VERSION": 1,
            "DESCRIPTION": 1,
            "HOMEPAGE_URL": 1,
            "LANGUAGES": "*",
            "SPDX_LICENSE": 1,
            "VERSION": "*",
        }
    ),
    "remove_definitions": spec("*"),
    "return": spec(kwargs={"PROPAGATE": "*"}),
    "separate_arguments": spec(
        "*",
        flags=(
            "UNIX_COMMAND",
            "WINDOWS_COMMAND",
            "NATIVE_COMMAND",
            "PROGRAM",
            "SEPARATE_ARGS",
        ),
    ),
    "set_directory_properties": spec(kwargs={"PROPERTIES": "*"}),
    "set_property": spec(
        flags=("APPEND", "APPEND_STRING", "GLOBAL"),
        kwargs={
            "CACHE": "*",
            "DIRECTORY": "*",
            "INSTALL": "*",
            "PROPERTY": "*",
            "SOURCE": "*",
            "TARGET": "*",
            "TARGET_DIRECTORY": "*",
            "TEST": "*",
        },
    ),
    "set_tests_properties": spec(kwargs={"DIRECTORY": 1, "PROPERTIES": "*"}),
    "site_name": spec(1),
    "source_group": spec(
        "*", kwargs={"FILES": "*", "REGULAR_EXPRESSION": "*", "TREE": 1, "PREFIX": 1}
    ),
    "string": spec(
        flags=("@ONLY", "ESCAPE_QUOTES", "REVERSE", "UTC"),
        kwargs=dict.fromkeys(
            (
                "ALPHABET",
                "ASCII",
                "COMPARE",
                "CONCAT",
                "CONFIGURE",
                "FIND",
                "LENGTH",
                "MAKE_C_IDENTIFIER",
                "MD5",
                "RANDOM",
                "RANDOM_SEED",
                "REGEX",
                "REPLACE",
                "SHA1",
                "SHA256",
                "SHA384",
                "SHA512",
                "STRIP",
                "SUBSTRING",
                "TIMESTAMP",
                "TOLOWER",
                "TOUPPER",
            ),
            "*",
        ),
    ),
    "target_compile_definitions": spec(kwargs={v: "+" for v in VISIBILITY}),
    "target_compile_features": spec(kwargs={v: "+" for v in VISIBILITY}),
    "target_compile_options": spec(kwargs={v: "+" for v in VISIBILITY}),
    "target_include_directories": spec(kwargs={v: "+" for v in VISIBILITY}),
    "target_link_directories": spec(kwargs={v: "+" for v in VISIBILITY}),
    "target_link_libraries": spec(
        kwargs={
            v: "+"
            for v in VISIBILITY
            + ("LINK_PRIVATE", "LINK_PUBLIC", "LINK_INTERFACE_LIBRARIES")
        }
    ),
    "target_link_options": spec(kwargs={v: "+" for v in VISIBILITY}),
    "target_precompile_headers": spec(
        kwargs={"REUSE_FROM": 1} | {v: "+" for v in VISIBILITY}
    ),
    "target_sources": spec(
        kwargs={
            v: spec(
                "*",
                kwargs={"FILE_SET": 1, "TYPE": 1, "BASE_DIRS": "+", "FILES": "+"},
            )
            for v in VISIBILITY
        }
    ),
    "try_compile": spec(
        [2, "+"],
        kwargs={
            "CMAKE_FLAGS": "*",
            "COMPILE_DEFINITIONS": "*",
            "COPY_FILE": "*",
            "COPY_FILE_ERROR": 1,
            "LINK_LIBRARIES": "*",
            "LINK_OPTIONS": "*",
            "LOG_DESCRIPTION": 1,
            "OUTPUT_VARIABLE": "*",
            "RESULT_VAR": "*",
            "SOURCES": "*",
            "SOURCE_FROM_CONTENT": 2,
            "SOURCE_FROM_FILE": 2,
            "SOURCE_FROM_VAR": 2,
            "C_STANDARD": 1,
            "CXX_STANDARD": 1,
        },
    ),
    "try_run": spec(
        kwargs={
            "ARGS": "*",
            "CMAKE_FLAGS": "*",
            "COMPILE_DEFINITIONS": "*",
            "COMPILE_OUTPUT_VARIABLE": "*",
            "OUTPUT_VARIABLE": "*",
            "RUN_OUTPUT_VARIABLE": "*",
            "SOURCES": "*",
        }
    ),
    "unset": spec("*", flags=("CACHE", "PARENT_SCOPE")),
    "variable_watch": spec("*"),
    # Commands from modules shipped with CMake.
    "check_c_compiler_flag": spec("*"),
    "check_c_source_compiles": spec("*", kwargs={"FAIL_REGEX": "*"}),
    "check_cxx_compiler_flag": spec("*"),
    "check_cxx_source_compiles": spec("*", kwargs={"FAIL_REGEX": "*"}),
    "check_function_exists": spec("*"),
    "check_include_file": spec("*"),
    "check_include_file_cxx": spec("*"),
    "check_include_files": spec("*", kwargs={"LANGUAGE": 1}),
    "check_ipo_supported": spec(kwargs={"RESULT": 1, "OUTPUT": 1, "LANGUAGES": "*"}),
    "check_library_exists": spec("*"),
    "check_symbol_exists": spec("*"),
    "check_cxx_symbol_exists": spec("*"),
    "check_type_size": spec("*", flags=("BUILTIN_TYPES_ONLY",), kwargs={"LANGUAGE": 1}),
    "cmake_print_variables": spec("*"),
    "configure_package_config_file": spec(
        "*",
        flags=("NO_SET_AND_CHECK_MACRO", "NO_CHECK_REQUIRED_COMPONENTS_MACRO"),
        kwargs={"INSTALL_DESTINATION": 1, "PATH_VARS": "*", "INSTALL_PREFIX": 1},
    ),
    "CPMAddPackage": spec("*", kwargs=CPM_KWARGS, spelling="CPMAddPackage"),
    "CPMDeclarePackage": spec("*", kwargs=CPM_KWARGS, spelling="CPMDeclarePackage"),
    "CPMFindPackage": spec("*", kwargs=CPM_KWARGS, spelling="CPMFindPackage"),
    "CPMGetPackage": spec("*", spelling="CPMGetPackage"),
    "CPMUsePackageLock": spec("*", spelling="CPMUsePackageLock"),
    "doxygen_add_docs": spec(
        "*",
        flags=("ALL", "USE_STAMP_FILE"),
        kwargs={"WORKING_DIRECTORY": 1, "COMMENT": "*", "CONFIG_FILE": 1},
    ),
    "ExternalProject_Add": spec(
        "*", kwargs=FETCH_KWARGS, spelling="ExternalProject_Add"
    ),
    "ExternalProject_Get_Property": spec("+", spelling="ExternalProject_Get_Property"),
    "FetchContent_Declare": spec(
        "*", kwargs=FETCH_KWARGS, spelling="FetchContent_Declare"
    ),
    "FetchContent_GetProperties": spec(
        "*",
        kwargs={"SOURCE_DIR": 1, "BINARY_DIR": 1, "POPULATED": 1},
        spelling="FetchContent_GetProperties",
    ),
    "FetchContent_MakeAvailable": spec("+", spelling="FetchContent_MakeAvailable"),
    "FetchContent_Populate": spec(
        "*", kwargs=FETCH_KWARGS, spelling="FetchContent_Populate"
    ),
    "find_package_handle_standard_args": spec(
        "*",
        flags=(
            "CONFIG_MODE",
            "HANDLE_COMPONENTS",
            "HANDLE_VERSION_RANGE",
            "NAME_MISMATCHED",
        ),
        kwargs={
            "DEFAULT_MSG": "*",
            "FAIL_MESSAGE": 1,
            "FOUND_VAR": 1,
            "REASON_FAILURE_MESSAGE": 1,
            "REQUIRED_VARS": "*",
            "VERSION_VAR": 1,
        },
    ),
    "generate_export_header": spec(
        "*",
        flags=("DEFINE_NO_DEPRECATED",),
        kwargs={
            name: 1
            for name in (
                "BASE_NAME",
                "CUSTOM_CONTENT_FROM_VARIABLE",
                "DEPRECATED_MACRO_NAME",
                "EXPORT_FILE_NAME",
                "EXPORT_MACRO_NAME",
                "INCLUDE_GUARD_NAME",
                "NO_DEPRECATED_MACRO_NAME",
                "NO_EXPORT_MACRO_NAME",
                "PREFIX_NAME",
                "STATIC_DEFINE",
            )
        },
    ),
    "gtest_add_tests": spec(
        flags=("SKIP_DEPENDENCY",),
        kwargs={
            "TARGET": 1,
            "SOURCES": "*",
            "EXTRA_ARGS": "*",
            "WORKING_DIRECTORY": 1,
            "TEST_PREFIX": 1,
            "TEST_SUFFIX": 1,
            "TEST_LIST": 1,
        },
    ),
    "gtest_discover_tests": spec(
        "*",
        flags=("NO_PRETTY_TYPES", "NO_PRETTY_VALUES"),
        kwargs={
            name: "*"
            for name in (
                "DISCOVERY_EXTRA_ARGS",
                "DISCOVERY_MODE",
                "DISCOVERY_TIMEOUT",
                "EXTRA_ARGS",
                "PROPERTIES",
                "TEST_FILTER",
                "TEST_LIST",
                "TEST_PREFIX",
                "TEST_SUFFIX",
                "WORKING_DIRECTORY",
                "XML_OUTPUT_DIR",
            )
        },
    ),
    "pkg_check_modules": spec(
        "*",
        flags=(
            "REQUIRED",
            "QUIET",
            "NO_CMAKE_PATH",
            "NO_CMAKE_ENVIRONMENT_PATH",
            "IMPORTED_TARGET",
            "GLOBAL",
        ),
    ),
    "pkg_search_module": spec(
        "*",
        flags=(
            "REQUIRED",
            "QUIET",
            "NO_CMAKE_PATH",
            "NO_CMAKE_ENVIRONMENT_PATH",
            "IMPORTED_TARGET",
            "GLOBAL",
        ),
    ),
    "write_basic_package_version_file": spec(
        "*",
        flags=("ARCH_INDEPENDENT",),
        kwargs={"VERSION": 1, "COMPATIBILITY": 1},
    ),
}


def _nest_kwargs(cmd: CmdSpec) -> None:
    """Make keyword arguments in SPECS nested argument groups (like cmake-format)."""
    for keyword, value in cmd.kwargs.items():
        if isinstance(value, (int, str)) and value != 0:
            cmd.kwargs[keyword] = spec(value)
        elif isinstance(value, CmdSpec):
            _nest_kwargs(value)


for _cmd in SPECS.values():
    _nest_kwargs(_cmd)

# Lowercase name -> spec, for case-insensitive lookup.
SPECS_LOWER: dict[str, CmdSpec] = {name.lower(): s for name, s in SPECS.items()}
