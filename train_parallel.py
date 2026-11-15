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
from agent2 import watchdog
from agent2.profiles import profile_for_champion, archetype_of
from controllers.utility_bot import UtilityBotController
from model.world import World
# reuse train.py's frozen-benchmark mechanism so brains_benchmark/ and report.py
# stay consistent across both trainers (same honest absolute metric).
from train import snapshot_benchmark, BENCH_DIR

BRAIN_DIR = L._BRAIN_DIR
REPORT = os.path.join(os.path.dirname(__file__), "training_report.json")
MAX_TICKS = 3000
# games played against the frozen benchmark per eval. Kept small so --quick
# stays fast while still giving a meaningful absolute winrate.
EVAL_GAMES = 10


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
    # collect each champion's reward estimates + win/loss this match, plus
    # behavior-switch telemetry (plain ints) so the main process can detect
    # pathological looping. Everything here must stay picklable under spawn.
    out = {"winner": world.structures.winner, "rewards": {}, "loop": {}}
    for n, ct in ctrls.items():
        if ct.agent.learner is None:
            continue
        key = world.by_name[n].champion_key()
        won = world.by_name[n].team == world.structures.winner
        out["rewards"][key] = {
            "beh_reward": ct.agent.learner.reward_snapshot()["beh_reward"],
            "won": won,
        }
        tel = ct.agent.switch_telemetry()
        out["loop"][key] = {"switches": int(tel["switches"]),
                            "ticks": int(tel["ticks"])}
    return out


# ---- worker: plays ONE match CURRENT (ALLY) vs FROZEN BENCHMARK (ENEMY) ----
def _worker_eval_match(args) -> dict:
    """Headless eval match: ally champs use the current weights, enemy champs
    use the frozen benchmark weights, nobody learns. Returns plain picklable
    data only (who won), so it is spawn-safe like _worker_match."""
    current_weights, benchmark_weights, time_scale, seed = args
    import random
    random.seed(seed)
    champs, ds, _, _ = scenarios.get("balanced")
    world = World(champs, dragon_spawn=ds)
    world.dt = 0.1 * time_scale
    ctrls = {}
    for ch in champs:
        c = UtilityBotController(profile_for_champion(ch.name))
        c.agent.learn = False
        if c.agent.learner is not None:
            key = ch.champion_key()
            src = current_weights if ch.team == "ALLY" else benchmark_weights
            # fall back to the baseline profile if this key is missing (e.g. an
            # empty brains_benchmark on a fresh run).
            if key in src:
                c.agent.learner.weights.update(src[key])
            c.agent.learner.rate = 0.0   # eval only, no self-update
        ctrls[ch.name] = c
    for _ in range(MAX_TICKS):
        for n, ct in ctrls.items():
            ct.decide(world, n)
        world.step({n: ct.agent.last.action for n, ct in ctrls.items()})
        if world.structures.winner:
            break
    return {"ally_win": bool(world.structures.winner == "ALLY"),
            "winner": world.structures.winner}


def load_weights_from(directory: str) -> dict:
    """Per-champion weights loaded from a directory (baseline-merged, so a
    missing brain falls back to the champion's baseline profile). Returns a
    plain picklable dict[str, dict[str, float]]."""
    out = {}
    for key in roster_keys():
        base = profile_for_champion(key)
        w = dict(base)
        path = os.path.join(directory, f"{key}.json")
        if os.path.exists(path):
            try:
                w.update(json.load(open(path)).get("weights", {}))
            except Exception:
                pass
        out[key] = w
    return out


def load_weights() -> dict:
    """Current per-champion weights (baseline if no brain yet)."""
    return load_weights_from(BRAIN_DIR)


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


def train(generations, matches_per_gen, speed, workers, eval_every,
          *, early_stop=True, loop_switch_rate=watchdog.LOOP_SWITCHES_PER_TICK_MAX,
          plateau_window=watchdog.PLATEAU_WINDOW,
          plateau_tol=watchdog.PLATEAU_TOLERANCE):
    keys = roster_keys()
    total = generations * matches_per_gen
    print(f"[parallel] roster: {keys}")
    print(f"[parallel] using {workers} of {os.cpu_count()} cores "
          f"(1 left free for you)")
    print(f"[parallel] {generations} generations x {matches_per_gen} matches "
          f"= {total} matches, speed {speed}x\n")

    weights = load_weights()
    # Freeze the current brains as the fixed benchmark ONCE, then capture its
    # weights as a plain picklable dict so eval workers never touch the disk.
    snapshot_benchmark()
    benchmark_weights = load_weights_from(BENCH_DIR)
    eval_every = max(1, eval_every)   # guard: eval at least every generation
    report = {"curve": [], "roster": keys}
    t0 = time.time()
    done = 0

    for gen in range(generations):
        frozen = {k: dict(v) for k, v in weights.items()}   # read-only snapshot
        jobs = [(frozen, speed, gen * 1000 + i) for i in range(matches_per_gen)]
        # aggregate rewards per champion across all parallel matches, and
        # accumulate switch/tick totals per champion for the looping detector
        agg = defaultdict(lambda: defaultdict(list))
        loop_switches = defaultdict(int)
        loop_ticks = defaultdict(int)
        wins = 0
        with ProcessPoolExecutor(max_workers=workers) as ex:
            for res in ex.map(_worker_match, jobs):
                if res["winner"] == "ALLY":
                    wins += 1
                for key, r in res["rewards"].items():
                    for beh, val in r["beh_reward"].items():
                        agg[key][beh].append(val)
                # only count matches long enough to make a switch rate meaningful
                for key, tel in res.get("loop", {}).items():
                    if tel["ticks"] >= watchdog.LOOP_MIN_TICKS:
                        loop_switches[key] += tel["switches"]
                        loop_ticks[key] += tel["ticks"]
        apply_updates(weights, agg)
        save_weights(weights)
        done += matches_per_gen

        elapsed = time.time() - t0
        rate = done / elapsed
        eta = (total - done) / rate if rate > 0 else 0
        wr = wins / matches_per_gen

        # Benchmark eval: every eval_every generations and always on the final
        # generation, measure the CURRENT field vs the FROZEN benchmark. This is
        # the honest absolute improvement signal (ally_winrate alone is a
        # trained-vs-trained mirror metric that hovers near 0.5). Eval games are
        # fanned across the same worker pool. Keep ally_winrate on EVERY curve
        # point so the plateau watchdog (which reads p["ally_winrate"]) is safe.
        is_eval_gen = (gen % eval_every == 0) or (gen == generations - 1)
        if is_eval_gen:
            cur_frozen = {k: dict(v) for k, v in weights.items()}
            eval_jobs = [(cur_frozen, benchmark_weights, speed,
                          gen * 1000 + 500 + i) for i in range(EVAL_GAMES)]
            bench_wins = 0
            with ProcessPoolExecutor(max_workers=workers) as ex:
                for res in ex.map(_worker_eval_match, eval_jobs):
                    if res["ally_win"]:
                        bench_wins += 1
            wr_bench = bench_wins / EVAL_GAMES
            report["curve"].append({"gen": gen, "match": done,
                                    "winrate_vs_benchmark": wr_bench,
                                    "ally_winrate": wr})
        else:
            report["curve"].append({"gen": gen, "match": done,
                                    "ally_winrate": wr})
        json.dump(report, open(REPORT, "w"), indent=1)
        print(f"  [gen {gen:3d} | {done}/{total} matches] ally winrate={wr:.2f} "
              f"| {rate:.1f} matches/s | elapsed {_fmt(elapsed)}, ETA {_fmt(eta)}")
        if is_eval_gen:
            print(f"  [gen {gen} | eval] winrate vs benchmark = {wr_bench:.2f} "
                  f"(over {EVAL_GAMES} games)")

        # per-generation watchdog: stop the whole run if the field is looping
        # or the learning curve has plateaued. Progress so far is already saved.
        if early_stop:
            rates = {k: loop_switches[k] / max(1, loop_ticks[k])
                     for k in loop_switches}
            loop_fired, _, loop_detail = watchdog.looping_signal(
                rates, max_rate=loop_switch_rate)
            curve_vals = [p["ally_winrate"] for p in report["curve"]]
            plat_fired, plat_detail = watchdog.plateau_signal(
                curve_vals, window=plateau_window, tolerance=plateau_tol)
            if loop_fired or plat_fired:
                if loop_fired:
                    kind, detail = "behavior_looping", loop_detail
                    msg = f"stopped: behavior looping detected - {detail}"
                else:
                    kind, detail = "learning_plateau", plat_detail
                    msg = (f"stopped: learning plateaued over {plateau_window} "
                           f"generations - {detail}")
                save_weights(weights)
                report["stopped_reason"] = {"kind": kind, "detail": detail,
                                            "generation": gen}
                report["total_matches"] = done
                report["seconds"] = round(time.time() - t0, 1)
                json.dump(report, open(REPORT, "w"), indent=1)
                print(f"\n[parallel] {msg}")
                print(f"[parallel] saved brains -> {BRAIN_DIR}/  "
                      f"(run report.py to inspect)")
                return

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
    # watchdog / early-stop tunables (defaults from agent2.watchdog)
    ap.add_argument("--no-early-stop", action="store_true",
                    help="disable the behavior-looping and plateau detectors")
    ap.add_argument("--loop-switch-rate", type=float,
                    default=watchdog.LOOP_SWITCHES_PER_TICK_MAX,
                    help="mean switches/tick at or above which looping fires")
    ap.add_argument("--plateau-window", type=int,
                    default=watchdog.PLATEAU_WINDOW,
                    help="trailing curve points the plateau detector inspects")
    ap.add_argument("--plateau-tol", type=float,
                    default=watchdog.PLATEAU_TOLERANCE,
                    help="max windowed spread treated as a plateau")
    a = ap.parse_args()
    free = max(1, (os.cpu_count() or 2) - 1)
    wd = dict(early_stop=not a.no_early_stop,
              loop_switch_rate=a.loop_switch_rate,
              plateau_window=a.plateau_window,
              plateau_tol=a.plateau_tol)
    if a.quick:
        train(generations=3, matches_per_gen=8, speed=3.0,
              workers=free, eval_every=1, **wd)
    else:
        train(a.generations, a.matches_per_gen, a.speed, a.workers,
              a.eval_every, **wd)
