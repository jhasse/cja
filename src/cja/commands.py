import glob as py_glob
import hashlib
import os
from pathlib import Path
import re
import sys
from .build_context import (
    BuildContext,
    find_matching_endfunction,
    find_matching_endmacro,
)
from .syntax import (
    FunctionDef,
    MacroDef,
    SourceFileProperties,
    evaluate_condition,
)
from .parser import Command
from .targets import Executable, Library
from .utils import (
    UNDEFINED_VAR_SENTINEL,
    is_truthy,
    resolve_cmake_path,
    strip_generator_expressions,
    to_posix_path,
)


def _is_supported_include_dir_genex(value: str) -> bool:
    """Return True for include-dir generator expressions we intentionally support."""
    return bool(re.fullmatch(r"\$<(BUILD_INTERFACE|INSTALL_INTERFACE):[^>]*>", value))


def handle_cmake_policy(
    ctx: BuildContext,
    cmd: Command,
    args: list[str],
) -> None:
    """Handle cmake_policy() command."""
    if args:
        subcommand = args[0].upper()
        if subcommand == "SET" and len(args) >= 3:
            policy = args[1]
            value = args[2].upper()
            if value == "OLD":
                ctx.print_warning(
                    f"cmake_policy(SET {policy} OLD) is called, but cja always uses NEW behavior for all policies",
                    cmd.line,
                )
        elif subcommand == "GET" and len(args) >= 3:
            var_name = args[2]
            # cja always uses NEW behavior
            ctx.variables[var_name] = "NEW"
        elif subcommand in ("PUSH", "POP", "VERSION"):
            pass


def handle_project(
    ctx: BuildContext,
    args: list[str],
) -> None:
    """Handle project() command."""
    if args:
        ctx.project_name = args[0]
        ctx.variables["PROJECT_NAME"] = args[0]
        ctx.variables["CMAKE_PROJECT_NAME"] = args[0]
        ctx.variables["CMAKE_C_FLAGS"] = ""  # TODO: Only set when C is enabled
        ctx.variables["CMAKE_CXX_FLAGS"] = ""  # TODO: Only set when CXX is enabled
        ctx.variables["PROJECT_SOURCE_DIR"] = str(ctx.current_source_dir)
        ctx.variables["PROJECT_BINARY_DIR"] = str(ctx.build_dir)
        source_var = f"{args[0]}_SOURCE_DIR"
        binary_var = f"{args[0]}_BINARY_DIR"
        ctx.variables[source_var] = str(ctx.current_source_dir)
        ctx.variables[binary_var] = str(ctx.build_dir)
        ctx.cache_variables.add(source_var)
        ctx.cache_variables.add(binary_var)


def _collect_directory_include_dirs(ctx: BuildContext) -> list[str]:
    """Collect INCLUDE_DIRECTORIES from current directory and parents."""
    try:
        current = ctx.current_source_dir.resolve()
    except FileNotFoundError:
        current = ctx.current_source_dir
    try:
        root = ctx.source_dir.resolve()
    except FileNotFoundError:
        root = ctx.source_dir

    chain: list[str] = []
    path = current
    while True:
        chain.append(str(path))
        if path == root or path.parent == path:
            break
        path = path.parent

    include_dirs: list[str] = []
    for d in reversed(chain):
        props = ctx.directory_properties.get(d)
        if not props:
            continue
        value = props.get("INCLUDE_DIRECTORIES")
        if value:
            include_dirs.extend([p for p in value.split(";") if p])
    return include_dirs


def handle_include_directories(
    ctx: BuildContext,
    cmd: Command,
    args: list[str],
    strict: bool,
) -> None:
    """Handle include_directories() command."""
    if not args:
        return

    dirs: list[str] = []
    for arg in args:
        if arg in ("BEFORE", "AFTER", "SYSTEM"):
            continue
        expanded = ctx.expand_variables(arg, strict, cmd.line)
        if "$<" in expanded:
            ctx.print_warning(
                f"generator expressions in include_directories are not yet supported: {arg}",
                cmd.line,
            )
        expanded = strip_generator_expressions(expanded)
        if not expanded:
            continue
        dirs.append(resolve_cmake_path(expanded, ctx.current_source_dir))

    if not dirs:
        return

    try:
        abs_dir = str(ctx.current_source_dir.resolve())
    except FileNotFoundError:
        abs_dir = str(ctx.current_source_dir.absolute())
    if abs_dir not in ctx.directory_properties:
        ctx.directory_properties[abs_dir] = {}

    existing = ctx.directory_properties[abs_dir].get("INCLUDE_DIRECTORIES")
    if existing:
        ctx.directory_properties[abs_dir]["INCLUDE_DIRECTORIES"] = (
            existing + ";" + ";".join(dirs)
        )
    else:
        ctx.directory_properties[abs_dir]["INCLUDE_DIRECTORIES"] = ";".join(dirs)


def handle_target_link_libraries(
    ctx: BuildContext,
    cmd: Command,
    args: list[str],
) -> None:
    """Handle target_link_libraries() command."""
    if len(args) >= 2:
        target_name = args[0]
        # Parse libraries with visibility keywords
        # CMake supports: target_link_libraries(<target> <PRIVATE|PUBLIC|INTERFACE> <item>...)
        visibility = "PUBLIC"  # Default visibility
        for arg in args[1:]:
            if len(arg) == 0:
                continue  # Argument might be an empty variable, skip
            if arg == "PUBLIC":
                visibility = "PUBLIC"
            elif arg == "INTERFACE":
                visibility = "INTERFACE"
            elif arg == "PRIVATE":
                visibility = "PRIVATE"
            else:
                # It's a library name
                if "$<" in arg:
                    from .utils import strip_generator_expressions

                    ctx.print_warning(
                        "generator expressions in target_link_libraries are not yet supported",
                        cmd.line,
                    )
                    arg = strip_generator_expressions(arg)
                    if not arg:
                        continue

                lib = ctx.get_library(target_name)
                if lib:
                    # For libraries, we track linked libraries but don't use them yet
                    # (static libraries don't link, but they might need to propagate flags)
                    if visibility == "PUBLIC":
                        lib.link_libraries.append(arg)
                        lib.public_link_libraries.append(arg)
                    elif visibility == "INTERFACE":
                        lib.public_link_libraries.append(arg)
                    else:
                        lib.link_libraries.append(arg)
                else:
                    exe = ctx.get_executable(target_name)
                    if exe:
                        exe.link_libraries.append(arg)


def handle_target_link_directories(
    ctx: BuildContext,
    cmd: Command,
    args: list[str],
    strict: bool,
) -> None:
    """Handle target_link_directories() command."""
    if len(args) >= 2:
        target_name = args[0]
        # Parse directories with visibility keywords
        public_dirs: list[str] = []
        target_dirs: list[str] = []
        visibility = "PUBLIC"  # Default visibility
        for arg in args[1:]:
            if arg == "PUBLIC":
                visibility = "PUBLIC"
            elif arg == "INTERFACE":
                visibility = "INTERFACE"
            elif arg == "PRIVATE":
                visibility = "PRIVATE"
            else:
                # Expand variables and resolve relative paths
                expanded = ctx.expand_variables(arg, strict, cmd.line)
                if "$<" in expanded:
                    ctx.print_warning(
                        f"generator expressions in target_compile_definitions are not yet supported: {arg}",
                        cmd.line,
                    )
                expanded = strip_generator_expressions(expanded)

                if not expanded:
                    continue
                expanded = resolve_cmake_path(expanded, ctx.current_source_dir)
                if visibility == "PUBLIC":
                    public_dirs.append(expanded)
                    target_dirs.append(expanded)
                elif visibility == "INTERFACE":
                    public_dirs.append(expanded)
                else:
                    target_dirs.append(expanded)
        # Add directories to library or executable
        lib = ctx.get_library(target_name)
        if lib:
            lib.link_directories.extend(target_dirs)
            lib.public_link_directories.extend(public_dirs)
        else:
            exe = ctx.get_executable(target_name)
            if exe:
                # Executables don't propagate, so all dirs go to link_directories
                exe.link_directories.extend(target_dirs)
                exe.link_directories.extend(public_dirs)


def handle_target_sources(
    ctx: BuildContext,
    args: list[str],
) -> None:
    """Handle target_sources() command."""
    if len(args) >= 2:
        target_name = args[0]
        sources = args[1:]
        # Skip visibility keywords
        sources = [s for s in sources if s not in ("PUBLIC", "PRIVATE", "INTERFACE")]
        resolved_sources: list[str] = []
        for source in sources:
            normalized = strip_generator_expressions(source)
            if not normalized:
                continue
            resolved_sources.extend(
                [
                    ctx.resolve_path(item)
                    for item in normalized.split(";")
                    if item and item.strip()
                ]
            )
        # Add sources to library or executable
        lib = ctx.get_library(target_name)
        if lib:
            lib.sources.extend(resolved_sources)
        else:
            exe = ctx.get_executable(target_name)
            if exe:
                exe.sources.extend(resolved_sources)


def handle_target_compile_features(
    ctx: BuildContext,
    args: list[str],
) -> None:
    """Handle target_compile_features() command."""
    if len(args) >= 2:
        target_name = args[0]
        # Parse features with visibility keywords
        public_features: list[str] = []
        target_features: list[str] = []
        visibility = "PUBLIC"  # Default visibility
        for arg in args[1:]:
            if arg == "PUBLIC":
                visibility = "PUBLIC"
            elif arg == "INTERFACE":
                visibility = "INTERFACE"
            elif arg == "PRIVATE":
                visibility = "PRIVATE"
            else:
                if visibility == "PUBLIC":
                    public_features.append(arg)
                    target_features.append(arg)
                elif visibility == "INTERFACE":
                    public_features.append(arg)
                else:
                    target_features.append(arg)
        # Add features to library or executable
        lib = ctx.get_library(target_name)
        if lib:
            lib.compile_features.extend(target_features)
            lib.public_compile_features.extend(public_features)
        else:
            exe = ctx.get_executable(target_name)
            if exe:
                # Executables don't propagate, so all features go to compile_features
                exe.compile_features.extend(target_features)
                exe.compile_features.extend(public_features)


def handle_target_include_directories(
    ctx: BuildContext,
    cmd: Command,
    args: list[str],
    strict: bool,
) -> None:
    """Handle target_include_directories() command."""
    if len(args) >= 2:
        target_name = args[0]
        # Parse directories with visibility keywords
        public_dirs: list[str] = []
        target_dirs: list[str] = []
        visibility = "PUBLIC"  # Default visibility
        for arg in args[1:]:
            if arg == "PUBLIC":
                visibility = "PUBLIC"
            elif arg == "INTERFACE":
                visibility = "INTERFACE"
            elif arg == "PRIVATE":
                visibility = "PRIVATE"
            elif arg == "SYSTEM":
                # SYSTEM keyword is accepted but we don't differentiate
                pass
            else:
                # Expand variables and resolve relative paths
                expanded = ctx.expand_variables(arg, strict, cmd.line)
                if "$<" in expanded:
                    if not _is_supported_include_dir_genex(expanded):
                        ctx.print_warning(
                            f"generator expressions in target_include_directories are not yet supported: {arg}",
                            cmd.line,
                        )
                expanded = strip_generator_expressions(expanded)
                if not expanded:
                    continue
                expanded = resolve_cmake_path(expanded, ctx.current_source_dir)
                if Path(expanded).is_absolute():
                    expanded = str(Path(expanded).resolve())
                if visibility == "PUBLIC":
                    public_dirs.append(expanded)
                    target_dirs.append(expanded)
                elif visibility == "INTERFACE":
                    public_dirs.append(expanded)
                else:
                    target_dirs.append(expanded)
        # Add directories to library or executable
        lib = ctx.get_library(target_name)
        if lib:
            lib.include_directories.extend(target_dirs)
            lib.public_include_directories.extend(public_dirs)
        else:
            exe = ctx.get_executable(target_name)
            if exe:
                # Executables don't propagate, so all dirs go to include_directories
                exe.include_directories.extend(target_dirs)
                exe.include_directories.extend(public_dirs)


def handle_target_compile_definitions(
    ctx: BuildContext,
    cmd: Command,
    args: list[str],
    strict: bool,
) -> None:
    """Handle target_compile_definitions() command."""
    if len(args) >= 2:
        target_name = args[0]
        # Parse definitions with visibility keywords
        public_defs: list[str] = []
        target_defs: list[str] = []
        visibility = "PUBLIC"  # Default visibility
        for arg in args[1:]:
            if arg == "PUBLIC":
                visibility = "PUBLIC"
            elif arg == "INTERFACE":
                visibility = "INTERFACE"
            elif arg == "PRIVATE":
                visibility = "PRIVATE"
            else:
                # Expand variables and resolve relative paths
                expanded = ctx.expand_variables(arg, strict, cmd.line)
                if "$<" in expanded:
                    ctx.print_warning(
                        f"generator expressions in target_include_directories are not yet supported: {arg}",
                        cmd.line,
                    )
                expanded = strip_generator_expressions(expanded)

                if not expanded:
                    continue
                if visibility == "PUBLIC":
                    public_defs.append(expanded)
                    target_defs.append(expanded)
                elif visibility == "INTERFACE":
                    public_defs.append(expanded)
                else:
                    target_defs.append(expanded)
        # Add definitions to library or executable
        lib = ctx.get_library(target_name)
        if lib:
            lib.compile_definitions.extend(target_defs)
            lib.public_compile_definitions.extend(public_defs)
        else:
            exe = ctx.get_executable(target_name)
            if exe:
                # Executables don't propagate, so all defs go to compile_definitions
                exe.compile_definitions.extend(target_defs)
                exe.compile_definitions.extend(public_defs)


def handle_target_compile_options(
    ctx: BuildContext,
    cmd: Command,
    args: list[str],
    strict: bool,
) -> None:
    """Handle target_compile_options() command."""
    if len(args) >= 2:
        target_name = args[0]
        public_opts: list[str] = []
        target_opts: list[str] = []
        visibility = "PUBLIC"  # Default visibility
        for arg in args[1:]:
            if arg == "PUBLIC":
                visibility = "PUBLIC"
            elif arg == "INTERFACE":
                visibility = "INTERFACE"
            elif arg == "PRIVATE":
                visibility = "PRIVATE"
            elif arg == "BEFORE":
                # BEFORE affects ordering only; ignored for now.
                pass
            else:
                expanded = ctx.expand_variables(arg, strict, cmd.line)
                if "$<" in expanded:
                    ctx.print_warning(
                        f"generator expressions in target_compile_options are not yet supported: {arg}",
                        cmd.line,
                    )
                expanded = strip_generator_expressions(expanded)
                if not expanded:
                    continue
                if visibility == "PUBLIC":
                    public_opts.append(expanded)
                    target_opts.append(expanded)
                elif visibility == "INTERFACE":
                    public_opts.append(expanded)
                else:
                    target_opts.append(expanded)
        # Add options to library or executable
        lib = ctx.get_library(target_name)
        if lib:
            lib.compile_options.extend(target_opts)
            lib.public_compile_options.extend(public_opts)
        else:
            exe = ctx.get_executable(target_name)
            if exe:
                # Executables don't propagate, so all options are local.
                exe.compile_options.extend(target_opts)
                exe.compile_options.extend(public_opts)


def handle_set_target_properties(
    ctx: BuildContext,
    cmd: Command,
    args: list[str],
    strict: bool,
) -> None:
    """Handle set_target_properties() command."""
    if len(args) >= 3 and "PROPERTIES" in args:
        props_idx = args.index("PROPERTIES")
        target_names = args[:props_idx]
        prop_args = args[props_idx + 1 :]

        # Parse property-value pairs
        properties: dict[str, str] = {}
        for j in range(0, len(prop_args), 2):
            if j + 1 < len(prop_args):
                properties[prop_args[j]] = prop_args[j + 1]

        for target_name in target_names:
            lib = ctx.get_library(target_name)
            exe = ctx.get_executable(target_name)

            for prop_name, prop_value in properties.items():
                if prop_name == "INTERFACE_INCLUDE_DIRECTORIES":
                    # Split semicolon-separated list
                    dirs = prop_value.split(";")
                    for d in dirs:
                        expanded = ctx.expand_variables(d, strict, cmd.line)
                        expanded = resolve_cmake_path(expanded, ctx.current_source_dir)
                        if lib:
                            lib.public_include_directories.append(expanded)
                        elif exe:
                            exe.include_directories.append(expanded)
                else:
                    if lib:
                        lib.properties[prop_name] = prop_value
                    elif exe:
                        exe.properties[prop_name] = prop_value
                    elif strict:
                        ctx.print_warning(
                            f"set_target_properties: property '{prop_name}' not yet supported",
                            cmd.line,
                        )


def handle_set_property(
    ctx: BuildContext,
    cmd: Command,
    args: list[str],
    strict: bool,
) -> None:
    """Handle set_property() command."""
    # set_property(scope_type [scope_args] [APPEND] [APPEND_STRING] PROPERTY prop_name [values...])
    if len(args) < 3:
        if strict:
            ctx.print_error(
                "set_property() requires scope, PROPERTY keyword, and property name",
                cmd.line,
            )
            sys.exit(1)
        return

    scope_type = args[0].upper()

    # Find PROPERTY keyword
    if "PROPERTY" not in args:
        if strict:
            ctx.print_error("set_property() requires PROPERTY keyword", cmd.line)
        return

    prop_idx = args.index("PROPERTY")
    scope_args = args[1:prop_idx]

    # Check for APPEND or APPEND_STRING
    append_mode = False
    append_string = False
    filtered_scope_args = []
    for arg in scope_args:
        if arg == "APPEND":
            append_mode = True
        elif arg == "APPEND_STRING":
            append_string = True
            append_mode = True
        else:
            filtered_scope_args.append(arg)
    scope_args = filtered_scope_args

    if prop_idx + 1 >= len(args):
        if strict:
            ctx.print_error(
                "set_property() requires property name after PROPERTY keyword",
                cmd.line,
            )
            sys.exit(1)
        return

    prop_name = args[prop_idx + 1]
    prop_values = args[prop_idx + 2 :]

    if scope_type == "GLOBAL":
        # Global property
        if prop_values:
            value = " ".join(prop_values) if append_string else ";".join(prop_values)
            if append_mode and prop_name in ctx.global_properties:
                separator = "" if append_string else ";"
                ctx.global_properties[prop_name] += separator + value
            else:
                ctx.global_properties[prop_name] = value
        else:
            # Empty value unsets the property
            ctx.global_properties.pop(prop_name, None)

    elif scope_type == "TARGET":
        # Target property
        for target_name in scope_args:
            lib = ctx.get_library(target_name)
            exe = ctx.get_executable(target_name)

            if prop_name == "INTERFACE_INCLUDE_DIRECTORIES":
                for value in prop_values:
                    expanded = ctx.expand_variables(value, strict, cmd.line)
                    expanded = resolve_cmake_path(expanded, ctx.current_source_dir)
                    if lib:
                        if append_mode:
                            lib.public_include_directories.append(expanded)
                        else:
                            lib.public_include_directories = [expanded]
                    elif exe:
                        if append_mode:
                            exe.include_directories.append(expanded)
                        else:
                            exe.include_directories = [expanded]
            elif prop_name == "COMPILE_DEFINITIONS":
                if lib:
                    if append_mode:
                        lib.compile_definitions.extend(prop_values)
                    else:
                        lib.compile_definitions = list(prop_values)
                elif exe:
                    # Executables don't have compile_definitions directly yet
                    pass
            else:
                value = ";".join(prop_values)
                if lib:
                    if append_mode and prop_name in lib.properties:
                        lib.properties[prop_name] += (
                            "" if append_string else ";"
                        ) + value
                    else:
                        lib.properties[prop_name] = value
                elif exe:
                    if append_mode and prop_name in exe.properties:
                        exe.properties[prop_name] += (
                            "" if append_string else ";"
                        ) + value
                    else:
                        exe.properties[prop_name] = value
                elif strict:
                    ctx.print_warning(
                        f"set_property(TARGET): property '{prop_name}' not yet supported",
                        cmd.line,
                    )

    elif scope_type == "SOURCE":
        # Source file property
        for source_file in scope_args:
            expanded_filename = ctx.expand_variables(source_file, strict, cmd.line)
            expanded_filename = resolve_cmake_path(
                expanded_filename, ctx.current_source_dir
            )

            if expanded_filename not in ctx.source_file_properties:
                ctx.source_file_properties[expanded_filename] = SourceFileProperties()

            file_props = ctx.source_file_properties[expanded_filename]

            if prop_name == "COMPILE_DEFINITIONS":
                if append_mode:
                    file_props.compile_definitions.extend(prop_values)
                else:
                    file_props.compile_definitions = list(prop_values)
            elif prop_name == "INCLUDE_DIRECTORIES":
                for value in prop_values:
                    expanded = ctx.expand_variables(value, strict, cmd.line)
                    expanded = resolve_cmake_path(expanded, ctx.current_source_dir)
                    if append_mode:
                        file_props.include_directories.append(expanded)
                    else:
                        file_props.include_directories = [expanded]
            elif prop_name == "OBJECT_DEPENDS":
                if append_mode:
                    file_props.object_depends.extend(prop_values)
                else:
                    file_props.object_depends = list(prop_values)
            elif strict:
                ctx.print_warning(
                    f"set_property(SOURCE): property '{prop_name}' not yet supported",
                    cmd.line,
                )

    elif scope_type == "DIRECTORY":
        # Directory property
        # scope_args can be empty (current directory) or contain a path
        dirs = scope_args if scope_args else [str(ctx.current_source_dir)]
        for d in dirs:
            abs_dir = resolve_cmake_path(d, ctx.current_source_dir)

            if abs_dir not in ctx.directory_properties:
                ctx.directory_properties[abs_dir] = {}

            value = ";".join(prop_values)
            if append_mode and prop_name in ctx.directory_properties[abs_dir]:
                separator = "" if append_string else ";"
                ctx.directory_properties[abs_dir][prop_name] += separator + value
            else:
                ctx.directory_properties[abs_dir][prop_name] = value

    elif scope_type in ("TEST", "CACHE", "INSTALL"):
        # These scopes are not commonly used in basic builds
        if strict:
            ctx.print_warning(
                f"set_property({scope_type}) is not yet supported",
                cmd.line,
            )
    else:
        if strict:
            ctx.print_error(
                f"set_property() unknown scope type: {scope_type}",
                cmd.line,
            )
            sys.exit(1)


def handle_get_property(
    ctx: BuildContext,
    cmd: Command,
    args: list[str],
    strict: bool,
) -> None:
    """Handle get_property() command."""
    # get_property(<variable> scope_type [scope_args] PROPERTY <prop_name> [SET|DEFINED|BRIEF_DOCS|FULL_DOCS])
    if len(args) < 4:
        if strict:
            ctx.print_error(
                "get_property() requires variable, scope, PROPERTY keyword, and property name",
                cmd.line,
            )
            sys.exit(1)
        return

    var_name = args[0]
    scope_type = args[1].upper()

    # Find PROPERTY keyword
    if "PROPERTY" not in args:
        if strict:
            ctx.print_error("get_property() requires PROPERTY keyword", cmd.line)
        return

    prop_idx = args.index("PROPERTY")
    scope_args = args[2:prop_idx]

    if prop_idx + 1 >= len(args):
        if strict:
            ctx.print_error(
                "get_property() requires property name after PROPERTY keyword",
                cmd.line,
            )
            sys.exit(1)
        return

    prop_name = args[prop_idx + 1]

    # Check for optional query type (SET, DEFINED, etc.)
    query_type = None
    if prop_idx + 2 < len(args):
        query_type = args[prop_idx + 2].upper()

    if scope_type == "GLOBAL":
        # Global property
        if query_type == "DEFINED":
            ctx.variables[var_name] = "1" if prop_name in ctx.global_properties else "0"
        elif query_type == "SET":
            ctx.variables[var_name] = (
                "1"
                if (
                    prop_name in ctx.global_properties
                    and ctx.global_properties[prop_name]
                )
                else "0"
            )
        else:
            # Get the value
            ctx.variables[var_name] = ctx.global_properties.get(prop_name, "")

    elif scope_type == "TARGET":
        # Target property
        if scope_args:
            target_name = scope_args[0]
            lib = ctx.get_library(target_name)

            value = ""
            if prop_name == "INTERFACE_INCLUDE_DIRECTORIES" and lib:
                value = ";".join(lib.public_include_directories)
            elif prop_name == "COMPILE_DEFINITIONS" and lib:
                value = ";".join(lib.compile_definitions)

            if query_type == "DEFINED":
                ctx.variables[var_name] = "1" if value else "0"
            elif query_type == "SET":
                ctx.variables[var_name] = "1" if value else "0"
            else:
                ctx.variables[var_name] = value

    elif scope_type == "SOURCE":
        # Source file property
        if scope_args:
            source_file = scope_args[0]
            expanded_filename = ctx.expand_variables(source_file, strict, cmd.line)
            expanded_filename = resolve_cmake_path(
                expanded_filename, ctx.current_source_dir
            )

            value = ""
            if expanded_filename in ctx.source_file_properties:
                file_props = ctx.source_file_properties[expanded_filename]
                if prop_name == "COMPILE_DEFINITIONS":
                    value = ";".join(file_props.compile_definitions)
                elif prop_name == "INCLUDE_DIRECTORIES":
                    value = ";".join(file_props.include_directories)
                elif prop_name == "OBJECT_DEPENDS":
                    value = ";".join(file_props.object_depends)

            if query_type == "DEFINED":
                ctx.variables[var_name] = "1" if value else "0"
            elif query_type == "SET":
                ctx.variables[var_name] = "1" if value else "0"
            else:
                ctx.variables[var_name] = value

    else:
        # For other scope types, just set empty
        if query_type in ("DEFINED", "SET"):
            ctx.variables[var_name] = "0"
        else:
            ctx.variables[var_name] = ""


def handle_get_directory_property(
    ctx: BuildContext,
    cmd: Command,
    args: list[str],
    strict: bool,
) -> None:
    """Handle get_directory_property() command."""
    # get_directory_property(<variable> [DIRECTORY <dir>] <prop>)
    if len(args) < 2:
        if strict:
            ctx.print_error(
                "get_directory_property() requires at least a variable and property name",
                cmd.line,
            )
            sys.exit(1)
        return

    var_name = args[0]
    # Last argument is the property name
    prop_name = args[-1]

    if prop_name == "PARENT_DIRECTORY":
        # For now, we don't support DIRECTORY <dir> argument properly,
        # just return parent of current directory
        ctx.variables[var_name] = ctx.parent_directory
    else:
        if strict:
            ctx.print_warning(
                f"get_directory_property: property '{prop_name}' not yet supported",
                cmd.line,
            )
        ctx.variables[var_name] = ""


def handle_get_filename_component(
    ctx: BuildContext,
    args: list[str],
) -> None:
    """Handle get_filename_component() command."""
    if len(args) >= 3:
        var_name = args[0]
        filename = args[1]
        mode = args[2]

        # Optional BASE_DIR
        base_dir = str(ctx.current_source_dir)
        if "BASE_DIR" in args:
            try:
                idx = args.index("BASE_DIR")
                if idx + 1 < len(args):
                    base_dir = args[idx + 1]
            except ValueError:
                pass

        result = ""
        if mode in ("DIRECTORY", "PATH"):
            result = os.path.dirname(filename)
        elif mode == "NAME":
            result = os.path.basename(filename)
        elif mode == "EXT":
            _, ext = os.path.splitext(filename)
            result = ext
        elif mode == "NAME_WE":
            basename = os.path.basename(filename)
            name_we, _ = os.path.splitext(basename)
            result = name_we
        elif mode in ("ABSOLUTE", "REALPATH"):
            p = Path(filename)
            if not p.is_absolute():
                p = Path(base_dir) / p
            if mode == "REALPATH":
                result = str(p.resolve())
            else:
                # ABSOLUTE in CMake just expands to full path without necessarily resolving symlinks,
                # but resolve() is safer and usually what people want.
                # Actually, resolve() resolves symlinks. absolute() doesn't.
                result = str(p.absolute())

        ctx.variables[var_name] = result


def handle_add_library(
    ctx: BuildContext,
    cmd: Command,
    args: list[str],
) -> None:
    """Handle add_library() command."""
    if len(args) >= 1:
        name = args[0]
        if len(name) == 0:
            ctx.print_error("add_library() requires a non-empty target name", cmd.line)
            sys.exit(1)
        # Check for ALIAS
        if len(args) >= 3 and args[1] == "ALIAS":
            target_name = args[2]
            # For now, just register the alias in imported_targets or something?
            # Or just ignore it if we don't need it.
            # CMake aliases are just pointers to other targets.
            # In cja, we can probably just ignore them or add them to ctx.libraries
            # as a copy if we want to support linking against the alias.
            lib = ctx.get_library(target_name)
            if lib:
                ctx.libraries.append(
                    Library(
                        name=name,
                        sources=lib.sources,
                        lib_type=lib.lib_type,
                        include_directories=lib.include_directories,
                        compile_definitions=lib.compile_definitions,
                        compile_options=lib.compile_options,
                        compile_features=lib.compile_features,
                        link_libraries=lib.link_libraries,
                        link_directories=lib.link_directories,
                        public_include_directories=lib.public_include_directories,
                        public_compile_definitions=lib.public_compile_definitions,
                        public_compile_options=lib.public_compile_options,
                        public_compile_features=lib.public_compile_features,
                        public_link_directories=lib.public_link_directories,
                        is_alias=True,
                        alias_for=target_name,
                        defined_file=ctx.current_list_file,
                        defined_line=cmd.line,
                    )
                )
            return

        # Check for STATIC/SHARED/OBJECT/MODULE/INTERFACE keyword
        sources = args[1:]
        lib_type = "STATIC"
        if sources and sources[0] in (
            "STATIC",
            "SHARED",
            "OBJECT",
            "MODULE",
            "INTERFACE",
        ):
            lib_type = sources[0]
            sources = sources[1:]
        if lib_type == "INTERFACE":
            sources = []
        resolved_sources: list[str] = []
        for source in sources:
            normalized = strip_generator_expressions(source)
            if not normalized:
                continue
            resolved_sources.extend(
                [
                    ctx.resolve_path(item)
                    for item in normalized.split(";")
                    if item and item.strip()
                ]
            )
        include_directories = _collect_directory_include_dirs(ctx)
        ctx.libraries.append(
            Library(
                name=name,
                sources=resolved_sources,
                lib_type=lib_type,
                include_directories=include_directories,
                defined_file=ctx.current_list_file,
                defined_line=cmd.line,
            )
        )


def handle_add_executable(
    ctx: BuildContext,
    cmd: Command,
    args: list[str],
) -> None:
    """Handle add_executable() command."""
    if len(args) >= 2:
        sources: list[str] = []
        for source in args[1:]:
            normalized = strip_generator_expressions(source)
            if not normalized:
                continue
            sources.extend(
                [ctx.resolve_path(item) for item in normalized.split(";") if item]
            )
        include_directories = _collect_directory_include_dirs(ctx)
        ctx.executables.append(
            Executable(
                name=args[0],
                sources=sources,
                include_directories=include_directories,
                defined_file=ctx.current_list_file,
                defined_line=cmd.line,
            )
        )


def handle_list(
    ctx: BuildContext,
    cmd: Command,
    args: list[str],
    strict: bool,
) -> None:
    """Handle list() command."""
    # list(SUBCOMMAND <list_var> ...)
    if len(args) < 2:
        if strict:
            ctx.print_error(
                "list() requires at least a subcommand and variable name",
                cmd.line,
            )
            sys.exit(1)
        return

    subcommand = args[0].upper()

    if subcommand == "LENGTH":
        # list(LENGTH <list> <output variable>)
        if len(args) < 3:
            if strict:
                ctx.print_error(
                    "list(LENGTH) requires list and output variable", cmd.line
                )
                sys.exit(1)
        else:
            list_name = args[1]
            out_var = args[2]
            list_val = ctx.variables.get(list_name, "")
            if list_val:
                items = list_val.split(";")
                ctx.variables[out_var] = str(len(items))
            else:
                ctx.variables[out_var] = "0"

    elif subcommand == "GET":
        # list(GET <list> <element index> [<element index> ...] <output variable>)
        if len(args) < 4:
            if strict:
                ctx.print_error(
                    "list(GET) requires list, indices, and output variable",
                    cmd.line,
                )
                sys.exit(1)
        else:
            list_name = args[1]
            indices = args[2:-1]
            out_var = args[-1]
            list_val = ctx.variables.get(list_name, "")
            items = list_val.split(";") if list_val else []
            result = []
            for idx_str in indices:
                try:
                    idx = int(idx_str)
                    if -len(items) <= idx < len(items):
                        result.append(items[idx])
                except ValueError, IndexError:
                    pass
            ctx.variables[out_var] = ";".join(result)

    elif subcommand == "APPEND":
        # list(APPEND <list> [<element> ...])
        list_name = args[1]
        elements = args[2:]
        list_val = ctx.variables.get(list_name, "")
        if list_val:
            items = list_val.split(";")
            items.extend(elements)
            ctx.variables[list_name] = ";".join(items)
        elif elements:
            ctx.variables[list_name] = ";".join(elements)

    elif subcommand == "PREPEND":
        # list(PREPEND <list> [<element> ...])
        list_name = args[1]
        elements = args[2:]
        list_val = ctx.variables.get(list_name, "")
        if list_val:
            items = list_val.split(";")
            items = elements + items
            ctx.variables[list_name] = ";".join(items)
        elif elements:
            ctx.variables[list_name] = ";".join(elements)

    elif subcommand == "INSERT":
        # list(INSERT <list> <element_index> <element> [<element> ...])
        if len(args) < 4:
            if strict:
                ctx.print_error(
                    "list(INSERT) requires list, index, and at least one element",
                    cmd.line,
                )
                sys.exit(1)
        else:
            list_name = args[1]
            try:
                index = int(args[2])
                elements = args[3:]
                list_val = ctx.variables.get(list_name, "")
                items = list_val.split(";") if list_val else []
                # Insert elements at index
                for i_offset, elem in enumerate(elements):
                    items.insert(index + i_offset, elem)
                ctx.variables[list_name] = ";".join(items)
            except ValueError:
                if strict:
                    ctx.print_error("list(INSERT) index must be an integer", cmd.line)
                    sys.exit(1)

    elif subcommand == "REMOVE_ITEM":
        # list(REMOVE_ITEM <list> <value> [<value> ...])
        list_name = args[1]
        values_to_remove = args[2:]
        list_val = ctx.variables.get(list_name, "")
        if list_val:
            items = list_val.split(";")
            items = [item for item in items if item not in values_to_remove]
            ctx.variables[list_name] = ";".join(items)

    elif subcommand == "REMOVE_AT":
        # list(REMOVE_AT <list> <index> [<index> ...])
        if len(args) < 3:
            if strict:
                ctx.print_error(
                    "list(REMOVE_AT) requires list and at least one index",
                    cmd.line,
                )
                sys.exit(1)
        else:
            list_name = args[1]
            indices = args[2:]
            list_val = ctx.variables.get(list_name, "")
            if list_val:
                items = list_val.split(";")
                # Convert indices and sort in reverse to remove from end
                idx_set = set()
                for idx_str in indices:
                    try:
                        idx = int(idx_str)
                        # Handle negative indices
                        if idx < 0:
                            idx = len(items) + idx
                        if 0 <= idx < len(items):
                            idx_set.add(idx)
                    except ValueError:
                        pass
                items = [item for i, item in enumerate(items) if i not in idx_set]
                ctx.variables[list_name] = ";".join(items)

    elif subcommand == "REMOVE_DUPLICATES":
        # list(REMOVE_DUPLICATES <list>)
        list_name = args[1]
        list_val = ctx.variables.get(list_name, "")
        if list_val:
            items = list_val.split(";")
            seen = set()
            unique_items = []
            for item in items:
                if item not in seen:
                    seen.add(item)
                    unique_items.append(item)
            ctx.variables[list_name] = ";".join(unique_items)

    elif subcommand == "REVERSE":
        # list(REVERSE <list>)
        list_name = args[1]
        list_val = ctx.variables.get(list_name, "")
        if list_val:
            items = list_val.split(";")
            items.reverse()
            ctx.variables[list_name] = ";".join(items)

    elif subcommand == "SORT":
        # list(SORT <list> [COMPARE <compare>] [CASE <case>] [ORDER <order>])
        list_name = args[1]
        list_val = ctx.variables.get(list_name, "")
        if list_val:
            items = list_val.split(";")
            # Parse options (simplified - ignoring COMPARE, CASE, ORDER for now)
            items.sort()
            ctx.variables[list_name] = ";".join(items)

    elif subcommand == "FIND":
        # list(FIND <list> <value> <output variable>)
        if len(args) < 4:
            if strict:
                ctx.print_error(
                    "list(FIND) requires list, value, and output variable",
                    cmd.line,
                )
                sys.exit(1)
        else:
            list_name = args[1]
            value = args[2]
            out_var = args[3]
            list_val = ctx.variables.get(list_name, "")
            if list_val:
                items = list_val.split(";")
                try:
                    idx = items.index(value)
                    ctx.variables[out_var] = str(idx)
                except ValueError:
                    ctx.variables[out_var] = "-1"
            else:
                ctx.variables[out_var] = "-1"

    elif subcommand == "JOIN":
        # list(JOIN <list> <glue> <output variable>)
        if len(args) < 4:
            if strict:
                ctx.print_error(
                    "list(JOIN) requires list, glue, and output variable",
                    cmd.line,
                )
                sys.exit(1)
        else:
            list_name = args[1]
            glue = args[2]
            out_var = args[3]
            list_val = ctx.variables.get(list_name, "")
            if list_val:
                items = list_val.split(";")
                ctx.variables[out_var] = glue.join(items)
            else:
                ctx.variables[out_var] = ""

    elif subcommand == "SUBLIST":
        # list(SUBLIST <list> <begin> <length> <output variable>)
        if len(args) < 5:
            if strict:
                ctx.print_error(
                    "list(SUBLIST) requires list, begin, length, and output variable",
                    cmd.line,
                )
                sys.exit(1)
        else:
            list_name = args[1]
            try:
                begin = int(args[2])
                length = int(args[3])
                out_var = args[4]
                list_val = ctx.variables.get(list_name, "")
                if list_val:
                    items = list_val.split(";")
                    # Handle negative length (means all remaining)
                    if length < 0:
                        sublist = items[begin:]
                    else:
                        sublist = items[begin : begin + length]
                    ctx.variables[out_var] = ";".join(sublist)
                else:
                    ctx.variables[out_var] = ""
            except ValueError:
                if strict:
                    ctx.print_error(
                        "list(SUBLIST) begin and length must be integers",
                        cmd.line,
                    )
                    sys.exit(1)

    elif subcommand == "TRANSFORM":
        # list(TRANSFORM <list> <ACTION> [<SELECTOR>] [OUTPUT_VARIABLE <output variable>])
        # Simplified implementation - handle common actions used by projects.
        if len(args) < 3:
            if strict:
                ctx.print_error("list(TRANSFORM) requires list and action", cmd.line)
                sys.exit(1)
        else:
            list_name = args[1]
            action = args[2].upper()
            # Check for OUTPUT_VARIABLE
            out_var = list_name
            if "OUTPUT_VARIABLE" in args:
                idx = args.index("OUTPUT_VARIABLE")
                if idx + 1 < len(args):
                    out_var = args[idx + 1]

            transform_args_end = (
                args.index("OUTPUT_VARIABLE")
                if "OUTPUT_VARIABLE" in args
                else len(args)
            )
            transform_args = args[3:transform_args_end]

            list_val = ctx.variables.get(list_name, "")
            if list_val:
                items = list_val.split(";")
                if action == "TOUPPER":
                    items = [item.upper() for item in items]
                elif action == "TOLOWER":
                    items = [item.lower() for item in items]
                elif action == "STRIP":
                    items = [item.strip() for item in items]
                elif action == "PREPEND":
                    if not transform_args:
                        if strict:
                            ctx.print_error(
                                "list(TRANSFORM ... PREPEND) requires a value",
                                cmd.line,
                            )
                            sys.exit(1)
                    else:
                        prefix = transform_args[0]
                        items = [f"{prefix}{item}" for item in items]
                ctx.variables[out_var] = ";".join(items)

    elif subcommand == "FILTER":
        # list(FILTER <list> <INCLUDE|EXCLUDE> REGEX <regex>)
        if len(args) < 5:
            if strict:
                ctx.print_error(
                    "list(FILTER) requires list, mode, REGEX, and pattern",
                    cmd.line,
                )
                sys.exit(1)
        else:
            list_name = args[1]
            mode = args[2].upper()
            if args[3].upper() == "REGEX" and len(args) >= 5:
                pattern = args[4]
                list_val = ctx.variables.get(list_name, "")
                if list_val:
                    items = list_val.split(";")
                    import re as regex_module

                    if mode == "INCLUDE":
                        items = [
                            item for item in items if regex_module.search(pattern, item)
                        ]
                    elif mode == "EXCLUDE":
                        items = [
                            item
                            for item in items
                            if not regex_module.search(pattern, item)
                        ]
                    ctx.variables[list_name] = ";".join(items)
    else:
        if strict:
            ctx.print_error(f"list() unknown subcommand: {subcommand}", cmd.line)
            sys.exit(1)


def handle_set(
    ctx: BuildContext,
    cmd: Command,
    args: list[str],
    strict: bool,
) -> None:
    """Handle set() command."""
    if args:
        var_name = ctx.expand_variables(args[0], strict, cmd.line)
        values = args[1:]

        # Handle CMAKE_POLICY_DEFAULT_CMPxxxx specially
        if var_name.startswith("CMAKE_POLICY_DEFAULT_CMP"):
            # Extract the value (should be NEW or OLD)
            policy_value = values[0] if values else ""
            if policy_value == "OLD":
                # cja always uses NEW behavior, warn about OLD
                ctx.print_warning(
                    f"{var_name} is set to OLD, but cja always uses NEW behavior for all policies",
                    cmd.line,
                )
            # For NEW, silently accept (this is what we want)
            # Don't actually set the variable, just acknowledge it
            return

        # Filter out CACHE, PARENT_SCOPE, and track FORCE
        filtered_values: list[str] = []
        has_force = False
        has_parent_scope = False
        has_cache = False
        skip_next = 0
        for idx, val in enumerate(values):
            if skip_next > 0:
                skip_next -= 1
                continue
            if val == "CACHE":
                has_cache = True
                # CACHE TYPE "docstring" [FORCE] - skip type and docstring
                skip_next = 2
                continue
            if val == "FORCE":
                has_force = True
                continue
            if val == "PARENT_SCOPE":
                has_parent_scope = True
                continue
            filtered_values.append(val)

        # Don't override cache variables unless FORCE is specified
        if var_name in ctx.cache_variables and not has_force:
            pass  # Skip, variable was set via -D flag
        elif has_parent_scope:
            # Set in parent scope (for function calls)
            if filtered_values:
                ctx.parent_scope_vars[var_name] = ";".join(filtered_values)
            else:
                ctx.parent_scope_vars[var_name] = ""
        elif filtered_values:
            ctx.variables[var_name] = ";".join(filtered_values)
            if has_cache:
                # Cache variables are global and survive function/directory scopes.
                ctx.cache_variables.add(var_name)
        else:
            # set(VAR) with no value unsets the variable
            ctx.variables.pop(var_name, None)


def handle_unset(
    ctx: BuildContext,
    cmd: Command,
    args: list[str],
    strict: bool,
) -> None:
    """Handle unset() command."""
    if not args:
        return
    var_name = ctx.expand_variables(args[0], strict, cmd.line)
    scope = args[1].upper() if len(args) > 1 else ""
    if scope == "PARENT_SCOPE":
        # Signal caller to remove the variable
        ctx.parent_scope_vars[var_name] = None
    elif scope == "CACHE":
        ctx.cache_variables.discard(var_name)
    else:
        ctx.variables.pop(var_name, None)


def handle_option(
    ctx: BuildContext,
    args: list[str],
) -> None:
    """Handle option() command."""
    # option(<variable> "<help_text>" [value])
    # Defines a boolean cache variable, default OFF
    # Does nothing if variable already defined
    if args:
        var_name = args[0]
        if var_name not in ctx.variables:
            # Default to OFF, or use provided value (3rd arg)
            value = "OFF"
            if len(args) >= 3:
                value = args[2]
            ctx.variables[var_name] = value


def handle_cmake_dependent_option(
    ctx: BuildContext,
    cmd: Command,
    args: list[str],
    strict: bool,
) -> None:
    """Handle cmake_dependent_option() command."""
    # cmake_dependent_option(<var> "<help>" <value> <depends> <force>)
    if len(args) < 5:
        if strict:
            ctx.print_error(
                "cmake_dependent_option requires variable, help, value, depends, and force value",
                cmd.line,
            )
            sys.exit(1)
        return

    option_name = args[0]
    default_value = ctx.expand_variables(args[2], strict, cmd.line)
    depends_expr = ctx.expand_variables(args[3], strict, cmd.line)
    force_value = ctx.expand_variables(args[4], strict, cmd.line)

    clauses = [clause.strip() for clause in depends_expr.split(";") if clause.strip()]
    condition_met = True
    for clause in clauses:
        if not evaluate_condition(clause.split(), ctx.variables):
            condition_met = False
            break

    if condition_met:
        # Behaves like option(): don't override an already-defined value.
        if option_name not in ctx.variables:
            ctx.variables[option_name] = default_value
    else:
        # When dependency is not satisfied, force to fallback value.
        ctx.variables[option_name] = force_value


def handle_cmake_parse_arguments(
    ctx: BuildContext,
    cmd: Command,
    strict: bool,
) -> None:
    """Handle cmake_parse_arguments() command."""
    expanded_args: list[str] = []
    for idx, arg in enumerate(cmd.args):
        expanded = ctx.expand_variables(arg, strict, cmd.line)
        quoted = cmd.is_quoted[idx] if idx < len(cmd.is_quoted) else False
        if idx < 4:
            expanded_args.append(expanded)
        elif ";" in expanded and (not quoted or idx >= 4):
            expanded_args.extend(expanded.split(";"))
        else:
            expanded_args.append(expanded)

    if len(expanded_args) < 4:
        if strict:
            ctx.print_error(
                "cmake_parse_arguments() requires PREFIX, OPTIONS, ONE_VALUE, and MULTI_VALUE lists",
                cmd.line,
            )
            sys.exit(1)
        return

    prefix = expanded_args[0]
    options_raw = expanded_args[1]
    one_value_raw = expanded_args[2]
    multi_value_raw = expanded_args[3]
    values = expanded_args[4:]

    options = options_raw.split(";") if options_raw else []
    one_value = one_value_raw.split(";") if one_value_raw else []
    multi_value = multi_value_raw.split(";") if multi_value_raw else []

    # Heuristic: allow missing OPTIONS list (common CPM.cmake pattern).
    # Detect when "options" tokens are actually used like one-value keywords.
    if expanded_args[3:] and options_raw and one_value_raw:
        keyword_set = set(options + one_value + multi_value)
        candidate_values = expanded_args[3:]
        candidate_values_flat: list[str] = []
        for raw in candidate_values:
            if ";" in raw:
                candidate_values_flat.extend(raw.split(";"))
            else:
                candidate_values_flat.append(raw)
        treat_as_missing_options = False
        for idx, token in enumerate(candidate_values_flat[:-1]):
            if token in options and candidate_values_flat[idx + 1] not in keyword_set:
                treat_as_missing_options = True
                break
        if treat_as_missing_options:
            options = []
            one_value = options_raw.split(";") if options_raw else []
            multi_value = one_value_raw.split(";") if one_value_raw else []
            values = candidate_values_flat

    keyword_set = set(options + one_value + multi_value)

    # Initialize outputs
    for opt in options:
        ctx.variables[f"{prefix}_{opt}"] = "FALSE"
    for key in one_value + multi_value:
        ctx.variables[f"{prefix}_{key}"] = UNDEFINED_VAR_SENTINEL
    ctx.variables[f"{prefix}_UNPARSED_ARGUMENTS"] = ""
    ctx.variables[f"{prefix}_KEYWORDS_MISSING_VALUES"] = ""

    unparsed: list[str] = []
    missing: list[str] = []
    i = 0
    while i < len(values):
        token = values[i]
        if token in options:
            ctx.variables[f"{prefix}_{token}"] = "TRUE"
            i += 1
            continue
        if token in one_value:
            if i + 1 >= len(values) or values[i + 1] in keyword_set:
                missing.append(token)
                i += 1
            else:
                ctx.variables[f"{prefix}_{token}"] = values[i + 1]
                i += 2
            continue
        if token in multi_value:
            collected: list[str] = []
            i += 1
            while i < len(values) and values[i] not in keyword_set:
                collected.append(values[i])
                i += 1
            if not collected:
                missing.append(token)
            ctx.variables[f"{prefix}_{token}"] = ";".join(collected)
            continue
        unparsed.append(token)
        i += 1

    if unparsed:
        ctx.variables[f"{prefix}_UNPARSED_ARGUMENTS"] = ";".join(unparsed)
    if missing:
        ctx.variables[f"{prefix}_KEYWORDS_MISSING_VALUES"] = ";".join(missing)


def handle_math(
    ctx: BuildContext,
    cmd: Command,
    args: list[str],
    strict: bool,
) -> None:
    """Handle math() command."""
    # math(EXPR <variable> "<expression>" [OUTPUT_FORMAT <format>])
    if len(args) >= 3 and args[0] == "EXPR":
        var_name = args[1]

        # Find if OUTPUT_FORMAT is present
        output_format = "DECIMAL"
        expr_args = args[2:]
        if "OUTPUT_FORMAT" in args:
            idx = args.index("OUTPUT_FORMAT")
            if idx + 1 < len(args):
                output_format = args[idx + 1]
            # Expression is everything between var_name and OUTPUT_FORMAT
            expr_args = args[2:idx]

        expr = " ".join(expr_args)
        expr = " ".join(expr.split())

        # Convert C-style operators to Python if necessary
        # Integer division is // in Python.
        # CMake's / is integer division.
        expr = expr.replace("/", "//")

        # Normalize leading-zero integer literals (CMake treats as decimal)
        def normalize_literals(match: re.Match) -> str:
            lit = match.group(0)
            if lit.startswith("0") and len(lit) > 1:
                stripped = lit.lstrip("0")
                return stripped if stripped else "0"
            return lit

        expr = re.sub(r"\b0\d+\b", normalize_literals, expr)

        try:
            # Evaluate expression in a restricted environment
            # Supporting basic arithmetic and bitwise operators
            result = eval(expr, {"__builtins__": {}}, {})
            if output_format == "HEXADECIMAL":
                ctx.variables[var_name] = hex(int(result))
            else:
                ctx.variables[var_name] = str(int(result))
        except Exception as e:
            if strict:
                ctx.print_error(
                    f"math(EXPR) failed to evaluate '{expr}': {e}", cmd.line
                )
                sys.exit(1)


def handle_function(
    ctx: BuildContext,
    commands: list[Command],
    pc: int,
    args: list[str],
) -> int:
    """Handle function() command."""
    cmd = commands[pc]
    if not args:
        ctx.raise_syntax_error("function() requires a name", cmd.line)

    # Find matching endfunction
    endfunction_idx = find_matching_endfunction(commands, pc, ctx)
    body = commands[pc + 1 : endfunction_idx]

    func_name = cmd.args[0].lower()  # CMake functions are case-insensitive
    func_params = cmd.args[1:]  # Parameter names

    # Store the function definition
    ctx.functions[func_name] = FunctionDef(
        name=func_name,
        params=func_params,
        body=body,
        defining_file=ctx.current_list_file,
    )

    # Skip to after endfunction
    return endfunction_idx + 1


def handle_macro(
    ctx: BuildContext,
    commands: list[Command],
    pc: int,
    args: list[str],
) -> int:
    """Handle macro() command."""
    cmd = commands[pc]
    if not args:
        ctx.raise_syntax_error("macro() requires a name", cmd.line)

    # Find matching endmacro
    endmacro_idx = find_matching_endmacro(commands, pc, ctx)
    body = commands[pc + 1 : endmacro_idx]

    macro_name = cmd.args[0].lower()  # CMake macros are case-insensitive
    macro_params = cmd.args[1:]  # Parameter names

    # Store the macro definition
    ctx.macros[macro_name] = MacroDef(
        name=macro_name,
        params=macro_params,
        body=body,
    )

    # Skip to after endmacro
    return endmacro_idx + 1


def handle_string(
    ctx: BuildContext,
    cmd: Command,
    args: list[str],
    strict: bool,
) -> None:
    """Handle string() command."""
    if len(args) < 2:
        if strict:
            ctx.print_error("string() requires at least a subcommand", cmd.line)
            sys.exit(1)
        return

    subcommand = args[0].upper()

    def reset_cmake_match_vars() -> None:
        keys = [
            key
            for key in ctx.variables
            if key == "CMAKE_MATCH_COUNT" or re.fullmatch(r"CMAKE_MATCH_\d+", key)
        ]
        for key in keys:
            ctx.variables.pop(key, None)

    if subcommand == "REPLACE":
        # string(REPLACE <match_string> <replace_string> <out_var> <input> [<input>...])
        if len(args) >= 5:
            match_str = args[1]
            replace_str = args[2]
            out_var = args[3]
            inputs = args[4:]
            full_input = "".join(inputs)
            ctx.variables[out_var] = full_input.replace(match_str, replace_str)

    elif subcommand == "REGEX":
        if len(args) >= 4:
            regex_sub = args[1].upper()
            if regex_sub == "MATCH":
                # string(REGEX MATCH <regex> <out_var> <input> [<input>...])
                if len(args) >= 5:
                    pattern = args[2]
                    out_var = args[3]
                    inputs = args[4:]
                    full_input = "".join(inputs)
                    match = re.search(pattern, full_input)
                    reset_cmake_match_vars()
                    if match:
                        ctx.variables[out_var] = match.group(0)
                        ctx.variables["CMAKE_MATCH_COUNT"] = str(len(match.groups()))
                        # Set CMAKE_MATCH_n variables for the current match only.
                        for j in range(len(match.groups()) + 1):
                            value = match.group(j)
                            ctx.variables[f"CMAKE_MATCH_{j}"] = (
                                value if value is not None else ""
                            )
                    else:
                        ctx.variables[out_var] = ""
                        ctx.variables["CMAKE_MATCH_COUNT"] = "0"
                        ctx.variables["CMAKE_MATCH_0"] = ""
            elif regex_sub == "MATCHALL":
                # string(REGEX MATCHALL <regex> <out_var> <input> [<input>...])
                if len(args) >= 5:
                    pattern = args[2]
                    out_var = args[3]
                    inputs = args[4:]
                    full_input = "".join(inputs)
                    matches = re.findall(pattern, full_input)
                    ctx.variables[out_var] = ";".join(matches)
            elif regex_sub == "REPLACE":
                # string(REGEX REPLACE <regex> <replace_string> <out_var> <input> [<input>...])
                if len(args) >= 6:
                    pattern = args[2]
                    replace_str = args[3]
                    out_var = args[4]
                    inputs = args[5:]
                    full_input = "".join(inputs)

                    # CMake uses \1, \2 etc for backreferences, Python uses \1, \2
                    # but also supports \g<1> which is safer.
                    # Actually CMake's REGEX REPLACE is a bit different.
                    ctx.variables[out_var] = re.sub(pattern, replace_str, full_input)

    elif subcommand == "SUBSTRING":
        # string(SUBSTRING <string> <begin> <length> <out_var>)
        if len(args) >= 5:
            string_val = args[1]
            try:
                begin = int(args[2])
                length = int(args[3])
                out_var = args[4]
                if length == -1:
                    ctx.variables[out_var] = string_val[begin:]
                else:
                    ctx.variables[out_var] = string_val[begin : begin + length]
            except ValueError:
                pass

    elif subcommand == "TOLOWER":
        # string(TOLOWER <string> <out_var>)
        if len(args) >= 3:
            string_val = args[1]
            out_var = args[2]
            ctx.variables[out_var] = string_val.lower()

    elif subcommand == "TOUPPER":
        # string(TOUPPER <string> <out_var>)
        if len(args) >= 3:
            string_val = args[1]
            out_var = args[2]
            ctx.variables[out_var] = string_val.upper()

    elif subcommand == "LENGTH":
        # string(LENGTH <string> <out_var>)
        if len(args) >= 3:
            string_val = args[1]
            out_var = args[2]
            ctx.variables[out_var] = str(len(string_val))

    elif subcommand == "APPEND":
        # string(APPEND <var> [<string>...])
        if len(args) >= 2:
            out_var = args[1]
            current_val = ctx.variables.get(out_var, "")
            ctx.variables[out_var] = current_val + "".join(args[2:])

    elif subcommand == "CONCAT":
        # string(CONCAT <out_var> [<string>...])
        if len(args) >= 2:
            out_var = args[1]
            ctx.variables[out_var] = "".join(args[2:])

    elif subcommand == "JOIN":
        # string(JOIN <glue> <out_var> [<string>...])
        if len(args) >= 3:
            glue = args[1]
            out_var = args[2]
            ctx.variables[out_var] = glue.join(args[3:])

    elif subcommand == "STRIP":
        # string(STRIP <string> <out_var>)
        if len(args) >= 3:
            string_val = args[1]
            out_var = args[2]
            ctx.variables[out_var] = string_val.strip()

    elif subcommand == "SHA1":
        # string(SHA1 <out_var> <input>)
        if len(args) >= 3:
            out_var = args[1]
            input_val = args[2]
            ctx.variables[out_var] = hashlib.sha1(input_val.encode()).hexdigest()

    elif subcommand == "COMPARE":
        # string(COMPARE <OP> <string1> <string2> <out_var>)
        if len(args) >= 5:
            op = args[1].upper()
            s1 = args[2]
            s2 = args[3]
            out_var = args[4]
            result = False
            if op == "EQUAL":
                result = s1 == s2
            elif op == "NOTEQUAL":
                result = s1 != s2
            elif op == "LESS":
                result = s1 < s2
            elif op == "GREATER":
                result = s1 > s2
            ctx.variables[out_var] = "1" if result else "0"


def handle_file(
    ctx: BuildContext,
    cmd: Command,
    args: list[str],
    strict: bool,
) -> None:
    """Handle file() command."""
    if not args:
        if strict:
            ctx.print_error("file() requires at least a subcommand", cmd.line)
            sys.exit(1)
        return

    subcommand = args[0].upper()

    if subcommand in ("WRITE", "APPEND"):
        # file(WRITE <filename> <content>...)
        if len(args) >= 2:
            filename = ctx.expand_variables(args[1], strict, cmd.line)
            if not Path(filename).is_absolute():
                filename = str(ctx.current_source_dir / filename)
            content = "".join(args[2:])
            mode = "w" if subcommand == "WRITE" else "a"
            assert len(str(ctx.build_dir)) > 1
            # check that build_dir is below cwd:
            assert str(ctx.build_dir).startswith(str(Path.cwd()))
            # check that only writing to files below build_dir:
            assert str(Path(filename).resolve()).startswith(
                str(ctx.build_dir.resolve())
            ), (
                "writing to files ({}) outside of build directory ({}) is not allowed".format(
                    filename, str(ctx.build_dir)
                )
            )
            Path(filename).parent.mkdir(parents=True, exist_ok=True)
            with open(filename, mode) as f:
                f.write(content)

    elif subcommand == "READ":
        # file(READ <filename> <variable> [OFFSET <offset>] [LIMIT <limit>] [HEX])
        if len(args) >= 3:
            filename = ctx.expand_variables(args[1], strict, cmd.line)
            if not Path(filename).is_absolute():
                filename = str(ctx.current_source_dir / filename)
            var_name = args[2]
            if Path(filename).exists():
                with open(filename, "r") as f:
                    ctx.variables[var_name] = f.read()
            else:
                ctx.variables[var_name] = ""

    elif subcommand == "GLOB":
        if len(args) >= 3:
            var_name = args[1]
            patterns: list[str] = []
            relative_base: Path | None = None
            list_directories: bool | None = None

            i = 2
            while i < len(args):
                token = args[i]
                token_upper = token.upper()
                if token_upper == "RELATIVE" and i + 1 < len(args):
                    rel_value = ctx.expand_variables(args[i + 1], strict, cmd.line)
                    relative_base = Path(rel_value)
                    if not relative_base.is_absolute():
                        relative_base = ctx.current_source_dir / relative_base
                    i += 2
                    continue
                if token_upper == "CONFIGURE_DEPENDS":
                    i += 1
                    continue
                if token_upper == "LIST_DIRECTORIES" and i + 1 < len(args):
                    list_directories = is_truthy(
                        ctx.expand_variables(args[i + 1], strict, cmd.line)
                    )
                    i += 2
                    continue
                patterns.append(token)
                i += 1

            matched_files: list[str] = []
            for pattern in patterns:
                expanded_pattern = ctx.expand_variables(pattern, strict, cmd.line)
                if Path(expanded_pattern).is_absolute():
                    matched = py_glob.glob(expanded_pattern)
                else:
                    matched = py_glob.glob(
                        str(ctx.current_source_dir / expanded_pattern)
                    )
                if list_directories is False:
                    matched = [m for m in matched if not Path(m).is_dir()]
                matched.sort()
                if relative_base is not None:
                    try:
                        base_resolved = relative_base.resolve()
                    except OSError:
                        base_resolved = relative_base
                    for m in matched:
                        m_path = Path(m)
                        try:
                            m_resolved = m_path.resolve()
                        except OSError:
                            m_resolved = m_path
                        try:
                            rel = m_resolved.relative_to(base_resolved)
                            matched_files.append(to_posix_path(rel))
                        except ValueError:
                            matched_files.append(to_posix_path(m))
                else:
                    matched_files.extend(to_posix_path(m) for m in matched)
            ctx.variables[var_name] = ";".join(matched_files)

    elif subcommand == "REMOVE_RECURSE":
        # file(REMOVE_RECURSE [<files>...])
        for arg in args[1:]:
            filename = ctx.expand_variables(arg, strict, cmd.line)
            if not Path(filename).is_absolute():
                filename = str(ctx.current_source_dir / filename)
            p = Path(filename)
            if p.exists():
                import shutil

                if p.is_dir():
                    shutil.rmtree(p)
                else:
                    p.unlink()

    elif subcommand == "MAKE_DIRECTORY":
        # file(MAKE_DIRECTORY [<directories>...])
        for arg in args[1:]:
            dirname = ctx.expand_variables(arg, strict, cmd.line)
            if not Path(dirname).is_absolute():
                dirname = str(ctx.current_source_dir / dirname)
            Path(dirname).mkdir(parents=True, exist_ok=True)

    elif subcommand == "TOUCH":
        # file(TOUCH [<files>...])
        for arg in args[1:]:
            filename = ctx.expand_variables(arg, strict, cmd.line)
            if not Path(filename).is_absolute():
                filename = str(ctx.current_source_dir / filename)
            Path(filename).touch()

    elif subcommand == "LOCK":
        # file(LOCK <path> [DIRECTORY] [RELEASE] [GUARD <FUNCTION|FILE|PROCESS>] [RESULT_VARIABLE <variable>] [TIMEOUT <seconds>])
        # Stub for now, just succeeds
        pass


def handle_configure_file(
    ctx: BuildContext,
    cmd: Command,
    args: list[str],
    strict: bool,
) -> None:
    """Handle configure_file() command."""
    # configure_file(<input> <output> [COPYONLY] [@ONLY] [ESCAPE_QUOTES] [NEWLINE_STYLE ...])
    if len(args) < 2:
        if strict:
            ctx.print_error("configure_file requires input and output", cmd.line)
            sys.exit(1)
        return

    input_path = ctx.expand_variables(args[0], strict, cmd.line)
    output_path = ctx.expand_variables(args[1], strict, cmd.line)

    copyonly = "COPYONLY" in args[2:]
    at_only = "@ONLY" in args[2:]
    escape_quotes = "ESCAPE_QUOTES" in args[2:]

    src = Path(input_path)
    if not src.is_absolute():
        src = ctx.current_source_dir / src

    dst = Path(output_path)
    if not dst.is_absolute():
        current_binary_dir = Path(
            ctx.variables.get("CMAKE_CURRENT_BINARY_DIR", str(ctx.build_dir))
        )
        dst = current_binary_dir / dst

    if not src.exists():
        if strict:
            ctx.print_error(f"configure_file input does not exist: {src}", cmd.line)
            sys.exit(1)
        return

    content = src.read_text()
    if not copyonly:
        # Handle CMake template lines:
        #   #cmakedefine VAR [value...]
        #   #cmakedefine01 VAR
        def replace_cmakedefine_line(line: str) -> str:
            newline = ""
            if line.endswith("\r\n"):
                line_core = line[:-2]
                newline = "\r\n"
            elif line.endswith("\n"):
                line_core = line[:-1]
                newline = "\n"
            else:
                line_core = line

            m01 = re.match(
                r"^(\s*)#cmakedefine01\s+([A-Za-z_][A-Za-z0-9_]*)\s*(.*)$",
                line_core,
            )
            if m01:
                indent, var_name, trailing = m01.groups()
                defined = "1" if is_truthy(ctx.variables.get(var_name, "")) else "0"
                if trailing:
                    return f"{indent}#define {var_name} {defined} {trailing}{newline}"
                return f"{indent}#define {var_name} {defined}{newline}"

            m = re.match(
                r"^(\s*)#cmakedefine\s+([A-Za-z_][A-Za-z0-9_]*)(.*)$",
                line_core,
            )
            if not m:
                return line

            indent, var_name, suffix = m.groups()
            if is_truthy(ctx.variables.get(var_name, "")):
                return f"{indent}#define {var_name}{suffix}{newline}"
            return f"{indent}/* #undef {var_name} */{newline}"

        content = "".join(
            replace_cmakedefine_line(line) for line in content.splitlines(keepends=True)
        )

        # @VAR@ replacement
        def replace_at_var(match: re.Match[str]) -> str:
            var_name = match.group(1)
            value = ctx.variables.get(var_name, "")
            if value == "" and var_name not in ctx.variables:
                # In config templates, undefined vars are replaced with empty strings,
                # even in strict mode; emit a warning for visibility.
                ctx.print_warning(
                    f"undefined variable referenced: {var_name}", cmd.line
                )
            return value

        content = re.sub(r"@([A-Za-z_][A-Za-z0-9_]*)@", replace_at_var, content)

        # ${VAR} replacement (unless @ONLY)
        if not at_only:
            # For template content, undefined ${VAR} should warn, not fail, in strict mode.
            content = ctx.expand_variables(content, False, cmd.line)

        if escape_quotes:
            content = content.replace('"', '\\"')

    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(content)
