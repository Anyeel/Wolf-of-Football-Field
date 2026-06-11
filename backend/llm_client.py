"""Provider-agnostic LLM client.

Primary provider: local Ollama (free, private, no rate limits).
Fallback provider: Google Gemini REST API, used automatically when Ollama
is not running and a GEMINI_API_KEY is configured.

Every provider exposes the same three capabilities:
  - generate(prompt)               -> str
  - generate(prompt, schema=...)   -> str (JSON constrained by the schema)
  - stream(prompt)                 -> Iterator[str] of text chunks
"""

import json
import os
import time

import requests
from dotenv import load_dotenv

load_dotenv()

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


class LLMUnavailableError(RuntimeError):
    """Raised when no LLM provider can serve the request."""


class OllamaProvider:
    """Local Ollama server. Supports schema-constrained decoding via `format`."""

    def __init__(self, model: str):
        self.model = model
        self._generate_url = f"{OLLAMA_BASE_URL}/api/generate"

    @property
    def name(self) -> str:
        return f"Ollama Local ({self.model})"

    def is_available(self) -> bool:
        try:
            return requests.get(OLLAMA_BASE_URL, timeout=2).status_code == 200
        except requests.RequestException:
            return False

    def _payload(self, prompt: str, schema: dict | None = None, stream: bool = False) -> dict:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": stream,
            "options": {"temperature": 0.3, "num_ctx": 8192},
        }
        if schema:
            # Ollama enforces the JSON schema at decoding time, so the
            # response is guaranteed to be parseable.
            payload["format"] = schema
        return payload

    def generate(self, prompt: str, schema: dict | None = None, timeout: int = 300) -> str:
        response = requests.post(
            self._generate_url, json=self._payload(prompt, schema), timeout=timeout
        )
        response.raise_for_status()
        return response.json().get("response", "")

    def stream(self, prompt: str):
        # timeout applies to the initial connection only; reading lasts as
        # long as the model keeps generating.
        response = requests.post(
            self._generate_url,
            json=self._payload(prompt, stream=True),
            timeout=30,
            stream=True,
        )
        response.raise_for_status()
        for line in response.iter_lines():
            if not line:
                continue
            chunk = json.loads(line)
            token = chunk.get("response", "")
            if token:
                yield token
            if chunk.get("done"):
                break


class GeminiProvider:
    """Google Gemini via plain REST (no SDK dependency)."""

    def __init__(self, model: str):
        self.model = model
        self.api_key = os.getenv("GEMINI_API_KEY", "")

    @property
    def name(self) -> str:
        return f"Gemini Cloud ({self.model})"

    def is_available(self) -> bool:
        return bool(self.api_key)

    def _request(self, prompt: str, schema: dict | None = None, stream: bool = False,
                 timeout: int = 120) -> requests.Response:
        endpoint = "streamGenerateContent?alt=sse" if stream else "generateContent"
        url = f"{GEMINI_BASE_URL}/models/{self.model}:{endpoint}"
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.3},
        }
        if schema:
            body["generationConfig"]["responseMimeType"] = "application/json"
            body["generationConfig"]["responseSchema"] = schema
        response = requests.post(
            url, json=body, headers={"x-goog-api-key": self.api_key},
            timeout=timeout, stream=stream,
        )
        response.raise_for_status()
        return response

    def generate(self, prompt: str, schema: dict | None = None, timeout: int = 120) -> str:
        data = self._request(prompt, schema, timeout=timeout).json()
        return data["candidates"][0]["content"]["parts"][0]["text"]

    def stream(self, prompt: str):
        response = self._request(prompt, stream=True)
        for line in response.iter_lines():
            if not line or not line.startswith(b"data: "):
                continue
            chunk = json.loads(line[len(b"data: "):])
            candidates = chunk.get("candidates", [])
            if not candidates:
                continue
            for part in candidates[0].get("content", {}).get("parts", []):
                text = part.get("text", "")
                if text:
                    yield text


class LLMClient:
    """Routes requests to the first available provider (Ollama, then Gemini)."""

    def __init__(self):
        self.providers = [
            OllamaProvider(os.getenv("OLLAMA_MODEL", "qwen3.5:9b")),
            GeminiProvider(os.getenv("GEMINI_MODEL", "gemini-2.5-flash")),
        ]

    def active_provider(self):
        """Returns the first available provider, or None if all are down."""
        for provider in self.providers:
            if provider.is_available():
                return provider
        return None

    @property
    def has_llm(self) -> bool:
        return self.active_provider() is not None

    def generate(self, prompt: str, schema: dict | None = None, max_retries: int = 2) -> str:
        provider = self.active_provider()
        if not provider:
            raise LLMUnavailableError("No LLM provider available (Ollama offline, no Gemini key).")

        last_error: Exception | None = None
        for attempt in range(max_retries):
            try:
                print(f"      -> [AI] {provider.name}: prompt of {len(prompt)} chars "
                      f"(attempt {attempt + 1}/{max_retries})...")
                return provider.generate(prompt, schema)
            except requests.RequestException as e:
                last_error = e
                print(f"      -> [AI] {provider.name} failed: {e}. Retrying...")
                time.sleep(2)
        raise LLMUnavailableError(f"{provider.name} failed after {max_retries} attempts: {last_error}")

    def generate_json(self, prompt: str, schema: dict, max_retries: int = 2) -> dict:
        """Generates a schema-constrained response and parses it as JSON."""
        text = self.generate(prompt, schema=schema, max_retries=max_retries)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Some models wrap JSON in markdown fences despite the schema.
            cleaned = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
            return json.loads(cleaned)

    def stream(self, prompt: str):
        provider = self.active_provider()
        if not provider:
            raise LLMUnavailableError("No LLM provider available (Ollama offline, no Gemini key).")
        print(f"      -> [AI] Streaming via {provider.name} ({len(prompt)} chars)...")
        yield from provider.stream(prompt)
