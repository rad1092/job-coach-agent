from __future__ import annotations

import json
import re
from typing import Any

from openai import OpenAI

from backend.app.core.settings import Settings


class LLMConfigurationError(RuntimeError):
    pass


class OpenAIJsonClient:
    def __init__(self, settings: Settings) -> None:
        if not settings.openai_api_key:
            raise LLMConfigurationError("OPENAI_API_KEY is required when LLM_PROVIDER=openai.")
        self._client = OpenAI(api_key=settings.openai_api_key)
        self._model = settings.openai_model

    def generate_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        response = self._client.responses.create(
            model=self._model,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        text = _extract_json_text(response.output_text)
        return json.loads(text)


def build_llm_client(settings: Settings) -> OpenAIJsonClient | None:
    if settings.llm_provider == "fixture":
        return None
    return OpenAIJsonClient(settings)


def _extract_json_text(raw_text: str) -> str:
    text = raw_text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text
