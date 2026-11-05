from collections.abc import Callable
from dataclasses import dataclass, field

from cja.build_context import Directory
from cja.parser import Command


@dataclass
class Frame:
    commands: list[Command] | None
    pc: int = 0
    on_exit: Callable[[], None] | None = None
    kind: str = "commands"
    foreach_items: list[str] = field(default_factory=list)
    foreach_index: int = 0
    foreach_loop_var: str = ""
    foreach_body: list[Command] | None = None
    while_command: Command | None = None
    while_body: list[Command] = field(default_factory=list)
    fetchcontent_names: list[str] = field(default_factory=list)
    fetchcontent_index: int = 0
    fetchcontent_cmd: Command | None = None
    fetchcontent_make_available: bool = True
    # The directory of a "directory" frame, whose deferred calls run at its end
    directory: Directory | None = None
    # Set on the frame running a deferred call, for CMAKE_CURRENT_LIST_LINE
    deferred_call_id: str = ""
