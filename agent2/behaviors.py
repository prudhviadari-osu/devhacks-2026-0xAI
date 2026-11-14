"""
The behavior library — a tight set of GENUINELY DISTINCT behaviors.

Consolidated from an earlier padded 52: every behavior here emits a visibly
different action or targets something different, so "what does this one do?" has
a clear answer. Phase-gated (agent2/phases) + hysteresis (agent2/agent) keep the
set stable.

Each behavior documents how it DIFFERS from its neighbors (the uniqueness note),
so the distinctions are auditable, not just asserted.

Families: FARMING, TRADING, PEELING, ENGAGING, TEAMFIGHT, OBJECTIVE, VISION,
SURVIVAL, MACRO. ~24 behaviors total.
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


def _enemy_carries(p):
    return [e for e in p.enemies() if e.role in ("ADC", "MID")] or p.enemies()


def _ally_carries(p, exclude=None):
    cs = [a for a in p.allies() if a.role in ("ADC", "MID") and a.name != exclude]
    return cs or [a for a in p.allies() if a.name != exclude]


# =========================================================================
# FARMING
# =========================================================================
class LastHit(Capability):  # noqa: F811  (distinct from the action class name)
    """Last-hit a minion for GOLD. Unique: the only behavior that targets a
    minion to gain economy; emits LastHit, not Move/Auto on a champion."""
    name, family, phases = "last_hit", "FARMING", (Phase.LANING,)

    def propose(self, p, w):
        me = p.me
        mm = getattr(p.world, "minions", None)
        if not mm:
            return None
        k = mm.nearest_killable(me, me.team)
        if not k:
            return None
        from model.world import LastHit as LastHitAction
        one_shot = k.hp <= me.stats.ad
        in_rng = p.dist(me, k) <= me.stats.attack_range
        base = 0.95 if (one_shot and in_rng) else 0.5
        return Proposal(base * self.w(w),
                        LastHitAction(k.uid) if in_rng else Move(k.x, k.y),
                        self.name, f"last-hit {k.kind} (+{k.gold}g)",
                        target=f"minion:{k.uid}")


class PushWave(Capability):
    """Shove the enemy wave for TEMPO/splitpush. Unique vs last_hit: hits ANY
    enemy minion (not just killable), to clear the wave fast rather than for
    gold efficiency. Only when no fight is nearby."""
    name, family, phases = "push_wave", "FARMING", (Phase.LANING,)

    def propose(self, p, w):
        me = p.me
        mm = getattr(p.world, "minions", None)
        if not mm:
            return None
        if any(p.dist(me, e) < 1500 for e in p.enemies()):
            return None   # don't shove with enemies on top of you
        wave = [m for m in mm.minions if m.team != me.team and m.alive
                and p.dist(me, m) < 1500]
        if len(wave) < 3:
            return None
        tgt = _nearest(me, wave)
        return Proposal(0.45 * self.w(w), Move(tgt.x, tgt.y), self.name,
                        "shove the wave for tempo")


# =========================================================================
# TRADING
# =========================================================================
class Poke(Capability):
    """Harass with a damage ABILITY from range. Unique: uses a spell (not autos),
    at ability range, when healthy — the long-range nick."""
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
            return Proposal((0.9 + 0.4 * max(0, fav)) * self.w(w),
                            Cast(slot, target=e.name), self.name,
                            f"poke {e.name}", target=e.name)
        # a mage out of poke range steps in to get it (keeps poke relevant)
        if p.dist(me, e) < me.abilities[slot].range * 1.6:
            return Proposal(0.6 * self.w(w), Move(e.x, e.y), self.name,
                            f"step in to poke {e.name}", target=e.name)
        return None


class AutoTrade(Capability):
    """Harass with AUTO-ATTACKS. Unique vs poke: no ability, just auto range,
    only when even-or-ahead on hp (a short favorable trade)."""
    name, family, phases = "auto_trade", "TRADING", (Phase.LANING, Phase.SKIRMISH)

    def propose(self, p, w):
        me = p.me
        e = _nearest(me, p.enemies())
        if not e or me.hp_frac < e.hp_frac or me.hp_frac < 0.4:
            return None
        if _in_range(me, e, me.stats.attack_range) and me.can_auto():
            return Proposal(0.5 * self.w(w), Auto(e.name), self.name,
                            f"auto-trade {e.name}", target=e.name)
        return None


# =========================================================================
# PEELING  (protecting an ALLY being attacked)
# =========================================================================
class CCTheDiver(Capability):
    """Hard-CC the enemy attacking my carry. Unique: casts a STUN/ROOT on the
    threat (not on self, not a shield) — the active lockdown peel."""
    name, family, phases = "cc_diver", "PEELING", (Phase.SKIRMISH, Phase.TEAMFIGHT)

    def propose(self, p, w):
        me = p.me
        carries = _ally_carries(p, exclude=me.name)
        if not carries:
            return None
        carry = _lowest(carries)
        threat = _nearest(carry, p.enemies())
        slot = _best_cc_slot(me)
        # looser trigger: a diver within 1600 of the carry is worth CCing, and if
        # the diver isn't in range yet, move toward it (so this fires more often)
        if not threat or not slot or p.dist(threat, carry) > 1600:
            return None
        if _in_range(me, threat, me.abilities[slot].range):
            # strong signature peel — should reliably beat a plain body_block
            return Proposal(1.9 * self.w(w), Cast(slot, target=threat.name),
                            self.name, f"CC diver {threat.name}",
                            comms=f"Stunning {threat.name} off you!",
                            target=threat.name)
        # not in CC range yet -> close the gap to land it
        return Proposal(1.2 * self.w(w), Move(threat.x, threat.y), self.name,
                        f"move to CC {threat.name}", target=threat.name)


class ShieldAlly(Capability):
    """Heal/shield the most-hurt ally. Unique: the only behavior that uses a
    HEAL/SHIELD ability on a friendly target (enchanter signature)."""
    name, family, phases = "shield_ally", "PEELING", (Phase.SKIRMISH, Phase.TEAMFIGHT)

    def propose(self, p, w):
        me = p.me
        slot = _support_slot(me)
        if not slot:
            return None
        # shield proactively (under 80%, not just when badly hurt) so the
        # enchanter signature actually fires in fights
        hurt = [a for a in p.allies() if a.hp_frac < 0.8]
        if not hurt:
            return None
        tgt = _lowest(hurt)
        if _in_range(me, tgt, me.abilities[slot].range):
            return Proposal((1.1 + (1 - tgt.hp_frac)) * self.w(w),
                            Cast(slot, target=tgt.name), self.name,
                            f"shield {tgt.name}", comms=f"Shield on you {tgt.name}!",
                            target=tgt.name)
        return Proposal(0.6 * self.w(w), Move(tgt.x, tgt.y), self.name,
                        f"move to shield {tgt.name}", target=tgt.name)


class BodyBlock(Capability):
    """Physically stand BETWEEN the diver and my carry. Unique: a Move to the
    midpoint (no cast) — soaks damage with position, works even on cooldown."""
    name, family, phases = "body_block", "PEELING", (Phase.SKIRMISH, Phase.TEAMFIGHT)

    def propose(self, p, w):
        me = p.me
        carries = _ally_carries(p, exclude=me.name)
        if not carries:
            return None
        carry = _lowest(carries)
        threat = _nearest(carry, p.enemies())
        if not threat or p.dist(threat, carry) > 1400:
            return None
        bx = carry.x + (threat.x - carry.x) * 0.25
        by = carry.y + (threat.y - carry.y) * 0.25
        # body_block is the FALLBACK peel (when you can't CC); score it below
        # cc_diver so a champ with CC up stuns instead of just walking in the way
        return Proposal((0.4 + 0.6 * (1 - carry.hp_frac)) * self.w(w),
                        Move(bx, by), self.name,
                        f"body-block for {carry.name}", target=carry.name,
                        comms=f"Blocking for you {carry.name}!")


class SelfPeel(Capability):
    """React when *I* am the one being dived: CC the attacker if I have it,
    else kite away. Unique: about MY survival as the target, not an ally's."""
    name, family, phases = "self_peel", "PEELING", (Phase.SKIRMISH, Phase.TEAMFIGHT)

    def propose(self, p, w):
        me = p.me
        threat = _nearest(me, p.enemies())
        if not threat or p.dist(me, threat) > 800:
            return None
        slot = _best_cc_slot(me)
        if slot and _in_range(me, threat, me.abilities[slot].range):
            return Proposal(1.0 * self.w(w), Cast(slot, target=threat.name),
                            self.name, "CC my own attacker", target=threat.name)
        # kite directly away
        return Proposal(0.85 * self.w(w),
                        Move(me.x + (me.x - threat.x) * 0.6,
                             me.y + (me.y - threat.y) * 0.6),
                        self.name, "kite off my attacker")


# =========================================================================
# ENGAGING  (starting a fight)
# =========================================================================
class DiveCarry(Capability):
    """Go for the enemy CARRY specifically. Unique: always targets ADC/MID
    (the backline), approaching then CCing — the assassination intent."""
    name, family, phases = "dive_carry", "ENGAGING", (Phase.SKIRMISH, Phase.TEAMFIGHT)

    def propose(self, p, w):
        me = p.me
        if me.hp_frac < 0.4:
            return None
        tgt = _lowest(_enemy_carries(p))
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


class PickIsolated(Capability):
    """Catch an enemy who is ALONE (far from teammates). Unique: target chosen
    by isolation, not by hp or role — the roam/catch intent."""
    name, family, phases = "pick_isolated", "ENGAGING", (Phase.SKIRMISH, Phase.LANING)

    def propose(self, p, w):
        me = p.me
        if me.hp_frac < 0.5:
            return None
        for e in p.enemies():
            others = [o for o in p.enemies() if o is not e]
            if others and all(p.dist(e, o) > 2500 for o in others) \
                    and p.dist(me, e) < 2200:
                slot = _best_cc_slot(me)
                if slot and _in_range(me, e, me.abilities[slot].range):
                    return Proposal(1.2 * self.w(w), Cast(slot, target=e.name),
                                    self.name, f"pick isolated {e.name}",
                                    comms=f"Picking {e.name}!", target=e.name)
                return Proposal(0.9 * self.w(w), Move(e.x, e.y), self.name,
                                f"catch isolated {e.name}", target=e.name)
        return None


class Collapse(Capability):
    """Join a fight a TEAMMATE already started. Unique: target is wherever an
    ally is already fighting — the follow-up intent, not initiating myself."""
    name, family, phases = "collapse", "ENGAGING", (Phase.SKIRMISH, Phase.TEAMFIGHT)

    def propose(self, p, w):
        me = p.me
        for a in p.allies():
            e = _nearest(a, p.enemies())
            if e and p.dist(a, e) < 900 and p.dist(me, e) < 3000:
                return Proposal(0.8 * self.w(w), Move(e.x, e.y), self.name,
                                f"collapse on {e.name}", comms="Collapsing!",
                                target=e.name)
        return None


class AllIn(Capability):
    """Full commit on a favorable kill: healthy me vs. a low, close enemy.
    Unique: a high-threshold GO signal — only when the math clearly wins."""
    name, family, phases = "all_in", "ENGAGING", (Phase.SKIRMISH,)

    def propose(self, p, w):
        me = p.me
        e = _nearest(me, p.enemies())
        if not e or me.hp_frac < 0.6 or e.hp_frac > 0.5 or p.dist(me, e) > 1200:
            return None
        slot = _best_cc_slot(me) or _dmg_slot(me)
        if slot and _in_range(me, e, me.abilities[slot].range):
            return Proposal(1.1 * self.w(w), Cast(slot, target=e.name),
                            self.name, f"all-in {e.name}",
                            comms=f"All-in {e.name}!", target=e.name)
        return Proposal(0.9 * self.w(w), Move(e.x, e.y), self.name,
                        f"commit to {e.name}", target=e.name)


# =========================================================================
# TEAMFIGHT  (behavior inside a big fight)
# =========================================================================
class FocusTarget(Capability):
    """Auto the best kill target: lowest-hp enemy, tie-broken toward carries.
    Unique: pure damage output on the optimal target (merges lowest+priority)."""
    name, family, phases = "focus_target", "TEAMFIGHT", (Phase.TEAMFIGHT, Phase.SKIRMISH)

    def propose(self, p, w):
        me = p.me
        enemies = p.enemies()
        if not enemies:
            return None
        # score targets: low hp good, carry good
        def val(e):
            return (1 - e.hp_frac) + (0.3 if e.role in ("ADC", "MID") else 0)
        tgt = max(enemies, key=val)
        if _in_range(me, tgt, me.stats.attack_range) and me.can_auto():
            return Proposal((0.9 + (1 - tgt.hp_frac)) * self.w(w),
                            Auto(tgt.name), self.name,
                            f"focus {tgt.name}", target=tgt.name)
        return Proposal(0.7 * self.w(w), Move(tgt.x, tgt.y), self.name,
                        f"close on {tgt.name}", target=tgt.name)


class ProtectCarry(Capability):
    """Stay glued to my own carry in a fight. Unique: a Move to MY carry's
    position (bodyguard), distinct from body_block (between a specific diver)."""
    name, family, phases = "protect_carry", "TEAMFIGHT", (Phase.TEAMFIGHT,)

    def propose(self, p, w):
        me = p.me
        carries = _ally_carries(p, exclude=me.name)
        if not carries:
            return None
        carry = _lowest(carries)
        if carry.hp_frac < 0.75:
            return Proposal((0.8 + (1 - carry.hp_frac)) * self.w(w),
                            Move(carry.x - 150, carry.y - 150), self.name,
                            f"guard {carry.name}", target=carry.name)
        return None


class Reposition(Capability):
    """Squishy drifts behind the frontline mid-fight. Unique: Move toward my own
    TANK/bruiser (not the carry, not away) — staying safe while dealing damage."""
    name, family, phases = "reposition", "TEAMFIGHT", (Phase.TEAMFIGHT,)

    def propose(self, p, w):
        me = p.me
        if me.role not in ("ADC", "MID", "SUPPORT"):
            return None
        threat = _nearest(me, p.enemies())
        frontline = _nearest(me, [a for a in p.allies()
                                  if a.role in ("TOP", "JUNGLE")])
        if threat and frontline and p.dist(me, threat) < 1000:
            return Proposal(0.6 * self.w(w), Move(frontline.x, frontline.y),
                            self.name, "reposition behind frontline")
        return None


# =========================================================================
# OBJECTIVE
# =========================================================================
class SecureObjective(Capability):
    """Take the objective. Unique: Move to the pit to claim it (offense)."""
    name, family, phases = "secure_objective", "OBJECTIVE", (Phase.OBJECTIVE,)

    def propose(self, p, w):
        o = p.world.objective
        return Proposal(1.0 * self.w(w), Move(o.x, o.y), self.name,
                        f"secure {o.name}", comms=f"Taking {o.name}!")


class ContestObjective(Capability):
    """Fight the enemies AT the objective. Unique vs secure: targets an enemy
    near the pit (deny), not the pit itself."""
    name, family, phases = "contest_objective", "OBJECTIVE", (Phase.OBJECTIVE,)

    def propose(self, p, w):
        me = p.me
        o = p.world.objective
        near = [e for e in p.enemies() if p.dist(e, o) < 2000]
        if near and me.hp_frac > 0.5:
            tgt = _nearest(me, near)
            return Proposal(0.9 * self.w(w), Move(tgt.x, tgt.y), self.name,
                            f"contest {o.name} vs {tgt.name}", target=tgt.name)
        return None


class TradeObjective(Capability):
    """Give the objective, take a lane instead when outnumbered at the pit.
    Unique: moves AWAY from the objective toward a wave — the tempo trade."""
    name, family, phases = "trade_objective", "OBJECTIVE", (Phase.OBJECTIVE,)

    def propose(self, p, w):
        me = p.me
        o = p.world.objective
        near_e = sum(1 for e in p.enemies() if p.dist(e, o) < 2000)
        near_a = sum(1 for a in p.allies() if p.dist(a, o) < 2000) + 1
        if near_e > near_a:
            mm = getattr(p.world, "minions", None)
            wave = [m for m in mm.minions if m.team != me.team and m.alive] if mm else []
            tgt = _nearest(me, wave) if wave else None
            if tgt:
                return Proposal(0.7 * self.w(w), Move(tgt.x, tgt.y), self.name,
                                "give objective, take a lane",
                                comms="Outnumbered — trading for a lane.")
        return None


# =========================================================================
# VISION  (one behavior; location depends on phase)
# =========================================================================
class Ward(Capability):
    """Place vision. Unique: the only behavior whose purpose is information; it
    moves to a ward spot that depends on phase (objective area, a flank, or
    defensively toward base when retreating)."""
    name, family = "ward", "VISION"
    phases = (Phase.LANING, Phase.OBJECTIVE, Phase.RETREAT)

    def propose(self, p, w):
        me = p.me
        if me.role != "SUPPORT":
            return None
        o = p.world.objective
        from agent2.phases import detect_phase
        phase = detect_phase(p)
        if phase == Phase.OBJECTIVE and p.dist(me, o) < 4000:
            return Proposal(0.5 * self.w(w), Move(o.x - 400, o.y + 400),
                            self.name, "ward the objective", comms="Warding objective.")
        if phase == Phase.RETREAT:
            return Proposal(0.3 * self.w(w), Move(me.spawn_x, me.spawn_y),
                            self.name, "defensive ward retreating")
        if me.hp_frac > 0.6:
            ally = _nearest(me, _ally_carries(p, exclude=me.name))
            if ally:
                return Proposal(0.3 * self.w(w, 0.6),
                                Move(ally.x + 600, ally.y - 600), self.name,
                                "ward a flank")
        return None


# =========================================================================
# SURVIVAL  (three genuinely different retreats)
# =========================================================================
class Flee(Capability):
    """Run STRAIGHT AWAY from the nearest threat. Unique: pure vector away from
    the enemy, used mid-combat when losing — maximum distance, fast."""
    name, family, phases = "flee", "SURVIVAL", (Phase.RETREAT,)

    def propose(self, p, w):
        me = p.me
        threat = _nearest(me, p.enemies())
        if not threat:
            return None
        # scale urgency with how low we are, so flee doesn't blanket-dominate the
        # RETREAT phase — a champ at 24% flees less hard than one at 5%
        urgency = 0.8 + 1.4 * (1 - me.hp_frac)
        return Proposal(urgency * self.w(w),
                        Move(me.x + (me.x - threat.x), me.y + (me.y - threat.y)),
                        self.name, "flee straight back", comms="Backing out!")


class Disengage(Capability):
    """Fall back TOWARD ALLIES (not just away). Unique vs flee: retreats to the
    team so you regroup, not into the open — used when down but not critical."""
    name, family, phases = "disengage", "SURVIVAL", (Phase.RETREAT, Phase.SKIRMISH)

    def propose(self, p, w):
        me = p.me
        onme = [e for e in p.enemies() if p.dist(me, e) < 1200]
        if me.hp_frac >= 0.4 or not onme:
            return None
        ally = _nearest(me, [a for a in p.allies() if a.name != me.name])
        dest = (ally.x, ally.y) if ally else (me.spawn_x, me.spawn_y)
        return Proposal((1.3 * (1 - me.hp_frac)) * self.w(w), Move(*dest),
                        self.name, "disengage toward allies")


class Recall(Capability):
    """Return to BASE to reset (heal/buy). Unique: goes to spawn when SAFE (no
    enemies near), a full reset — not a combat retreat."""
    name, family, phases = "recall", "SURVIVAL", (Phase.RESET,)

    def propose(self, p, w):
        me = p.me
        if any(p.dist(me, e) < 1500 for e in p.enemies()):
            return None   # not safe to recall
        return Proposal(1.2 * self.w(w), Move(me.spawn_x, me.spawn_y),
                        self.name, "recall to reset", comms="Resetting.")


# =========================================================================
# MACRO
# =========================================================================
class Group(Capability):
    """Regroup with a teammate when alone and an enemy is near. Unique: Move to
    the nearest ALLY (safety in numbers), triggered by being split."""
    name, family, phases = "group", "MACRO", (Phase.LANING, Phase.SKIRMISH,
                                              Phase.OBJECTIVE)

    def propose(self, p, w):
        me = p.me
        allies, enemies = p.allies(), p.enemies()
        if not allies or not enemies:
            return None
        na, ne = _nearest(me, allies), _nearest(me, enemies)
        if na and ne and p.dist(me, na) > 1800 and p.dist(me, ne) < 2800:
            return Proposal(0.7 * self.w(w), Move(na.x, na.y), self.name,
                            f"group with {na.name}", comms="Grouping up.")
        return None


class Roam(Capability):
    """Leave lane to help a fight ELSEWHERE. Unique vs group: goes to where an
    ally is actively fighting an enemy (proactive help), not just clustering."""
    name, family, phases = "roam", "MACRO", (Phase.LANING,)

    def propose(self, p, w):
        me = p.me
        if me.role not in ("MID", "SUPPORT", "JUNGLE"):
            return None
        for a in p.allies():
            e = _nearest(a, p.enemies())
            if e and p.dist(a, e) < 1500 and 1500 < p.dist(me, a) < 5000:
                return Proposal(0.55 * self.w(w), Move(a.x, a.y), self.name,
                                f"roam to help {a.name}", comms="Roaming to help!")
        return None


class Hold(Capability):
    """Default presence: stay near the carry. Unique: lowest-priority fallback
    so the champ is never idle in the open; always proposes, always low."""
    name, family, phases = "hold", "MACRO", ()

    def propose(self, p, w):
        me = p.me
        carries = _ally_carries(p, exclude=me.name)
        if carries:
            carry = _lowest(carries)
            return Proposal(0.2 * self.w(w),
                            Move(carry.x - 200, carry.y - 200), self.name,
                            f"hold near {carry.name}")
        return Proposal(0.1 * self.w(w), Idle(), self.name, "hold")


# =========================================================================
# the consolidated library (~24 genuinely-distinct behaviors)
# =========================================================================
FULL_REPERTOIRE = [
    LastHit(), PushWave(),                                    # FARMING (2)
    Poke(), AutoTrade(),                                      # TRADING (2)
    CCTheDiver(), ShieldAlly(), BodyBlock(), SelfPeel(),      # PEELING (4)
    DiveCarry(), PickIsolated(), Collapse(), AllIn(),         # ENGAGING (4)
    FocusTarget(), ProtectCarry(), Reposition(),              # TEAMFIGHT (3)
    SecureObjective(), ContestObjective(), TradeObjective(),  # OBJECTIVE (3)
    Ward(),                                                   # VISION (1)
    Flee(), Disengage(), Recall(),                            # SURVIVAL (3)
    Group(), Roam(), Hold(),                                  # MACRO (3)
]
