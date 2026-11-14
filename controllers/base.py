"""
Controller interface — one per champion.

Every champion in the world is driven by a CharacterController with the SAME
interface, so the game loop never special-cases who's human, bot, or replay:

    decide(world, me_name) -> Action

- HumanController  : reads keyboard/mouse (you play)
- BotController    : our Planner + triage + survival gate (the support brain)
- ReplayController : plays back recorded/past-game actions

This is the MVC "Controller" layer: it reads the Model (world) and returns an
action the Model will apply. The View is separate (view/render.py).
"""
from __future__ import annotations

from model.world import Action, Idle, World


class CharacterController:
    def decide(self, world: World, me_name: str) -> Action:
        return Idle()
