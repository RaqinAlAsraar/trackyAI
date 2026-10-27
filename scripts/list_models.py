"""
Helper script to fetch and list all available Gemini and Gemma models
from Google AI Studio API for model selection.
"""

import sys
import json
import warnings
from typing import List, Dict

with warnings.catch_warnings():
    warnings.simplefilter("ignore", category=FutureWarning)
    import google.generativeai as genai

FALLBACK_MODELS = [
    {"name": "models/gemma-4-26b-a4b-it", "description": "Gemma 4 26B A4B instruction-tuned model (Default Primary)"},
    {"name": "models/gemma-4-31b-it", "description": "Gemma 4 31B instruction-tuned model"},
    {"name": "models/gemini-3.1-flash-lite", "description": "High quota (1500 RPD) ultra-fast fallback without thinking delay (Recommended Backup)"},
    {"name": "models/gemini-3-flash-preview", "description": "Fast multimodal preview model"},
]


def fetch_models(api_key: str) -> List[Dict[str, str]]:
    if not api_key:
        return FALLBACK_MODELS

    try:
        genai.configure(api_key=api_key)
        all_models = genai.list_models()
        valid_models = []
        model_names_seen = set()

        # Always include Gemma 4 models at the top
        for gm in FALLBACK_MODELS:
            if "gemma-4" in gm["name"]:
                valid_models.append(gm)
                model_names_seen.add(gm["name"])

        for m in all_models:
            # Filter models that support content generation
            methods = getattr(m, "supported_generation_methods", [])
            if "generateContent" in methods:
                clean_name = m.name.replace("models/", "")
                if clean_name not in model_names_seen:
                    desc = getattr(m, "display_name", "") or getattr(m, "description", "")
                    valid_models.append({"name": clean_name, "description": desc[:70] if desc else clean_name})
                    model_names_seen.add(clean_name)

        if valid_models:
            return valid_models
    except Exception:
        pass

    return FALLBACK_MODELS


if __name__ == "__main__":
    import os

    key = ""
    for arg in sys.argv[1:]:
        if not arg.startswith("--"):
            key = arg
            break

    if not key:
        key = os.environ.get("GEMINI_API_KEY", "")

    if not key and os.path.exists("config.json"):
        try:
            with open("config.json", "r") as f:
                cfg = json.load(f)
                key = cfg.get("gemini", {}).get("api_key", "")
        except Exception:
            pass

    as_json = "--json" in sys.argv
    models = fetch_models(key)

    if as_json:
        print(json.dumps(models))
    else:
        for idx, m in enumerate(models, 1):
            print(f"{idx}) {m['name']} - {m['description']}")
