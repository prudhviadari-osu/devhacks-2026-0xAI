# 0xAI — a League-accurate 5v5 sim where the bots *learn*

Ten champions play a top-down 5v5 in a League-grounded simulation. Each champion
runs the same utility-AI brain but a different archetype profile, and every brain
**adapts its own behavior over many matches** via online learning — so a support
learns to shield and peel, a marksman learns to focus and space, a tank learns to
engage with CC, all from reward, not hand-scripting. Built for the DevHacks '26
Riot "Gameplay bots" track.

> The deliverable the track asks for is "the bot, plus a small environment where
> its decisions can be observed." This is that: a real sim, a legible per-tick
> decision for every champion, and a learning loop you can watch move the weights.

Graphics are deliberately plain shapes in a browser canvas — **the fidelity is in
the numbers and the behavior, not the art.**

---

## Quick start (the demo)

Two terminals, no install, stdlib only:

```bash
python3 state_server.py                 # terminal 1: runs the sim + AI, serves state
cd web && python3 -m http.server 8000   # terminal 2: serves the browser renderer
```

Open **http://localhost:8000** and hard-refresh (⌘⇧R). Use the scenario dropdown
to switch matchups and the camera button to frame the action.

Inspect what the bots have learned:

```bash
python3 report.py
```

Prints the training curve (winrate vs a frozen benchmark) and, per champion, the
behavior weights that drifted most from the starting profile plus the favorite item.

---

## How a champion decides (utility AI)

Every tick, each champion's brain runs the same loop:

1. **Perceive** the world (allies, enemies, objective, structures, threats).
2. **Detect a phase** (laning / skirmish / teamfight / objective / defend / …),
   with hysteresis so the phase doesn't flicker frame to frame.
3. Every **behavior relevant to that phase** proposes an action with a score
   (`utility × its learned weight`).
4. A **hysteresis state machine** picks the winner — a dwell window, a switch
   margin, and an emergency override stop the champion from thrashing between
   behaviors (the old "state loop" bug).

No fixed priority list. The situation and the learned weights decide.

### The 29 behaviors (`agent2/behaviors.py`)

Each is a `Capability` that proposes an action when it's relevant. Grouped by intent:

| Group | Behaviors |
|---|---|
| **Farm / push** | `LastHit`, `PushWave`, `SiegeStructure` |
| **Poke / trade** | `Poke`, `AutoTrade`, `FocusTarget` |
| **Engage / dive** | `DiveCarry`, `PickIsolated`, `Collapse`, `AllIn`, `CCTheDiver` |
| **Protect / support** | `ShieldAlly`, `BodyBlock`, `ProtectCarry`, `SelfPeel` |
| **Reposition / survive** | `Spacing`, `Reposition`, `Flee`, `Disengage`, `Recall` |
| **Objective** | `SecureObjective`, `ContestObjective`, `TradeObjective` |
| **Map / tempo** | `Group`, `Roam`, `Ward`, `Advance`, `Hold` |
| **Structures** | `DefendStructure` (threat-scaled — one of the highest priorities) |

`Spacing` is the self-preservation behavior: survival is earned through **evasive
movement (juke = move-away + strafe)**, not by retreating out of the fight.

---

## How a champion learns (online weight adaptation)

Each behavior carries a weight. After acting, the brain estimates a reward and
nudges that behavior's weight toward what earned reward — Option A **online weight
adaptation**, chosen over genetic search or deep RL for 24-hour reliability and a
legible trace.

**Reward signal** (`agent2/learning.py`) — what the bots are rewarded for:

| Weight | Rewards |
|---|---|
| `W_KILL` 1.0 / `W_STREAK` 0.4 | securing kills, snowballing a streak |
| `W_ASSIST` 0.7 | assisting (teamplay) |
| `W_SUPPORT` 1.1 / `W_PROTECT` 0.9 | nearby allies staying alive because of you |
| `W_OBJECTIVE` 0.9 / `W_TOWER` 0.6 | dragon secured, structure damage |
| `W_SURVIVE` 0.45 / `W_TIME` 0.1 | staying healthy (earned via evasion) |
| `W_DEATH` 0.8 | penalty for dying |

Mechanics: `LEARN_RATE 0.06` (how fast weights move), `BASELINE_PULL 0.01` (gentle
decay back toward the archetype so weights can't run away), `EWMA_ALPHA 0.2`
(smoothing on reward estimates).

**Two timescales:**
- **Fast** — per-behavior weights adapt within and across matches (`learning.py`).
- **Slow** — a win/loss meta-record drifts the baseline only when a result happens
  *consistently*, so a single loss doesn't jerk the whole brain (`meta_learning.py`).

**Items are learned too** — each champion credits the items that correlated with
reward and prefers them next time.

Everything persists to `brains/<Champion>.json` (and `.meta.json`), so learning
carries across runs.

---

## The roster (10 champions, 5 archetypes)

Same brain, different starting profile (`agent2/profiles.py`):

| Archetype | Champions | Plays like |
|---|---|---|
| **Enchanter** | Sona, Lulu | protect / peel / shield, stay back |
| **Mage** | Ryze, Lux, Ahri | poke / burst from range, scale |
| **Marksman** | Ashe | farm, kite-auto, focus; never initiate |
| **Bruiser** | Jax, Darius | dive the carry, catch picks, commit |
| **Tank** | Zac, Leona | engage with the body, peel with CC, frontline |

Mirror matchups work (`Jax2` keys to `Jax`'s brain). What a recent run actually
learned, straight from `report.py`:

- **Sona / Lulu** → leaned hardest into `shield_ally` + `cc_diver` + `spacing`
- **Ashe** → `focus_target` + `spacing` (stay safe, lock a target)
- **Ahri / Lux / Ryze** → `spacing` + `focus_target` (kite and burst)
- **Leona / Zac** → `cc_diver` + `defend` + `collapse` (engage and frontline)
- **Jax / Darius** → `defend` + `dive_carry` + `disengage`

The behavior each archetype converged on matches its role — learned, not scripted.

---

## The world (`model/`) — real League numbers

| File | What it models |
|---|---|
| `stats.py` | per-level growth `base + growth·(L−1)·(0.7025+0.0175·(L−1))`; mitigation `raw·100/(100+resist)` |
| `champion.py` | a live champion: stats@level, abilities, hp/mana/cooldowns, gold, items, KDA, killstreak, DPS trade-balance |
| `abilities.py` | real Q/W/E/R data (damage, ratios, cooldown, CC) |
| `world.py` | ticks movement, autos, abilities; applies mitigation and CC; per-instance `dt` (lets training fast-forward the clock) |
| `items.py` | shop + item stats (AD/AP/resist), dragon buff |
| `minions.py` | lane minion waves |
| `structures.py` | towers + nexus, win condition (expose the nexus when a lane breaks) |

Exact & public: growth curve, mitigation, Data-Dragon base stats, hand-entered
ability data. Approximated (labeled `SIMPLIFIED`): aura/combo stacking,
pathfinding, projectile internals Riot doesn't publish.

---

## Training

Two trainers, both stdlib-only. Learned brains persist to `brains/`.

```bash
# parallel tournament trainer (fast — one match per CPU core, leaves 1 core free)
python3 train_parallel.py --generations 40 --matches-per-gen 24 --speed 3
python3 train_parallel.py --quick            # short smoke run

# sequential round-robin co-evolution (has the frozen-benchmark eval)
python3 train.py --cycles 10 --speed 3
```

- **Co-evolution / arms race** — each generation trains against the improved
  field, so bots learn to counter and protect as the others get better.
- **Frozen-benchmark eval** — brains are snapshotted at the start of a run; the
  trainer periodically plays current-vs-benchmark and logs a real
  `winrate_vs_benchmark` curve (the honest "are they improving" signal). Both
  trainers emit this; `report.py` reads it.
- **Speed scaling** (`--speed`) — fast-forwards the sim clock via a bigger `dt`,
  so the same game trains in ~1/N the steps. 3× is the sweet spot, 4× the ceiling.
- **Early-stop watchdog** (`agent2/watchdog.py`, on by default, `--no-early-stop`
  to disable) — halts a run if it detects pathological behavior looping or a
  learning plateau, so you don't burn cores on a stuck run.

Then `python3 report.py` to see the curve and the per-champion learned behavior.

---

## Scenarios

Switch matchups from the web dropdown or via `SCENARIO=` for the server. Each
showcases a behavior family:

`balanced` (full 5v5) · `dive` (peel) · `farm` (last-hitting) · `teamfight`
(focus/protect/reposition) · `objective` (secure/contest) · `skirmish`
(trade/engage) · `retreat` (flee/disengage) · `poke` (poke/kite)

---

## The web renderer (`web/`)

A browser canvas (`index.html` + `renderer.js`, no build step) that polls the
state server each tick and draws:

- champions as team-tinted tokens with HP bars, attack-range rings, per-champion
  particle trails/bursts, and a scale-up pulse timed to attack speed
- minions, towers, nexus (glowing/pulsing), the dragon objective, and projectile
  trails for ranged attacks
- a **broadcast-style HUD**: game timer, per-team KDA / gold / dragons / nexus
  bars, a victory banner
- a side panel showing each champion's **current AI behavior** and what it has
  learned, plus a live combat feed
- a dynamic camera that frames the largest champion cluster, scaling with zoom

`state_server.py` runs the sim and serves world state as JSON over HTTP, so the
renderer is a dumb display — **zero game logic leaves Python.** Any renderer
(web, and historically Unity) could poll the same `/state` endpoint.

---

## Architecture at a glance

```
  model/        the world + rules + real League stats (the body)
  agent2/       the brain: behaviors, phases, hysteresis, learning, watchdog
  controllers/  base + utility_bot (wires a brain to a champion)
  scenarios.py  the matchups
  state_server.py  runs the sim, serves JSON state (renderer-agnostic)
  web/          the browser renderer
  train*.py     the two training harnesses
  report.py     reads training_report.json + brains/ and prints the results
```

**Design choices & tradeoffs:**
- **Utility AI over a behavior tree or RL** for a legible per-tick trace and
  24-hour reliability; online weight adaptation gives learning without the
  instability of deep RL.
- **Sim over live-client control** — Riot blocked game-memory access (Oct 2026)
  and Vanguard blocks input injection, so no external program can drive a live
  champion. The sim is exactly what the track prompt asks for, and the brain is
  decoupled from it (it only touches world state + actions), so it could run on
  another environment behind the same interface.
- **Mirror self-play + frozen-benchmark eval** so improvement is measured
  honestly, not just as co-adaptation noise.

---

## What another week would add

A learned-RL controller behind the existing utility seam; richer item builds
(matches currently end before much gold banks); more objectives; and an A/B
holdout to measure whether the learned brains transfer to unseen matchups.
