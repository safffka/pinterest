import json
import os
import threading
import time
import traceback
import requests

import accounts
import main
import main1
import main3
import parse
import prompts
import proxy
import settings

STATE_PATH = os.path.join(os.path.dirname(__file__), "bot_state.json")


def _resolve_state_path() -> str:
    if os.path.isdir(STATE_PATH):
        return os.path.join(STATE_PATH, "state.json")
    return STATE_PATH


def load_state() -> dict:
    state_path = _resolve_state_path()
    if not os.path.isfile(state_path):
        return {"users": {}, "jobs": {}}
    with open(state_path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(state: dict) -> None:
    state_path = _resolve_state_path()
    os.makedirs(os.path.dirname(state_path) or ".", exist_ok=True)
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=True)


def get_user_state(state: dict, user_id: str) -> dict:
    users = state.setdefault("users", {})
    return users.setdefault(user_id, {})


def send_message(token: str, chat_id: int, text: str, reply_markup: dict | None = None) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    requests.post(url, json=payload, timeout=20)


def build_keyboard(rows: list[list[str]]) -> dict:
    return {"keyboard": rows, "resize_keyboard": True, "one_time_keyboard": False}


def main_menu_markup() -> dict:
    return build_keyboard(
        [
            ["Run", "Status"],
            ["Accounts", "Prompts"],
            ["Settings", "Help"],
        ]
    )


def accounts_menu_markup() -> dict:
    return build_keyboard(
        [
            ["List", "Select"],
            ["Add", "Edit"],
            ["Back"],
        ]
    )


def models_menu_markup() -> dict:
    return build_keyboard(
        [
            ["Gemini", "OpenAI"],
            ["Video"],
            ["Back"],
        ]
    )


def run_confirm_markup() -> dict:
    return build_keyboard(
        [
            ["Start", "Cancel"],
            ["Back"],
        ]
    )


def is_allowed(user_id: int) -> bool:
    allowed = settings.get_setting("allowed_user_ids", default=[])
    if not allowed:
        return True
    return user_id in allowed


def load_accounts_data() -> dict:
    return accounts.load_accounts()


def save_accounts_data(data: dict) -> None:
    path = os.path.join(os.path.dirname(__file__), "accounts.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=True)


def load_prompts_data() -> dict:
    path = os.path.join(os.path.dirname(__file__), "prompts.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_prompts_data(data: dict) -> None:
    path = os.path.join(os.path.dirname(__file__), "prompts.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=True)


def load_settings_data() -> dict:
    path = os.path.join(os.path.dirname(__file__), "settings.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_settings_data(data: dict) -> None:
    path = os.path.join(os.path.dirname(__file__), "settings.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=True)


def update_job(state: dict, job_id: str, **kwargs) -> None:
    jobs = state.setdefault("jobs", {})
    job = jobs.setdefault(job_id, {})
    job.update(kwargs)
    save_state(state)


def run_pipeline(token: str, chat_id: int, user_id: str, job_id: str, account_alias: str, model: str):
    state = load_state()
    update_job(state, job_id, status="running", started_at=time.time())
    try:
        account = accounts.get_account(account_alias)
        send_message(token, chat_id, f"▶ Парсинг начат ({account_alias})")
        parse.run_bot(account, headless=True)

        send_message(token, chat_id, f"▶ Генерация начата ({model})")
        if model == "gemini":
            main1.process_account(account)
            media_kind = "image"
        elif model == "openai":
            main.process_account(account)
            media_kind = "image"
        else:
            main3.process_account_videos(account["alias"])
            media_kind = "video"

        send_message(token, chat_id, "▶ Публикация начата")
        for board_id in proxy.list_account_board_ids(account):
            proxy.publish_generated_board(account, board_id, media_kind=media_kind)

        update_job(state, job_id, status="done", finished_at=time.time())
        send_message(token, chat_id, "✅ Готово")
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        update_job(state, job_id, status="error", error=err, finished_at=time.time())
        send_message(token, chat_id, f"❌ Ошибка: {err}")
        traceback.print_exc()
    finally:
        state = load_state()
        user_state = get_user_state(state, user_id)
        user_state["running_job"] = None
        save_state(state)


def handle_pending(token: str, chat_id: int, user_id: str, text: str, state: dict) -> bool:
    user_state = get_user_state(state, user_id)
    pending = user_state.get("pending")
    if not pending:
        return False

    action = pending.get("action")
    normalized = text.strip().lower()
    if action == "account_add":
        try:
            payload = json.loads(text)
            if not payload.get("alias"):
                send_message(token, chat_id, "❌ В JSON нужен ключ alias")
            else:
                data = load_accounts_data()
                data.setdefault("accounts", []).append(payload)
                save_accounts_data(data)
                send_message(token, chat_id, f"✅ Аккаунт добавлен: {payload['alias']}")
        except Exception as e:
            send_message(token, chat_id, f"❌ Ошибка JSON: {e}")
    elif action == "account_edit":
        alias = pending.get("alias")
        try:
            patch = json.loads(text)
            data = load_accounts_data()
            updated = False
            for acc in data.get("accounts", []):
                if acc.get("alias") == alias:
                    acc.update(patch)
                    updated = True
                    break
            if not updated:
                send_message(token, chat_id, f"❌ Аккаунт не найден: {alias}")
            else:
                save_accounts_data(data)
                send_message(token, chat_id, f"✅ Аккаунт обновлен: {alias}")
        except Exception as e:
            send_message(token, chat_id, f"❌ Ошибка JSON: {e}")
    elif action == "prompt_edit":
        key = pending.get("key")
        data = load_prompts_data()
        data[key] = text
        save_prompts_data(data)
        send_message(token, chat_id, f"✅ Промпт обновлен: {key}")
    elif action == "settings_edit":
        key = pending.get("key")
        data = load_settings_data()
        data[key] = text
        save_settings_data(data)
        send_message(token, chat_id, f"✅ Настройка обновлена: {key}")
    elif action == "run":
        step = pending.get("step")
        if normalized == "back":
            user_state["pending"] = None
            save_state(state)
            send_message(token, chat_id, "Главное меню", reply_markup=main_menu_markup())
            return True

        if step == "choose_account":
            if normalized in ("cancel", "accounts", "settings", "prompts", "status", "help", "run"):
                user_state["pending"] = None
                save_state(state)
                send_message(token, chat_id, "Отменено", reply_markup=main_menu_markup())
                return True

            alias = text.strip()
            try:
                accounts.get_account(alias)
                user_state["account_alias"] = alias
                pending["step"] = "choose_model"
                save_state(state)
                send_message(token, chat_id, "Выбери модель", reply_markup=models_menu_markup())
            except Exception as e:
                send_message(token, chat_id, f"❌ {e}")
            return True

        if step == "choose_model":
            if normalized not in ("gemini", "openai", "video"):
                send_message(token, chat_id, "Выбери модель кнопкой", reply_markup=models_menu_markup())
                return True
            user_state["model"] = normalized
            pending["step"] = "confirm"
            save_state(state)
            send_message(
                token,
                chat_id,
                f"Готово к запуску: аккаунт {user_state.get('account_alias')}, модель {normalized}",
                reply_markup=run_confirm_markup(),
            )
            return True

        if step == "confirm":
            if normalized == "start":
                user_state["pending"] = None
                save_state(state)
                handle_command(token, chat_id, user_id, "/run")
            elif normalized == "cancel":
                user_state["pending"] = None
                save_state(state)
                send_message(token, chat_id, "Отменено", reply_markup=main_menu_markup())
            else:
                send_message(token, chat_id, "Выбери Start или Cancel", reply_markup=run_confirm_markup())
            return True

    elif action == "account_select":
        if normalized == "back":
            user_state["pending"] = None
            save_state(state)
            send_message(token, chat_id, "Аккаунты", reply_markup=accounts_menu_markup())
            return True
        alias = text.strip()
        try:
            accounts.get_account(alias)
            user_state["account_alias"] = alias
            user_state["pending"] = None
            save_state(state)
            send_message(token, chat_id, f"✅ Аккаунт выбран: {alias}", reply_markup=accounts_menu_markup())
        except Exception as e:
            send_message(token, chat_id, f"❌ {e}")
        return True

    user_state["pending"] = None
    save_state(state)
    return True


def handle_command(token: str, chat_id: int, user_id: str, text: str):
    state = load_state()
    user_state = get_user_state(state, user_id)
    normalized = text.strip().lower()

    if text.startswith("/start") or text.startswith("/help") or normalized == "help":
        send_message(
            token,
            chat_id,
            "Команды:\n"
            "/accounts\n"
            "/account_set <alias>\n"
            "/account_add\n"
            "/account_edit <alias>\n"
            "/prompts\n"
            "/prompt_show <key>\n"
            "/prompt_edit <key>\n"
            "/settings\n"
            "/settings_edit <key>\n"
            "/model <gemini|openai>\n"
            "/run\n"
            "/status",
            reply_markup=main_menu_markup(),
        )
        return

    if text.startswith("/accounts") or normalized == "accounts":
        data = load_accounts_data()
        names = [a.get("alias") for a in data.get("accounts", [])]
        send_message(
            token,
            chat_id,
            "Аккаунты: " + ", ".join(names),
            reply_markup=accounts_menu_markup(),
        )
        return

    if text.startswith("/account_set") or normalized == "select":
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            data = load_accounts_data()
            names = [a.get("alias") for a in data.get("accounts", [])]
            if not names:
                send_message(token, chat_id, "❌ Нет аккаунтов", reply_markup=accounts_menu_markup())
            else:
                send_message(
                    token,
                    chat_id,
                    "Выбери alias",
                    reply_markup=build_keyboard([[a] for a in names] + [["Back"]]),
                )
                user_state["pending"] = {"action": "account_select"}
                save_state(state)
            return
        alias = parts[1].strip()
        try:
            accounts.get_account(alias)
            user_state["account_alias"] = alias
            save_state(state)
            send_message(token, chat_id, f"✅ Аккаунт выбран: {alias}", reply_markup=accounts_menu_markup())
        except Exception as e:
            send_message(token, chat_id, f"❌ {e}", reply_markup=accounts_menu_markup())
        return

    if text.startswith("/account_add") or normalized == "add":
        user_state["pending"] = {"action": "account_add"}
        save_state(state)
        send_message(
            token,
            chat_id,
            "Отправь JSON для нового аккаунта (одним сообщением). Пример:\n"
            '{"alias":"acc1","email":"...","password":"...","late_api_key":"...","late_base_url":"https://getlate.dev/api/v1","proxy":{"host":"","port":"","user":"","pass":""}}',
        )
        return

    if text.startswith("/account_edit") or normalized == "edit":
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            send_message(token, chat_id, "❌ Укажи alias: /account_edit <alias>")
            return
        alias = parts[1].strip()
        user_state["pending"] = {"action": "account_edit", "alias": alias}
        save_state(state)
        send_message(
            token,
            chat_id,
            "Отправь JSON с полями для обновления аккаунта (одним сообщением).",
        )
        return

    if text.startswith("/prompts") or normalized == "prompts":
        data = load_prompts_data()
        keys = ", ".join(sorted(data.keys()))
        send_message(
            token,
            chat_id,
            "Промпты: " + keys + "\nПосмотреть: /prompt_show <key>",
            reply_markup=main_menu_markup(),
        )
        return

    if text.startswith("/prompt_show"):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            send_message(token, chat_id, "❌ Укажи ключ: /prompt_show <key>")
            return
        key = parts[1].strip()
        data = load_prompts_data()
        if key not in data:
            send_message(token, chat_id, f"❌ Не найден ключ: {key}")
            return
        send_message(token, chat_id, data[key], reply_markup=main_menu_markup())
        return

    if text.startswith("/prompt_edit"):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            send_message(token, chat_id, "❌ Укажи ключ: /prompt_edit <key>")
            return
        key = parts[1].strip()
        user_state["pending"] = {"action": "prompt_edit", "key": key}
        save_state(state)
        send_message(token, chat_id, f"Отправь новый текст промпта для {key}")
        return

    if text.startswith("/settings") or normalized == "settings":
        data = load_settings_data()
        keys = ", ".join(sorted(data.keys()))
        send_message(token, chat_id, "Настройки: " + keys, reply_markup=main_menu_markup())
        return

    if text.startswith("/settings_edit"):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            send_message(token, chat_id, "❌ Укажи ключ: /settings_edit <key>")
            return
        key = parts[1].strip()
        user_state["pending"] = {"action": "settings_edit", "key": key}
        save_state(state)
        send_message(token, chat_id, f"Отправь новое значение для {key}")
        return

    if text.startswith("/model") or normalized in ("gemini", "openai", "video"):
        parts = text.split(maxsplit=1)
        if len(parts) < 2 and normalized not in ("gemini", "openai", "video"):
            send_message(token, chat_id, "❌ Укажи модель: /model gemini|openai")
            return
        model = normalized if normalized in ("gemini", "openai", "video") else parts[1].strip().lower()
        if model not in ("gemini", "openai", "video"):
            send_message(token, chat_id, "❌ Доступны: gemini, openai")
            return
        user_state["model"] = model
        save_state(state)
        send_message(token, chat_id, f"✅ Модель выбрана: {model}", reply_markup=main_menu_markup())
        return

    if text.startswith("/status") or normalized == "status":
        job_id = user_state.get("last_job")
        if not job_id:
            send_message(token, chat_id, "Нет задач", reply_markup=main_menu_markup())
            return
        job = state.get("jobs", {}).get(job_id, {})
        status = job.get("status", "unknown")
        send_message(token, chat_id, f"Статус: {status}", reply_markup=main_menu_markup())
        return

    if text.startswith("/run") or normalized == "run":
        if normalized == "run" and not text.startswith("/run"):
            data = load_accounts_data()
            names = [a.get("alias") for a in data.get("accounts", [])]
            if not names:
                send_message(token, chat_id, "❌ Нет аккаунтов")
                return
            user_state["pending"] = {"action": "run", "step": "choose_account"}
            save_state(state)
            send_message(
                token,
                chat_id,
                "Выбери аккаунт",
                reply_markup=build_keyboard([[a] for a in names] + [["Back"]]),
            )
            return

        if user_state.get("running_job"):
            send_message(token, chat_id, "⏳ Уже выполняется задача")
            return
        alias = user_state.get("account_alias")
        model = user_state.get("model")
        if not alias:
            send_message(token, chat_id, "❌ Выбери аккаунт: /account_set <alias>")
            return
        if not model:
            send_message(token, chat_id, "❌ Выбери модель: /model gemini|openai")
            return

        job_id = str(int(time.time() * 1000))
        user_state["last_job"] = job_id
        user_state["running_job"] = job_id
        save_state(state)
        update_job(state, job_id, status="queued", account_alias=alias, model=model)
        send_message(token, chat_id, f"✅ Задача запущена: {job_id}")
        t = threading.Thread(
            target=run_pipeline,
            args=(token, chat_id, user_id, job_id, alias, model),
            daemon=True,
        )
        t.start()
        return

    if normalized == "back":
        send_message(token, chat_id, "Главное меню", reply_markup=main_menu_markup())
        return

    if normalized == "list":
        handle_command(token, chat_id, user_id, "/accounts")
        return

    prompts_data = load_prompts_data()
    if text in prompts_data:
        send_message(token, chat_id, prompts_data[text], reply_markup=main_menu_markup())
        return

    send_message(token, chat_id, "Неизвестная команда. /help", reply_markup=main_menu_markup())


def main_loop():
    token = settings.get_setting("telegram_bot_token", env_var="TELEGRAM_BOT_TOKEN") or ""
    if not token:
        print("❌ Не задан telegram_bot_token в settings.json или TELEGRAM_BOT_TOKEN")
        return

    offset = 0
    while True:
        try:
            resp = requests.get(
                f"https://api.telegram.org/bot{token}/getUpdates",
                params={"timeout": 30, "offset": offset},
                timeout=40,
            )
            data = resp.json()
        except Exception:
            time.sleep(2)
            continue

        if not data.get("ok"):
            time.sleep(2)
            continue

        for upd in data.get("result", []):
            offset = max(offset, upd["update_id"] + 1)
            msg = upd.get("message") or {}
            text = msg.get("text")
            if not text:
                continue
            user = msg.get("from") or {}
            user_id = user.get("id")
            chat_id = msg.get("chat", {}).get("id")
            if user_id is None or chat_id is None:
                continue
            if not is_allowed(user_id):
                send_message(token, chat_id, "❌ Доступ запрещен")
                continue

            state = load_state()
            if not text.startswith("/") and handle_pending(token, chat_id, str(user_id), text, state):
                continue

            handle_command(token, chat_id, str(user_id), text)

        time.sleep(0.2)


if __name__ == "__main__":
    main_loop()
