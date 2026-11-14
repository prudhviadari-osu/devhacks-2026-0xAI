"""
Capability framework — the repertoire of things a character CAN do.

The old brain had 5 hardcoded behaviors chosen by a rigid tree. This replaces
that with a UTILITY system: every capability looks at the situation and returns
a Proposal (a score + the concrete World action + a reason). The agent scores
them all and does the highest. "Versatile character" = many capabilities; a
ROLE (support, later) = a set of weights over them.

Each capability is small, independent, and testable. Add a new thing the
character can do = add one Capability subclass. Nothing else changes.

A capability reads a neutral `Perception` (built from the World) so it stays
decoupled and the agent could later run over a different world/live feed.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from model.world import Action, Idle, World


@dataclass
class Proposal:
    score: float                 # utility in [0, ~2]; agent picks the max
    action: Action               # the concrete World action to execute
    name: str                    # capability name (for the trace)
    reason: str = ""             # human-readable why (for callouts + debugging)
    comms: str = ""              # optional teammate callout if chosen
    target: str | None = None


@dataclass
class Perception:
    """What the agent sees this tick (vision-limited later; full for now)."""
    world: World
    me_name: str

    @property
    def me(self):
        return self.world.get(self.me_name)

    def allies(self):
        return [c for c in self.world.allies_of(self.me.team)
                if c.name != self.me_name]

    def enemies(self):
        return self.world.enemies_of(self.me.team)

    def dist(self, a, b) -> float:
        return ((a.x - b.x) ** 2 + (a.y - b.y) ** 2) ** 0.5


class Capability:
    """Base class. Override propose(); return None to abstain this tick.

    `phases` declares which game phases this behavior competes in. The agent
    gates capabilities by the current phase, so only a relevant subset competes
    each tick (prevents 50 behaviors from thrashing). Empty = all phases.
    """
    name = "capability"
    phases: tuple = ()      # Phase values this behavior is relevant in; () = any
    family = "misc"         # grouping for readability / the AI panel

    def propose(self, p: Perception, weights: dict[str, float]) -> Proposal | None:
        return None

    def relevant_in(self, phase) -> bool:
        return not self.phases or phase in self.phases

    def w(self, weights: dict[str, float], default: float = 1.0) -> float:
        """Role weight multiplier for this capability (1.0 if unweighted)."""
        return weights.get(self.name, default)
