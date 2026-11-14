"""
ReplayController — plays back a recorded sequence of actions ("data run").

Feed it a list of (tick_index, Action) or just a per-tick list; it returns the
next action each decide() call. Lets you populate the world with champions that
reproduce a prior game / a scripted scenario, so the playable env can be "you +
bots + data runs" with no special-casing in the loop.
"""
from __future__ import annotations

from controllers.base import CharacterController
from model.world import Action, Idle, World


class ReplayController(CharacterController):
    def __init__(self, actions: list[Action]):
        self.actions = actions
        self.i = 0

    def decide(self, world: World, me_name: str) -> Action:
        if self.i >= len(self.actions):
            return Idle()
        a = self.actions[self.i]
        self.i += 1
        return a
