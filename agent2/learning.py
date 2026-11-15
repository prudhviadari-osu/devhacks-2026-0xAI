"""
Online weight adaptation — champions evolve toward what works (Option A).

Each champion tracks the OUTCOMES of its recent behavior against a multi-objective
reward and nudges its own behavior weights toward what's been earning reward. Over
a match, a champion that keeps dying while diving learns to dive less and value
spacing/disengage more; one whose shields keep saving allies learns to shield
more. This is lightweight reinforcement on the utility weights — not a neural net,
but genuinely adaptive and live-demoable.

Reward (your three objectives, combined):
    survivability  — staying alive, keeping/ gaining hp, not dying
    support        — allies near me surviving / being healthier because of me
    objective      — progress on securing the dragon

Mechanism (credit assignment, simplified for real-time):
    - each tick we compute a reward delta for the champion
    - we attribute it to the behavior it chose on the PREVIOUS tick
    - EWMA the per-behavior reward; periodically nudge that behavior's weight
      toward its average reward (good -> weight up, bad -> weight down)
    - weights are clamped and decay toward their archetype baseline so a champ
      stays recognizably itself while adapting
"""
from __future__ import annotations

from dataclasses import dataclass, field


# reward term coefficients (how much each objective matters)
W_SURVIVE = 1.0
W_SUPPORT = 0.8
W_OBJECTIVE = 0.6

LEARN_RATE = 0.06          # how fast weights move toward observed reward
WEIGHT_MIN, WEIGHT_MAX = 0.05, 2.5
BASELINE_PULL = 0.01       # gentle decay back toward the archetype baseline
EWMA_ALPHA = 0.2           # smoothing on per-behavior reward estimates


@dataclass
class Learner:
    """Per-champion. Owns the live (mutable) weights and the reward memory."""
    baseline: dict[str, float]                  # archetype weights (the anchor)
    weights: dict[str, float] = field(default_factory=dict)
    beh_reward: dict[str, float] = field(default_factory=dict)  # EWMA per behavior
    last_behavior: str | None = None
    # snapshots for computing reward deltas tick-to-tick
    _prev_hp: float = 1.0
    _prev_ally_hp: float = 1.0
    _prev_obj_secured: bool = False
    _alive_prev: bool = True
    adapt_count: int = 0

    def __post_init__(self):
        if not self.weights:
            self.weights = dict(self.baseline)

    # ---- called each tick by the controller ----
    def observe(self, champ, world, chosen_behavior: str) -> None:
        reward = self._reward(champ, world)
        # attribute this tick's reward to the behavior chosen LAST tick
        if self.last_behavior is not None:
            prev = self.beh_reward.get(self.last_behavior, 0.0)
            self.beh_reward[self.last_behavior] = (
                (1 - EWMA_ALPHA) * prev + EWMA_ALPHA * reward)
        self.last_behavior = chosen_behavior
        self.adapt_count += 1
        # adapt weights periodically (every ~10 ticks) so it's stable + visible
        if self.adapt_count % 10 == 0:
            self._adapt()

    def _reward(self, champ, world) -> float:
        # --- survivability ---
        hp = champ.hp_frac if champ.alive else 0.0
        survive = (hp - self._prev_hp)                  # hp gained/lost this window
        if self._alive_prev and not champ.alive:
            survive -= 1.0                              # big penalty for dying
        self._prev_hp = hp
        self._alive_prev = champ.alive

        # --- support: average hp of nearby allies (did I keep them alive?) ---
        allies = [a for a in world.allies_of(champ.team)
                  if a.name != champ.name and a.alive]
        near = [a for a in allies
                if (a.x - champ.x) ** 2 + (a.y - champ.y) ** 2 < 2000 ** 2]
        ally_hp = (sum(a.hp_frac for a in near) / len(near)) if near else self._prev_ally_hp
        support = (ally_hp - self._prev_ally_hp)
        self._prev_ally_hp = ally_hp

        # --- objective: reward the transition of securing the dragon ---
        secured = world.objective.secured_by == champ.team \
            if hasattr(world.objective, "secured_by") else False
        objective = 0.0
        if secured and not self._prev_obj_secured:
            objective = 1.0
        self._prev_obj_secured = secured

        return (W_SURVIVE * survive + W_SUPPORT * support
                + W_OBJECTIVE * objective)

    def _adapt(self) -> None:
        for beh, r in self.beh_reward.items():
            base = self.baseline.get(beh, 1.0)
            cur = self.weights.get(beh, base)
            # move weight toward (baseline scaled by observed reward sign)
            # positive reward -> push above baseline; negative -> below
            target = base * (1.0 + r)
            cur += LEARN_RATE * (target - cur)
            # gentle pull back to baseline so identity persists
            cur += BASELINE_PULL * (base - cur)
            self.weights[beh] = max(WEIGHT_MIN, min(WEIGHT_MAX, cur))

    # a small readable summary of what this champ has learned (for the panel)
    def summary(self) -> dict:
        drift = {}
        for beh in self.baseline:
            b = self.baseline[beh]
            c = self.weights.get(beh, b)
            if abs(c - b) > 0.08:
                drift[beh] = round(c - b, 2)
        # biggest movers: 'up' = weights that grew, 'down' = weights that shrank
        ups = sorted([(k, v) for k, v in drift.items() if v > 0],
                     key=lambda kv: -kv[1])[:2]
        downs = sorted([(k, v) for k, v in drift.items() if v < 0],
                       key=lambda kv: kv[1])[:2]
        return {"up": ups, "down": downs}
