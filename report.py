"""
Read the training report: print the win-rate-vs-benchmark curve + per-champion
learned summaries. Run after (or during) training:  python3 report.py
"""
from __future__ import annotations

import json
import os

HERE = os.path.dirname(__file__)
REPORT = os.path.join(HERE, "training_report.json")
BRAINS = os.path.join(HERE, "brains")


def ascii_curve(points):
    """A tiny terminal chart of winrate over matches. Handles both trainers:
    sequential uses 'winrate_vs_benchmark', parallel uses 'ally_winrate'."""
    if not points:
        return "  (no eval points yet)"
    rows = 10
    out = []
    key = ("winrate_vs_benchmark" if "winrate_vs_benchmark" in points[0]
           else "ally_winrate")
    vals = [p.get(key, 0.5) for p in points]
    for r in range(rows, -1, -1):
        thresh = r / rows
        line = f"{thresh:4.1f} |"
        for v in vals:
            line += "#" if v >= thresh else " "
        out.append(line)
    out.append("     +" + "-" * len(vals))
    out.append(f"      0 matches -> {points[-1]['match']}  "
               f"(each col = one eval; 0.5 line = even with benchmark)")
    return "\n".join(out)


def main():
    if os.path.exists(REPORT):
        rep = json.load(open(REPORT))
        print("=== TRAINING CURVE (winrate of trained brains vs frozen benchmark) ===")
        print(ascii_curve(rep.get("curve", [])))
        c = rep.get("curve", [])
        if c:
            last = c[-1]
            if "winrate_vs_benchmark" in last:
                label = "latest winrate vs benchmark"
                latest = last["winrate_vs_benchmark"]
            else:
                label = "latest ally winrate"
                latest = last.get("ally_winrate", 0.5)
            print(f"\n{label}: {latest:.2f}")
            print(f"total matches so far: {rep.get('total_matches', last['match'])}")
    else:
        print("no training_report.json yet — run train.py first")

    # per-champion learned summary
    if os.path.isdir(BRAINS):
        from agent2.profiles import profile_for_champion, archetype_of
        print("\n=== PER-CHAMPION LEARNED BRAINS ===")
        for fn in sorted(os.listdir(BRAINS)):
            if not fn.endswith(".json") or fn.endswith(".meta.json"):
                continue
            name = fn[:-5]
            data = json.load(open(os.path.join(BRAINS, fn)))
            base = profile_for_champion(name)
            w = data.get("weights", {})
            drift = {k: round(w[k] - base.get(k, 1.0), 2)
                     for k in w if abs(w[k] - base.get(k, 1.0)) > 0.03}
            top = [kv for kv in sorted(drift.items(), key=lambda x: -x[1])
                   if kv[1] > 0][:3]
            bot = [kv for kv in sorted(drift.items(), key=lambda x: x[1])
                   if kv[1] < 0][:3]
            items = data.get("item_prefs", {})
            best_item = max(items.items(), key=lambda x: x[1], default=("—", 0))
            print(f"  {name:8} [{archetype_of(name):9}] "
                  f"learned+={top}  learned-={bot}  fav_item={best_item[0]}")


if __name__ == "__main__":
    main()
