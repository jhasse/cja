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
)
from .parser import Command
from .targets import Executable, Library


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
                    f"cmake_policy(SET {policy} OLD) is called, but cninja always uses NEW behavior for all policies",
                    cmd.line,
                )
        elif subcommand == "GET" and len(args) >= 3:
            var_name = args[2]
            # cninja always uses NEW behavior
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
        ctx.variables[f"{args[0]}_SOURCE_DIR"] = str(ctx.current_source_dir)
        ctx.variables[f"{args[0]}_BINARY_DIR"] = str(ctx.build_dir)


def handle_target_link_libraries(
    ctx: BuildContext,
    args: list[str],
) -> None:
    """Handle target_link_libraries() command."""
    if len(args) >= 2:
        target_name = args[0]
        # Parse libraries with visibility keywords
        # CMake supports: target_link_libraries(<target> <PRIVATE|PUBLIC|INTERFACE> <item>...)
        visibility = "PUBLIC"  # Default visibility
        for arg in args[1:]:
            if arg == "PUBLIC":
                visibility = "PUBLIC"
            elif arg == "INTERFACE":
                visibility = "INTERFACE"
            elif arg == "PRIVATE":
                visibility = "PRIVATE"
            else:
                # It's a library name
                lib = ctx.get_library(target_name)
                if lib:
                    # For libraries, we track linked libraries but don't use them yet
                    # (static libraries don't link, but they might need to propagate flags)
                    # TODO: differentiate based on visibility
                    pass
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
                if not Path(expanded).is_absolute():
                    expanded = str(ctx.current_source_dir / expanded)
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
        sources = [ctx.resolve_path(s) for s in sources]
        # Add sources to library or executable
        lib = ctx.get_library(target_name)
        if lib:
            lib.sources.extend(sources)
        else:
            exe = ctx.get_executable(target_name)
            if exe:
                exe.sources.extend(sources)


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
                if not Path(expanded).is_absolute():
                    expanded = str(ctx.current_source_dir / expanded)
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
                # Expand variables
                expanded = ctx.expand_variables(arg, strict, cmd.line)
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
                        if not Path(expanded).is_absolute():
                            expanded = str(ctx.current_source_dir / expanded)
                        if lib:
                            lib.public_include_directories.append(expanded)
                        elif exe:
                            exe.include_directories.append(expanded)
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
                    if not Path(expanded).is_absolute():
                        expanded = str(ctx.current_source_dir / expanded)
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
            elif strict:
                ctx.print_warning(
                    f"set_property(TARGET): property '{prop_name}' not yet supported",
                    cmd.line,
                )

    elif scope_type == "SOURCE":
        # Source file property
        for source_file in scope_args:
            expanded_filename = ctx.expand_variables(source_file, strict, cmd.line)
            if not Path(expanded_filename).is_absolute():
                expanded_filename = str(ctx.current_source_dir / expanded_filename)

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
                    if not Path(expanded).is_absolute():
                        expanded = str(ctx.current_source_dir / expanded)
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
        # Directory property - for now, we'll just store it but not act on it
        # Common properties: EP_BASE, INCLUDE_DIRECTORIES, etc.
        if strict:
            ctx.print_warning(
                "set_property(DIRECTORY) is not yet fully supported",
                cmd.line,
            )

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
            exe = ctx.get_executable(target_name)

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
            if not Path(expanded_filename).is_absolute():
                expanded_filename = str(ctx.current_source_dir / expanded_filename)

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
    args: list[str],
) -> None:
    """Handle add_library() command."""
    if len(args) >= 2:
        name = args[0]
        # Check for STATIC/SHARED/OBJECT keyword
        sources = args[1:]
        lib_type = "STATIC"
        if sources and sources[0] in ("STATIC", "SHARED", "OBJECT"):
            lib_type = sources[0]
            sources = sources[1:]
        sources = [ctx.resolve_path(s) for s in sources]
        ctx.libraries.append(
            Library(
                name=name,
                sources=sources,
                lib_type=lib_type,
            )
        )


def handle_add_executable(
    ctx: BuildContext,
    args: list[str],
) -> None:
    """Handle add_executable() command."""
    if len(args) >= 2:
        sources = [ctx.resolve_path(s) for s in args[1:]]
        ctx.executables.append(Executable(name=args[0], sources=sources))


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
                except (ValueError, IndexError):
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
        # Simplified implementation - just handle basic TOUPPER/TOLOWER/STRIP
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

            list_val = ctx.variables.get(list_name, "")
            if list_val:
                items = list_val.split(";")
                if action == "TOUPPER":
                    items = [item.upper() for item in items]
                elif action == "TOLOWER":
                    items = [item.lower() for item in items]
                elif action == "STRIP":
                    items = [item.strip() for item in items]
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
) -> None:
    """Handle set() command."""
    if args:
        var_name = args[0]
        values = args[1:]

        # Handle CMAKE_POLICY_DEFAULT_CMPxxxx specially
        if var_name.startswith("CMAKE_POLICY_DEFAULT_CMP"):
            # Extract the value (should be NEW or OLD)
            policy_value = values[0] if values else ""
            if policy_value == "OLD":
                # cninja always uses NEW behavior, warn about OLD
                ctx.print_warning(
                    f"{var_name} is set to OLD, but cninja always uses NEW behavior for all policies",
                    cmd.line,
                )
            # For NEW, silently accept (this is what we want)
            # Don't actually set the variable, just acknowledge it
            return

        # Filter out CACHE, PARENT_SCOPE, and track FORCE
        filtered_values: list[str] = []
        has_force = False
        has_parent_scope = False
        skip_next = 0
        for idx, val in enumerate(values):
            if skip_next > 0:
                skip_next -= 1
                continue
            if val == "CACHE":
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
        else:
            # set(VAR) with no value unsets the variable
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
                return lit.lstrip("0")
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
