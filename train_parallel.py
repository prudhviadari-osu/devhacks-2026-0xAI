"""
Parallel tournament trainer — many sims at once across CPU cores.

Why: sequential round-robin trains one match at a time on one core. This runs a
whole GENERATION of matches in parallel (one per core), which on an 8-core
machine is ~8x the throughput of train.py — the real speedup.

Design (keeps the round-robin / arms-race spirit at the generation level):

  for each generation:
    1. freeze the current brains into a read-only snapshot
    2. fan out G matches across worker processes; each worker plays a match
       from the FROZEN snapshot and returns its reward deltas (no file writes,
       so no clobbering between parallel matches)
    3. the main process AGGREGATES all workers' rewards per champion and applies
       ONE combined weight update per champion
    4. next generation faces the improved field -> the arms race continues

Because workers only READ the snapshot and RETURN data, there are zero write
conflicts — that's what makes it safe to parallelize.

Usage (on your machine):
    python3 train_parallel.py --generations 40 --matches-per-gen 24 --speed 3
    python3 train_parallel.py --quick
    python3 train_parallel.py --workers 8      # cap cores used
"""
from __future__ import annotations

import argparse
import functools
import json
import os
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor

print = functools.partial(print, flush=True)

import scenarios
from agent2 import learning as L
from agent2.learning import EWMA_ALPHA, LEARN_RATE, WEIGHT_MIN, WEIGHT_MAX, BASELINE_PULL
from agent2.profiles import profile_for_champion, archetype_of
from controllers.utility_bot import UtilityBotController
from model.world import World

BRAIN_DIR = L._BRAIN_DIR
REPORT = os.path.join(os.path.dirname(__file__), "training_report.json")
MAX_TICKS = 3000


def roster_keys():
    champs, _, _, _ = scenarios.get("balanced")
    keys = []
    for c in champs:
        k = c.champion_key()
        if k not in keys:
            keys.append(k)
    return keys


# ---- worker: runs ONE match from frozen weights, returns reward deltas ----
def _worker_match(args) -> dict:
    frozen_weights, time_scale, seed = args
    import random
    random.seed(seed)
    champs, ds, _, _ = scenarios.get("balanced")
    world = World(champs, dragon_spawn=ds)
    world.dt = 0.1 * time_scale
    ctrls = {}
    for ch in champs:
        c = UtilityBotController(profile_for_champion(ch.name))
        if c.agent.learner is not None:
            key = ch.champion_key()
            # load the FROZEN weights for this generation (read-only)
            if key in frozen_weights:
                c.agent.learner.weights.update(frozen_weights[key])
            c.agent.learner.rate = 0.0   # workers don't self-update; we aggregate
        ctrls[ch.name] = c
    for _ in range(MAX_TICKS):
        for n, ct in ctrls.items():
            ct.decide(world, n)
        world.step({n: ct.agent.last.action for n, ct in ctrls.items()})
        if world.structures.winner:
            break
    # collect each champion's reward estimates + win/loss this match
    out = {"winner": world.structures.winner, "rewards": {}}
    for n, ct in ctrls.items():
        if ct.agent.learner is None:
            continue
        key = world.by_name[n].champion_key()
        won = world.by_name[n].team == world.structures.winner
        out["rewards"][key] = {
            "beh_reward": ct.agent.learner.reward_snapshot()["beh_reward"],
            "won": won,
        }
    return out


def load_weights() -> dict:
    """Current per-champion weights (baseline if no brain yet)."""
    out = {}
    for key in roster_keys():
        base = profile_for_champion(key)
        w = dict(base)
        path = os.path.join(BRAIN_DIR, f"{key}.json")
        if os.path.exists(path):
            try:
                w.update(json.load(open(path)).get("weights", {}))
            except Exception:
                pass
        out[key] = w
    return out


def save_weights(weights: dict):
    os.makedirs(BRAIN_DIR, exist_ok=True)
    for key, w in weights.items():
        path = os.path.join(BRAIN_DIR, f"{key}.json")
        data = {}
        if os.path.exists(path):
            try:
                data = json.load(open(path))
            except Exception:
                pass
        data["weights"] = w
        json.dump(data, open(path, "w"))


def apply_updates(weights: dict, agg: dict):
    """Apply ONE combined weight update per champion from aggregated rewards."""
    for key, beh_rewards in agg.items():
        base = profile_for_champion(key)
        for beh, rewards in beh_rewards.items():
            if not rewards:
                continue
            avg_r = sum(rewards) / len(rewards)
            b = base.get(beh, 1.0)
            cur = weights[key].get(beh, b)
            target = b * (1.0 + avg_r)
            cur += LEARN_RATE * (target - cur)
            cur += BASELINE_PULL * (b - cur)
            weights[key][beh] = max(WEIGHT_MIN, min(WEIGHT_MAX, cur))


def train(generations, matches_per_gen, speed, workers, eval_every):
    keys = roster_keys()
    total = generations * matches_per_gen
    print(f"[parallel] roster: {keys}")
    print(f"[parallel] using {workers} of {os.cpu_count()} cores "
          f"(1 left free for you)")
    print(f"[parallel] {generations} generations x {matches_per_gen} matches "
          f"= {total} matches, speed {speed}x\n")

    weights = load_weights()
    report = {"curve": [], "roster": keys}
    t0 = time.time()
    done = 0

    for gen in range(generations):
        frozen = {k: dict(v) for k, v in weights.items()}   # read-only snapshot
        jobs = [(frozen, speed, gen * 1000 + i) for i in range(matches_per_gen)]
        # aggregate rewards per champion across all parallel matches
        agg = defaultdict(lambda: defaultdict(list))
        wins = 0
        with ProcessPoolExecutor(max_workers=workers) as ex:
            for res in ex.map(_worker_match, jobs):
                if res["winner"] == "ALLY":
                    wins += 1
                for key, r in res["rewards"].items():
                    for beh, val in r["beh_reward"].items():
                        agg[key][beh].append(val)
        apply_updates(weights, agg)
        save_weights(weights)
        done += matches_per_gen

        elapsed = time.time() - t0
        rate = done / elapsed
        eta = (total - done) / rate if rate > 0 else 0
        wr = wins / matches_per_gen
        report["curve"].append({"gen": gen, "match": done, "ally_winrate": wr})
        json.dump(report, open(REPORT, "w"), indent=1)
        print(f"  [gen {gen:3d} | {done}/{total} matches] ally winrate={wr:.2f} "
              f"| {rate:.1f} matches/s | elapsed {_fmt(elapsed)}, ETA {_fmt(eta)}")

    report["total_matches"] = done
    report["seconds"] = round(time.time() - t0, 1)
    json.dump(report, open(REPORT, "w"), indent=1)
    print(f"\n[parallel] done: {done} matches in {_fmt(time.time()-t0)}")
    print(f"[parallel] trained brains -> {BRAIN_DIR}/  (run report.py to inspect)")


def _fmt(s):
    s = int(s)
    return f"{s}s" if s < 90 else (f"{s//60}m {s%60}s" if s < 3600
                                   else f"{s//3600}h {(s%3600)//60}m")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--generations", type=int, default=40)
    ap.add_argument("--matches-per-gen", type=int, default=24)
    ap.add_argument("--speed", type=float, default=3.0)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1),
                    help="worker processes (default: all cores minus 1, so your "
                         "Mac stays responsive while training)")
    ap.add_argument("--eval-every", type=int, default=5)
    ap.add_argument("--quick", action="store_true")
    a = ap.parse_args()
    free = max(1, (os.cpu_count() or 2) - 1)
    if a.quick:
        train(generations=3, matches_per_gen=8, speed=3.0,
              workers=free, eval_every=1)
    else:
        train(a.generations, a.matches_per_gen, a.speed, a.workers, a.eval_every)
