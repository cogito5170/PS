"""Replaceable model-provider adapters.

The engine is fully functional with ``NullProvider`` (no model): deterministic
extraction covers English; other languages are reported as limitations unless a
translation is in the corpus.  A provider may add:

* ``extract(text, language)`` → list of proposition dicts (non-English passages)
* ``translate(text, source_language, target_language)`` → str

Everything a provider returns is labelled ``deterministic=False`` and
``method="model:<name>"``; propositions extracted by a model are marked
``review_required`` and model output is never treated as verified evidence.
"""
from __future__ import annotations

import json
import os
from typing import Optional, Protocol

PROPOSITION_SCHEMA = {
    "type": "object",
    "properties": {
        "propositions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "sentence": {"type": "string", "description": "verbatim source sentence"},
                    "subject": {"type": "string"},
                    "predicate": {"type": "string"},
                    "object": {"type": ["string", "null"]},
                    "claim_type": {"type": "string", "enum": [
                        "empirical", "statistical", "causal", "correlational", "definition",
                        "opinion", "normative", "prediction", "hypothesis", "observation",
                        "mathematical"]},
                    "negated": {"type": "boolean"},
                    "hedged": {"type": "boolean"},
                    "quantity": {"type": ["string", "null"]},
                    "time": {"type": ["string", "null"]},
                    "location": {"type": ["string", "null"]},
                    "population": {"type": ["string", "null"]},
                    "conditions": {"type": "array", "items": {"type": "string"}},
                    "english_gloss": {"type": "string"},
                },
                "required": ["sentence", "subject", "predicate", "object", "claim_type", "negated",
                             "hedged", "quantity", "time", "location", "population", "conditions",
                             "english_gloss"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["propositions"],
    "additionalProperties": False,
}


class Provider(Protocol):
    name: str

    def extract(self, text: str, language: str) -> Optional[list[dict]]: ...

    def translate(self, text: str, source_language: str, target_language: str) -> Optional[str]: ...


class NullProvider:
    """No model available: every method declines."""
    name = "none"
    calls = 0

    def extract(self, text: str, language: str) -> Optional[list[dict]]:
        return None

    def translate(self, text: str, source_language: str, target_language: str) -> Optional[str]:
        return None


class AnthropicProvider:
    """Optional adapter for the Claude API (``pip install anthropic``; credentials
    resolved by the SDK).  Not exercised by the automated tests, which must run
    offline; see README for how to enable it."""

    def __init__(self, model: str = "claude-opus-5-5", effort: str = "low"):
        import anthropic  # imported lazily: optional dependency

        self.client = anthropic.Anthropic()
        self.model = model
        self.effort = effort
        self.name = f"anthropic:{model}"
        self.calls = 0

    def _call(self, system: str, user: str, schema: Optional[dict]) -> Optional[str]:
        output_config: dict = {"effort": self.effort}
        if schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": schema}
        self.calls += 1
        response = self.client.beta.messages.create(
            model=self.model,
            max_tokens=16000,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config=output_config,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        if response.stop_reason == "refusal":
            return None
        return next((b.text for b in response.content if b.type == "text"), None)

    def extract(self, text: str, language: str) -> Optional[list[dict]]:
        system = ("You extract atomic propositions from text for a fact-checking engine. "
                  "One principal claim per proposition. Keep negation, hedging, quantities, units, "
                  "time, location, population and conditions exactly as stated; never add facts. "
                  "Copy the source sentence verbatim into 'sentence'.")
        out = self._call(system, f"Language: {language}\n\nText:\n{text}", PROPOSITION_SCHEMA)
        if out is None:
            return None
        try:
            return json.loads(out)["propositions"]
        except (ValueError, KeyError):
            return None

    def translate(self, text: str, source_language: str, target_language: str) -> Optional[str]:
        system = ("Translate faithfully. Preserve negation, modality (may/must), quantifiers and "
                  "every number exactly. Output only the translation.")
        return self._call(system, f"From {source_language} to {target_language}:\n{text}", None)


def get_provider(name: Optional[str]) -> Provider:
    if not name or name == "none":
        return NullProvider()
    if name.startswith("anthropic"):
        model = name.split(":", 1)[1] if ":" in name else os.environ.get("UPAE_MODEL", "claude-opus-5-5")
        return AnthropicProvider(model=model)
    raise ValueError(f"unknown provider '{name}'")
