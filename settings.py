import json
import os

DEFAULT_SETTINGS_PATH = os.path.join(os.path.dirname(__file__), "settings.json")


def load_settings(path: str = DEFAULT_SETTINGS_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_setting(key: str, default=None, env_var: str | None = None):
    if env_var:
        env_val = os.getenv(env_var)
        if env_val is not None and env_val != "":
            return env_val

    data = load_settings()
    return data.get(key, default)
