"""
Slow cross-match learning from wins/losses (the OUTER loop).

Within a match, the fast Learner adapts tactics from per-tick reward. This layer
is different and deliberately SLOW: it records each champion's match outcomes
(win/loss + how they performed) and only nudges their LEARNED-WEIGHT BASELINE
when a *consistent pattern* emerges — so one unlucky loss doesn't scramble a
champion, but a sustained losing streak gradually shifts how it plays.

Design (matches the user's intent):
  - every finished match appends an outcome to the champion's history
  - we look at a smoothed recent WIN RATE (EWMA over the last N matches)
  - only when that win rate drifts well below 0.5 for a while do we apply a
    small, bounded nudge to the baseline weights (toward safer/more supportive
    play); a sustained winning pattern reinforces the current baseline instead
  - nudges are tiny and capped, so identity persists and change is gradual

Stored in brains/<champion>.meta.json alongside the fast weights.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

_BRAIN_DIR = os.path.join(os.path.dirname(__file__), "..", "brains")

WINRATE_ALPHA = 0.25        # EWMA smoothing on win rate (lower = slower)
NUDGE_THRESHOLD = 0.40      # win rate must sit below this to trigger adjustment
NUDGE_STEP = 0.03           # how much a baseline weight moves per qualifying match
NUDGE_CAP = 0.5            # max cumulative drift from the original archetype
MIN_MATCHES = 4             # need at least this many games before any nudge


@dataclass
class MetaRecord:
    champion: str
    matches: int = 0
    wins: int = 0
    winrate_ewma: float = 0.5          # smoothed recent win rate
    # cumulative drift applied to baseline weights (so we can cap it)
    baseline_drift: dict[str, float] = field(default_factory=dict)

    @classmethod
    def load(cls, champion: str) -> "MetaRecord":
        path = os.path.join(_BRAIN_DIR, f"{champion}.meta.json")
        if os.path.exists(path):
            try:
                with open(path) as f:
                    d = json.load(f)
                return cls(**d)
            except Exception:
                pass
        return cls(champion=champion)

    def save(self) -> None:
        os.makedirs(_BRAIN_DIR, exist_ok=True)
        path = os.path.join(_BRAIN_DIR, f"{self.champion}.meta.json")
        with open(path, "w") as f:
            json.dump({"champion": self.champion, "matches": self.matches,
                       "wins": self.wins, "winrate_ewma": self.winrate_ewma,
                       "baseline_drift": self.baseline_drift}, f)

    def record_match(self, won: bool, baseline: dict[str, float]) -> dict:
        """Record one match outcome and, if a losing PATTERN has set in, apply a
        small nudge to the baseline weights. Returns the (possibly) adjusted
        baseline to use next match."""
        self.matches += 1
        self.wins += 1 if won else 0
        self.winrate_ewma = ((1 - WINRATE_ALPHA) * self.winrate_ewma
                             + WINRATE_ALPHA * (1.0 if won else 0.0))

        adjusted = dict(baseline)
        # only act once there's enough history AND a consistent losing pattern
        if self.matches >= MIN_MATCHES and self.winrate_ewma < NUDGE_THRESHOLD:
            # how far below the line we are scales the nudge (bounded)
            severity = (NUDGE_THRESHOLD - self.winrate_ewma) / NUDGE_THRESHOLD
            step = NUDGE_STEP * severity
            # a losing champion shifts toward survivability + support + grouping
            # (play safer / more as a team) and away from solo risk
            toward = {"spacing": +1, "disengage": +1, "shield_ally": +1,
                      "group": +1, "protect_carry": +1, "flee": +0.5}
            away = {"dive_carry": -1, "all_in": -1, "pick_isolated": -1}
            for beh, sign in {**toward, **away}.items():
                if beh not in adjusted:
                    continue
                cur_drift = self.baseline_drift.get(beh, 0.0)
                new_drift = cur_drift + sign * step
                new_drift = max(-NUDGE_CAP, min(NUDGE_CAP, new_drift))  # cap it
                self.baseline_drift[beh] = new_drift
        # apply the accumulated drift to the archetype baseline
        for beh, drift in self.baseline_drift.items():
            if beh in adjusted:
                adjusted[beh] = max(0.05, adjusted[beh] + drift)
        return adjusted

    def apply_drift(self, baseline: dict[str, float]) -> dict:
        """Apply the accumulated cross-match drift to a baseline (used at load)."""
        adjusted = dict(baseline)
        for beh, drift in self.baseline_drift.items():
            if beh in adjusted:
                adjusted[beh] = max(0.05, adjusted[beh] + drift)
        return adjusted

    def summary(self) -> dict:
        return {"matches": self.matches, "wins": self.wins,
                "winrate": round(self.winrate_ewma, 2),
                "drift": {k: round(v, 2) for k, v in self.baseline_drift.items()
                          if abs(v) > 0.02}}
