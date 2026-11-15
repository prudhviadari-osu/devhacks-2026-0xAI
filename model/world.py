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
        self.time = 0.0
        self.objective = Objective("DRAGON", *DRAGON_POS, spawns_in=dragon_spawn)
        self.log: list[str] = []
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

    # ---- queries controllers use ----
    def get(self, name: str) -> Champion:
        return self.by_name[name]

    def allies_of(self, team: str) -> list[Champion]:
        return [c for c in self.champions if c.team == team and c.alive]

    def enemies_of(self, team: str) -> list[Champion]:
        return [c for c in self.champions if c.team != team and c.alive]

    # ---- the tick: apply each champion's action, then advance timers ----
    def step(self, actions: dict[str, Action]) -> None:
        self.time += TICK
        self.fx = []   # clear last tick's effects; this tick refills it
        for c in self.champions:
            c.tick(TICK)
            if c.alive:
                c.time_alive += TICK
                c.total_time_alive += TICK
            self._handle_respawn(c)
        self.objective.spawns_in = max(0.0, self.objective.spawns_in - TICK)

        for name, action in actions.items():
            champ = self.by_name.get(name)
            if champ is None or not champ.alive or champ.cc_remaining > 0:
                continue
            self._apply(champ, action)

        # minions march/fight, towers shoot, after champions act
        self.minions.update(self, TICK)
        self.structures.update(self, TICK)

    def _respawn_time(self) -> float:
        """League-like scaling respawn: longer as the game goes on."""
        # simple, readable curve: ~8s early, growing with match time
        return min(45.0, 6.0 + self.time * 0.02)

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
                c.respawn_timer = max(0.0, c.respawn_timer - TICK)
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
        step = min(champ.stats.move_speed * TICK, d)   # real move speed / sec
        champ.x += dx / d * step
        champ.y += dy / d * step
        # keep champions on the map (defensive clamp)
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

        # damage
        dmg = ab.dmg(rank)  # (AP/AD ratios wire in with items; 0 bonus for v1)
        if dmg > 0 and target and target.team != champ.team:
            dealt = target.take_damage(dmg, ab.damage_type,
                                       source=champ.name, now=self.time)
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

    # ---- objective ----
    def objective_up(self) -> bool:
        return self.objective.spawns_in <= 0.0
