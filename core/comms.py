"""
Comms layer — the differentiator.

Turns the bot's chosen (priority, action, target) into a short, natural callout
to the human teammate. This is the "AI teammate that talks/explains" role the
deck highlights (PUBG Ally). LLM for natural phrasing, with a template fallback
so it always says *something* useful even offline.
"""
from __future__ import annotations

from core.schema import BotOutput, GameState, Priority
from llm.provider import LLMProvider

_TEMPLATES = {
    ("PEEL_CARRY", "ENGAGE_CC"): "Stunning {target} off you — stay behind me.",
    ("PEEL_CARRY", "PEEL"): "Peeling for you — {target}, hold your ground.",
    ("SETUP_OBJECTIVE", "WARD_OBJECTIVE"): "Warding {target} — group up, we take it.",
    ("ENGAGE", "ENGAGE_CC"): "Engaging on {target} — follow up!",
    ("PLAY_SAFE", "RETREAT"): "Backing off, I can't peel here — play safe.",
}


class Comms:
    def __init__(self, llm: LLMProvider | None = None):
        self.llm = llm

    def say(self, gs: GameState, out: BotOutput) -> str:
        if not out.health_ok:
            return "Safe mode: playing simple and defensive."
        if self.llm is not None:
            msg = self._llm_say(gs, out)
            if msg:
                return msg
        return self._template(out)

    def _template(self, out: BotOutput) -> str:
        tmpl = _TEMPLATES.get((out.priority.value, out.action))
        if not tmpl:
            return ""
        return tmpl.format(target=out.target or "team")

    def _llm_say(self, gs: GameState, out: BotOutput) -> str:
        prompt = (
            "You are a League SUPPORT bot talking to your human ADC teammate.\n"
            "One short in-game callout (<= 12 words), no quotes.\n"
            f"Priority: {out.priority.value}\n"
            f"Action: {out.action} target={out.target}\n"
            f"Carry hp: {gs.ally_carry().hp_frac:.2f}\n"
            if gs.ally_carry() else ""
        )
        # warm/chatty tone for comms
        return (self.llm.complete(prompt, temperature=0.8) or "").strip()
