import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from llm_checker import LLMNewsChecker


class FakeProvider:
    name = "Fake LLM"


class FakeClient:
    """Stub LLMClient: returns a canned structured verdict."""

    has_llm = True

    def __init__(self, report):
        self.report = report
        self.last_prompt = None

    def active_provider(self):
        return FakeProvider()

    def generate_json(self, prompt, schema, max_retries=2):
        self.last_prompt = prompt
        return self.report


class OfflineClient(FakeClient):
    has_llm = False

    def __init__(self):
        super().__init__(report={})

    def active_provider(self):
        return None


def test_batch_check_merges_ai_verdicts(monkeypatch):
    client = FakeClient({
        "players": [{"name": "Pedri", "safe": False, "reason": "Hamstring injury"}]
    })
    checker = LLMNewsChecker(client=client)
    monkeypatch.setattr(
        checker, "_fetch_news",
        lambda name: "Pedri sufre molestias" if name == "Pedri" else "",
    )

    verdicts = checker.check_players_status(["Pedri", "Lewandowski"])

    # Pedri had news -> went through the LLM and was flagged.
    assert verdicts["Pedri"] == (False, "Hamstring injury")
    # Lewandowski had no news -> safe without spending an LLM call.
    assert verdicts["Lewandowski"][0] is True
    # Only players with news appear in the prompt.
    assert "Pedri" in client.last_prompt
    assert "Lewandowski" not in client.last_prompt


def test_keyword_fallback_when_llm_offline(monkeypatch):
    checker = LLMNewsChecker(client=OfflineClient())
    monkeypatch.setattr(checker, "_fetch_news", lambda name: "rotura muscular, baja confirmada")

    safe, reason = checker.check_player_status("Vinicius")

    assert safe is False
    assert "rotura" in reason or "baja" in reason


def test_parse_cart_verdict_extracts_status_and_reason():
    text = "STATUS: SUGGESTIONS\nREASON: Vende antes de pujar, vas muy justo de saldo."
    status, reason = LLMNewsChecker._parse_cart_verdict(text)

    assert status == "SUGGESTIONS"
    assert reason.startswith("Vende antes")


def test_parse_cart_verdict_defaults_to_ok():
    status, _ = LLMNewsChecker._parse_cart_verdict("Looks great, go for it!")
    assert status == "OK"
