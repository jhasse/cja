import re
from .parser import Command
from .build_context import (
    BuildContext,
    find_matching_endforeach,
    find_matching_endif,
)
from .syntax import evaluate_condition, find_else_or_elseif


def select_if_block(
    ctx: BuildContext,
    commands: list[Command],
    pc: int,
    strict: bool,
) -> tuple[int, tuple[int, int] | None]:
    """Select the if/elseif/else block to execute."""
    cmd = commands[pc]
    # Find matching endif
    endif_idx = find_matching_endif(commands, pc, ctx)
    # Find elseif/else blocks
    blocks = find_else_or_elseif(commands, pc, endif_idx)

    block_start = pc + 1

    def target_exists(name: str) -> bool:
        return (
            ctx.get_library(name) is not None
            or ctx.get_executable(name) is not None
            or name in ctx.imported_targets
        )

    def _is_empty_string_token(token: str) -> bool:
        return token == "" or token in ('""', "''")

    def _is_exact_var_token(token: str) -> bool:
        return (
            (token.startswith("${") and token.endswith("}"))
            or (token.startswith('"${') and token.endswith('}"'))
            or (token.startswith("'${") and token.endswith("}'"))
        )

    # Check the if condition
    if_args = []
    for i, arg in enumerate(cmd.args):
        allow_undefined = (
            i + 2 < len(cmd.args)
            and cmd.args[i + 1] == "STREQUAL"
            and _is_empty_string_token(cmd.args[i + 2])
            and _is_exact_var_token(arg)
        )
        # Match CMake condition behavior: undefined ${VAR} in if()/elseif()
        # evaluates as empty, rather than producing a strict warning.
        allow_undefined = allow_undefined or _is_exact_var_token(arg)
        if_args.append(
            ctx.expand_variables(
                arg,
                strict,
                cmd.line,
                allow_undefined_empty=allow_undefined,
                allow_undefined_warning="${${" in arg,
            )
        )
    if evaluate_condition(if_args, ctx.variables, target_exists=target_exists):
        # Execute commands from if to first elseif/else or endif
        block_end = blocks[0][1] if blocks else endif_idx
        return endif_idx, (block_start, block_end)

    # Check elseif/else blocks
    for j, (block_type, block_idx, block_args) in enumerate(blocks):
        if block_type == "elseif":
            elseif_args = []
            for i, arg in enumerate(block_args):
                allow_undefined = (
                    i + 2 < len(block_args)
                    and block_args[i + 1] == "STREQUAL"
                    and _is_empty_string_token(block_args[i + 2])
                    and _is_exact_var_token(arg)
                )
                allow_undefined = allow_undefined or _is_exact_var_token(arg)
                elseif_args.append(
                    ctx.expand_variables(
                        arg,
                        strict,
                        commands[block_idx].line,
                        allow_undefined_empty=allow_undefined,
                        allow_undefined_warning="${${" in arg,
                    )
                )
            if evaluate_condition(
                elseif_args, ctx.variables, target_exists=target_exists
            ):
                block_start = block_idx + 1
                block_end = blocks[j + 1][1] if j + 1 < len(blocks) else endif_idx
                return endif_idx, (block_start, block_end)
        elif block_type == "else":
            block_start = block_idx + 1
            return endif_idx, (block_start, endif_idx)

    return endif_idx, None


def build_foreach_info(
    ctx: BuildContext,
    commands: list[Command],
    pc: int,
    args: list[str],
) -> tuple[int, str, list[str], list[Command]]:
    """Build foreach() iteration info."""
    cmd = commands[pc]
    if not args:
        ctx.raise_syntax_error("foreach() requires at least a loop variable", cmd.line)

    # Find matching endforeach
    endforeach_idx = find_matching_endforeach(commands, pc, ctx)
    body = commands[pc + 1 : endforeach_idx]

    loop_var = cmd.args[0]  # Use unexpanded for variable name
    remaining = args[1:]  # Use expanded args for values

    # Determine iteration items
    items: list[str] = []
    if remaining and remaining[0] == "RANGE":
        # foreach(var RANGE stop) or foreach(var RANGE start stop [step])
        range_args = remaining[1:]
        if len(range_args) == 1:
            stop = int(range_args[0])
            items = [str(x) for x in range(stop + 1)]
        elif len(range_args) == 2:
            start, stop = int(range_args[0]), int(range_args[1])
            items = [str(x) for x in range(start, stop + 1)]
        elif len(range_args) >= 3:
            start, stop, step = (
                int(range_args[0]),
                int(range_args[1]),
                int(range_args[2]),
            )
            items = [str(x) for x in range(start, stop + 1, step)]
    elif remaining and remaining[0] == "IN":
        # foreach(var IN LISTS list1 ... | ITEMS item1 ...)
        mode = remaining[1] if len(remaining) > 1 else ""
        values = remaining[2:]
        if mode == "LISTS":
            for list_name in values:
                list_val = ctx.variables.get(list_name, "")
                if list_val:
                    items.extend(list_val.split())
        elif mode == "ITEMS":
            items = values
    else:
        # foreach(var item1 item2 ...)
        items = remaining

    return endforeach_idx, loop_var, items, body


_VERSION_RE = re.compile(r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?")


def _version_components(version: str) -> tuple[str, str, str]:
    match = _VERSION_RE.match(version.strip())
    if not match:
        return "0", "0", "0"
    major = match.group(1) or "0"
    minor = match.group(2) or "0"
    patch = match.group(3) or "0"
    return major, minor, patch


def _render_basic_package_version_file(
    version: str,
    compatibility: str,
    arch_independent: bool,
    ctx: BuildContext,
) -> str:
    major, minor, _ = _version_components(version)
    arch_block = ""
    if arch_independent:
        arch_block = "set(PACKAGE_VERSION_UNSUITABLE FALSE)\n"
    else:
        sizeof_void_p = ctx.variables.get(
            "CMAKE_SIZEOF_VOID_P", "${CMAKE_SIZEOF_VOID_P}"
        )
        arch_block = (
            f'set(PACKAGE_VERSION_SIZEOF_VOID_P "{sizeof_void_p}")\n'
            "if(NOT CMAKE_SIZEOF_VOID_P STREQUAL PACKAGE_VERSION_SIZEOF_VOID_P)\n"
            "  set(PACKAGE_VERSION_UNSUITABLE TRUE)\n"
            "endif()\n"
        )

    return (
        f'set(PACKAGE_VERSION "{version}")\n'
        "set(PACKAGE_VERSION_COMPATIBLE FALSE)\n"
        "set(PACKAGE_VERSION_EXACT FALSE)\n"
        f"{arch_block}"
        "if(PACKAGE_VERSION VERSION_LESS PACKAGE_FIND_VERSION)\n"
        "  set(PACKAGE_VERSION_COMPATIBLE FALSE)\n"
        "else()\n"
        f'  if("{compatibility}" STREQUAL "AnyNewerVersion")\n'
        "    set(PACKAGE_VERSION_COMPATIBLE TRUE)\n"
        f'  elseif("{compatibility}" STREQUAL "SameMajorVersion")\n'
        f'    if(PACKAGE_FIND_VERSION_MAJOR STREQUAL "{major}")\n'
        "      set(PACKAGE_VERSION_COMPATIBLE TRUE)\n"
        "    endif()\n"
        f'  elseif("{compatibility}" STREQUAL "SameMinorVersion")\n'
        f'    if(PACKAGE_FIND_VERSION_MAJOR STREQUAL "{major}" AND '
        f'PACKAGE_FIND_VERSION_MINOR STREQUAL "{minor}")\n'
        "      set(PACKAGE_VERSION_COMPATIBLE TRUE)\n"
        "    endif()\n"
        f'  elseif("{compatibility}" STREQUAL "ExactVersion")\n'
        "    if(PACKAGE_FIND_VERSION STREQUAL PACKAGE_VERSION)\n"
        "      set(PACKAGE_VERSION_COMPATIBLE TRUE)\n"
        "    endif()\n"
        "  endif()\n"
        "endif()\n"
        "if(PACKAGE_VERSION_COMPATIBLE AND PACKAGE_FIND_VERSION STREQUAL PACKAGE_VERSION)\n"
        "  set(PACKAGE_VERSION_EXACT TRUE)\n"
        "endif()\n"
        "if(NOT DEFINED PACKAGE_VERSION_UNSUITABLE)\n"
        "  set(PACKAGE_VERSION_UNSUITABLE FALSE)\n"
        "endif()\n"
    )


def _render_package_init_block(
    install_destination: str,
    *,
    no_set_and_check_macro: bool,
    no_check_required_components_macro: bool,
) -> str:
    install_destination = install_destination.replace("\\", "/").strip()
    if install_destination.startswith("/"):
        prefix_expr = install_destination
    else:
        parts = [p for p in install_destination.split("/") if p and p != "."]
        up = "/".join([".."] * len(parts))
        prefix_expr = (
            "${CMAKE_CURRENT_LIST_DIR}"
            if not up
            else f"${{CMAKE_CURRENT_LIST_DIR}}/{up}"
        )

    lines = [
        "# Generated by cja: configure_package_config_file()",
        f'get_filename_component(PACKAGE_PREFIX_DIR "{prefix_expr}" ABSOLUTE)',
        "",
    ]

    if not no_set_and_check_macro:
        lines.extend(
            [
                "macro(set_and_check _var _file)",
                '  set(${_var} "${_file}")',
                '  if(NOT EXISTS "${_file}")',
                '    message(FATAL_ERROR "File or directory ${_file} referenced by ${_var} does not exist")',
                "  endif()",
                "endmacro()",
                "",
            ]
        )

    if not no_check_required_components_macro:
        lines.extend(
            [
                "macro(check_required_components _NAME)",
                "  foreach(comp ${${_NAME}_FIND_COMPONENTS})",
                "    if(NOT ${_NAME}_${comp}_FOUND)",
                "      if(${_NAME}_FIND_REQUIRED_${comp})",
                "        set(${_NAME}_FOUND FALSE)",
                "      endif()",
                "    endif()",
                "  endforeach()",
                "endmacro()",
                "",
            ]
        )

    return "\n".join(lines)
