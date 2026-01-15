import json
import os

DEFAULT_ACCOUNTS_PATH = os.path.join(os.path.dirname(__file__), "accounts.json")


def load_accounts(path: str = DEFAULT_ACCOUNTS_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_account(alias: str | None = None, path: str = DEFAULT_ACCOUNTS_PATH) -> dict:
    data = load_accounts(path)
    accounts = data.get("accounts", [])
    if not accounts:
        raise RuntimeError("No accounts configured in accounts.json")

    target_alias = alias or data.get("default") or accounts[0].get("alias")
    for acc in accounts:
        if acc.get("alias") == target_alias:
            return acc

    raise RuntimeError(f"Account alias not found: {target_alias}")


def get_account_from_env(env_var: str = "ACCOUNT_ALIAS") -> dict:
    alias = os.getenv(env_var)
    return get_account(alias=alias)
