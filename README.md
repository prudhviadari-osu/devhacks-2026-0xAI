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
