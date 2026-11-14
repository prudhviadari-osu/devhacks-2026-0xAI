# Support Bot — a League teammate that plays a *role* and talks about it

A hierarchical AI **support** for League of Legends: a slow **strategic planner**
decides the team priority, a fast **reactive controller** executes the support
mechanics, and a **comms layer** tells the human teammate what the bot is doing
and why. Built for the DevHacks '26 Riot "Gameplay bots" track.

> The value of a support isn't its mechanics score — it's whether it plays the
> right *role* at the right moment and keeps its human carry in the fight. This
> bot is built and measured around that.

## Why this, and why not a live-client bot

Riot blocked game-memory access (Oct 2026) and Vanguard blocks input injection,
so no external program can read or drive a live League champion — not as a ToS
matter, there's simply no hook. The track prompt asks instead for *"the bot, plus
a small environment where its decisions can be observed"* and a *bot → scenario →
behavior trace* demo. So:

- The bot's **body** lives in a small, League-grounded **sim** (`sources/sim.py`).
- The bot's **perception** can also come from **real League**, read-only, via the
  sanctioned Live Client Data API (`sources/live_client.py`).
- Both emit the **same `GameState`**, so the agent runs unchanged on either. That
  is the integratability story: dropping into Riot's engine is one more source
  behind the same interface.

## The playable League-accurate sim (MVC)

A real, playable top-down game — graphics are plain shapes on purpose; **fidelity
is in the numbers, not the art**. You (or the bot) play Sona; the rest are bots
or data runs.

```
model/        MODEL — the world + rules + REAL League stats
  stats.py      verified growth curve + armor/MR mitigation formulas
  abilities.py  real Q/W/E/R data (dmg, ratios, cd, cc) for the roster
  champion.py   a live champion: stats@level + abilities + hp/mana/cooldowns
  world.py      ticks movement, autos, abilities; applies real mitigation/CC
controllers/  CONTROLLER — one per champion, same decide(world) interface
  human.py      you play (keyboard/mouse)
  bot.py        the support brain (planner + triage + survival gate)
  replay.py     plays back recorded / past-game actions
view/         VIEW — pygame window: champions, HP/mana bars, ranges, CC, callouts
game.py       the loop: input -> controllers -> world.step -> render
```

**Statistical fidelity (what's exact vs. approximated):**
- Exact & public: per-level stat growth `base + growth·(L-1)·(0.7025+0.0175·(L-1))`,
  mitigation `raw·100/(100+resist)`, Data-Dragon base stats, hand-entered ability
  damage/ratios/cooldowns/CC.
- Approximated (and labeled `SIMPLIFIED`): aura/combo mechanics (Ryze stacking,
  Sona auras), pathfinding, exact leash/projectile internals Riot doesn't publish.

**Roster (v1):** Jax, Lulu, Ryze, Sona, Zac.
**Scope (v1 = a):** movement + auto-attacks + one ability + growth + mitigation.
Next (b): all four abilities per champion (data already present).

**Items & leveling (planned, additive — not a rewrite):** the stat engine already
accepts `level` + `bonus_*` stats and ability `dmg()` already takes AP/AD ratios.
So items = an `Inventory` summing Data-Dragon item stats into those bonuses; XP
= a system that grants levels/ability ranks from minions/kills. The mitigation
formula, growth curve, ability data, MVC split, and the utility bot are all
unchanged by this — it layers on top.

**Rendering:** `python3 -m view.render` runs a headless draw self-test (no window)
to confirm the draw path works before you deal with a display.

Run it (on a machine with a display):

```bash
pip install pygame
HUMAN=0 python3 game.py                       # watch the bots (default: dive scenario)
SCENARIO=teamfight HUMAN=0 python3 game.py    # a specific demo scenario
python3 game.py                               # you play the scenario's hero
```
Controls: right-click = move, left-click a champion = auto-attack, Q/W/E/R = cast.

**Demo scenarios** (`SCENARIO=...`), each showcasing a behavior family:
`dive` (peel), `farm` (last-hitting), `teamfight` (focus/protect/reposition),
`objective` (secure/contest/ward), `skirmish` (trade/engage), `retreat`
(flee/disengage/recall), `poke` (poke/kite). `HUMAN_CHAMP=Name` to play a
specific champion; `HUMAN=0` for all-bots.

## Transition to an Overwolf overlay (later)

The bot brain is fully decoupled from the sim (it only touches `GameState` /
`BotOutput`). To ship as a live-game overlay on a teammate's Windows PC: wrap
`agent.act()` in a localhost service (≈ `run_live.py`), have an Overwolf app read
the Live Client Data API and POST state to it, and draw the returned callouts as
an overlay. No brain rewrite — the live adapter (`sources/live_client.py`) already
exists. The overlay version is a macro coach (live API has no positions), while
the full reactive bot that *plays* lives in the sim.

## How it decides who to help (triage)

Every tick the bot scores each ally (and each objective) on ONE scale, and helps
the highest. No hand-ranked priority list — the situation decides.

```
time_to_die   = ally_hp / effective_damage_rate     # secs until they die
time_to_reach = distance_to_ally / my_move_speed     # secs for me to arrive
reachable     = time_to_reach < time_to_die          # can I get there in time?
threat        = low_hp x (enemies near/approaching) x urgency
reachability  = reachable ? 1/(1+distance) : ~0      # distance nudge + hard cutoff
help_score    = threat x reachability
```

- **Predictive, not reactive**: `effective_damage_rate` includes *anticipated*
  burst from an enemy closing on the ally, so the bot peels *before* the dive
  lands instead of after (a support that waits for HP to drop reacts too late).
- **Reachability cutoff**: an ally dying across the map scores ~0 because
  `time_to_reach > time_to_die`, so the bot helps someone nearby or takes the
  objective instead — the "don't run across the map and lose everyone" rule.
- **Lean support**: an endangered, reachable ally outranks aggression/objectives.

## Contribute, don't throw (the survival gate)

The user's rule: on its own the bot still plays actively, but it must not make
plays that throw its life for nothing. So after choosing an action, a **survival
gate** checks a risky commit (dive-in CC, body-block): if the bot would die for
no gain, it DOWNGRADES to the best *safe* contribution (zone an objective,
reposition) rather than either feeding OR going passive.

## Architecture

```
            ┌─────────────── one interface: GameState ───────────────┐
 sim.py ────┤                                                        │
            │   Planner (slow, LLM)   ── Priority ──▶  Controller     │
 live_ ─────┤   WHAT to prioritize                    (fast, tree)    │
 client.py  │                                          HOW to execute │
            │                               │                         │
            │                               ▼                         │
            │                        Health / circuit breaker         │
            │                               │                         │
            │                               ▼                         │
            │                        Comms (LLM) ── callout ──▶ human  │
            └──────────────────────── BotOutput ─────────────────────┘
```

- **`core/schema.py`** — `GameState` and `BotOutput`. The whole system is defined
  by these two types; everything else is swappable behind them.
- **`core/planner.py`** — slow strategic layer. Picks one `Priority`
  (PEEL_CARRY / ENGAGE / SETUP_OBJECTIVE / PLAY_SAFE / ROAM). LLM-backed, with a
  deterministic heuristic fallback that doubles as a baseline.
- **`core/controller.py`** — fast reactive layer (behavior tree). Maps
  `(priority, state) → action`. **RL swap seam** documented inline.
- **`core/comms.py`** — turns intent into a short teammate callout. LLM for
  phrasing, templates as fallback.
- **`core/health.py`** — action-entropy + outcome signal → **circuit breaker**
  that drops to a safe policy when the bot both collapses *and* is losing.
- **`core/agent.py`** — wires it together: `act(GameState) -> BotOutput`.

## Run it

```bash
# offline — no API keys, pure stdlib. Planner=heuristic, comms=templates.
python3 run_sim.py

# with an LLM planner + comms (pick one):
LLM=ollama python3 run_sim.py      # local on your Mac via Ollama
LLM=openai python3 run_sim.py      # needs OPENAI_API_KEY

# evidence: compare against simpler bots across two scenarios
python3 evaluate.py

# real League perception (be in a Practice Tool game first):
pip install -r requirements.txt
python3 run_live.py
```

## Evidence (the rubric's "credible evidence")

`evaluate.py` runs two scenarios against two baselines:

| variant                    | dive | objective | wins |
|----------------------------|------|-----------|------|
| no support (baseline)      | FAIL | FAIL      | 0/2  |
| dumb support (always peel) | PASS | FAIL      | 1/2  |
| **our agent**              | PASS | PASS      | 2/2  |

The naive "always peel" bot looks fine in the dive scenario and fails the moment
the right play changes (a free dragon). The planner-driven agent reads the board
and wins both — the role is the value, not a single behavior.

## The four things the mentor will ask (slide 12)

- **Architecture**: one `GameState`/`BotOutput` interface; slow planner over fast
  controller (hierarchical control, per mentor slide 6); comms as a separate head.
- **Tradeoffs**: behavior-tree controller over RL for 24h reliability and a
  legible trace (clean seam to swap in RL). LLM only in the slow + comms paths,
  never in fast control. Sim over live-client control because the control hook
  doesn't exist.
- **Failure modes**: LLM slow/wrong → planner validates and falls back to the
  heuristic; degenerate/thrashing play → circuit breaker → safe policy, and the
  comms layer *says* "safe mode." Live feed hides positions under fog of war (by
  design) — documented in `live_client.py`.
- **Evidence**: `evaluate.py`, two scenarios, two baselines, deterministic seeds.

## What another week would add

Learned RL controller behind the existing seam; richer sim (multiple divers,
mana, more objectives); real position data from the `eventdata` feed; A/B with a
human-in-the-loop holdout to measure *transfer* (does a human ADC play better
with the bot's comms than without).
```
