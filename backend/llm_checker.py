"""AI-powered news analysis for Fantasy Football decisions.

Responsibilities:
  - Gather recent injury/rotation news per player (DuckDuckGo, filtered to
    futbolfantasy.com, the most reliable La Liga Fantasy source).
  - Ask the LLM for a verdict in a single batched call with a JSON schema,
    so one inference covers the whole market instead of one call per player.
  - Stream the final "cart review" evaluation token by token (SSE).

Financial decisions (e.g. whether a buyout clause is worth paying) are NOT
handled here: they are deterministic arithmetic and live in strategy.py.
"""

import datetime
import json
import re

from ddgs import DDGS

from llm_client import LLMClient, LLMUnavailableError

# Schema for the batched injury check: guarantees a parseable verdict per player.
INJURY_REPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "players": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "safe": {"type": "boolean"},
                    "reason": {"type": "string"},
                },
                "required": ["name", "safe", "reason"],
            },
        }
    },
    "required": ["players"],
}

# Keyword fallback used when no LLM provider is available.
DANGER_KEYWORDS = [
    "injury", "injured", "tear", "ruled out", "surgery", "doubt",
    "lesión", "lesionado", "rotura", "baja", "duda", "quirófano", "molestias",
]


class LLMNewsChecker:
    """Checks player health/rotation news and reviews the final operation."""

    def __init__(self, client: LLMClient | None = None):
        self.client = client or LLMClient()
        provider = self.client.active_provider()
        if provider:
            print(f"[AI] LLM engine ready: {provider.name}")
        else:
            print("[AI] Warning: no LLM available (Ollama offline, no Gemini key). "
                  "Falling back to keyword analysis.")

    @property
    def has_llm(self) -> bool:
        return self.client.has_llm

    # ------------------------------------------------------------------
    # News gathering
    # ------------------------------------------------------------------

    def _fetch_news(self, player_name: str) -> str:
        """Returns last-week news snippets for a player, or '' if none found.

        Only the weekly window is searched: a broader monthly fallback used to
        surface stale articles ("X se lesionó" from weeks ago, long recovered)
        that made the LLM flag healthy players as injured.
        """
        try:
            results = DDGS().text(
                f"site:futbolfantasy.com {player_name} lesion rotacion",
                max_results=3, timelimit="w",
            )
            # Titles carry the actual headline; bodies are often nav/boilerplate.
            return " | ".join(
                f"{r.get('title', '')}: {r.get('body', '')}" for r in results
            )
        except Exception as e:
            print(f"[AI] Web search failed for {player_name}: {e}")
            return ""

    # ------------------------------------------------------------------
    # Injury / rotation verdicts
    # ------------------------------------------------------------------

    def check_players_status(self, player_names: list[str]) -> dict[str, tuple[bool, str]]:
        """Batch health check: one LLM call for the whole list of players.

        Returns a dict {player_name: (is_safe, reason)}. Players without any
        recent news are considered safe and skip the LLM entirely.
        """
        verdicts: dict[str, tuple[bool, str]] = {}
        news_by_player: dict[str, str] = {}

        for name in player_names:
            print(f"[AI] Searching recent news for {name}...")
            snippets = self._fetch_news(name)
            if snippets:
                news_by_player[name] = snippets
            else:
                verdicts[name] = (True, "No recent news found. Assuming player is fit.")

        if not news_by_player:
            return verdicts

        if not self.has_llm:
            for name, snippets in news_by_player.items():
                verdicts[name] = self._keyword_check(snippets)
            return verdicts

        news_block = "\n".join(
            f'- {name}: "{snippets[:600]}"' for name, snippets in news_by_player.items()
        )
        today = datetime.date.today().strftime("%d %B %Y")
        prompt = f"""You are an expert analyst in football and Fantasy Football (Mister Fantasy).
Today is {today}. Below are news snippets from the last 7 days for several players,
one per line (format: "title: body"):

{news_block}

For EACH player decide if he is safe to sign. BE CONSERVATIVE — mark a player
NOT SAFE (safe=false) ONLY if a snippet EXPLICITLY reports that THIS player is
CURRENTLY injured, doubtful for the upcoming match, suspended, or being rotated.

Mark SAFE (safe=true) when:
- The news reports a recovery, a return to training, or a comeback.
- The snippet is about a DIFFERENT player or is generic site text that merely
  contains words like "lesión" or "rotación" without a specific report on him.
- The information is vague, outdated, or you are not sure.

Never invent injuries that the snippets do not state. Give a one-sentence reason
(max 15 words) per player, quoting the snippet's claim when flagging someone.
Reply for every player listed, using their exact names.
"""

        try:
            report = self.client.generate_json(prompt, INJURY_REPORT_SCHEMA)
            ai_verdicts = {p["name"]: (bool(p["safe"]), p["reason"]) for p in report["players"]}
        except (LLMUnavailableError, KeyError, TypeError, json.JSONDecodeError) as e:
            print(f"[AI] Batched check failed ({e}). Using keyword fallback.")
            ai_verdicts = {}

        for name, snippets in news_by_player.items():
            if name in ai_verdicts:
                verdicts[name] = ai_verdicts[name]
            else:
                verdicts[name] = self._keyword_check(snippets)

        return verdicts

    def check_player_status(self, player_name: str) -> tuple[bool, str]:
        """Single-player convenience wrapper around the batch check."""
        return self.check_players_status([player_name])[player_name]

    def _keyword_check(self, text: str) -> tuple[bool, str]:
        """Zero-cost fallback: scan the news text for danger keywords."""
        text_lower = text.lower()
        for word in DANGER_KEYWORDS:
            if word in text_lower:
                return False, f"Keyword alert: '{word}' found in recent news."
        return True, "No signs of injury in recent headlines."

    # ------------------------------------------------------------------
    # Final cart review (streamed over SSE)
    # ------------------------------------------------------------------

    def evaluate_cart_stream(self, cart_summary: str):
        """Streams the LLM review of the full operation as SSE events.

        Yields `data: {...}` lines. Intermediate events carry a `token`;
        the final event has `done: true` plus the parsed status and reason.
        """
        if not self.has_llm:
            yield self._sse({"token": "", "done": True, "status": "ERROR",
                             "reason": "No LLM provider connected (Ollama offline, no Gemini key)."})
            return

        full_text = ""
        try:
            for token in self.client.stream(self._build_cart_prompt(cart_summary)):
                full_text += token
                yield self._sse({"token": token, "done": False})

            status, reason = self._parse_cart_verdict(full_text)
            yield self._sse({"token": "", "done": True, "status": status, "reason": reason})
        except Exception as e:
            yield self._sse({"token": "", "done": True, "status": "ERROR",
                             "reason": f"Streaming error: {e}"})

    @staticmethod
    def _sse(payload: dict) -> str:
        return f"data: {json.dumps(payload)}\n\n"

    @staticmethod
    def _parse_cart_verdict(text: str) -> tuple[str, str]:
        """Extracts (status, reason) from the model's STATUS/REASON reply."""
        upper = text.upper()
        if "STATUS: BAD" in upper:
            status = "BAD"
        elif "STATUS: SUGGESTIONS" in upper:
            status = "SUGGESTIONS"
        else:
            status = "OK"

        parts = re.split(r"REASON:\s*", text, maxsplit=1, flags=re.IGNORECASE)
        reason = parts[1].strip() if len(parts) > 1 else text.strip()
        return status, reason

    @staticmethod
    def _build_cart_prompt(cart_summary: str) -> str:
        return f"""You are the Head Coach (AI) of a Fantasy Football team (Mister Fantasy).
Your assistant has prepared the following operation for today:

{cart_summary}

Evaluate the entire operation.
RESPOND STRICTLY FOLLOWING THIS FORMAT:

STATUS: OK (solid move), SUGGESTIONS (good but you have tactical or financial tips), or BAD (huge mistakes: injured starters, negative projected balance, or terrible decisions).
REASON: (from here on, a detailed paragraph in Spanish using Markdown formatting).

In your REASON, analyze:
1. Purchases vs sales: do they make sense sportingly and financially?
2. Projected balance: are we left negative or too tight?
3. Starting 11: is it competitive? Any injured or suspended players?
4. Opportunities: if a rival owns top players, suggest specific buyout-clause ("clausulazo") targets.

Be like the Wolf of Wall Street but for football — confident, strategic and ruthless. Give plenty of constructive, specific feedback.
"""


if __name__ == "__main__":
    checker = LLMNewsChecker()
    verdicts = checker.check_players_status(["Pedri", "Lamine Yamal"])
    for player, (safe, reason) in verdicts.items():
        print(f"Sign {player}? {safe} -> {reason}")
