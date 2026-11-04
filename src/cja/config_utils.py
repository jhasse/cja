import re

from .build_context import (
    BuildContext,
    find_matching_endforeach,
    find_matching_endif,
)
from .parser import Command
from .syntax import evaluate_condition, find_else_or_elseif
from .utils import split_unquoted_list_args


def _is_exact_var_token(token: str) -> bool:
    return (
        (token.startswith("${") and token.endswith("}"))
        or (token.startswith('"${') and token.endswith('}"'))
        or (token.startswith("'${") and token.endswith("}'"))
    )


def _condition_args(ctx: BuildContext, command: Command, strict: bool) -> list[str]:
    """Expand the arguments of a condition, splitting unquoted lists."""
    expanded: list[str] = []
    for i, arg in enumerate(command.args):
        if i < len(command.is_bracket) and command.is_bracket[i]:
            expanded.append(arg)
            continue
        # Match CMake condition behavior: undefined ${VAR} in a condition
        # evaluates as empty, rather than producing a strict warning.
        value = ctx.expand_variables(
            arg,
            strict,
            command.line,
            allow_undefined_empty=_is_exact_var_token(arg),
        )
        quoted = i < len(command.is_quoted) and command.is_quoted[i]
        if ";" in value and not quoted:
            expanded.extend(item for item in split_unquoted_list_args(value) if item)
        else:
            expanded.append(value)
    return expanded


def condition_holds(ctx: BuildContext, command: Command, strict: bool) -> bool:
    """Evaluate the condition of an if(), elseif() or while() command."""
    return expanded_condition_holds(ctx, _condition_args(ctx, command, strict))


def expanded_condition_holds(ctx: BuildContext, args: list[str]) -> bool:
    """Evaluate a condition whose arguments are already expanded and unquoted."""

    def target_exists(name: str) -> bool:
        return (
            ctx.get_library(name) is not None
            or ctx.get_executable(name) is not None
            or name in ctx.imported_targets
        )

    return evaluate_condition(
        args,
        ctx.variables,
        target_exists=target_exists,
        command_exists=lambda name: name in ctx.functions or name in ctx.macros,
        test_exists=lambda name: any(test.name == name for test in ctx.tests),
    )


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

    # Check the if condition
    if condition_holds(ctx, cmd, strict):
        # Execute commands from if to first elseif/else or endif
        block_end = blocks[0][1] if blocks else endif_idx
        return endif_idx, (block_start, block_end)

    # Check elseif/else blocks
    for j, (block_type, block_idx, _) in enumerate(blocks):
        if block_type == "elseif":
            if condition_holds(ctx, commands[block_idx], strict):
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
    strict: bool = False,
) -> tuple[int, str, list[str], list[Command]]:
    """Build foreach() iteration info."""
    cmd = commands[pc]
    if not args:
        ctx.raise_syntax_error("foreach() requires at least a loop variable", cmd.line)
    # foreach(<var>... IN ZIP_LISTS <lists>)
    for idx in range(1, len(args) - 1):
        if args[idx] == "IN" and args[idx + 1] == "ZIP_LISTS":
            ctx.check_unsupported_args(cmd, ["ZIP_LISTS"], strict)

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
        # foreach(var IN [LISTS list1 ...] [ITEMS item1 ...])
        mode = ""
        for value in remaining[1:]:
            if value in ("LISTS", "ITEMS") and mode != "ITEMS":
                mode = value
            elif mode == "LISTS":
                # CMake lists are ";"-separated, so split on ";" (not whitespace).
                list_val = ctx.variables.get(value, "")
                if list_val:
                    items.extend(list_val.split(";"))
            elif mode == "ITEMS":
                items.append(value)
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
