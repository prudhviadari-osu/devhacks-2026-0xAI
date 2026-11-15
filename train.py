"""
Co-evolution training harness — round-robin curriculum.

Trains all champions to fine-tuned per-champion brains via an arms race:

  * FOCUS one champion at a time: it learns FAST (high rate) while the rest play
    with their current brains at a low rate (a near-stable field to adapt to).
  * When the focus champion has had its block of matches, freeze its gains and
    move focus to the next champion.
  * CYCLE through all champions repeatedly, so each one re-adapts as the others
    improve — counter, protect, adapt. This is what makes everyone keep getting
    better instead of converging to a static equilibrium.

Guard against tail-chasing: a FROZEN benchmark set of brains is snapshotted at
the start; every cycle we measure win-rate vs. that benchmark so "improvement"
is real (absolute), not just co-adaptation. The training curve is the evidence.

Brains persist to brains/<Champion>.json between matches (and runs), so training
accumulates and you can stop/resume.

Usage (on your machine — it can be long):
    python3 train.py                       # default deep run
    python3 train.py --cycles 8 --block 150
    python3 train.py --quick               # short sanity run
"""
from __future__ import annotations

import argparse
import functools
import json
import os
import shutil
import sys
import time

# flush prints immediately so you see training progress live
print = functools.partial(print, flush=True)

import scenarios
from agent2 import learning as L
from agent2.profiles import profile_for_champion, archetype_of
from controllers.utility_bot import UtilityBotController
from model.world import World

BRAIN_DIR = L._BRAIN_DIR
BENCH_DIR = os.path.join(os.path.dirname(__file__), "brains_benchmark")
REPORT = os.path.join(os.path.dirname(__file__), "training_report.json")

# learning rates for focus vs. background champions during a training block
FOCUS_RATE = 0.18        # the champion being trained learns fast
BACKGROUND_RATE = 0.03   # others drift slowly (near-stable field)


def roster():
    champs, _, _, _ = scenarios.get("balanced")
    return [c.name for c in champs]


def play_match(focus: str | None, focus_rate: float, bg_rate: float,
               learn: bool = True) -> str | None:
    """Run one headless match. `focus` champion learns at focus_rate, others at
    bg_rate (or not at all if learn=False, for evaluation). Returns winner."""
    champs, ds, _, _ = scenarios.get("balanced")
    world = World(champs, dragon_spawn=ds)
    ctrls = {}
    for ch in champs:
        c = UtilityBotController(profile_for_champion(ch.name),
                                 persist_key=ch.champion_key())
        if c.agent.learner is not None:
            is_focus = (ch.champion_key() == focus)
            c.agent.learner.rate = (focus_rate if is_focus else bg_rate) if learn else 0.0
        ctrls[ch.name] = c
    # run to a decision or a cap (6000 ticks = ~10 min sim; most end sooner)
    for _ in range(6000):
        for n, ct in ctrls.items():
            ct.decide(world, n)
        world.step({n: ct.agent.last.action for n, ct in ctrls.items()})
        if world.structures.winner:
            break
    # persist learned brains + record win/loss for the slow meta-learner
    if learn:
        for n, ct in ctrls.items():
            champ = world.by_name.get(n)
            won = (champ is not None and world.structures.winner is not None
                   and champ.team == world.structures.winner)
            ct.agent.end_match(won)   # saves brain + records win/loss meta
    return world.structures.winner


def snapshot_benchmark():
    """Freeze the current brains as the fixed benchmark to measure against."""
    if os.path.exists(BENCH_DIR):
        shutil.rmtree(BENCH_DIR)
    if os.path.exists(BRAIN_DIR):
        shutil.copytree(BRAIN_DIR, BENCH_DIR)
    else:
        os.makedirs(BENCH_DIR, exist_ok=True)


def eval_vs_benchmark(games: int = 20) -> float:
    """Win rate of the CURRENT ally brains vs the FROZEN benchmark brains.
    Allies load current brains; enemies load benchmark brains. No learning."""
    if not os.path.exists(BENCH_DIR):
        return 0.5
    wins = 0
    for _ in range(games):
        champs, ds, _, _ = scenarios.get("balanced")
        world = World(champs, dragon_spawn=ds)
        ctrls = {}
        for ch in champs:
            # enemies use benchmark brains (load from BENCH_DIR), allies current
            brain_dir = BRAIN_DIR if ch.team == "ALLY" else BENCH_DIR
            c = UtilityBotController(profile_for_champion(ch.name))
            c.agent.learn = False
            # load the right brain set
            if c.agent.learner is not None:
                c.agent.learner.rate = 0.0
                _load_from(c.agent.learner, ch.champion_key(), brain_dir)
            ctrls[ch.name] = c
        for _ in range(6000):
            for n, ct in ctrls.items():
                ct.decide(world, n)
            world.step({n: ct.agent.last.action for n, ct in ctrls.items()})
            if world.structures.winner:
                break
        if world.structures.winner == "ALLY":
            wins += 1
    return wins / games


def _load_from(learner, key, directory):
    path = os.path.join(directory, f"{key}.json")
    if os.path.exists(path):
        try:
            with open(path) as f:
                data = json.load(f)
            learner.weights.update(data.get("weights", {}))
        except Exception:
            pass


def train(cycles: int, block: int, eval_every: int):
    names = []
    for n in roster():
        key = n.rstrip("0123456789")
        if key not in names:
            names.append(key)
    print(f"[train] roster: {names}")
    print(f"[train] {cycles} cycles x {len(names)} champions x {block} matches "
          f"= {cycles*len(names)*block} training matches\n")

    snapshot_benchmark()
    report = {"curve": [], "roster": names}
    t0 = time.time()
    match_count = 0

    for cycle in range(cycles):
        for champ in names:
            for _ in range(block):
                play_match(focus=champ, focus_rate=FOCUS_RATE,
                           bg_rate=BACKGROUND_RATE)
                match_count += 1
                if match_count % eval_every == 0:
                    wr = eval_vs_benchmark(games=12)
                    elapsed = time.time() - t0
                    report["curve"].append(
                        {"match": match_count, "winrate_vs_benchmark": wr,
                         "cycle": cycle, "focus": champ})
                    print(f"  [{match_count:5d} matches | cycle {cycle} | "
                          f"focus {champ:7}] winrate vs benchmark = {wr:.2f} "
                          f"({elapsed:.0f}s)")
                    # write report incrementally so an interrupted run keeps data
                    with open(REPORT, "w") as f:
                        json.dump(report, f, indent=1)
            print(f"[cycle {cycle}] finished training {champ}")
        print(f"=== cycle {cycle} complete ===\n")

    report["total_matches"] = match_count
    report["seconds"] = round(time.time() - t0, 1)
    with open(REPORT, "w") as f:
        json.dump(report, f, indent=1)
    print(f"\n[train] done: {match_count} matches in {report['seconds']}s")
    print(f"[train] report -> {REPORT}")
    print(f"[train] trained brains -> {BRAIN_DIR}/")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cycles", type=int, default=6,
                    help="how many times to loop through all champions")
    ap.add_argument("--block", type=int, default=120,
                    help="matches focused on each champion per cycle")
    ap.add_argument("--eval-every", type=int, default=40,
                    help="run a benchmark eval every N matches")
    ap.add_argument("--quick", action="store_true",
                    help="short sanity run (2 cycles x 15 matches)")
    args = ap.parse_args()
    if args.quick:
        train(cycles=2, block=15, eval_every=10)
    else:
        train(cycles=args.cycles, block=args.block, eval_every=args.eval_every)
