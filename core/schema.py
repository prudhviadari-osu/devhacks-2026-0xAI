"""
The interface. THIS is the scale story.

Every source (the sim, the real League Live Client Data feed, and in theory a
Riot server-side adapter) produces a `GameState`. Every tick the agent returns a
`BotOutput`. Because the planner/controller/comms only ever touch these two
types, the bot is completely decoupled from where the data comes from. "Integrate
into League" = write one more source that emits GameState. Nothing else changes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Team(str, Enum):
    ALLY = "ALLY"
    ENEMY = "ENEMY"


class Role(str, Enum):
    TOP = "TOP"
    JUNGLE = "JUNGLE"
    MID = "MID"
    ADC = "ADC"
    SUPPORT = "SUPPORT"


@dataclass
class Champion:
    name: str                 # e.g. "Leona" — matches Data Dragon keys
    team: Team
    role: Role
    x: float                  # position on a normalized 0..1 map (0,0 = bot-left)
    y: float
    hp_frac: float            # 0..1
    mana_frac: float          # 0..1
    # cooldowns remaining in seconds, keyed by ability slot "Q"/"W"/"E"/"R"
    cooldowns: dict[str, float] = field(default_factory=dict)
    cc_remaining: float = 0.0  # seconds this champ is crowd-controlled

    def ability_ready(self, slot: str) -> bool:
        return self.cooldowns.get(slot, 0.0) <= 0.0


@dataclass
class Objective:
    name: str                 # "DRAGON", "HERALD", "BARON"
    x: float
    y: float
    spawns_in: float          # seconds until it's available (0 = up now)
    contested: bool = False


@dataclass
class GameState:
    """One snapshot of the world, normalized. Source-agnostic on purpose."""
    time: float                              # match time in seconds
    champions: list[Champion]
    objectives: list[Objective] = field(default_factory=list)
    # who the bot is controlling (its own name); must be in champions
    self_name: str = ""

    # --- convenience lookups the planner/controller/comms all reuse ---
    def me(self) -> Champion:
        return next(c for c in self.champions if c.name == self.self_name)

    def allies(self) -> list[Champion]:
        return [c for c in self.champions if c.team == Team.ALLY]

    def enemies(self) -> list[Champion]:
        return [c for c in self.champions if c.team == Team.ENEMY]

    def ally_carry(self) -> Champion | None:
        """The teammate a support most needs to keep alive."""
        carries = [c for c in self.allies() if c.role in (Role.ADC, Role.MID)]
        return min(carries, key=lambda c: c.hp_frac, default=None)

    def next_objective(self) -> Objective | None:
        if not self.objectives:
            return None
        return min(self.objectives, key=lambda o: o.spawns_in)


class Priority(str, Enum):
    """The one signal the planner hands down to the controller.

    Deliberately small: the planner decides WHAT the team should prioritize,
    the controller decides HOW the support executes it this instant.
    """
    PEEL_CARRY = "PEEL_CARRY"        # protect the ADC/mid, the diving-assassin case
    ENGAGE = "ENGAGE"                # start a fight, look for CC onto priority target
    SETUP_OBJECTIVE = "SETUP_OBJECTIVE"  # ward + zone around dragon/herald/baron
    PLAY_SAFE = "PLAY_SAFE"          # behind / low — disengage, farm, reset
    ROAM = "ROAM"                    # help another lane


@dataclass
class BotOutput:
    """What the agent emits each tick."""
    priority: Priority
    action: str                      # concrete support action the controller chose
    target: str | None = None        # champion/objective the action is aimed at
    comms: str = ""                  # natural-language callout to the human teammate
    # bookkeeping for the demo + evidence
    trace: list[str] = field(default_factory=list)
    health_ok: bool = True           # False => circuit breaker tripped to safe mode
