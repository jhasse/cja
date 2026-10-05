"""Tests for the CMake features that bundled Find modules rely on."""

from pathlib import Path

import pytest

from cja.generator import BuildContext, process_commands
from cja.parser import Command
from cja.utils import join_flags, split_flags


def _ctx(tmp_path: Path) -> BuildContext:
    return BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")


def _run(ctx: BuildContext, *commands: tuple[str, list[str]]) -> None:
    process_commands(
        [Command(name=n, args=a, line=i + 1) for i, (n, a) in enumerate(commands)],
        ctx,
    )


# --- nested variable references ---------------------------------------------


def test_nested_reference_with_concatenated_name(tmp_path: Path) -> None:
    """FindGTest's __gtest_import_library reads ${${_var}${_config_suffix}}."""
    ctx = _ctx(tmp_path)

    _run(
        ctx,
        ("set", ["GTEST_LIBRARY_RELEASE", "/x/libgtest.a"]),
        ("set", ["_var", "GTEST_LIBRARY"]),
        ("set", ["_suffix", "_RELEASE"]),
        ("set", ["OUT", "${${_var}${_suffix}}"]),
    )

    assert ctx.variables["OUT"] == "/x/libgtest.a"


# --- file(STRINGS) -----------------------------------------------------------


def test_file_strings_regex_filters_lines(tmp_path: Path) -> None:
    header = tmp_path / "v.h"
    header.write_text("alpha\nbeta 12\ngamma\n")
    ctx = _ctx(tmp_path)

    _run(ctx, ("file", ["STRINGS", str(header), "OUT", "REGEX", "^[ab]"]))

    assert ctx.variables["OUT"] == "alpha;beta 12"


def test_file_strings_regex_sets_match_variables(tmp_path: Path) -> None:
    header = tmp_path / "v.h"
    header.write_text("#define VER 3\n#define OTHER 4\n")
    ctx = _ctx(tmp_path)

    _run(
        ctx,
        ("file", ["STRINGS", str(header), "OUT", "REGEX", "^#define VER ([0-9]+)"]),
    )

    assert ctx.variables["OUT"] == "#define VER 3"
    assert ctx.variables["CMAKE_MATCH_1"] == "3"
    assert ctx.variables["CMAKE_MATCH_COUNT"] == "1"


def test_file_strings_limit_count(tmp_path: Path) -> None:
    f = tmp_path / "f.txt"
    f.write_text("a\nb\nc\n")
    ctx = _ctx(tmp_path)

    _run(ctx, ("file", ["STRINGS", str(f), "OUT", "LIMIT_COUNT", "2"]))

    assert ctx.variables["OUT"] == "a;b"


def test_file_strings_missing_file_gives_empty_variable(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)

    _run(ctx, ("file", ["STRINGS", str(tmp_path / "nope.h"), "OUT"]))

    assert ctx.variables["OUT"] == ""


def test_file_strings_relative_path_uses_source_dir(tmp_path: Path) -> None:
    (tmp_path / "rel.txt").write_text("one\n")
    ctx = _ctx(tmp_path)

    _run(ctx, ("file", ["STRINGS", "rel.txt", "OUT"]))

    assert ctx.variables["OUT"] == "one"


# --- list(POP_*), string(ASCII) ---------------------------------------------


def test_list_pop_front_and_back(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    ctx.variables["L"] = "a;b;c"

    _run(ctx, ("list", ["POP_FRONT", "L", "first"]))
    assert ctx.variables["first"] == "a"
    assert ctx.variables["L"] == "b;c"

    _run(ctx, ("list", ["POP_BACK", "L", "last"]))
    assert ctx.variables["last"] == "c"
    assert ctx.variables["L"] == "b"


def test_list_pop_front_empties_list_and_unsets_extra_vars(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    ctx.variables["L"] = "only"
    ctx.variables["second"] = "stale"

    _run(ctx, ("list", ["POP_FRONT", "L", "first", "second"]))

    assert ctx.variables["first"] == "only"
    assert "second" not in ctx.variables
    assert ctx.variables["L"] == ""


def test_string_ascii(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)

    _run(ctx, ("string", ["ASCII", "72", "105", "OUT"]))

    assert ctx.variables["OUT"] == "Hi"


# --- flag helpers ------------------------------------------------------------


def test_split_join_flags_round_trip_with_spaces_and_backslashes() -> None:
    tokens = ["-lfoo", r"C:\Program Files\x y\z.lib", "-Wl,--as-needed"]

    assert split_flags(join_flags(tokens)) == tokens


def test_join_flags_deduplicates() -> None:
    assert join_flags(["-lm", "-lm", "-lz"]) == "-lm -lz"


# --- imported targets ---------------------------------------------------------


def test_set_property_on_imported_target(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    include = tmp_path / "inc"

    _run(
        ctx,
        ("add_library", ["Foo::foo", "UNKNOWN", "IMPORTED"]),
        (
            "set_property",
            [
                "TARGET",
                "Foo::foo",
                "APPEND",
                "PROPERTY",
                "INTERFACE_LINK_LIBRARIES",
                "-lm",
            ],
        ),
        (
            "set_property",
            [
                "TARGET",
                "Foo::foo",
                "PROPERTY",
                "INTERFACE_INCLUDE_DIRECTORIES",
                str(include),
            ],
        ),
    )

    imported = ctx.imported_targets["Foo::foo"]
    assert "-lm" in split_flags(imported.libs)
    assert any(t.startswith("-I") and "inc" in t for t in split_flags(imported.cflags))


def test_imported_interface_link_libraries_propagate_other_targets(
    tmp_path: Path,
) -> None:
    ctx = _ctx(tmp_path)

    _run(
        ctx,
        ("add_library", ["Foo::bar", "UNKNOWN", "IMPORTED"]),
        (
            "set_target_properties",
            ["Foo::bar", "PROPERTIES", "IMPORTED_LOCATION", "/x/libbar.a"],
        ),
        ("add_library", ["Foo::foo", "UNKNOWN", "IMPORTED"]),
        (
            "set_target_properties",
            [
                "Foo::foo",
                "PROPERTIES",
                "IMPORTED_LOCATION",
                "/x/libfoo.a",
                "INTERFACE_LINK_LIBRARIES",
                "Foo::bar",
            ],
        ),
    )

    foo = ctx.imported_targets["Foo::foo"]
    assert split_flags(foo.libs) == ["/x/libfoo.a"]
    assert foo.link_targets == ["Foo::bar"]


def test_imported_link_flag_strings_are_split(tmp_path: Path) -> None:
    """A flag string like "-L<dir> -lfoo" in INTERFACE_LINK_LIBRARIES gives
    separate link arguments, not one quoted token."""
    from cja.generator import generate_ninja

    ctx = _ctx(tmp_path)
    _run(
        ctx,
        ("add_library", ["Bar::bar", "UNKNOWN", "IMPORTED"]),
        (
            "set_target_properties",
            ["Bar::bar", "PROPERTIES", "INTERFACE_LINK_LIBRARIES", "-L/x/lib -lbar"],
        ),
        ("add_executable", ["app", "main.cpp"]),
        ("target_link_libraries", ["app", "PRIVATE", "Bar::bar"]),
    )

    assert split_flags(ctx.imported_targets["Bar::bar"].libs) == ["-L/x/lib", "-lbar"]
    ninja_path = tmp_path / "build.ninja"
    generate_ninja(ctx, ninja_path, "build")
    assert " -L/x/lib -lbar" in ninja_path.read_text()


def test_imported_location_uses_forward_slashes(tmp_path: Path) -> None:
    """On Windows, IMPORTED_LOCATION built from CMAKE_CURRENT_LIST_DIR has
    backslashes; like find_* results, it's stored with forward slashes."""
    ctx = _ctx(tmp_path)
    _run(
        ctx,
        ("add_library", ["Foo::foo", "STATIC", "IMPORTED"]),
        (
            "set_target_properties",
            [
                "Foo::foo",
                "PROPERTIES",
                "IMPORTED_LOCATION_RELEASE",
                "C:\\pkg\\lib\\cmake\\Foo/libfoo.a",
            ],
        ),
    )

    assert split_flags(ctx.imported_targets["Foo::foo"].libs) == [
        "C:/pkg/lib/cmake/Foo/libfoo.a"
    ]


def test_imported_link_targets_resolved_at_generation(tmp_path: Path) -> None:
    """Like <Pkg>Targets.cmake, set the link interface before the dependency's
    IMPORTED_LOCATION (which comes from <Pkg>Targets-release.cmake)."""
    from cja.generator import generate_ninja

    ctx = _ctx(tmp_path)
    _run(
        ctx,
        ("add_library", ["Foo::bar", "STATIC", "IMPORTED"]),
        ("add_library", ["Foo::foo", "STATIC", "IMPORTED"]),
        (
            "set_target_properties",
            ["Foo::foo", "PROPERTIES", "INTERFACE_LINK_LIBRARIES", "Foo::bar"],
        ),
        (
            "set_target_properties",
            ["Foo::foo", "PROPERTIES", "IMPORTED_LOCATION_RELEASE", "/x/libfoo.a"],
        ),
        (
            "set_target_properties",
            ["Foo::bar", "PROPERTIES", "IMPORTED_LOCATION_RELEASE", "/x/libbar.a"],
        ),
        ("add_executable", ["app", "main.cpp"]),
        ("target_link_libraries", ["app", "PRIVATE", "Foo::foo"]),
    )

    ninja_path = tmp_path / "build.ninja"
    generate_ninja(ctx, ninja_path, "build")
    content = ninja_path.read_text()
    assert "/x/libfoo.a /x/libbar.a" in content
    assert "Foo::" not in content


# --- find_* options -----------------------------------------------------------


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return path


def test_find_library_names_per_dir(tmp_path: Path) -> None:
    dir1 = tmp_path / "d1"
    dir2 = tmp_path / "d2"
    _touch(dir1 / "libb.a")
    _touch(dir2 / "liba.a")
    args = ["A", "NAMES", "a", "b", "PATHS", str(dir1), str(dir2), "NO_DEFAULT_PATH"]

    default = _ctx(tmp_path)
    _run(default, ("find_library", list(args)))
    per_dir = _ctx(tmp_path)
    _run(per_dir, ("find_library", [*args, "NAMES_PER_DIR"]))

    assert Path(default.variables["A"]).name == "liba.a"
    assert Path(per_dir.variables["A"]).name == "libb.a"


def test_find_library_no_default_path_ignores_prefix_path(tmp_path: Path) -> None:
    prefix = tmp_path / "prefix"
    _touch(prefix / "lib" / "libfoo.a")
    other = tmp_path / "other"
    other.mkdir()

    searching = _ctx(tmp_path)
    searching.variables["CMAKE_PREFIX_PATH"] = str(prefix)
    _run(searching, ("find_library", ["V", "foo"]))
    restricted = _ctx(tmp_path)
    restricted.variables["CMAKE_PREFIX_PATH"] = str(prefix)
    _run(restricted, ("find_library", ["V", "foo", "PATHS", str(other), "NO_DEFAULT_PATH"]))

    assert Path(searching.variables["V"]).name == "libfoo.a"
    assert restricted.variables["V"] == "V-NOTFOUND"


def test_find_path_no_default_path_ignores_prefix_path(tmp_path: Path) -> None:
    prefix = tmp_path / "prefix"
    _touch(prefix / "include" / "foo.h")
    other = tmp_path / "other"
    other.mkdir()

    ctx = _ctx(tmp_path)
    ctx.variables["CMAKE_PREFIX_PATH"] = str(prefix)
    _run(ctx, ("find_path", ["V", "foo.h", "PATHS", str(other), "NO_DEFAULT_PATH"]))

    assert ctx.variables["V"] == "V-NOTFOUND"


def test_find_library_honors_find_library_suffixes(tmp_path: Path) -> None:
    lib_dir = tmp_path / "lib"
    _touch(lib_dir / "libfoo.so")
    _touch(lib_dir / "libfoo.a")
    ctx = _ctx(tmp_path)
    ctx.variables["CMAKE_FIND_LIBRARY_SUFFIXES"] = ".a"

    _run(ctx, ("find_library", ["V", "foo", "PATHS", str(lib_dir), "NO_DEFAULT_PATH"]))

    assert Path(ctx.variables["V"]).name == "libfoo.a"


# --- find_package() request variables ------------------------------------------


def _module_ctx(tmp_path: Path) -> BuildContext:
    modules = tmp_path / "cmake"
    modules.mkdir()
    (modules / "FindFoo.cmake").write_text("set(Foo_FOUND TRUE)\n")
    ctx = _ctx(tmp_path)
    ctx.variables["CMAKE_MODULE_PATH"] = str(modules)
    return ctx


def test_find_module_receives_version_and_components(tmp_path: Path) -> None:
    ctx = _module_ctx(tmp_path)

    _run(
        ctx,
        (
            "find_package",
            [
                "Foo",
                "1.2.3",
                "EXACT",
                "QUIET",
                "REQUIRED",
                "COMPONENTS",
                "a",
                "b",
                "OPTIONAL_COMPONENTS",
                "c",
            ],
        ),
    )

    v = ctx.variables
    assert v["Foo_FIND_VERSION"] == "1.2.3"
    assert (v["Foo_FIND_VERSION_MAJOR"], v["Foo_FIND_VERSION_MINOR"]) == ("1", "2")
    assert v["Foo_FIND_VERSION_PATCH"] == "3"
    assert v["Foo_FIND_VERSION_COUNT"] == "3"
    assert v["Foo_FIND_VERSION_EXACT"] == "TRUE"
    assert v["Foo_FIND_QUIETLY"] == "TRUE"
    assert v["Foo_FIND_COMPONENTS"] == "a;b;c"
    assert v["Foo_FIND_REQUIRED_a"] == "TRUE"
    assert v["Foo_FIND_REQUIRED_b"] == "TRUE"
    assert v["Foo_FIND_REQUIRED_c"] == "FALSE"


def test_find_module_version_range_variables(tmp_path: Path) -> None:
    ctx = _module_ctx(tmp_path)

    _run(ctx, ("find_package", ["Foo", "1.0...<2.0"]))

    v = ctx.variables
    assert v["Foo_FIND_VERSION"] == "1.0"
    assert v["Foo_FIND_VERSION_RANGE"] == "1.0...<2.0"
    assert v["Foo_FIND_VERSION_MAX"] == "2.0"
    assert v["Foo_FIND_VERSION_RANGE_MAX"] == "EXCLUDE"


def test_find_module_request_variables_do_not_leak_between_calls(
    tmp_path: Path,
) -> None:
    ctx = _module_ctx(tmp_path)

    _run(ctx, ("find_package", ["Foo", "1.2", "COMPONENTS", "a"]))
    _run(ctx, ("find_package", ["Foo"]))

    assert "Foo_FIND_VERSION" not in ctx.variables
    assert "Foo_FIND_COMPONENTS" not in ctx.variables
    assert "Foo_FIND_REQUIRED_a" not in ctx.variables


# --- find_package_handle_standard_args() ----------------------------------------


def _fphsa_ctx(tmp_path: Path, **variables: str) -> BuildContext:
    ctx = _ctx(tmp_path)
    ctx.variables["Foo_LIB"] = "/usr/lib/libfoo.a"
    ctx.variables["Foo_VER"] = "2.1.0"
    ctx.variables.update(variables)
    return ctx


def _fphsa(ctx: BuildContext, *extra: str) -> str:
    _run(
        ctx,
        (
            "find_package_handle_standard_args",
            ["Foo", "REQUIRED_VARS", "Foo_LIB", "VERSION_VAR", "Foo_VER", *extra],
        ),
    )
    return ctx.variables["Foo_FOUND"]


def test_fphsa_sets_uppercase_found_variable(tmp_path: Path) -> None:
    ctx = _fphsa_ctx(tmp_path)

    assert _fphsa(ctx) == "TRUE"
    assert ctx.variables["FOO_FOUND"] == "TRUE"


@pytest.mark.parametrize(
    ("requested", "exact", "expected"),
    [
        ("2.0", "FALSE", "TRUE"),
        ("2.1.0", "FALSE", "TRUE"),
        ("3.0", "FALSE", "FALSE"),
        ("2.1", "TRUE", "TRUE"),  # exact compares only the requested components
        ("2.0", "TRUE", "FALSE"),
    ],
)
def test_fphsa_version_check(
    tmp_path: Path, requested: str, exact: str, expected: str
) -> None:
    ctx = _fphsa_ctx(
        tmp_path, Foo_FIND_VERSION=requested, Foo_FIND_VERSION_EXACT=exact
    )

    assert _fphsa(ctx) == expected
    assert ctx.variables["FOO_FOUND"] == expected


def test_fphsa_version_range(tmp_path: Path) -> None:
    def check(maximum: str, range_max: str, handle_range: bool = True) -> str:
        ctx = _fphsa_ctx(
            tmp_path,
            Foo_FIND_VERSION="1.0",
            Foo_FIND_VERSION_RANGE=f"1.0...{maximum}",
            Foo_FIND_VERSION_MAX=maximum.lstrip("<"),
            Foo_FIND_VERSION_RANGE_MAX=range_max,
        )
        return _fphsa(ctx, *(["HANDLE_VERSION_RANGE"] if handle_range else []))

    assert check("3.0", "INCLUDE") == "TRUE"
    assert check("2.1.0", "INCLUDE") == "TRUE"
    assert check("2.1.0", "EXCLUDE") == "FALSE"
    assert check("2.0", "INCLUDE") == "FALSE"


def test_fphsa_missing_version_when_one_is_requested(tmp_path: Path) -> None:
    ctx = _fphsa_ctx(tmp_path, Foo_FIND_VERSION="1.0")
    ctx.variables["Foo_VER"] = ""

    assert _fphsa(ctx) == "FALSE"


def test_fphsa_required_failure_raises(tmp_path: Path) -> None:
    ctx = _fphsa_ctx(
        tmp_path, Foo_FIND_VERSION="9.0", Foo_FIND_REQUIRED="TRUE"
    )

    with pytest.raises(SystemExit):
        _fphsa(ctx)


def test_fphsa_handle_components(tmp_path: Path) -> None:
    def check(**variables: str) -> str:
        ctx = _fphsa_ctx(
            tmp_path,
            Foo_FIND_COMPONENTS="a;b",
            Foo_FIND_REQUIRED_a="TRUE",
            Foo_FIND_REQUIRED_b="FALSE",
            **variables,
        )
        return _fphsa(ctx, "HANDLE_COMPONENTS")

    assert check(Foo_a_FOUND="TRUE") == "TRUE"
    assert check() == "FALSE"  # required component `a` is missing
    assert check(Foo_a_FOUND="TRUE", Foo_b_FOUND="FALSE") == "TRUE"  # b optional


def test_fphsa_handle_version_range_keyword_is_not_a_required_var(
    tmp_path: Path,
) -> None:
    ctx = _ctx(tmp_path)
    ctx.variables["Foo_LIB"] = "/usr/lib/libfoo.a"

    _run(
        ctx,
        (
            "find_package_handle_standard_args",
            ["Foo", "REQUIRED_VARS", "Foo_LIB", "HANDLE_VERSION_RANGE"],
        ),
    )

    assert ctx.variables["Foo_FOUND"] == "TRUE"
