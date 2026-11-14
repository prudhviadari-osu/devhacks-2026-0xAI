"""
The playable game: Model + Controllers + View wired together (MVC loop).

Loop each frame:
    1. read human input (pygame) -> InputState on the HumanController
    2. every champion's controller.decide(world) -> Action
    3. world.step(actions)              (the Model advances with real rules)
    4. renderer.draw(world)             (the View)

Default scene: you play Sona (support). Lulu (ally carry, scripted-ish), Zac
(enemy diver, bot), Jax/Ryze fill the fight. Swap your champion / controllers
below. Set HUMAN=False to watch the bot play Sona instead (great for the demo).

Run on your Mac:
    pip install pygame
    python3 game.py            # you play Sona
    HUMAN=0 python3 game.py    # bot plays Sona, you watch

Controls: right-click = move, Q/W/E/R = cast (at cursor, or at champion under
cursor), left-click a champion = auto-attack it.
"""
from __future__ import annotations

import os
import sys

from controllers.bot import BotController
from controllers.human import HumanController, InputState
from controllers.replay import ReplayController
from model.champion import Champion
from model.world import Auto, Cast, Idle, Move, World, dist, MAP_SIZE

TICK_HZ = 30  # frames per second


def build_scene(human_plays):
    """Build the selected demo scenario (SCENARIO env var; default 'dive').

    Each champion gets its archetype-profiled utility brain. One champion may be
    human-controlled: the scenario names a default human champ, overridable with
    HUMAN_CHAMP. HUMAN=0 makes it all-bots (best for watching behaviors).
    """
    import scenarios
    from agent2.profiles import profile_for_champion
    from controllers.utility_bot import UtilityBotController

    scenario_name = os.environ.get("SCENARIO", "dive")
    champs, dragon_spawn, desc, default_human = scenarios.get(scenario_name)
    world = World(champs, dragon_spawn=dragon_spawn)
    print(f"[scenario: {scenario_name}] {desc}")

    human_champ = os.environ.get("HUMAN_CHAMP", default_human) if human_plays else None
    human = HumanController()

    controllers = {}
    for ch in champs:
        if human_champ and ch.name == human_champ:
            controllers[ch.name] = human
        else:
            controllers[ch.name] = UtilityBotController(
                profile_for_champion(ch.name))

    # which controller's decisions drive the HUD callout (a bot, if one exists)
    hud_bot = next((controllers[ch.name] for ch in champs
                    if ch.name != human_champ), None)
    return world, controllers, human, hud_bot


# --- lightweight scripted AIs for the non-hero champions (placeholder brains) ---
class _CarryAI:
    def decide(self, world: World, me: str):
        c = world.get(me)
        enemies = world.enemies_of(c.team)
        if not enemies:
            return Idle()
        tgt = min(enemies, key=lambda e: dist(c, e))
        if dist(c, tgt) <= c.stats.attack_range:
            return Auto(tgt.name)
        return Move(tgt.x, tgt.y)


class _DiverAI:
    def decide(self, world: World, me: str):
        c = world.get(me)
        enemies = world.enemies_of(c.team)
        carries = [e for e in enemies if e.role in ("ADC", "MID")]
        target = min(carries or enemies, key=lambda e: dist(c, e), default=None)
        if not target:
            return Idle()
        d = dist(c, target)
        if c.ability_ready("E") and d <= c.abilities["E"].range:
            return Cast("E", target=target.name)
        if d <= c.stats.attack_range:
            return Auto(target.name)
        return Move(target.x, target.y)


def _carry_ai():
    return _CarryAI()


def _diver_ai():
    return _DiverAI()


def read_input(renderer, human: HumanController) -> bool:
    """Translate pygame events into the human's InputState. Returns quit flag."""
    pg = renderer.pygame
    from view.render import WIN_W, WIN_H
    state = InputState()
    mx, my = pg.mouse.get_pos()
    # cursor in game units (flip y so screen-up = north)
    gx = mx / WIN_W * MAP_SIZE
    gy = (WIN_H - my) / WIN_H * MAP_SIZE
    state.cursor = (gx, gy)

    for e in pg.event.get():
        if e.type == pg.QUIT:
            return True
        if e.type == pg.KEYDOWN:
            if e.key == pg.K_ESCAPE:
                return True
            for k, slot in ((pg.K_q, "Q"), (pg.K_w, "W"),
                            (pg.K_e, "E"), (pg.K_r, "R")):
                if e.key == k:
                    state.cast_slot = slot
        if e.type == pg.MOUSEBUTTONDOWN:
            if e.button == 3:               # right-click move
                state.move_to = (gx, gy)
            elif e.button == 1:             # left-click: auto nearest to cursor
                state.auto_target = _champ_under(gx, gy)
    human.set_input(state)
    return False


_WORLD_REF: World | None = None


def _champ_under(gx, gy) -> str | None:
    if _WORLD_REF is None:
        return None
    best, bd = None, 1e9
    for c in _WORLD_REF.champions:
        if not c.alive:
            continue
        d = (c.x - gx) ** 2 + (c.y - gy) ** 2
        if d < bd:
            best, bd = c.name, d
    return best if bd < 600 ** 2 else None


def main() -> None:
    global _WORLD_REF
    human_plays = os.environ.get("HUMAN", "1") != "0"
    world, controllers, human, bot = build_scene(human_plays)
    _WORLD_REF = world

    # which champion (if any) is human-controlled -> highlight it in the view
    human_name = next((name for name, ctrl in controllers.items()
                       if ctrl is human), None) if human_plays else None

    # animated renderer by default (textured map + sprites + smooth movement);
    # RENDERER=basic falls back to the simple shape renderer.
    if os.environ.get("RENDERER", "animated") == "basic":
        from view.render import Renderer
        renderer = Renderer(human_name=human_name)
    else:
        from view.animated import AnimatedRenderer as Renderer
        renderer = Renderer(human_name=human_name)
    clock = renderer.pygame.time.Clock()

    running = True
    while running:
        if human_plays:
            if read_input(renderer, human):
                break
        else:
            if renderer.poll_quit():
                break

        actions = {name: ctrl.decide(world, name)
                   for name, ctrl in controllers.items()}
        world.step(actions)

        # feed the AI overlay panel: each controller's current decision + why
        ai_info = {}
        for name, ctrl in controllers.items():
            ai_info[name] = {
                "priority": getattr(ctrl, "last_priority", "human"),
                "considered": getattr(ctrl, "last_considered", []),
            }
        renderer.ai_info = ai_info

        callout = bot.last_comms if bot else ""
        priority = bot.last_priority if bot else ""
        renderer.draw(world, callout=callout, priority=priority)
        clock.tick(TICK_HZ)

    renderer.close()


if __name__ == "__main__":
    main()
