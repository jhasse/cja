from dataclasses import dataclass, field
from typing import Callable

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
    fetchcontent_names: list[str] = field(default_factory=list)
    fetchcontent_index: int = 0
    fetchcontent_cmd: Command | None = None
    fetchcontent_make_available: bool = True
