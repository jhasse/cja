import itertools
import re

from .build_context import (
    BuildContext,
    find_matching_endforeach,
    find_matching_endif,
    is_exact_variable_reference,
)
from .parser import Command
from .syntax import evaluate_condition, find_else_or_elseif
from .utils import expand_list, split_unquoted_list_args


def _condition_args(ctx: BuildContext, command: Command, strict: bool) -> list[str]:
    """Expand the arguments of a condition, splitting unquoted lists."""
    expanded: list[str] = []
    for i, arg in enumerate(command.args):
        if i < len(command.is_bracket) and command.is_bracket[i]:
            expanded.append(arg)
            continue
        # Match CMake condition behavior: undefined ${VAR} or $CACHE{VAR} in a
        # condition evaluates as empty, rather than producing a strict warning.
        value = ctx.expand_variables(
            arg,
            strict,
            command.line,
            allow_undefined_empty=is_exact_variable_reference(arg),
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
    return evaluate_condition(
        args,
        ctx.variables,
        cache=ctx.cache_values,
        target_exists=ctx.target_exists,
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
) -> tuple[int, list[str], list[tuple[str | None, ...]], list[Command]]:
    """Build foreach() iteration info.

    Returns the index of the matching endforeach(), the loop variables, what
    each iteration sets them to (None leaves one unset) and the loop's body.
    """
    cmd = commands[pc]
    if not args:
        ctx.raise_syntax_error("foreach() requires at least a loop variable", cmd.line)

    # Find matching endforeach
    endforeach_idx = find_matching_endforeach(commands, pc, ctx)
    body = commands[pc + 1 : endforeach_idx]

    # Like in CMake, the variables of foreach(<var>... IN ...) end at the IN
    in_idx = args.index("IN") if "IN" in args else 0
    mode = args[in_idx + 1 : in_idx + 2]
    if in_idx >= 1 and mode == ["ZIP_LISTS"]:
        loop_vars, zipped = _zip_lists(ctx, cmd, args[:in_idx], args[in_idx + 2 :])
        return endforeach_idx, loop_vars, zipped, body
    if in_idx > 1 and mode in (["LISTS"], ["ITEMS"]):
        ctx.raise_syntax_error(
            "ITEMS or LISTS require exactly one iteration variable", cmd.line
        )

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
                items.extend(expand_list(ctx.variable_value(value)))
            elif mode == "ITEMS":
                items.append(value)
    else:
        # foreach(var item1 item2 ...)
        items = remaining

    return endforeach_idx, [loop_var], [(item,) for item in items], body


def _zip_lists(
    ctx: BuildContext, cmd: Command, loop_vars: list[str], list_names: list[str]
) -> tuple[list[str], list[tuple[str | None, ...]]]:
    """The loop variables of foreach(<var>... IN ZIP_LISTS <lists>) and what
    each iteration sets them to: the elements of the lists at that position.

    Like in CMake, a single variable stands for <var>_0, <var>_1, ..., one for
    each list, and a variable is left unset (None) once its list has ended.
    """
    if "LISTS" in list_names or "ITEMS" in list_names:
        ctx.raise_syntax_error(
            "ZIP_LISTS can not be used with LISTS or ITEMS", cmd.line
        )
    if len(loop_vars) == 1:
        loop_vars = [f"{loop_vars[0]}_{index}" for index in range(len(list_names))]
    elif len(loop_vars) != len(list_names):
        ctx.raise_syntax_error(
            f"Expected {len(loop_vars)} list variables, but given {len(list_names)}",
            cmd.line,
        )
    lists = [expand_list(ctx.variable_value(name)) for name in list_names]
    return loop_vars, list(itertools.zip_longest(*lists))


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
