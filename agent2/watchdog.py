"""Training watchdog: detect failure modes and let a trainer early-stop.

This is a MONITOR layered on top of the existing anti-oscillation machinery in
UtilityAgent (dwell / switch margin / phase hysteresis). It does NOT change any
runtime agent decision logic or reward math. It only reads telemetry the agent
already produces and reports two failure modes so a trainer can stop a run that
is no longer learning anything useful:

  1. Behavior looping: champions churn the same few behaviors over and over
     (pathological A<->B oscillation within matches), seen as a high mean
     switch-per-tick rate across the field.
  2. Learning plateau: the training metric flatlines or bounces around the same
     value with no real improvement across generations / evals.

The module is stdlib-only and importable at module top level with no global
side effects, so train_parallel.py can import it under macOS spawn semantics.
No em dashes anywhere by project convention.
"""
from __future__ import annotations

# ---- named default thresholds -------------------------------------------------

# Mean behavior switches per tick, averaged across champions, above which the
# field is considered to be looping. A healthy champion commits a behavior for
# HARD_DWELL (about 8 ticks) before reconsidering, so normal play sits well
# below one switch every several ticks. A sustained mean near or above roughly
# one switch per three ticks (~0.33) is pathological A<->B churn, so 0.35 is a
# conservative line that normal play stays under.
LOOP_SWITCHES_PER_TICK_MAX = 0.35

# Ignore matches shorter than this many ticks: too few ticks to make a switch
# rate meaningful (a short match can show a noisy rate that means nothing).
LOOP_MIN_TICKS = 200

# Number of trailing curve points the plateau detector looks at.
PLATEAU_WINDOW = 6

# Absolute tolerance for the plateau detector. The parallel trainer's metric
# legitimately sits near 0.5, so a plateau is when the windowed (max - min)
# stays within this band, meaning no meaningful change over the window.
PLATEAU_TOLERANCE = 0.02

# Minimum number of points required before the plateau detector can fire. Equal
# to the window so we never declare a plateau on a partial window.
PLATEAU_MIN_POINTS = PLATEAU_WINDOW


# ---- detectors ----------------------------------------------------------------

def looping_signal(switch_rates, *, max_rate=LOOP_SWITCHES_PER_TICK_MAX):
    """Detect pathological behavior looping from per-champion switch rates.

    Accepts either a dict {champ_key: switches_per_tick} or a list of rates.
    Computes the mean rate across champions and tracks the worst offenders.

    Returns (fired, mean_rate, detail):
      fired     True when mean_rate >= max_rate.
      mean_rate float mean switch-per-tick rate across the given champions.
      detail    human-readable string naming the metric and worst offenders.
    """
    if isinstance(switch_rates, dict):
        items = list(switch_rates.items())
        rates = [float(r) for _, r in items]
    else:
        items = None
        rates = [float(r) for r in switch_rates]

    if not rates:
        return (False, 0.0, "behavior looping: no switch-rate data")

    mean_rate = sum(rates) / len(rates)
    fired = mean_rate >= max_rate

    if items is not None:
        worst = sorted(items, key=lambda kv: kv[1], reverse=True)[:3]
        worst_str = ", ".join(f"{k} {v:.2f}" for k, v in worst)
        detail = (f"behavior looping detected - mean switch rate "
                  f"{mean_rate:.2f}/tick (worst: {worst_str})")
    else:
        worst_str = ", ".join(f"{v:.2f}" for v in sorted(rates, reverse=True)[:3])
        detail = (f"behavior looping detected - mean switch rate "
                  f"{mean_rate:.2f}/tick (worst rates: {worst_str})")

    return (fired, mean_rate, detail)


def plateau_signal(curve_values, *, window=PLATEAU_WINDOW,
                   tolerance=PLATEAU_TOLERANCE):
    """Detect a learning plateau from a metric curve.

    Looks only at the last `window` values. If fewer than `window` values exist
    it returns (False, ...) because the window is not full yet. Fires when the
    windowed (max - min) stays within `tolerance`, meaning the metric has not
    moved meaningfully. Robust to a metric that legitimately sits near 0.5.

    Returns (fired, detail).
    """
    values = [float(v) for v in curve_values]
    if len(values) < window:
        return (False,
                f"learning plateau: only {len(values)} of {window} points")

    window_vals = values[-window:]
    spread = max(window_vals) - min(window_vals)
    fired = spread <= tolerance
    centre = sum(window_vals) / len(window_vals)
    detail = (f"learning plateaued over {window} points - metric stayed within "
              f"{spread:.3f} (values ~{centre:.2f})")
    return (fired, detail)
