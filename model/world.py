"""
World — the MODEL. Holds all champions + objective, applies actions, ticks rules.

Scope (a): movement, auto-attacks, ONE ability per champion, real armor/MR
mitigation and the growth curve. Actions are explicit dataclasses so every
controller (human / bot / replay) speaks one language. Scope (b) = allow more
ability slots in `_apply_ability`; nothing else changes.

Units: positions in GAME UNITS (Summoner's Rift ~ 15000 x 15000). Movement and
ranges use real-ish units so distances are League-meaningful, not 0..1.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from model.champion import Champion

TICK = 0.1                  # 10 Hz model update
MAP_SIZE = 15000.0
DRAGON_POS = (9866.0, 4414.0)   # approx SR dragon pit


# ---- action types every controller emits ----
@dataclass
class Move:
    x: float
    y: float


@dataclass
class Auto:
    target: str              # champion name


@dataclass
class Cast:
    slot: str                # "Q".."R"
    target: str | None = None    # champion name, or None for self/point
    x: float | None = None
    y: float | None = None


@dataclass
class LastHit:
    """Attack a specific enemy minion (for farming / last-hitting gold)."""
    minion_uid: int


@dataclass
class Idle:
    pass


Action = Move | Auto | Cast | LastHit | Idle


def dist(a: Champion, b: Champion) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


@dataclass
class Objective:
    name: str
    x: float
    y: float
    spawns_in: float
    secured_by: str | None = None   # team that has secured it


class World:
    def __init__(self, champions: list[Champion], dragon_spawn: float = 0.0):
        self.champions = champions
        self.by_name = {c.name: c for c in champions}
        # per-world time step. Default = module TICK (0.1s). Training can set a
        # bigger dt (e.g. 0.3) so the SAME game resolves in ~1/3 the steps —
        # genuine speedup since cost is proportional to step count. All timers
        # (cooldowns, movement, respawn) use self.dt so physics stays consistent.
        self.dt = TICK
        self.time = 0.0
        self.objective = Objective("DRAGON", *DRAGON_POS, spawns_in=dragon_spawn)
        self.log: list[str] = []
        # match pressure ramps 0 -> 1 over ~8 min: teams get more push-happy as
        # the game goes long, so a winner emerges instead of a permanent stalemate.
        self.match_pressure = 0.0
        # visual effects produced THIS tick, for the renderer to draw.
        # each: {"kind": "auto"|"cast"|"heal", "src": name, "dst": name,
        #        "slot": str|None, "cc": bool}
        self.fx: list[dict] = []
        # minions / lane economy
        from model.minions import MinionManager
        self.minions = MinionManager()
        # towers + nexus (map structure + win condition)
        from model.structures import StructureManager
        self.structures = StructureManager()
        # set each champion's BASE to its team's nexus corner, so respawns return
        # to the fountain (real League) regardless of where they start the match
        for c in self.champions:
            nx = self.structures.nexus(c.team)
            if nx is not None:
                c.base_x, c.base_y = nx.x, nx.y
                c.spawn_x, c.spawn_y = nx.x, nx.y

    # ---- queries controllers use ----
    def get(self, name: str) -> Champion:
        return self.by_name[name]

    def allies_of(self, team: str) -> list[Champion]:
        return [c for c in self.champions if c.team == team and c.alive]

    def enemies_of(self, team: str) -> list[Champion]:
        return [c for c in self.champions if c.team != team and c.alive]

    # ---- the tick: apply each champion's action, then advance timers ----
    def step(self, actions: dict[str, Action]) -> None:
        self.time += self.dt
        self.fx = []   # clear last tick's effects; this tick refills it
        for c in self.champions:
            c.tick(self.dt)
            if c.alive:
                c.time_alive += self.dt
                c.total_time_alive += self.dt
            self._handle_respawn(c)
        self.objective.spawns_in = max(0.0, self.objective.spawns_in - self.dt)
        self.match_pressure = min(1.0, self.time / 480.0)   # full by ~8 min
        self._update_dragon()

        for name, action in actions.items():
            champ = self.by_name.get(name)
            if champ is None or not champ.alive or champ.cc_remaining > 0:
                continue
            self._apply(champ, action)

        # soft separation so champions don't stack into a single blob
        for c in self.champions:
            if c.alive:
                self._separate(c)
            self._try_shop(c)

        # minions march/fight, towers shoot, after champions act
        self.minions.update(self, self.dt)
        self.structures.update(self, self.dt)

    def _try_shop(self, c: Champion) -> None:
        """Buy an item when at base. The item CHOICE is trainable: a per-champion
        `item_prefs` dict (set by the learner, higher = better-performing item)
        biases which affordable item is bought, so champions learn their best
        builds over matches. Falls back to archetype default when unlearned."""
        from model.items import ITEMS, item_stats_total
        from agent2.profiles import archetype_of
        at_base = (not c.alive) or \
            math.hypot(c.x - c.base_x, c.y - c.base_y) < 1500
        if not at_base:
            return
        arch = archetype_of(c.name)
        owned = {it.name for it in c.items}
        affordable = [it for it in ITEMS if it.cost <= c.gold
                      and it.name not in owned
                      and (not it.for_roles or arch in it.for_roles)]
        if not affordable:
            return
        prefs = getattr(c, "item_prefs", {}) or {}
        # score = learned preference (default 1.0) weighted by item cost (bigger
        # spike), so learning can shift the build but cost still matters
        def score(it):
            return (1.0 + prefs.get(it.name, 0.0)) * (it.cost / 1000.0)
        item = max(affordable, key=score)
        if c.buy(item):
            self.log.append(f"{c.name} bought {item.name} ({item.cost}g)")
            # tell the controller what was bought so it can credit reward to it
            self._last_purchase = getattr(self, "_last_purchase", {})
            self._last_purchase[c.name] = item.name

    def _respawn_time(self) -> float:
        """League-like scaling respawn: grows meaningfully with match time so a
        late death is a real setback (base 10s -> up to ~50s late game)."""
        return min(50.0, 10.0 + self.time * 0.08)

    ASSIST_WINDOW = 10.0   # seconds: recent damagers get assist credit on a kill

    def _award_kill(self, victim: Champion) -> None:
        """On death, credit the killer (last damager) + assists (recent damagers)."""
        recent = [(name, t) for name, t in victim.recent_damagers.items()
                  if self.time - t <= self.ASSIST_WINDOW and name in self.by_name]
        if not recent:
            return
        # killer = most recent damager
        killer_name = max(recent, key=lambda nt: nt[1])[0]
        killer = self.by_name[killer_name]
        killer.kills += 1
        killer.killstreak += 1
        streak_txt = f" (streak {killer.killstreak})" if killer.killstreak >= 2 else ""
        self.log.append(f"{killer_name} killed {victim.name}{streak_txt}")
        # assists = other recent damagers on the killer's team
        for name, _ in recent:
            if name != killer_name and self.by_name[name].team == killer.team:
                self.by_name[name].assists += 1

    def _handle_respawn(self, c: Champion) -> None:
        if c.dead:
            if c.respawn_timer <= 0.0:
                c.deaths += 1
                self._award_kill(c)                       # credit killer/assists
                c.respawn_timer = self._respawn_time()   # just died -> start timer
                self.log.append(f"{c.name} died (respawn in {c.respawn_timer:.0f}s)")
            else:
                c.respawn_timer = max(0.0, c.respawn_timer - self.dt)
                if c.respawn_timer <= 0.0:
                    c.respawn()
                    self.log.append(f"{c.name} respawned")

    def _apply(self, champ: Champion, action: Action) -> None:
        if isinstance(action, Move):
            self._move_toward(champ, action.x, action.y)
        elif isinstance(action, Auto):
            self._auto(champ, action.target)
        elif isinstance(action, Cast):
            self._cast(champ, action)
        elif isinstance(action, LastHit):
            self._last_hit(champ, action.minion_uid)
        # Idle: nothing

    def _last_hit(self, champ: Champion, uid: int) -> None:
        minion = next((m for m in self.minions.minions if m.uid == uid), None)
        if not minion or not minion.alive or not champ.can_auto():
            return
        if math.hypot(champ.x - minion.x, champ.y - minion.y) > \
                champ.stats.attack_range:
            return
        self.minions.champion_hit_minion(self, champ, minion,
                                         champ.stats.ad, "physical")
        champ.attack_cd = 1.0 / max(0.1, champ.stats.attack_speed)
        self.fx.append({"kind": "auto", "src": champ.name,
                        "dst": f"minion:{uid}", "slot": None, "cc": False})

    def _move_toward(self, champ: Champion, tx: float, ty: float) -> None:
        dx, dy = tx - champ.x, ty - champ.y
        d = math.hypot(dx, dy)
        if d < 1e-6:
            return
        step = min(champ.stats.move_speed * self.dt, d)   # real move speed / sec
        champ.x += dx / d * step
        champ.y += dy / d * step
        # keep champions on the map (defensive clamp)
        champ.x = max(0.0, min(MAP_SIZE, champ.x))
        champ.y = max(0.0, min(MAP_SIZE, champ.y))

    def _separate(self, champ: Champion) -> None:
        """Soft collision: nudge champions apart so they don't stack into one
        blob. Keeps a minimum spacing so the camera shows distinct bodies."""
        MIN_SEP = 220.0
        for other in self.champions:
            if other is champ or not other.alive:
                continue
            dx, dy = champ.x - other.x, champ.y - other.y
            d2 = dx * dx + dy * dy
            if 1e-6 < d2 < MIN_SEP * MIN_SEP:
                d = d2 ** 0.5
                push = (MIN_SEP - d) * 0.5
                champ.x += dx / d * push
                champ.y += dy / d * push
                champ.x = max(0.0, min(MAP_SIZE, champ.x))
                champ.y = max(0.0, min(MAP_SIZE, champ.y))

    def _auto(self, champ: Champion, target_name: str) -> None:
        # special: attack the nearest attackable enemy structure
        if target_name == "__struct__":
            s = self.structures.nearest_attackable_enemy_structure(champ)
            if s and champ.can_auto() and \
                    math.hypot(s.x - champ.x, s.y - champ.y) <= champ.stats.attack_range:
                self.structures.damage_structure(s, champ.stats.ad, self)
                champ.attack_cd = 1.0 / max(0.1, champ.stats.attack_speed)
            return
        target = self.by_name.get(target_name)
        if not target or not target.alive or not champ.can_auto():
            return
        if dist(champ, target) > champ.stats.attack_range:
            return
        dealt = target.take_damage(champ.stats.ad, "physical",
                                   source=champ.name, now=self.time)
        champ.record_dealt(dealt, self.time)     # track DPS dealt
        # attack cooldown = 1 / attack_speed
        champ.attack_cd = 1.0 / max(0.1, champ.stats.attack_speed)
        self.log.append(f"{champ.name} autos {target.name} for {dealt:.0f}")
        self.fx.append({"kind": "auto", "src": champ.name,
                        "dst": target.name, "slot": None, "cc": False})

    def _cast(self, champ: Champion, cast: Cast) -> None:
        ab = champ.abilities.get(cast.slot)
        if not ab or not champ.ability_ready(cast.slot):
            return
        rank = champ.ability_ranks.get(cast.slot, 1)
        target = self.by_name.get(cast.target) if cast.target else None

        # range check (point or target)
        tx = target.x if target else (cast.x if cast.x is not None else champ.x)
        ty = target.y if target else (cast.y if cast.y is not None else champ.y)
        if math.hypot(tx - champ.x, ty - champ.y) > ab.range:
            return

        champ.cooldowns[cast.slot] = ab.cd(rank)
        did_cc = False

        # damage — now scaled by the caster's AP and bonus AD from items
        dmg = ab.dmg(rank, ap=champ.stats.ap, ad=champ.stats.ad)
        if dmg > 0 and target and target.team != champ.team:
            dealt = target.take_damage(dmg, ab.damage_type,
                                       source=champ.name, now=self.time)
            champ.record_dealt(dealt, self.time)     # track DPS dealt
            self.log.append(
                f"{champ.name} {ab.slot} ({ab.name}) hits {target.name} "
                f"for {dealt:.0f} {ab.damage_type}")

        # crowd control
        if ab.cc_type and target and target.team != champ.team:
            target.cc_remaining = max(target.cc_remaining, ab.cc(rank))
            did_cc = True
            self.log.append(
                f"{champ.name} {ab.slot} {ab.cc_type}s {target.name} "
                f"for {ab.cc(rank):.2f}s")

        # heal / shield to an ally (or self)
        heal_amt = ab.heal[min(rank - 1, len(ab.heal) - 1)]
        if heal_amt > 0:
            ally = target if (target and target.team == champ.team) else champ
            ally.heal(heal_amt)
            self.log.append(f"{champ.name} {ab.slot} heals {ally.name} {heal_amt:.0f}")
            self.fx.append({"kind": "heal", "src": champ.name,
                            "dst": ally.name, "slot": cast.slot, "cc": False})

        if target:
            self.fx.append({"kind": "cast", "src": champ.name, "dst": target.name,
                            "slot": cast.slot, "cc": did_cc})

    def _update_dragon(self) -> None:
        """Dragon = a real objective: a team that holds the pit uncontested
        'slays' it, gains a permanent team stat buff (AD+AP), and it respawns on
        a timer. This gives the objective an actual payoff like League."""
        o = self.objective
        if not self.objective_up():
            return
        near = {"ALLY": 0, "ENEMY": 0}
        for c in self.champions:
            if c.alive and math.hypot(c.x - o.x, c.y - o.y) < 1400:
                near[c.team] += 1
        # only one team present and nobody contesting -> channel the kill
        holder = None
        if near["ALLY"] > 0 and near["ENEMY"] == 0:
            holder = "ALLY"
        elif near["ENEMY"] > 0 and near["ALLY"] == 0:
            holder = "ENEMY"
        if holder:
            self._dragon_channel = getattr(self, "_dragon_channel", 0.0) + self.dt
            if self._dragon_channel >= 3.0:           # ~3s uncontested = slain
                self._slay_dragon(holder)
        else:
            self._dragon_channel = 0.0

    def _slay_dragon(self, team: str) -> None:
        stacks = getattr(self, f"_dragon_stacks_{team}", 0) + 1
        setattr(self, f"_dragon_stacks_{team}", stacks)
        # permanent team buff: each dragon adds AD + AP to that team
        for c in self.champions:
            if c.team == team:
                c.dragon_ad = getattr(c, "dragon_ad", 0.0) + 8.0
                c.dragon_ap = getattr(c, "dragon_ap", 0.0) + 10.0
                c.apply_dragon_buff()
        self.log.append(f"{team} slew the DRAGON (team buff x{stacks})")
        self.objective.secured_by = team
        self.objective.spawns_in = 90.0               # respawns in 90s
        self._dragon_channel = 0.0

    # ---- objective ----
    def objective_up(self) -> bool:
        return self.objective.spawns_in <= 0.0
