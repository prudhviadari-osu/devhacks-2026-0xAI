"""
The repertoire — concrete capabilities (broad first, support tuning later).

Each returns a Proposal with a utility score. Scores are roughly comparable in
[0,2]; role weights scale them. These all work with the CURRENT world (no
projectiles/minions): dodge and last-hit arrive when those systems do.

Capabilities implemented:
  PeelCarry        protect the most-threatened reachable ally (CC/body-block)
  EngageCC         start a fight: hard-CC the priority enemy target
  KiteAttack       attack-move: auto then reposition (ranged kiting)
  Trade            poke/trade an in-range enemy when it's favorable
  WardObjective    move to + zone the objective when it's up and safe
  Recall           retreat to base to reset when low and safe
  Disengage        get out when losing / focused and can't win
  FollowCarry      default: stay near the most valuable ally (presence)
"""
from __future__ import annotations

from agent2.capability import Capability, Perception, Proposal
from model.world import Auto, Cast, Idle, Move


# --- shared helpers ---
def _nearest(me, group):
    return min(group, key=lambda c: (c.x - me.x) ** 2 + (c.y - me.y) ** 2,
               default=None)


def _best_cc_slot(champ):
    hard = ("stun", "root", "knockup", "polymorph")
    best, dur = None, 0.0
    for slot, ab in champ.abilities.items():
        if ab.cc_type in hard and champ.ability_ready(slot):
            d = ab.cc(champ.ability_ranks.get(slot, 1))
            if d > dur:
                best, dur = slot, d
    return best


def _in_range(me, tgt, rng) -> bool:
    return ((me.x - tgt.x) ** 2 + (me.y - tgt.y) ** 2) ** 0.5 <= rng


class PeelCarry(Capability):
    name = "peel_carry"

    def propose(self, p, weights):
        me = p.me
        allies = [a for a in p.allies() if a.role in ("ADC", "MID")] or p.allies()
        if not allies:
            return None
        enemies = p.enemies()
        if not enemies:
            return None
        # most threatened reachable ally: low hp + an enemy closing on it
        best, best_threat = None, 0.0
        for a in allies:
            e = _nearest(a, enemies)
            d_ea = p.dist(e, a)
            proximity = max(0.0, 1.0 - d_ea / 3000.0)   # game units
            threat = (0.3 + (1 - a.hp_frac)) * (0.5 + proximity)
            # reachable: can I get there before it dies-ish (coarse)
            if p.dist(me, a) < 3500 and threat > best_threat:
                best, best_threat = a, threat
        if not best or best_threat < 0.4:
            return None
        threat_enemy = _nearest(best, enemies)
        cc = _best_cc_slot(me)
        if cc and _in_range(me, threat_enemy, me.abilities[cc].range):
            return Proposal(1.6 * self.w(weights) * best_threat,
                            Cast(cc, target=threat_enemy.name), self.name,
                            f"CC {threat_enemy.name} off {best.name}",
                            comms=f"Stunning {threat_enemy.name} off you!",
                            target=threat_enemy.name)
        # body-block between threat and carry
        bx = best.x + (threat_enemy.x - best.x) * 0.15
        by = best.y + (threat_enemy.y - best.y) * 0.15
        return Proposal(1.3 * self.w(weights) * best_threat, Move(bx, by),
                        self.name, f"body-block for {best.name}",
                        comms=f"Peeling for you — {best.name}, hold!",
                        target=best.name)


class EngageCC(Capability):
    """Initiate a fight. If the CC ability is in range, cast it; if not, this
    capability still proposes MOVING toward the target (so bruisers/tanks with
    short-range engage actually walk in to dive instead of wandering)."""
    name = "engage_cc"

    def propose(self, p, weights):
        me = p.me
        enemies = p.enemies()
        if not enemies or me.hp_frac < 0.4:
            return None
        cc = _best_cc_slot(me)
        if not cc:
            return None
        # pick the best dive target: prefer the lowest-hp enemy carry
        carries = [e for e in enemies if e.role in ("ADC", "MID")] or enemies
        tgt = min(carries, key=lambda e: e.hp_frac)
        advantage = len(p.allies()) + 1 - len(enemies)
        rng = me.abilities[cc].range

        if _in_range(me, tgt, rng):
            score = 1.0 + 0.3 * max(0, advantage) + 0.4 * (1 - tgt.hp_frac)
            return Proposal(score * self.w(weights, 0.8),
                            Cast(cc, target=tgt.name), self.name,
                            f"engage {tgt.name}",
                            comms=f"Engaging {tgt.name} — follow up!",
                            target=tgt.name)

        # out of range: APPROACH the target (slightly lower score than casting,
        # but high enough that an engage-weighted champ commits to the dive)
        d = p.dist(me, tgt)
        if d < 4000:  # only commit to a dive from a reasonable distance
            score = 0.8 + 0.3 * max(0, advantage) + 0.3 * (1 - tgt.hp_frac)
            return Proposal(score * self.w(weights, 0.8),
                            Move(tgt.x, tgt.y), self.name,
                            f"close in on {tgt.name} to engage",
                            comms=f"Going in on {tgt.name}.", target=tgt.name)
        return None


class KiteAttack(Capability):
    name = "kite"

    def propose(self, p, weights):
        me = p.me
        enemies = p.enemies()
        if not enemies:
            return None
        tgt = _nearest(me, enemies)
        d = p.dist(me, tgt)
        if d <= me.stats.attack_range and me.can_auto():
            return Proposal(0.7 * self.w(weights), Auto(tgt.name), self.name,
                            f"auto {tgt.name}", target=tgt.name)
        if d <= me.stats.attack_range:
            # on cooldown -> reposition away a touch (kite back)
            bx = me.x + (me.x - tgt.x) * 0.1
            by = me.y + (me.y - tgt.y) * 0.1
            return Proposal(0.5 * self.w(weights), Move(bx, by), self.name,
                            "kite back between autos")
        if d < me.stats.attack_range * 1.5:
            return Proposal(0.45 * self.w(weights), Move(tgt.x, tgt.y),
                            self.name, f"step into auto range of {tgt.name}")
        return None


class Trade(Capability):
    name = "trade"

    def propose(self, p, weights):
        me = p.me
        enemies = p.enemies()
        if not enemies or me.hp_frac < 0.5:
            return None
        # poke with a ranged damage ability if up and in range
        for slot, ab in me.abilities.items():
            if ab.base_damage[0] <= 0 or not me.ability_ready(slot):
                continue
            tgt = _nearest(me, enemies)
            if _in_range(me, tgt, ab.range) and ab.cc_type not in (
                    "stun", "root", "knockup"):   # save hard CC for peel/engage
                favorable = me.hp_frac - tgt.hp_frac   # we're healthier
                score = 0.6 + 0.4 * max(0.0, favorable)
                return Proposal(score * self.w(weights, 0.7),
                                Cast(slot, target=tgt.name), self.name,
                                f"trade {slot} on {tgt.name}", target=tgt.name)
        return None


class WardObjective(Capability):
    name = "ward_objective"

    def propose(self, p, weights):
        me = p.me
        o = p.world.objective
        if not p.world.objective_up():
            # anticipate: small pull as it's about to spawn
            if o.spawns_in > 8:
                return None
        # only valuable when nobody is in immediate danger
        enemies = p.enemies()
        danger = any((1 - a.hp_frac) > 0.4 and _nearest(a, enemies)
                     and p.dist(_nearest(a, enemies), a) < 1500
                     for a in p.allies()) if enemies else False
        if danger:
            return None
        base = 0.8 if p.world.objective_up() else 0.5
        return Proposal(base * self.w(weights), Move(o.x, o.y), self.name,
                        f"set up {o.name}",
                        comms=f"Setting up {o.name} — group with me.")


class Recall(Capability):
    name = "recall"

    def propose(self, p, weights):
        me = p.me
        enemies = p.enemies()
        near = _nearest(me, enemies) if enemies else None
        threatened = near and p.dist(me, near) < 1500
        if me.hp_frac < 0.3 and not threatened:
            # head home (toward own base corner); strong pull when low & safe
            score = 1.2 * (0.3 - me.hp_frac + 0.3)
            return Proposal(max(0.6, score) * self.w(weights),
                            Move(0.0, 0.0), self.name, "recall to reset",
                            comms="Backing to reset.")
        return None


class Disengage(Capability):
    name = "disengage"

    def propose(self, p, weights):
        me = p.me
        enemies = p.enemies()
        if not enemies:
            return None
        onme = [e for e in enemies if p.dist(me, e) < 1200]
        losing = me.hp_frac < 0.3 and len(onme) >= 1
        if not losing:
            return None
        # move away from the centroid of nearby threats
        cx = sum(e.x for e in onme) / len(onme)
        cy = sum(e.y for e in onme) / len(onme)
        bx = me.x + (me.x - cx)
        by = me.y + (me.y - cy)
        score = 1.4 * (1 - me.hp_frac)
        return Proposal(score * self.w(weights), Move(bx, by), self.name,
                        "disengage — losing this", comms="Backing off, too risky.")


class Farm(Capability):
    """Last-hit a killable enemy minion for gold. The core laning micro-decision.

    Scores higher when: a minion is about to die (good last-hit), no ally is in
    danger, and this champion is a farming role. Lower for supports (who should
    prioritize peel/ward over CS).
    """
    name = "farm"

    def propose(self, p, weights):
        me = p.me
        mm = getattr(p.world, "minions", None)
        if mm is None:
            return None
        killable = mm.nearest_killable(me, me.team)
        if not killable:
            return None
        from model.world import LastHit
        # a minion we can one-shot (hp <= our AD) is a clean last-hit -> high value
        one_shot = killable.hp <= me.stats.ad
        in_range = p.dist(me, killable) <= me.stats.attack_range
        base = 0.9 if (one_shot and in_range) else 0.5
        # don't farm if an ally is being dived (peel will outscore anyway, but
        # lower farm so it yields cleanly)
        return Proposal(base * self.w(weights, 1.0),
                        LastHit(killable.uid) if in_range
                        else Move(killable.x, killable.y),
                        self.name,
                        f"last-hit {killable.kind} (hp {killable.hp:.0f})",
                        target=f"minion:{killable.uid}")


class FollowCarry(Capability):
    """Default presence: stay near the most valuable ally. Always proposes low."""
    name = "follow_carry"

    def propose(self, p, weights):
        me = p.me
        allies = [a for a in p.allies() if a.role in ("ADC", "MID")] or p.allies()
        if not allies:
            return Proposal(0.15 * self.w(weights), Idle(), self.name, "idle")
        carry = min(allies, key=lambda a: a.hp_frac)
        return Proposal(0.25 * self.w(weights),
                        Move(carry.x - 200, carry.y - 200), self.name,
                        f"stay near {carry.name}")


# the default broad repertoire (order doesn't matter; utility decides)
DEFAULT_REPERTOIRE = [
    PeelCarry(), EngageCC(), KiteAttack(), Trade(), Farm(),
    WardObjective(), Recall(), Disengage(), FollowCarry(),
]
