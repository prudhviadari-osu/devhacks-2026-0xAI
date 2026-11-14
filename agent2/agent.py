"""
UtilityAgent — scores the whole repertoire, picks the best, guards against throws.

This replaces the rigid planner+tree with: look at every capability, take each
one's Proposal (score + action), pick the highest, then run a survival gate so
the character still CONTRIBUTES without making a dumb play ("don't sell").

Role = weights over capabilities. The default weights are neutral (broad); the
support role (next step) just raises peel/ward/protect weights.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from agent2.capabilities import DEFAULT_REPERTOIRE
from agent2.capability import Capability, Perception, Proposal
from model.world import Action, Idle, Move, World


@dataclass
class Decision:
    action: Action
    chosen: str                      # capability name
    reason: str
    comms: str
    score: float
    considered: list[tuple[str, float]] = field(default_factory=list)
    gated: bool = False              # survival gate downgraded the pick


class UtilityAgent:
    def __init__(self, repertoire: list[Capability] | None = None,
                 weights: dict[str, float] | None = None):
        self.repertoire = repertoire or DEFAULT_REPERTOIRE
        self.weights = weights or {}
        self.last: Decision | None = None

    def decide(self, world: World, me_name: str) -> Decision:
        p = Perception(world, me_name)
        proposals: list[Proposal] = []
        for cap in self.repertoire:
            prop = cap.propose(p, self.weights)
            if prop is not None:
                proposals.append(prop)

        if not proposals:
            d = Decision(Idle(), "idle", "no proposal", "", 0.0)
            self.last = d
            return d

        proposals.sort(key=lambda pr: pr.score, reverse=True)
        best = proposals[0]

        # survival gate: don't throw. If the best pick is a risky commit and we'd
        # die for nothing, downgrade to the best SAFE proposal instead of feeding.
        gated = False
        if self._is_risky(best) and not self._would_survive(p):
            safe = self._best_safe(proposals)
            if safe is not None and safe is not best:
                best, gated = safe, True

        d = Decision(
            action=best.action, chosen=best.name, reason=best.reason,
            comms=best.comms, score=best.score,
            considered=[(pr.name, round(pr.score, 2)) for pr in proposals[:5]],
            gated=gated,
        )
        self.last = d
        return d

    # risky = commits us toward enemies (engage / body-block / step-in)
    def _is_risky(self, prop: Proposal) -> bool:
        return prop.name in ("engage_cc", "peel_carry", "kite", "trade")

    def _would_survive(self, p: Perception) -> bool:
        me = p.me
        enemies_on_me = sum(1 for e in p.enemies() if p.dist(me, e) < 1000)
        return not (me.hp_frac < 0.25 and enemies_on_me >= 1)

    def _best_safe(self, proposals: list[Proposal]) -> Proposal | None:
        for pr in proposals:
            if pr.name in ("disengage", "recall", "ward_objective",
                           "follow_carry"):
                return pr
        return None
