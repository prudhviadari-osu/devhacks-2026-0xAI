"""
Health monitor + circuit breaker.

Mentor deck, slide 4: "If it can't fail, don't ship it." + action entropy as a
health signal + circuit breakers that hand control to a simpler system.

The failure we guard against is *degenerate thrashing that isn't working*: the bot
flipping between actions (or mashing one) while the situation keeps getting worse.
We detect that with TWO signals that must BOTH be bad before we trip:

  1. low action entropy      -> the policy has collapsed / is stuck
  2. a falling outcome signal -> whatever it's doing isn't helping

Consistently holding ONE correct action while things are fine is healthy, so low
entropy alone must NOT trip the breaker (that was the v1 bug). When tripped, the
agent drops to a dead-simple safe policy and the comms layer says so. This is also
the integration-readiness argument: safe enough to run behind a real engine.
"""
from __future__ import annotations

import math
from collections import deque


class HealthMonitor:
    def __init__(self, window: int = 8, min_entropy: float = 0.25):
        self.window = window
        self.min_entropy = min_entropy
        self.actions: deque[str] = deque(maxlen=window)
        self.outcomes: deque[float] = deque(maxlen=window)  # e.g. carry hp
        self.tripped = False

    def record(self, action: str, outcome: float = 1.0) -> None:
        self.actions.append(action)
        self.outcomes.append(outcome)

    def entropy(self) -> float:
        """Normalized Shannon entropy over the action window, in [0, 1].

        A single repeated action is intentionally defined as entropy 0 but is only
        a problem when paired with a falling outcome (see `check`).
        """
        if len(self.actions) < self.window:
            return 1.0
        counts: dict[str, int] = {}
        for a in self.actions:
            counts[a] = counts.get(a, 0) + 1
        n = len(self.actions)
        h = -sum((c / n) * math.log2(c / n) for c in counts.values())
        # normalize against the max entropy achievable over the WINDOW size,
        # not the number of distinct actions (that was the v1 divide-by bug)
        h_max = math.log2(min(self.window, len(set(self.actions)))) if n else 0.0
        if h_max <= 0:
            return 0.0
        return h / h_max

    def outcome_falling(self) -> bool:
        if len(self.outcomes) < self.window:
            return False
        return self.outcomes[-1] < self.outcomes[0] - 1e-6

    def check(self) -> bool:
        """Healthy unless the policy has collapsed AND the outcome is worsening."""
        self.tripped = self.entropy() < self.min_entropy and self.outcome_falling()
        return not self.tripped
