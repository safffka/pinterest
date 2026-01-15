import json
import os

_PROMPTS_CACHE = None


def load_prompts(path: str | None = None) -> dict:
    global _PROMPTS_CACHE
    if _PROMPTS_CACHE is not None:
        return _PROMPTS_CACHE

    prompts_path = path or os.path.join(os.path.dirname(__file__), "prompts.json")
    with open(prompts_path, "r", encoding="utf-8") as f:
        _PROMPTS_CACHE = json.load(f)
    return _PROMPTS_CACHE


def render_prompt(key: str, **kwargs) -> str:
    prompts = load_prompts()
    if key not in prompts:
        raise KeyError(f"Prompt key not found: {key}")
    template = prompts[key]
    return template.format(**kwargs)
