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
    SWITCH_MARGIN = 0.12          # challenger must score 12% higher to steal
    MIN_COMMIT_TICKS = 5          # ~0.5s at 10Hz before reconsidering a switch

    def __init__(self, repertoire: list[Capability] | None = None,
                 weights: dict[str, float] | None = None,
                 learn: bool = True, persist_key: str | None = None):
        self.repertoire = repertoire or FULL_REPERTOIRE
        self.weights = weights or {}
        self.last: Decision | None = None
        self._committed: str | None = None   # name of current capability
        self._commit_ticks = 0
        # anti-oscillation: remember recently-left behaviors and how long ago,
        # to damp A<->B cycles (ward<->group) that slip past commit timing
        self._recent_left: dict[str, int] = {}
        self._age = 0
        # online learning: weights adapt toward what earns reward (Option A)
        self.learn = learn
        self.learner = None
        self.persist_key = persist_key
        self.meta = None
        if learn:
            from agent2.learning import Learner
            baseline = dict(self.weights)
            # apply slow cross-match (win/loss) drift to the baseline first
            if persist_key:
                from agent2.meta_learning import MetaRecord
                self.meta = MetaRecord.load(persist_key)
                baseline = self.meta.apply_drift(baseline)   # slow win/loss drift
            self.learner = Learner(baseline=baseline)
            # then load fast per-behavior weights learned in previous matches
            if persist_key:
                self.learner.load(persist_key)

    def end_match(self, won: bool) -> None:
        """Record the win/loss for slow cross-match learning + persist."""
        if self.meta is not None and self.persist_key:
            self.meta.record_match(won, dict(self.weights))
            self.meta.save()
        self.save_brain()

    def save_brain(self) -> None:
        if self.learner is not None and self.persist_key:
            self.learner.save(self.persist_key)

    def decide(self, world: World, me_name: str) -> Decision:
        p = Perception(world, me_name)
        from agent2.phases import detect_phase
        raw_phase = detect_phase(p)
        # phase hysteresis: don't let the phase flip every tick (that flickers
        # which behaviors are available and causes flee<->hold / advance<->hold
        # churn). Hold a phase for a few ticks before accepting a change.
        if not hasattr(self, "_phase"):
            self._phase, self._phase_pending = raw_phase, 0
        if raw_phase == self._phase:
            self._phase_pending = 0          # stable -> reset the change counter
        else:
            self._phase_pending += 1         # a different phase is being seen
            if self._phase_pending >= 6:     # sustained ~0.6s -> accept the change
                self._phase = raw_phase
                self._phase_pending = 0
        phase = self._phase
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

        # CENTRAL ARRIVAL DEADZONE (anti-loop, applies to every behavior at once):
        # a Move proposal whose destination we've basically reached is a no-op —
        # keeping it lets two move-behaviors ping-pong (hold<->advance,
        # group<->ward, etc.). Drop such proposals so a champion that has arrived
        # doesn't keep "deciding" to go where it already is.
        from model.world import Move
        me = p.me
        DEADZONE = 350.0
        for pr in proposals:
            # if a Move proposal has basically ARRIVED, convert it to Idle but
            # KEEP its name/score. This is the key anti-churn fix: an arrived
            # behavior stays selected (champion stands still) instead of
            # vanishing and letting another move-behavior yank it back. No
            # move->arrive->hold->move-back bounce can form.
            if isinstance(pr.action, Move) and \
                    ((pr.action.x - me.x) ** 2 + (pr.action.y - me.y) ** 2) \
                    <= DEADZONE ** 2:
                pr.action = Idle()

        # tiny decision noise so near-tied choices aren't perfectly deterministic
        # -> matches play out with natural variety (not the exact same game twice)
        import random
        for pr in proposals:
            pr.score *= (1.0 + random.uniform(-0.04, 0.04))
        # fallback: if nothing proposed (e.g. no enemies + already centered),
        # idle in place rather than crash. Keeps the decide loop total.
        if not proposals:
            self._committed = "idle"
            d = Decision(Idle(), "idle", "nothing to do", "", 0.0)
            self.last = d
            if self.learner is not None:
                self.learner.observe(p.me, world, "idle")
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

    # behaviors that are low-urgency "positioning" — the churn-prone ones
    LOW_PRIORITY = {"hold", "advance", "ward", "group", "recall", "roam",
                    "last_hit", "push_wave", "freeze_wave", "spacing"}
    HARD_DWELL = 8      # min ticks to keep a decision (lowered — was too sticky)
    EMERGENCY = 1.1     # a proposal this strong interrupts anything (lowered so
                        # real fights/engages actually interrupt a wander)

    def _apply_hysteresis(self, top: Proposal,
                          proposals: list[Proposal]) -> Proposal:
        """Clean state machine that prevents oscillation for ALL behaviors.

        Rules, in order:
          1. An EMERGENCY (very high score) always wins immediately.
          2. Within the dwell window, keep the current decision. If the current
             behavior vanished (e.g. a move arrived), HOLD instead of hopping.
          3. After dwell, switch only if a challenger clearly beats the current
             one. Two low-priority behaviors need a large margin; otherwise a
             champion settles into HOLD rather than churning.
        """
        self._age += 1
        self._commit_ticks += 1
        by_name = {pr.name: pr for pr in proposals}
        hold_prop = by_name.get("hold")
        top_raw = max(proposals, key=lambda pr: pr.score)

        # 1. emergency override — a big spike interrupts anything, resets dwell
        if top_raw.name != self._committed and top_raw.score >= self.EMERGENCY:
            self._commit(top_raw.name)
            return top_raw

        committed = by_name.get(self._committed)

        # HOLD is a fallback, not a sticky commitment: if we're holding and ANY
        # real behavior (not another low-priority wander) wants to act, let it,
        # immediately. This stops champions from settling into hold and never
        # fighting. A meaningfully-scored non-wander challenger breaks hold now.
        if self._committed == "hold":
            best_real = max((pr for pr in proposals
                             if pr.name not in self.LOW_PRIORITY),
                            key=lambda pr: pr.score, default=None)
            if best_real is not None and best_real.score > 0.4:
                self._commit(best_real.name)
                return best_real
            # otherwise let a non-hold low-priority (advance/push/farm) take over
            best_lp = max((pr for pr in proposals if pr.name != "hold"),
                          key=lambda pr: pr.score, default=None)
            if best_lp is not None and best_lp.score > 0.35:
                self._commit(best_lp.name)
                return best_lp
            return hold_prop if hold_prop else top_raw

        # 2. within dwell: keep the current decision. If the committed behavior
        # vanished (move arrived), hold in place. No switching at all.
        if self._committed is not None and self._commit_ticks <= self.HARD_DWELL:
            if committed is not None:
                return committed
            if hold_prop is not None:
                return hold_prop   # arrived / vanished -> settle, don't hop
            # committed gone and no hold -> fall through to re-decide

        # 3. past dwell (or nothing committed): decide whether to switch
        chal = top_raw
        if committed is None:
            # current behavior is gone. Take a clearly-worthwhile action, else hold.
            if chal.name not in self.LOW_PRIORITY and chal.score > 0.45:
                self._commit(chal.name)
                return chal
            if hold_prop is not None:
                self._commit("hold")
                return hold_prop
            self._commit(chal.name)
            return chal

        # both present: require a margin to switch; a bit bigger if both are
        # low-priority wanders (just enough to stop churn, not so high it freezes)
        margin = self.SWITCH_MARGIN
        if self._committed in self.LOW_PRIORITY and chal.name in self.LOW_PRIORITY:
            margin = 0.5     # modest — damps churn without freezing into hold
        if chal.name != self._committed and \
                chal.score > committed.score * (1 + margin):
            self._commit(chal.name)
            return chal
        return committed

    def _commit(self, name: str) -> None:
        self._committed = name
        self._commit_ticks = 0

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
