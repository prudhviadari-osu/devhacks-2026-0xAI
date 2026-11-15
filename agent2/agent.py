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

from agent2.behaviors import FULL_REPERTOIRE
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
    # hysteresis: a NEW capability must beat the one we're committed to by this
    # fraction before we switch, and we hold a pick for a minimum time. Together
    # these stop the peel<->kite<->attack flip-flop (near-tied scores thrashing).
    SWITCH_MARGIN = 0.20          # challenger must score 20% higher to steal
    MIN_COMMIT_TICKS = 5          # ~0.5s at 10Hz before reconsidering a switch

    def __init__(self, repertoire: list[Capability] | None = None,
                 weights: dict[str, float] | None = None,
                 learn: bool = True):
        self.repertoire = repertoire or FULL_REPERTOIRE
        self.weights = weights or {}
        self.last: Decision | None = None
        self._committed: str | None = None   # name of current capability
        self._commit_ticks = 0
        # online learning: weights adapt toward what earns reward (Option A)
        self.learn = learn
        self.learner = None
        if learn:
            from agent2.learning import Learner
            self.learner = Learner(baseline=dict(self.weights))

    def decide(self, world: World, me_name: str) -> Decision:
        p = Perception(world, me_name)
        from agent2.phases import detect_phase
        phase = detect_phase(p)
        self.phase = phase
        # use the learner's adapting weights if learning is on, else static
        active_weights = self.learner.weights if self.learner else self.weights
        proposals: list[Proposal] = []
        for cap in self.repertoire:
            if not cap.relevant_in(phase):
                continue   # phase-gated: only relevant behaviors compete
            prop = cap.propose(p, active_weights)
            if prop is not None:
                proposals.append(prop)

        if not proposals:
            self._committed = None
            d = Decision(Idle(), "idle", "no proposal", "", 0.0)
            self.last = d
            return d

        proposals.sort(key=lambda pr: pr.score, reverse=True)
        top = proposals[0]
        best = self._apply_hysteresis(top, proposals)

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
        # learning: attribute reward to the chosen behavior and adapt weights
        if self.learner is not None:
            self.learner.observe(p.me, world, best.name)
        return d

    def _apply_hysteresis(self, top: Proposal,
                          proposals: list[Proposal]) -> Proposal:
        """Stick with the committed capability unless a challenger clearly wins.

        Prevents thrashing between near-tied capabilities (the infinite
        peel/kite/attack loop). We only switch if either (a) the committed
        capability no longer proposes, or (b) the new top beats it by
        SWITCH_MARGIN after the minimum commit time.
        """
        committed_prop = next(
            (pr for pr in proposals if pr.name == self._committed), None)

        # nothing committed, or our commitment vanished -> take the top, commit
        if committed_prop is None:
            self._committed = top.name
            self._commit_ticks = 0
            return top

        self._commit_ticks += 1

        # still early in the commitment -> keep doing it (don't reconsider yet)
        if self._commit_ticks < self.MIN_COMMIT_TICKS:
            return committed_prop

        # past min commit: only switch if the challenger clearly beats us
        if top.name != self._committed and \
                top.score > committed_prop.score * (1 + self.SWITCH_MARGIN):
            self._committed = top.name
            self._commit_ticks = 0
            return top

        return committed_prop

    # risky = commits us toward/at enemies
    def _is_risky(self, prop: Proposal) -> bool:
        return prop.name in ("dive_carry", "pick_isolated", "all_in", "collapse",
                             "focus_target", "cc_diver", "body_block", "poke",
                             "auto_trade", "contest_objective")

    def _would_survive(self, p: Perception) -> bool:
        me = p.me
        enemies_on_me = sum(1 for e in p.enemies() if p.dist(me, e) < 1000)
        return not (me.hp_frac < 0.25 and enemies_on_me >= 1)

    def _best_safe(self, proposals: list[Proposal]) -> Proposal | None:
        for pr in proposals:
            if pr.name in ("spacing", "flee", "disengage", "recall", "group",
                           "shield_ally", "ward", "hold"):
                return pr
        return None
