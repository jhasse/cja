"""The commands of CMake's FeatureSummary module.

Like the module, they keep their state in global properties, so projects can
read ENABLED_FEATURES or change FeatureSummary_PKG_TYPES as with CMake. The
packages come from the properties that find_package() sets.
"""

import re

from .build_context import BuildContext
from .commands import handle_file, handle_message
from .config_utils import expanded_condition_holds
from .parser import Command
from .utils import is_truthy

_PKG_TYPES = "FeatureSummary_PKG_TYPES"
_REQUIRED_PKG_TYPES = "FeatureSummary_REQUIRED_PKG_TYPES"
_DEFAULT_PKG_TYPE = "FeatureSummary_DEFAULT_PKG_TYPE"

_BASE_WHAT_TITLES = {
    "ENABLED_FEATURES": "The following features have been enabled:",
    "DISABLED_FEATURES": "The following features have been disabled:",
    "PACKAGES_FOUND": "The following packages have been found:",
    "PACKAGES_NOT_FOUND": "The following packages have not been found:",
}


class _Args:
    """The arguments of a command, parsed like cmake_parse_arguments()."""

    def __init__(
        self,
        args: list[str],
        options: tuple[str, ...] = (),
        one_value: tuple[str, ...] = (),
        multi_value: tuple[str, ...] = (),
    ) -> None:
        self.options: set[str] = set()
        self.values: dict[str, str] = {}
        self.lists: dict[str, list[str]] = {}
        self.unparsed: list[str] = []
        keywords = {*options, *one_value, *multi_value}
        current: list[str] | None = None
        i = 0
        while i < len(args):
            arg = args[i]
            i += 1
            if arg in options:
                self.options.add(arg)
                current = None
            elif arg in one_value:
                current = None
                if i < len(args) and args[i] not in keywords:
                    self.values[arg] = args[i]
                    i += 1
            elif arg in multi_value:
                current = self.lists.setdefault(arg, [])
            elif current is not None:
                current.append(arg)
            else:
                self.unparsed.append(arg)


def _fatal_error(ctx: BuildContext, cmd: Command, message: str) -> None:
    ctx.print_error(message, cmd.line)
    raise SystemExit(1)


def _status(ctx: BuildContext, cmd: Command, message: str) -> None:
    handle_message(ctx, cmd, ["STATUS", message])


def _get(ctx: BuildContext, name: str) -> str:
    return ctx.global_properties.get(name, "")


def _get_list(ctx: BuildContext, name: str) -> list[str]:
    return [item for item in _get(ctx, name).split(";") if item]


def _append(ctx: BuildContext, name: str, value: str) -> None:
    if name in ctx.global_properties:
        ctx.global_properties[name] += ";" + value
    else:
        ctx.global_properties[name] = value


def _types_message(types: list[str]) -> str:
    """List the types like "A, B and C"."""
    if len(types) < 2:
        return "".join(types)
    return f"{', '.join(types[:-1])} and {types[-1]}"


def include_feature_summary(ctx: BuildContext) -> None:
    """Set the defaults of include(FeatureSummary) that a project didn't set."""
    ctx.global_properties.setdefault(_PKG_TYPES, "RUNTIME;OPTIONAL;RECOMMENDED;REQUIRED")
    ctx.global_properties.setdefault(_REQUIRED_PKG_TYPES, "REQUIRED")
    ctx.global_properties.setdefault(_DEFAULT_PKG_TYPE, "OPTIONAL")


def _get_feature_summary(
    ctx: BuildContext, cmd: Command, what: str, include_quiet: bool
) -> str:
    """The list of features or packages for one part of ``feature_summary()``."""
    pkg_types = _get_list(ctx, _PKG_TYPES)
    default_type = _get(ctx, _DEFAULT_PKG_TYPE)
    required_types = _get_list(ctx, _REQUIRED_PKG_TYPES)

    wanted_type = "ANY"
    for pkg_type in pkg_types:
        if re.search(f"{pkg_type}_PACKAGES_(NOT_)?FOUND", what):
            wanted_type = pkg_type
            break
    if "PACKAGES_FOUND" in what:
        what = "PACKAGES_FOUND"
    elif "PACKAGES_NOT_FOUND" in what:
        what = "PACKAGES_NOT_FOUND"

    text = ""
    for name in dict.fromkeys(_get_list(ctx, what)):
        current_type = _get(ctx, f"_CMAKE_{name}_TYPE")
        if not is_truthy(current_type):
            if default_type not in pkg_types:
                _fatal_error(
                    ctx,
                    cmd,
                    f"Bad package property type {default_type} used in global "
                    f"property {_DEFAULT_PKG_TYPE}. Valid types are "
                    f"{_types_message(pkg_types)}. Either update {_DEFAULT_PKG_TYPE} "
                    f"or add {default_type} to the {_PKG_TYPES} global property.",
                )
            current_type = default_type
        if wanted_type not in ("ANY", current_type):
            continue

        # QUIET packages are only listed if they're required or asked for.
        if (
            current_type not in required_types
            and not include_quiet
            and is_truthy(_get(ctx, f"_CMAKE_{name}_QUIET"))
        ):
            continue
        if is_truthy(_get(ctx, f"_CMAKE_{name}_TRANSITIVE_DEPENDENCY")):
            continue

        text += f"\n * {name}"
        if is_truthy(version := _get(ctx, f"_CMAKE_{name}_REQUIRED_VERSION")):
            text += f" (required version {version})"
        if is_truthy(description := _get(ctx, f"_CMAKE_{name}_DESCRIPTION")):
            text += f", {description}"
        if is_truthy(url := _get(ctx, f"_CMAKE_{name}_URL")):
            text += f", <{url}>"
        for purpose in _get_list(ctx, f"_CMAKE_{name}_PURPOSE"):
            text += f"\n   {purpose}"
    return text


def handle_feature_summary(
    ctx: BuildContext, cmd: Command, args: list[str], strict: bool
) -> None:
    """Handle feature_summary()."""
    include_feature_summary(ctx)
    parsed = _Args(
        args,
        options=(
            "APPEND",
            "INCLUDE_QUIET_PACKAGES",
            "FATAL_ON_MISSING_REQUIRED_PACKAGES",
            "QUIET_ON_EMPTY",
            "DEFAULT_DESCRIPTION",
        ),
        one_value=("FILENAME", "VAR", "DESCRIPTION"),
        multi_value=("WHAT",),
    )
    if parsed.unparsed:
        _fatal_error(
            ctx,
            cmd,
            "Unknown keywords given to FEATURE_SUMMARY(): "
            f'"{";".join(parsed.unparsed)}"',
        )
    what = parsed.lists.get("WHAT", [])
    if not what:
        _fatal_error(
            ctx,
            cmd,
            "The call to FEATURE_SUMMARY() doesn't set the required WHAT argument.",
        )
    include_quiet = "INCLUDE_QUIET_PACKAGES" in parsed.options
    quiet_on_empty = "QUIET_ON_EMPTY" in parsed.options
    description = parsed.values.get("DESCRIPTION")
    default_description = "DEFAULT_DESCRIPTION" in parsed.options
    if default_description and description is not None:
        ctx.print_warning(
            "DEFAULT_DESCRIPTION option discarded since DESCRIPTION is set.", cmd.line
        )
        default_description = False

    pkg_types = _get_list(ctx, _PKG_TYPES)
    required_types = _get_list(ctx, _REQUIRED_PKG_TYPES)
    titles = dict(_BASE_WHAT_TITLES)
    for pkg_type in pkg_types:
        type_description = ctx.global_properties.get(
            f"FeatureSummary_{pkg_type}_DESCRIPTION", f"{pkg_type} packages"
        )
        titles[f"{pkg_type}_PACKAGES_FOUND"] = (
            f"The following {type_description} have been found:"
        )
        titles[f"{pkg_type}_PACKAGES_NOT_FOUND"] = (
            f"The following {type_description} have not been found:"
        )
    required_parts = {f"{t}_PACKAGES_NOT_FOUND" for t in required_types}

    text: str | None = None
    required_packages_not_found = False
    if len(what) == 1 and what[0] in titles:
        summary = _get_feature_summary(ctx, cmd, what[0], include_quiet)
        if is_truthy(summary) or not quiet_on_empty:
            if default_description:
                text = f"{titles[what[0]]}\n{summary}\n"
            else:
                text = f"{description or ''}{summary}\n"
        if is_truthy(summary) and what[0] in required_parts:
            required_packages_not_found = True
    else:
        if what == ["ALL"]:
            parts = [
                "ENABLED_FEATURES",
                *(f"{t}_PACKAGES_FOUND" for t in pkg_types),
                "DISABLED_FEATURES",
                *(f"{t}_PACKAGES_NOT_FOUND" for t in pkg_types),
            ]
        else:
            parts = []
            for part in what:
                if part in titles:
                    parts.append(part)
                elif part == "ALL":
                    _fatal_error(
                        ctx,
                        cmd,
                        "The WHAT argument of FEATURE_SUMMARY() contains ALL, "
                        "which cannot be combined with other values.",
                    )
                else:
                    _fatal_error(
                        ctx,
                        cmd,
                        f"The WHAT argument of FEATURE_SUMMARY() contains {part}, "
                        "which is not a valid value.",
                    )
        text = description or ""
        for part in parts:
            summary = _get_feature_summary(ctx, cmd, part, include_quiet)
            if is_truthy(summary):
                if is_truthy(text):
                    text += "\n-- "
                text += f"{titles[part]}\n{summary}\n"
                if part in required_parts:
                    required_packages_not_found = True

    if is_truthy(text or "") or not quiet_on_empty:
        text = text or ""
        var = parsed.values.get("VAR")
        if filename := parsed.values.get("FILENAME"):
            mode = "APPEND" if "APPEND" in parsed.options else "WRITE"
            handle_file(ctx, cmd, [mode, filename, text], strict)
        elif not var:
            _status(ctx, cmd, text)
        if var:
            ctx.variables[var] = text

    if (
        required_packages_not_found
        and "FATAL_ON_MISSING_REQUIRED_PACKAGES" in parsed.options
    ):
        _fatal_error(
            ctx,
            cmd,
            "feature_summary() Error: REQUIRED package(s) are missing, "
            "aborting CMake run.",
        )


def handle_set_package_properties(
    ctx: BuildContext, cmd: Command, args: list[str]
) -> None:
    """Handle set_package_properties(<name> PROPERTIES ...)."""
    include_feature_summary(ctx)
    if len(args) < 2 or args[1] != "PROPERTIES":
        _fatal_error(
            ctx, cmd, "PROPERTIES keyword is missing in SET_PACKAGE_PROPERTIES() call."
        )
    name = args[0]
    parsed = _Args(args[2:], one_value=("DESCRIPTION", "URL", "TYPE", "PURPOSE"))
    if parsed.unparsed:
        _fatal_error(
            ctx,
            cmd,
            "Unknown keywords given to SET_PACKAGE_PROPERTIES(): "
            f'"{";".join(parsed.unparsed)}"',
        )

    description = parsed.values.get("DESCRIPTION", "")
    if is_truthy(description):
        prop = f"_CMAKE_{name}_DESCRIPTION"
        old = _get(ctx, prop)
        if is_truthy(old) and old != description:
            _status(
                ctx,
                cmd,
                f"Warning: Property DESCRIPTION for package {name} already set to "
                f'"{old}", overriding it with "{description}"',
            )
        ctx.global_properties[prop] = description

    url = parsed.values.get("URL", "")
    if is_truthy(url):
        prop = f"_CMAKE_{name}_URL"
        old = _get(ctx, prop)
        if is_truthy(old) and old != url:
            _status(
                ctx,
                cmd,
                f'Warning: Property URL already set to "{old}", overriding it with '
                f'"{url}"',
            )
        ctx.global_properties[prop] = url

    # A package can have several purposes inside a project.
    purpose = parsed.values.get("PURPOSE", "")
    if is_truthy(purpose):
        _append(ctx, f"_CMAKE_{name}_PURPOSE", purpose)

    if (pkg_type := parsed.values.get("TYPE")) is not None:
        # The types are listed in FeatureSummary_PKG_TYPES by priority.
        pkg_types = _get_list(ctx, _PKG_TYPES)
        if pkg_type not in pkg_types:
            _fatal_error(
                ctx,
                cmd,
                f"Bad package property type {pkg_type} used in "
                f"SET_PACKAGE_PROPERTIES(). Valid types are {_types_message(pkg_types)}.",
            )
        prop = f"_CMAKE_{name}_TYPE"
        previous = _get(ctx, prop)
        previous_index = pkg_types.index(previous) if previous in pkg_types else -1
        # A previously set TYPE isn't lowered.
        if pkg_types.index(pkg_type) > previous_index:
            ctx.global_properties[prop] = pkg_type


def handle_add_feature_info(ctx: BuildContext, cmd: Command, args: list[str]) -> None:
    """Handle add_feature_info(<name> <depends> <description>)."""
    if len(args) < 3:
        _fatal_error(ctx, cmd, "add_feature_info() requires name, depends and description")
    name, depends, description = args[:3]
    # CMake 3.28, which cja reports as CMAKE_VERSION, doesn't have CMP0183 yet,
    # so each element of <depends> is split at spaces, not parsed as a condition.
    enabled = all(
        expanded_condition_holds(ctx, [token for token in re.split(" +", d) if token])
        for d in depends.split(";")
        if d
    )
    _append(ctx, "ENABLED_FEATURES" if enabled else "DISABLED_FEATURES", name)
    ctx.global_properties[f"_CMAKE_{name}_DESCRIPTION"] = description


def handle_set_package_info(ctx: BuildContext, cmd: Command, args: list[str]) -> None:
    """Handle the deprecated set_package_info(<name> <description> [<url> [<purpose>]])."""
    handle_message(
        ctx,
        cmd,
        [
            "DEPRECATION",
            "SET_PACKAGE_INFO is deprecated. Use SET_PACKAGE_PROPERTIES instead.",
        ],
    )
    if len(args) < 2:
        _fatal_error(ctx, cmd, "set_package_info() requires name and description")
    name = args[0]
    ctx.global_properties[f"_CMAKE_{name}_DESCRIPTION"] = args[1]
    if len(args) > 2 and args[2]:
        ctx.global_properties[f"_CMAKE_{name}_URL"] = args[2]
    if len(args) > 3 and args[3]:
        _append(ctx, f"_CMAKE_{name}_PURPOSE", args[3])


def handle_set_feature_info(ctx: BuildContext, cmd: Command, args: list[str]) -> None:
    """Handle the deprecated set_feature_info(), the same as set_package_info()."""
    handle_message(
        ctx,
        cmd,
        ["DEPRECATION", "SET_FEATURE_INFO is deprecated. Use ADD_FEATURE_INFO instead."],
    )
    handle_set_package_info(ctx, cmd, args)


def handle_print_features(
    ctx: BuildContext, cmd: Command, what: str, description: str, strict: bool
) -> None:
    """Handle the deprecated print_enabled_features() and print_disabled_features()."""
    handle_message(
        ctx,
        cmd,
        [
            "DEPRECATION",
            f"{cmd.name.upper()} is deprecated. Use\n"
            f'    feature_summary(WHAT {what} DESCRIPTION "{description}")',
        ],
    )
    handle_feature_summary(ctx, cmd, ["WHAT", what, "DESCRIPTION", description], strict)
