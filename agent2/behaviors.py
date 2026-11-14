"""
The behavior library — 50+ distinct patterns, organized into families and gated
by game phase so only a relevant subset competes each tick.

Design: each behavior is a small Capability with a `family`, the `phases` it's
relevant in, and a `propose()` that returns a scored action or None. Phase gating
(agent2/phases) + hysteresis (agent2/agent) keep 50 behaviors from thrashing —
at any instant maybe 8-12 are live.

Families:
  FARMING, TRADING, PEELING, ENGAGING, TEAMFIGHT, OBJECTIVE,
  VISION, SURVIVAL, MACRO
"""
from __future__ import annotations

from agent2.capability import Capability, Perception, Proposal
from agent2.phases import Phase
from model.world import Auto, Cast, Idle, LastHit, Move


# ---------- shared helpers ----------
def _nearest(me, group):
    return min(group, key=lambda c: (c.x - me.x) ** 2 + (c.y - me.y) ** 2,
               default=None)


def _lowest(group):
    return min(group, key=lambda c: c.hp_frac, default=None)


def _best_cc_slot(champ):
    hard = ("stun", "root", "knockup", "polymorph")
    best, dur = None, 0.0
    for slot, ab in champ.abilities.items():
        if ab.cc_type in hard and champ.ability_ready(slot):
            d = ab.cc(champ.ability_ranks.get(slot, 1))
            if d > dur:
                best, dur = slot, d
    return best


def _support_slot(champ):
    for s, ab in champ.abilities.items():
        if (ab.heal[0] > 0 or ab.shield[0] > 0) and champ.ability_ready(s):
            return s
    return None


def _dmg_slot(champ):
    for s, ab in champ.abilities.items():
        if ab.base_damage[0] > 0 and champ.ability_ready(s) \
                and ab.cc_type not in ("stun", "root", "knockup"):
            return s
    return None


def _in_range(me, tgt, rng) -> bool:
    return ((me.x - tgt.x) ** 2 + (me.y - tgt.y) ** 2) ** 0.5 <= rng


def _away(me, threat, factor=1.0):
    return Move(me.x + (me.x - threat.x) * factor,
                me.y + (me.y - threat.y) * factor)


# =========================================================================
# FARMING family (LANING)
# =========================================================================
class LastHitMinion(Capability):
    name, family, phases = "last_hit", "FARMING", (Phase.LANING,)

    def propose(self, p, w):
        me = p.me
        mm = getattr(p.world, "minions", None)
        if not mm:
            return None
        k = mm.nearest_killable(me, me.team)
        if not k:
            return None
        one_shot = k.hp <= me.stats.ad
        in_rng = p.dist(me, k) <= me.stats.attack_range
        base = 0.95 if (one_shot and in_rng) else 0.5
        return Proposal(base * self.w(w), LastHit(k.uid) if in_rng
                        else Move(k.x, k.y), self.name,
                        f"last-hit {k.kind}", target=f"minion:{k.uid}")


class PushWave(Capability):
    name, family, phases = "push_wave", "FARMING", (Phase.LANING,)

    def propose(self, p, w):
        me = p.me
        mm = getattr(p.world, "minions", None)
        if not mm:
            return None
        enemy_minions = [m for m in mm.minions if m.team != me.team and m.alive
                         and p.dist(me, m) < 1500]
        if len(enemy_minions) < 3:
            return None   # only worth shoving when a wave is present
        tgt = _nearest(me, enemy_minions)
        if p.dist(me, tgt) <= me.stats.attack_range:
            return Proposal(0.45 * self.w(w), Auto(tgt.name if hasattr(tgt, "name")
                            else tgt), self.name, "push the wave")
        return Proposal(0.4 * self.w(w), Move(tgt.x, tgt.y), self.name,
                        "move to push wave")


class FreezeWave(Capability):
    name, family, phases = "freeze_wave", "FARMING", (Phase.LANING,)

    def propose(self, p, w):
        me = p.me
        mm = getattr(p.world, "minions", None)
        if not mm:
            return None
        own = [m for m in mm.minions if m.team == me.team and m.alive
               and p.dist(me, m) < 1200]
        # freeze = hold near own minions, only last-hit; low steady pull
        if own:
            return Proposal(0.3 * self.w(w, 0.6),
                            Move(own[0].x - 100, own[0].y - 100), self.name,
                            "hold/freeze near own minions")
        return None


class CatchSideWave(Capability):
    name, family, phases = "catch_side_wave", "FARMING", (Phase.LANING,)

    def propose(self, p, w):
        me = p.me
        mm = getattr(p.world, "minions", None)
        if not mm:
            return None
        # a wave far from me and from enemies = free farm to collect
        far = [m for m in mm.minions if m.team != me.team and m.alive
               and p.dist(me, m) > 2500]
        if not far:
            return None
        tgt = _nearest(me, far)
        safe = all(p.dist(tgt, e) > 2000 for e in p.enemies())
        if not safe:
            return None
        return Proposal(0.35 * self.w(w, 0.6), Move(tgt.x, tgt.y), self.name,
                        "collect a side wave")


# =========================================================================
# TRADING family (LANING, SKIRMISH)
# =========================================================================
class PokeTrade(Capability):
    name, family, phases = "poke", "TRADING", (Phase.LANING, Phase.SKIRMISH)

    def propose(self, p, w):
        me = p.me
        if me.hp_frac < 0.45:
            return None
        slot = _dmg_slot(me)
        e = _nearest(me, p.enemies())
        if not slot or not e:
            return None
        if _in_range(me, e, me.abilities[slot].range):
            fav = me.hp_frac - e.hp_frac
            return Proposal((0.55 + 0.4 * max(0, fav)) * self.w(w),
                            Cast(slot, target=e.name), self.name,
                            f"poke {e.name}", target=e.name)
        return None


class AutoWeave(Capability):
    name, family, phases = "auto_weave", "TRADING", (Phase.LANING, Phase.SKIRMISH)

    def propose(self, p, w):
        me = p.me
        e = _nearest(me, p.enemies())
        if not e or me.hp_frac < 0.4:
            return None
        if _in_range(me, e, me.stats.attack_range) and me.can_auto():
            return Proposal(0.5 * self.w(w), Auto(e.name), self.name,
                            f"auto-weave {e.name}", target=e.name)
        return None


class AllIn(Capability):
    name, family, phases = "all_in", "TRADING", (Phase.SKIRMISH,)

    def propose(self, p, w):
        me = p.me
        e = _nearest(me, p.enemies())
        if not e:
            return None
        # commit when we're clearly healthier and they're killable soon
        if me.hp_frac > 0.6 and e.hp_frac < 0.5 and p.dist(me, e) < 1200:
            slot = _best_cc_slot(me) or _dmg_slot(me)
            if slot and _in_range(me, e, me.abilities[slot].range):
                return Proposal(1.1 * self.w(w), Cast(slot, target=e.name),
                                self.name, f"all-in {e.name}",
                                comms=f"All-in {e.name}!", target=e.name)
            return Proposal(0.9 * self.w(w), Move(e.x, e.y), self.name,
                            f"commit to {e.name}", target=e.name)
        return None


class ShortTrade(Capability):
    name, family, phases = "short_trade", "TRADING", (Phase.LANING, Phase.SKIRMISH)

    def propose(self, p, w):
        me = p.me
        e = _nearest(me, p.enemies())
        if not e or me.hp_frac < 0.5:
            return None
        # a quick auto then back out — favorable only at even/ahead hp
        if _in_range(me, e, me.stats.attack_range) and me.can_auto() \
                and me.hp_frac >= e.hp_frac:
            return Proposal(0.5 * self.w(w), Auto(e.name), self.name,
                            f"short trade {e.name}", target=e.name)
        return None


class BaitAndPunish(Capability):
    name, family, phases = "bait_punish", "TRADING", (Phase.SKIRMISH,)

    def propose(self, p, w):
        me = p.me
        e = _nearest(me, p.enemies())
        if not e:
            return None
        # if an enemy over-committed (low hp, deep) punish with CC
        if e.hp_frac < 0.4 and p.dist(me, e) < 900:
            slot = _best_cc_slot(me)
            if slot and _in_range(me, e, me.abilities[slot].range):
                return Proposal(1.0 * self.w(w), Cast(slot, target=e.name),
                                self.name, f"punish overextended {e.name}",
                                target=e.name)
        return None


# =========================================================================
# PEELING family (SKIRMISH, TEAMFIGHT)
# =========================================================================
class BodyBlock(Capability):
    name, family, phases = "body_block", "PEELING", (Phase.SKIRMISH, Phase.TEAMFIGHT)

    def propose(self, p, w):
        me = p.me
        carries = [a for a in p.allies() if a.role in ("ADC", "MID")]
        if not carries:
            return None
        carry = _lowest(carries)
        threat = _nearest(carry, p.enemies())
        if not threat or p.dist(threat, carry) > 1400:
            return None
        bx = carry.x + (threat.x - carry.x) * 0.2
        by = carry.y + (threat.y - carry.y) * 0.2
        score = (0.4 + (1 - carry.hp_frac)) * 1.2
        return Proposal(score * self.w(w), Move(bx, by), self.name,
                        f"body-block for {carry.name}", target=carry.name,
                        comms=f"Peeling for you {carry.name}!")


class CCTheDiver(Capability):
    name, family, phases = "cc_diver", "PEELING", (Phase.SKIRMISH, Phase.TEAMFIGHT)

    def propose(self, p, w):
        me = p.me
        carries = [a for a in p.allies() if a.role in ("ADC", "MID", "SUPPORT")
                   and a.name != me.name]
        if not carries:
            return None
        carry = _lowest(carries)
        threat = _nearest(carry, p.enemies())
        slot = _best_cc_slot(me)
        if not threat or not slot:
            return None
        if _in_range(me, threat, me.abilities[slot].range) \
                and p.dist(threat, carry) < 1000:
            return Proposal(1.5 * self.w(w), Cast(slot, target=threat.name),
                            self.name, f"CC diver {threat.name}",
                            comms=f"Stunning {threat.name}!", target=threat.name)
        return None


class ShieldAlly(Capability):
    name, family, phases = "shield_ally", "PEELING", (Phase.SKIRMISH, Phase.TEAMFIGHT)

    def propose(self, p, w):
        me = p.me
        slot = _support_slot(me)
        if not slot:
            return None
        hurt = [a for a in p.allies() if a.hp_frac < 0.6]
        if not hurt:
            return None
        tgt = _lowest(hurt)
        if _in_range(me, tgt, me.abilities[slot].range):
            return Proposal((0.6 + (1 - tgt.hp_frac)) * self.w(w),
                            Cast(slot, target=tgt.name), self.name,
                            f"shield {tgt.name}", target=tgt.name,
                            comms=f"Shield on you {tgt.name}!")
        return Proposal(0.5 * self.w(w), Move(tgt.x, tgt.y), self.name,
                        f"move to shield {tgt.name}", target=tgt.name)


class ZoneDiver(Capability):
    name, family, phases = "zone_diver", "PEELING", (Phase.SKIRMISH, Phase.TEAMFIGHT)

    def propose(self, p, w):
        me = p.me
        carries = [a for a in p.allies() if a.role in ("ADC", "MID")]
        if not carries:
            return None
        carry = _lowest(carries)
        threat = _nearest(carry, p.enemies())
        if not threat or p.dist(threat, carry) > 1600:
            return None
        # stand between, facing the threat, to zone it off without casting
        mx = (carry.x + threat.x) / 2
        my = (carry.y + threat.y) / 2
        return Proposal(0.7 * self.w(w), Move(mx, my), self.name,
                        f"zone {threat.name} off {carry.name}", target=carry.name)


class SelfPeelKite(Capability):
    name, family, phases = "self_peel", "PEELING", (Phase.SKIRMISH, Phase.TEAMFIGHT)

    def propose(self, p, w):
        me = p.me
        # if I'm the one being diven, kite away while attacking
        threat = _nearest(me, p.enemies())
        if not threat or p.dist(me, threat) > 900:
            return None
        if me.role in ("ADC", "MID") and me.hp_frac < 0.7:
            return Proposal(0.9 * self.w(w), _away(me, threat, 0.6), self.name,
                            "self-peel / kite the diver")
        return None


class CounterEngage(Capability):
    name, family, phases = "counter_engage", "PEELING", (Phase.TEAMFIGHT,)

    def propose(self, p, w):
        me = p.me
        slot = _best_cc_slot(me)
        if not slot:
            return None
        # enemy engaged onto us -> CC the deepest attacker
        deep = [e for e in p.enemies() if p.dist(me, e) < 1200]
        if len(deep) >= 1 and me.hp_frac > 0.4:
            tgt = _nearest(me, deep)
            if _in_range(me, tgt, me.abilities[slot].range):
                return Proposal(1.0 * self.w(w), Cast(slot, target=tgt.name),
                                self.name, f"counter-engage {tgt.name}",
                                target=tgt.name)
        return None


# =========================================================================
# ENGAGING family (SKIRMISH, TEAMFIGHT)
# =========================================================================
class DiveCarry(Capability):
    name, family, phases = "dive_carry", "ENGAGING", (Phase.SKIRMISH, Phase.TEAMFIGHT)

    def propose(self, p, w):
        me = p.me
        if me.hp_frac < 0.4:
            return None
        carries = [e for e in p.enemies() if e.role in ("ADC", "MID")] or p.enemies()
        tgt = _lowest(carries)
        if not tgt:
            return None
        slot = _best_cc_slot(me)
        rng = me.abilities[slot].range if slot else me.stats.attack_range
        if slot and _in_range(me, tgt, rng):
            return Proposal((1.0 + 0.4 * (1 - tgt.hp_frac)) * self.w(w),
                            Cast(slot, target=tgt.name), self.name,
                            f"dive {tgt.name}", comms=f"Diving {tgt.name}!",
                            target=tgt.name)
        if p.dist(me, tgt) < 4000:
            return Proposal((0.8 + 0.3 * (1 - tgt.hp_frac)) * self.w(w),
                            Move(tgt.x, tgt.y), self.name,
                            f"close on {tgt.name}", target=tgt.name)
        return None


class FlankEngage(Capability):
    name, family, phases = "flank", "ENGAGING", (Phase.TEAMFIGHT,)

    def propose(self, p, w):
        me = p.me
        enemies = p.enemies()
        if not enemies or me.hp_frac < 0.5:
            return None
        # approach the backline from the side (approximate: aim behind lowest)
        back = _lowest([e for e in enemies if e.role in ("ADC", "MID")] or enemies)
        if not back:
            return None
        fx = back.x + (back.x - me.x) * 0.2
        fy = back.y + (back.y - me.y) * 0.2
        return Proposal(0.7 * self.w(w), Move(fx, fy), self.name,
                        f"flank onto {back.name}", target=back.name)


class PickIsolated(Capability):
    name, family, phases = "pick_isolated", "ENGAGING", (Phase.SKIRMISH,)

    def propose(self, p, w):
        me = p.me
        enemies = p.enemies()
        allies = p.allies()
        for e in enemies:
            others = [o for o in enemies if o is not e]
            isolated = all(p.dist(e, o) > 2500 for o in others)
            if isolated and p.dist(me, e) < 2000 and me.hp_frac > 0.5:
                slot = _best_cc_slot(me)
                if slot and _in_range(me, e, me.abilities[slot].range):
                    return Proposal(1.2 * self.w(w), Cast(slot, target=e.name),
                                    self.name, f"pick isolated {e.name}",
                                    comms=f"Picking {e.name}!", target=e.name)
                return Proposal(0.9 * self.w(w), Move(e.x, e.y), self.name,
                                f"catch isolated {e.name}", target=e.name)
        return None


class WaitForCooldowns(Capability):
    name, family, phases = "wait_cds", "ENGAGING", (Phase.SKIRMISH, Phase.TEAMFIGHT)

    def propose(self, p, w):
        me = p.me
        # if our key ability is down, don't commit — hold a beat near allies
        if _best_cc_slot(me) is None and me.hp_frac > 0.4:
            ally = _nearest(me, p.allies())
            if ally:
                return Proposal(0.3 * self.w(w), Move(ally.x, ally.y), self.name,
                                "wait for cooldowns")
        return None


class Collapse(Capability):
    name, family, phases = "collapse", "ENGAGING", (Phase.SKIRMISH, Phase.TEAMFIGHT)

    def propose(self, p, w):
        me = p.me
        # a teammate is already fighting an enemy -> collapse to help
        for a in p.allies():
            e = _nearest(a, p.enemies())
            if e and p.dist(a, e) < 900:   # ally in a fight
                return Proposal(0.8 * self.w(w), Move(e.x, e.y), self.name,
                                f"collapse on {e.name}", target=e.name,
                                comms="Collapsing!")
        return None


# =========================================================================
# TEAMFIGHT family (TEAMFIGHT)
# =========================================================================
class FocusLowest(Capability):
    name, family, phases = "focus_lowest", "TEAMFIGHT", (Phase.TEAMFIGHT, Phase.SKIRMISH)

    def propose(self, p, w):
        me = p.me
        tgt = _lowest(p.enemies())
        if not tgt or tgt.hp_frac > 0.6:
            return None
        if _in_range(me, tgt, me.stats.attack_range):
            return Proposal((1.0 + (1 - tgt.hp_frac)) * self.w(w),
                            Auto(tgt.name), self.name,
                            f"focus {tgt.name}", target=tgt.name)
        return Proposal(0.8 * self.w(w), Move(tgt.x, tgt.y), self.name,
                        f"close on low {tgt.name}", target=tgt.name)


class FocusPriority(Capability):
    name, family, phases = "focus_priority", "TEAMFIGHT", (Phase.TEAMFIGHT,)

    def propose(self, p, w):
        me = p.me
        # priority = enemy carries (ADC/MID) even if not lowest
        carries = [e for e in p.enemies() if e.role in ("ADC", "MID")]
        if not carries:
            return None
        tgt = _nearest(me, carries)
        if _in_range(me, tgt, me.stats.attack_range):
            return Proposal(0.9 * self.w(w), Auto(tgt.name), self.name,
                            f"focus priority {tgt.name}", target=tgt.name)
        return None


class ProtectOwnCarry(Capability):
    name, family, phases = "protect_carry", "TEAMFIGHT", (Phase.TEAMFIGHT,)

    def propose(self, p, w):
        me = p.me
        carries = [a for a in p.allies() if a.role in ("ADC", "MID")]
        if not carries:
            return None
        carry = _lowest(carries)
        if carry.hp_frac < 0.7:
            return Proposal((0.8 + (1 - carry.hp_frac)) * self.w(w),
                            Move(carry.x - 150, carry.y - 150), self.name,
                            f"stay on {carry.name}", target=carry.name)
        return None


class Cleanup(Capability):
    name, family, phases = "cleanup", "TEAMFIGHT", (Phase.TEAMFIGHT, Phase.SKIRMISH)

    def propose(self, p, w):
        me = p.me
        runners = [e for e in p.enemies() if e.hp_frac < 0.25]
        if not runners:
            return None
        tgt = _nearest(me, runners)
        if p.dist(me, tgt) < 2500:
            return Proposal(1.0 * self.w(w), Move(tgt.x, tgt.y), self.name,
                            f"clean up {tgt.name}", target=tgt.name)
        return None


class RepositionFight(Capability):
    name, family, phases = "reposition", "TEAMFIGHT", (Phase.TEAMFIGHT,)

    def propose(self, p, w):
        me = p.me
        # squishy and someone's close -> drift to safer side (toward allies)
        if me.role in ("ADC", "MID", "SUPPORT"):
            threat = _nearest(me, p.enemies())
            ally = _nearest(me, [a for a in p.allies()
                                 if a.role in ("TOP", "JUNGLE")])
            if threat and p.dist(me, threat) < 1000 and ally:
                return Proposal(0.6 * self.w(w), Move(ally.x, ally.y),
                                self.name, "reposition behind frontline")
        return None


# =========================================================================
# OBJECTIVE family (OBJECTIVE)
# =========================================================================
class SecureDragon(Capability):
    name, family, phases = "secure_objective", "OBJECTIVE", (Phase.OBJECTIVE,)

    def propose(self, p, w):
        o = p.world.objective
        return Proposal(1.0 * self.w(w), Move(o.x, o.y), self.name,
                        f"secure {o.name}", comms=f"Taking {o.name}!")


class ContestObjective(Capability):
    name, family, phases = "contest_objective", "OBJECTIVE", (Phase.OBJECTIVE,)

    def propose(self, p, w):
        me = p.me
        o = p.world.objective
        enemies_near = [e for e in p.enemies() if p.dist(e, o) < 2000]
        if enemies_near and me.hp_frac > 0.5:
            tgt = _nearest(me, enemies_near)
            return Proposal(0.9 * self.w(w), Move(tgt.x, tgt.y), self.name,
                            f"contest {o.name} vs {tgt.name}", target=tgt.name)
        return None


class ZonePit(Capability):
    name, family, phases = "zone_pit", "OBJECTIVE", (Phase.OBJECTIVE,)

    def propose(self, p, w):
        me = p.me
        o = p.world.objective
        # a tank stands in the pit entrance to zone
        if me.role in ("TOP", "JUNGLE", "SUPPORT"):
            return Proposal(0.7 * self.w(w), Move(o.x - 200, o.y - 200),
                            self.name, f"zone {o.name} pit")
        return None


class BaitObjective(Capability):
    name, family, phases = "bait_objective", "OBJECTIVE", (Phase.OBJECTIVE,)

    def propose(self, p, w):
        me = p.me
        o = p.world.objective
        if me.hp_frac > 0.7 and me.role in ("TOP", "JUNGLE"):
            return Proposal(0.4 * self.w(w), Move(o.x + 200, o.y + 200),
                            self.name, f"bait at {o.name}")
        return None


# =========================================================================
# VISION family (LANING, OBJECTIVE, SKIRMISH)
# =========================================================================
class WardObjectiveArea(Capability):
    name, family = "ward_obj_area", "VISION"
    phases = (Phase.LANING, Phase.OBJECTIVE)

    def propose(self, p, w):
        me = p.me
        o = p.world.objective
        if me.role == "SUPPORT" and p.dist(me, o) < 4000:
            return Proposal(0.5 * self.w(w), Move(o.x - 400, o.y + 400),
                            self.name, f"ward near {o.name}",
                            comms="Warding the objective.")
        return None


class WardFlank(Capability):
    name, family, phases = "ward_flank", "VISION", (Phase.LANING, Phase.SKIRMISH)

    def propose(self, p, w):
        me = p.me
        if me.role == "SUPPORT" and me.hp_frac > 0.5:
            # drift to a flank point near allies to "ward" it
            ally = _nearest(me, [a for a in p.allies() if a.role in ("ADC", "MID")])
            if ally:
                return Proposal(0.3 * self.w(w, 0.6),
                                Move(ally.x + 600, ally.y - 600), self.name,
                                "ward a flank")
        return None


class DefensiveWard(Capability):
    name, family, phases = "defensive_ward", "VISION", (Phase.RETREAT, Phase.LANING)

    def propose(self, p, w):
        me = p.me
        if me.role == "SUPPORT" and me.hp_frac < 0.5:
            return Proposal(0.3 * self.w(w), Move(me.spawn_x, me.spawn_y),
                            self.name, "place a defensive ward retreating")
        return None


# =========================================================================
# SURVIVAL family (RETREAT, RESET, any)
# =========================================================================
class Flee(Capability):
    name, family, phases = "flee", "SURVIVAL", (Phase.RETREAT,)

    def propose(self, p, w):
        me = p.me
        threat = _nearest(me, p.enemies())
        if not threat:
            return None
        return Proposal(1.8 * self.w(w), _away(me, threat, 1.0), self.name,
                        "flee the fight", comms="Backing out!")


class RecallReset(Capability):
    name, family, phases = "recall", "SURVIVAL", (Phase.RESET,)

    def propose(self, p, w):
        me = p.me
        return Proposal(1.2 * self.w(w), Move(me.spawn_x, me.spawn_y),
                        self.name, "recall to reset", comms="Resetting.")


class Disengage(Capability):
    name, family, phases = "disengage", "SURVIVAL", (Phase.RETREAT, Phase.SKIRMISH)

    def propose(self, p, w):
        me = p.me
        onme = [e for e in p.enemies() if p.dist(me, e) < 1200]
        if me.hp_frac < 0.35 and onme:
            cx = sum(e.x for e in onme) / len(onme)
            cy = sum(e.y for e in onme) / len(onme)
            return Proposal((1.3 * (1 - me.hp_frac)) * self.w(w),
                            Move(me.x + (me.x - cx), me.y + (me.y - cy)),
                            self.name, "disengage — losing")
        return None


class WallHug(Capability):
    name, family, phases = "wall_hug", "SURVIVAL", (Phase.RETREAT,)

    def propose(self, p, w):
        me = p.me
        # retreat toward own base corner (uses terrain conceptually)
        if me.hp_frac < 0.4:
            return Proposal(0.9 * self.w(w, 0.8), Move(me.spawn_x, me.spawn_y),
                            self.name, "retreat along the wall")
        return None


class BaitCooldown(Capability):
    name, family, phases = "bait_cd", "SURVIVAL", (Phase.RETREAT,)

    def propose(self, p, w):
        me = p.me
        # durable champ low-ish baits a chase then turns (tank/bruiser only)
        if me.role in ("TOP", "JUNGLE") and 0.25 < me.hp_frac < 0.45:
            threat = _nearest(me, p.enemies())
            if threat and p.dist(me, threat) < 1500:
                return Proposal(0.5 * self.w(w), _away(me, threat, 0.4),
                                self.name, "bait the chase, ready to turn")
        return None


# =========================================================================
# MACRO family (LANING, any neutral)
# =========================================================================
class GroupUp(Capability):
    name, family, phases = "group", "MACRO", (Phase.LANING, Phase.SKIRMISH,
                                              Phase.OBJECTIVE)

    def propose(self, p, w):
        me = p.me
        allies = p.allies()
        enemies = p.enemies()
        if not allies or not enemies:
            return None
        na = _nearest(me, allies)
        ne = _nearest(me, enemies)
        if na and ne and p.dist(me, na) > 1800 and p.dist(me, ne) < 2800:
            return Proposal(0.7 * self.w(w), Move(na.x, na.y), self.name,
                            f"group with {na.name}", comms="Grouping up.")
        return None


class SplitPush(Capability):
    name, family, phases = "split_push", "MACRO", (Phase.LANING,)

    def propose(self, p, w):
        me = p.me
        mm = getattr(p.world, "minions", None)
        if not mm or me.role not in ("TOP", "ADC"):
            return None
        # push a sidelane wave when no enemies are near
        if all(p.dist(me, e) > 3000 for e in p.enemies()):
            wave = [m for m in mm.minions if m.team != me.team and m.alive]
            tgt = _nearest(me, wave) if wave else None
            if tgt:
                return Proposal(0.4 * self.w(w, 0.6), Move(tgt.x, tgt.y),
                                self.name, "split-push a sidelane")
        return None


class Rotate(Capability):
    name, family, phases = "rotate", "MACRO", (Phase.LANING, Phase.OBJECTIVE)

    def propose(self, p, w):
        me = p.me
        o = p.world.objective
        # rotate toward an upcoming objective when healthy and no fight local
        if p.world.objective_up() and me.hp_frac > 0.6 \
                and all(p.dist(me, e) > 2500 for e in p.enemies()):
            return Proposal(0.45 * self.w(w), Move(o.x, o.y), self.name,
                            "rotate to objective")
        return None


class HoldPosition(Capability):
    name, family, phases = "hold", "MACRO", ()   # any phase, low-priority default

    def propose(self, p, w):
        me = p.me
        allies = [a for a in p.allies() if a.role in ("ADC", "MID")] or p.allies()
        if allies:
            carry = _lowest(allies)
            return Proposal(0.2 * self.w(w), Move(carry.x - 200, carry.y - 200),
                            self.name, f"hold near {carry.name}")
        return Proposal(0.1 * self.w(w), Idle(), self.name, "hold")


class FollowCarry(Capability):
    name, family, phases = "follow_carry", "MACRO", ()

    def propose(self, p, w):
        me = p.me
        allies = [a for a in p.allies() if a.role in ("ADC", "MID")]
        if not allies:
            return Proposal(0.12 * self.w(w), Idle(), self.name, "idle")
        carry = _lowest(allies)
        return Proposal(0.22 * self.w(w), Move(carry.x - 180, carry.y - 180),
                        self.name, f"follow {carry.name}")


# =========================================================================
# EXTRA behaviors to reach 50+ distinct patterns
# =========================================================================
class DeepWard(Capability):
    name, family, phases = "deep_ward", "VISION", (Phase.LANING,)

    def propose(self, p, w):
        me = p.me
        if me.role == "SUPPORT" and me.hp_frac > 0.6 \
                and all(p.dist(me, e) > 3000 for e in p.enemies()):
            # push into enemy side to place a deep ward
            e = _nearest(me, p.enemies())
            if e:
                return Proposal(0.35 * self.w(w, 0.6), Move(e.x, e.y),
                                self.name, "place a deep ward")
        return None


class SweepVision(Capability):
    name, family, phases = "sweep_vision", "VISION", (Phase.OBJECTIVE,)

    def propose(self, p, w):
        me = p.me
        o = p.world.objective
        if me.role == "SUPPORT" and p.dist(me, o) < 2500:
            return Proposal(0.4 * self.w(w), Move(o.x + 300, o.y - 300),
                            self.name, "sweep vision around objective")
        return None


class TradeObjectiveForObjective(Capability):
    name, family, phases = "trade_objective", "OBJECTIVE", (Phase.OBJECTIVE,)

    def propose(self, p, w):
        me = p.me
        o = p.world.objective
        # if we're outnumbered at the pit, don't contest — push a lane instead
        near_e = sum(1 for e in p.enemies() if p.dist(e, o) < 2000)
        near_a = sum(1 for a in p.allies() if p.dist(a, o) < 2000) + 1
        if near_e > near_a:
            mm = getattr(p.world, "minions", None)
            wave = [m for m in mm.minions if m.team != me.team and m.alive] if mm else []
            tgt = _nearest(me, wave) if wave else None
            if tgt:
                return Proposal(0.55 * self.w(w), Move(tgt.x, tgt.y), self.name,
                                "give objective, take a lane instead")
        return None


class PeelSelfWithCC(Capability):
    name, family, phases = "self_cc_peel", "PEELING", (Phase.SKIRMISH, Phase.TEAMFIGHT)

    def propose(self, p, w):
        me = p.me
        threat = _nearest(me, p.enemies())
        slot = _best_cc_slot(me)
        if threat and slot and p.dist(me, threat) < 600 \
                and _in_range(me, threat, me.abilities[slot].range):
            return Proposal(0.95 * self.w(w), Cast(slot, target=threat.name),
                            self.name, "CC my own attacker (self-peel)",
                            target=threat.name)
        return None


class KiteBackToTower(Capability):
    name, family, phases = "kite_to_tower", "SURVIVAL", (Phase.SKIRMISH, Phase.RETREAT)

    def propose(self, p, w):
        me = p.me
        if me.hp_frac < 0.5:
            # retreat toward own base (stand-in for tower safety)
            return Proposal(0.7 * self.w(w, 0.8), Move(me.spawn_x, me.spawn_y),
                            self.name, "kite back to safety")
        return None


class PeelForLowestAlly(Capability):
    name, family, phases = "peel_lowest_ally", "TEAMFIGHT", (Phase.TEAMFIGHT,)

    def propose(self, p, w):
        me = p.me
        allies = [a for a in p.allies() if a.name != me.name and a.hp_frac < 0.5]
        if not allies:
            return None
        tgt = _lowest(allies)
        threat = _nearest(tgt, p.enemies())
        slot = _best_cc_slot(me)
        if threat and slot and _in_range(me, threat, me.abilities[slot].range):
            return Proposal(1.1 * self.w(w), Cast(slot, target=threat.name),
                            self.name, f"peel for low {tgt.name}",
                            target=threat.name)
        return None


class EngageOnCooldownAdvantage(Capability):
    name, family, phases = "engage_cd_adv", "ENGAGING", (Phase.SKIRMISH,)

    def propose(self, p, w):
        me = p.me
        # engage when the enemy's key ability likely down (approx: enemy low mana)
        e = _nearest(me, p.enemies())
        e_mana = (e.mp / e.stats.max_mp) if (e and e.stats.max_mp) else 1.0
        if e and e_mana < 0.3 and me.hp_frac > 0.5 and p.dist(me, e) < 1500:
            slot = _best_cc_slot(me)
            if slot and _in_range(me, e, me.abilities[slot].range):
                return Proposal(1.0 * self.w(w), Cast(slot, target=e.name),
                                self.name, f"engage {e.name} (cooldown advantage)",
                                target=e.name)
        return None


class ShoveAndRoam(Capability):
    name, family, phases = "shove_roam", "MACRO", (Phase.LANING,)

    def propose(self, p, w):
        me = p.me
        # mid/support: after shoving, roam toward a teammate who has an enemy near
        if me.role not in ("MID", "SUPPORT"):
            return None
        for a in p.allies():
            e = _nearest(a, p.enemies())
            if e and p.dist(a, e) < 1500 and p.dist(me, a) < 4000:
                return Proposal(0.5 * self.w(w), Move(a.x, a.y), self.name,
                                f"roam to help {a.name}", comms="Roaming to help!")
        return None


class BackOffOutnumbered(Capability):
    name, family, phases = "back_outnumbered", "SURVIVAL", (Phase.SKIRMISH,)

    def propose(self, p, w):
        me = p.me
        near_e = sum(1 for e in p.enemies() if p.dist(me, e) < 2000)
        near_a = sum(1 for a in p.allies() if p.dist(me, a) < 2000) + 1
        if near_e > near_a and me.hp_frac < 0.7:
            threat = _nearest(me, p.enemies())
            if threat:
                return Proposal(0.9 * self.w(w), _away(me, threat, 0.8),
                                self.name, "back off — outnumbered",
                                comms="Outnumbered, backing.")
        return None


class PushForObjectivePrio(Capability):
    name, family, phases = "push_for_prio", "MACRO", (Phase.LANING, Phase.OBJECTIVE)

    def propose(self, p, w):
        me = p.me
        mm = getattr(p.world, "minions", None)
        # objective about to spawn -> push the wave first for tempo
        o = p.world.objective
        if mm and 0 < o.spawns_in < 12 and me.role in ("MID", "ADC"):
            wave = [m for m in mm.minions if m.team != me.team and m.alive
                    and p.dist(me, m) < 1500]
            tgt = _nearest(me, wave) if wave else None
            if tgt:
                return Proposal(0.5 * self.w(w), Move(tgt.x, tgt.y), self.name,
                                "push wave before objective spawns")
        return None


# =========================================================================
# the full library (50+ behaviors)
# =========================================================================
FULL_REPERTOIRE = [
    # FARMING
    LastHitMinion(), PushWave(), FreezeWave(), CatchSideWave(),
    # TRADING
    PokeTrade(), AutoWeave(), AllIn(), ShortTrade(), BaitAndPunish(),
    # PEELING
    BodyBlock(), CCTheDiver(), ShieldAlly(), ZoneDiver(), SelfPeelKite(),
    CounterEngage(),
    # ENGAGING
    DiveCarry(), FlankEngage(), PickIsolated(), WaitForCooldowns(), Collapse(),
    # TEAMFIGHT
    FocusLowest(), FocusPriority(), ProtectOwnCarry(), Cleanup(),
    RepositionFight(),
    # OBJECTIVE
    SecureDragon(), ContestObjective(), ZonePit(), BaitObjective(),
    # VISION
    WardObjectiveArea(), WardFlank(), DefensiveWard(),
    # SURVIVAL
    Flee(), RecallReset(), Disengage(), WallHug(), BaitCooldown(),
    # MACRO
    GroupUp(), SplitPush(), Rotate(), HoldPosition(), FollowCarry(),
    # EXTRAS (to 50+)
    DeepWard(), SweepVision(), TradeObjectiveForObjective(), PeelSelfWithCC(),
    KiteBackToTower(), PeelForLowestAlly(), EngageOnCooldownAdvantage(),
    ShoveAndRoam(), BackOffOutnumbered(), PushForObjectivePrio(),
]
