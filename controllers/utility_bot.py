"""
UtilityBotController — plugs the new utility agent into the game loop.

Same CharacterController interface as human/bot/replay, so the loop is unchanged.
This drives any champion with the full broad repertoire (support weighting is
applied by passing a weights dict).
"""
from __future__ import annotations

from agent2.agent import UtilityAgent
from controllers.base import CharacterController
from model.world import Action, World


class UtilityBotController(CharacterController):
    def __init__(self, weights: dict[str, float] | None = None,
                 persist_key: str | None = None):
        self.agent = UtilityAgent(weights=weights, persist_key=persist_key)
        self.last_comms = ""
        self.last_priority = ""
        self.last_considered: list = []

    def decide(self, world: World, me_name: str) -> Action:
        d = self.agent.decide(world, me_name)
        self.last_comms = d.comms
        self.last_priority = d.chosen + (" (gated)" if d.gated else "")
        self.last_considered = d.considered
        return d.action
