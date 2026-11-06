"""
Generate the `models.yaml` that the official VitaBench code reads at import time.

VitaBench calls LLMs through a raw HTTP POST to `models[<name>]["base_url"]` with
`models[<name>]["headers"]`, merging every other key of the model entry into the
request body. This helper builds that file from the OpenAI-compatible endpoint
Harbor passes in via environment variables so the upstream code runs unmodified.

Must be called before `import vita`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def _chat_completions_url(base_url: str) -> str:
    base_url = base_url.rstrip("/")
    if base_url.endswith("/chat/completions"):
        return base_url
    return f"{base_url}/chat/completions"


def _model_entry(name: str, override_json: str | None) -> dict[str, Any]:
    # Mirrors the upstream `models.yaml` example entry for gpt-4.1.
    entry: dict[str, Any] = {"name": name, "max_tokens": 8192}
    if override_json:
        decoded = json.loads(override_json)
        if not isinstance(decoded, dict):
            raise ValueError("LLM args override must decode to a JSON object.")
        entry.update(decoded)
    return entry


def write_models_config(models: dict[str, str | None]) -> Path:
    """Write models.yaml for the given {model_name: override_json} mapping.

    Returns the path written. The path is taken from VITA_MODEL_CONFIG_PATH.
    """
    import yaml

    path = Path(os.environ.get("VITA_MODEL_CONFIG_PATH", "/app/vita_models.yaml"))
    api_key = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1"

    config = {
        "default": {
            "base_url": _chat_completions_url(base_url),
            "temperature": 0.0,
            "max_input_tokens": 32768,
            "headers": {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        },
        "models": [
            _model_entry(name, override) for name, override in models.items() if name
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    os.environ["VITA_MODEL_CONFIG_PATH"] = str(path)
    return path
