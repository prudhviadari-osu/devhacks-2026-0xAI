"""
HumanController — you play one champion.

Kept UI-agnostic: the game loop fills an `InputState` (from pygame or anything
else) and sets it on the controller before calling decide(). That way the
controller has no hard pygame dependency and stays testable.

Controls (filled by the view):
    move_to (x, y)  : right-click / click target position in game units
    cast_slot       : "Q".."R" pressed this tick (point/target from cursor)
    cursor (x, y)   : current cursor in game units (for cast target)
    auto_target     : champion name to auto-attack, if any
"""
from __future__ import annotations

from dataclasses import dataclass

from controllers.base import CharacterController
from model.world import Action, Auto, Cast, Idle, Move, World


@dataclass
class InputState:
    move_to: tuple[float, float] | None = None
    cast_slot: str | None = None
    cursor: tuple[float, float] | None = None
    auto_target: str | None = None


class HumanController(CharacterController):
    def __init__(self) -> None:
        self.input = InputState()

    def set_input(self, state: InputState) -> None:
        self.input = state

    def decide(self, world: World, me_name: str) -> Action:
        inp = self.input
        # casting takes priority this tick
        if inp.cast_slot:
            if inp.auto_target:
                return Cast(inp.cast_slot, target=inp.auto_target)
            if inp.cursor:
                return Cast(inp.cast_slot, x=inp.cursor[0], y=inp.cursor[1])
            return Cast(inp.cast_slot)
        if inp.auto_target:
            return Auto(inp.auto_target)
        if inp.move_to:
            return Move(*inp.move_to)
        return Idle()
