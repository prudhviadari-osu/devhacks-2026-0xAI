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


# ---- reward term weights (each objective tuned independently) ----
# rebalanced so support + objectives matter, not just raw survival.
W_SURVIVE   = 0.45    # staying alive / keeping hp — survival matters again, but
W_TIME      = 0.1     # it's meant to be earned via EVASIVE MOVEMENT (dodge/kite/
W_DEATH     = 0.8     # space), not by retreating out of the fight. The reward is
                      # survival-agnostic; the EVASIVE behaviors (weighted up in
                      # profiles) are how champions chase that reward.
W_KILL      = 1.0     # securing a kill
W_STREAK    = 0.4     # extra per point of killstreak (snowball reward)
W_ASSIST    = 0.7     # assisting a kill (rewards teamplay/support)
W_SUPPORT   = 1.1     # nearby allies staying healthy because of you (weighted UP)
W_PROTECT   = 0.9     # an ally you were near avoided death
W_OBJECTIVE = 0.9     # dragon secured (weighted UP)
W_TOWER     = 0.6     # enemy tower/structure damage (pushing/winning)

LEARN_RATE = 0.06          # how fast weights move toward observed reward
WEIGHT_MIN, WEIGHT_MAX = 0.05, 2.5
BASELINE_PULL = 0.01       # gentle decay back toward the archetype baseline
EWMA_ALPHA = 0.2           # smoothing on per-behavior reward estimates

import os
_BRAIN_DIR = os.path.join(os.path.dirname(__file__), "..", "brains")


@dataclass
class Learner:
    """Per-champion. Owns the live (mutable) weights and the reward memory."""
    baseline: dict[str, float]                  # archetype weights (the anchor)
    weights: dict[str, float] = field(default_factory=dict)
    beh_reward: dict[str, float] = field(default_factory=dict)  # EWMA per behavior
    last_behavior: str | None = None
    rate: float = LEARN_RATE          # per-instance learn rate (trainer tunes it)
    # snapshots for computing reward deltas tick-to-tick
    _prev_hp: float = 1.0
    _prev_ally_hp: float = 1.0
    _prev_obj_secured: bool = False
    _alive_prev: bool = True
    _prev_kills: int = 0
    _prev_assists: int = 0
    _prev_streak: int = 0
    _prev_time_alive: float = 0.0
    _prev_enemy_tower_hp: float = -1.0
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
        r = 0.0

        # --- survivability: hp delta, a death penalty, and time-alive bonus ---
        hp = champ.hp_frac if champ.alive else 0.0
        r += W_SURVIVE * (hp - self._prev_hp)
        self._prev_hp = hp
        if self._alive_prev and not champ.alive:
            r -= W_DEATH                               # dying is costly
        self._alive_prev = champ.alive
        # time-alive: small steady reward for each second survived this life
        r += W_TIME * max(0.0, champ.time_alive - self._prev_time_alive)
        self._prev_time_alive = champ.time_alive

        # --- kills / killstreaks / assists ---
        if champ.kills > self._prev_kills:
            r += W_KILL * (champ.kills - self._prev_kills)
            r += W_STREAK * champ.killstreak           # snowball: bigger streak = more
        self._prev_kills = champ.kills
        if champ.assists > self._prev_assists:
            r += W_ASSIST * (champ.assists - self._prev_assists)
        self._prev_assists = champ.assists

        # --- support: nearby allies staying healthy because of you ---
        allies = [a for a in world.allies_of(champ.team)
                  if a.name != champ.name and a.alive]
        near = [a for a in allies
                if (a.x - champ.x) ** 2 + (a.y - champ.y) ** 2 < 2200 ** 2]
        ally_hp = (sum(a.hp_frac for a in near) / len(near)) if near else self._prev_ally_hp
        r += W_SUPPORT * (ally_hp - self._prev_ally_hp)
        self._prev_ally_hp = ally_hp
        # protect: a nearby ally that's healthy-ish while enemies are around = good
        if near:
            threatened = any(
                any((e.x - a.x) ** 2 + (e.y - a.y) ** 2 < 1400 ** 2
                    for e in world.enemies_of(champ.team))
                for a in near)
            if threatened:
                r += W_PROTECT * 0.02 * len(near)      # steady while you shield them

        # --- objective (dragon) ---
        secured = getattr(world.objective, "secured_by", None) == champ.team
        if secured and not self._prev_obj_secured:
            r += W_OBJECTIVE
        self._prev_obj_secured = secured

        # --- pushing: enemy tower hp going down near you (you're sieging) ---
        sm = getattr(world, "structures", None)
        if sm is not None:
            enemy_tower_hp = sum(s.hp for s in sm.structures
                                 if s.team != champ.team and s.kind == "tower")
            if self._prev_enemy_tower_hp >= 0:
                dropped = self._prev_enemy_tower_hp - enemy_tower_hp
                if dropped > 0:
                    # credit the push only if you're near the action
                    if sm.nearest_attackable_enemy_structure(champ) and \
                       any((s.x - champ.x) ** 2 + (s.y - champ.y) ** 2 < 1800 ** 2
                           for s in sm.structures if s.team != champ.team):
                        r += W_TOWER * min(1.0, dropped / 300.0)
            self._prev_enemy_tower_hp = enemy_tower_hp

        return r

    def _adapt(self) -> None:
        for beh, r in self.beh_reward.items():
            base = self.baseline.get(beh, 1.0)
            cur = self.weights.get(beh, base)
            # move weight toward (baseline scaled by observed reward sign)
            # positive reward -> push above baseline; negative -> below
            target = base * (1.0 + r)
            cur += self.rate * (target - cur)
            # gentle pull back to baseline so identity persists
            cur += BASELINE_PULL * (base - cur)
            self.weights[beh] = max(WEIGHT_MIN, min(WEIGHT_MAX, cur))

    # ---- persistence: keep what a champion learned ACROSS matches ----
    def reward_snapshot(self) -> dict:
        """Export this match's accumulated per-behavior reward estimates + item
        prefs, so a parallel worker can return them for central aggregation
        (instead of writing the shared brain file). Pure data, picklable."""
        return {"beh_reward": dict(self.beh_reward),
                "item_prefs": dict(getattr(self, "_item_prefs", {}))}

    def item_prefs(self) -> dict:
        """Learned per-item preference (reward-weighted). Items that correlated
        with reward get a positive bias; the shop uses this to build better."""
        return getattr(self, "_item_prefs", {})

    def credit_item(self, item_name: str, recent_reward: float) -> None:
        """Nudge an owned item's preference by how well things have gone since
        buying it. Called with a smoothed reward signal."""
        if not hasattr(self, "_item_prefs"):
            self._item_prefs = {}
        cur = self._item_prefs.get(item_name, 0.0)
        self._item_prefs[item_name] = cur + 0.05 * recent_reward

    def save(self, champion_key: str) -> None:
        import json, os
        os.makedirs(_BRAIN_DIR, exist_ok=True)
        path = os.path.join(_BRAIN_DIR, f"{champion_key}.json")
        with open(path, "w") as f:
            json.dump({"weights": self.weights,
                       "beh_reward": self.beh_reward,
                       "item_prefs": getattr(self, "_item_prefs", {})}, f)

    def load(self, champion_key: str) -> bool:
        """Load previously-learned weights if present. Returns True if loaded."""
        import json, os
        path = os.path.join(_BRAIN_DIR, f"{champion_key}.json")
        if not os.path.exists(path):
            return False
        try:
            with open(path) as f:
                data = json.load(f)
            # merge onto baseline so new behaviors still get their default
            self.weights = dict(self.baseline)
            self.weights.update(data.get("weights", {}))
            self.beh_reward = data.get("beh_reward", {})
            self._item_prefs = data.get("item_prefs", {})
            return True
        except Exception:
            return False

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
