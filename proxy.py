import os
import json
import requests
import accounts

os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"
os.environ["HTTP_PROXY"] = ""
os.environ["HTTPS_PROXY"] = ""

session = requests.Session()
session.trust_env = False

def get_pinterest_account_id(account):
    r = session.get(
        f"{account['late_base_url']}/accounts",
        headers={"Authorization": f"Bearer {account['late_api_key']}"},
    )
    r.raise_for_status()

    for acc in r.json().get("accounts", []):
        if acc.get("platform") == "pinterest":
            return acc["_id"]

    raise RuntimeError("No Pinterest account")



def get_pinterest_boards(account, account_id):
    r = session.get(
        f"{account['late_base_url']}/accounts/{account_id}/pinterest-boards",
        headers={"Authorization": f"Bearer {account['late_api_key']}"},
    )
    r.raise_for_status()

    boards = r.json().get("boards", [])
    print("\n🧩 Доски:")
    for b in boards:
        print(f" • {b['name']} ({b['id']})")

    return boards




def _guess_mime(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext in (".jpg", ".jpeg"):
        return "image/jpeg"
    if ext == ".png":
        return "image/png"
    if ext == ".webp":
        return "image/webp"
    if ext == ".mp4":
        return "video/mp4"
    return "application/octet-stream"


def late_upload_media(account, media_path: str) -> str:
    url = f"{account['late_base_url']}/media"
    headers = {
        "Authorization": f"Bearer {account['late_api_key']}"
    }

    with open(media_path, "rb") as f:
        files = {
            "files": (os.path.basename(media_path), f, _guess_mime(media_path))
        }

        r = session.post(url, headers=headers, files=files, timeout=60)

    print("RAW:", r.text)

    r.raise_for_status()

    data = r.json()


    return data["files"][0]["url"]


def late_publish_pin(
    account,
    pinterest_account_id: str,
    board_id: str,
    title: str,
    description: str,
    media_url: str,
    link: str = None,
    media_type: str | None = "image",
):
    url = f"{account['late_base_url']}/posts"
    headers = {
        "Authorization": f"Bearer {account['late_api_key']}",
        "Content-Type": "application/json"
    }

    payload = {
        "content": description,
        "platforms": [
            {
                "platform": "pinterest",
                "accountId": pinterest_account_id,
                "platformSpecificData": {
                    "title": title,
                    "boardId": board_id,
                }
            }
        ],
        "mediaItems": [
            {
                "url": media_url,
            }
        ]
    }
    if media_type:
        payload["mediaItems"][0]["type"] = media_type

    if link:
        payload["platforms"][0]["platformSpecificData"]["link"] = link

    print("📤 PUBLISHING:", json.dumps(payload, indent=2, ensure_ascii=False))

    r = session.post(url, headers=headers, json=payload, timeout=60)
    if r.status_code != 200:
        print("❌ ERROR:", r.text)
        r.raise_for_status()
    return r.json()


def build_pin_records_from_generated(account, board_id: str, limit=5, media_kind: str = "image"):
    if media_kind == "video":
        folder = os.path.join("generated_videos", account["alias"], board_id)
        media_ext = ".mp4"
    else:
        folder = os.path.join("generated_gemini", account["alias"], board_id)
        media_ext = ".jpg"
    records = []

    files = sorted([f for f in os.listdir(folder) if f.endswith(".json")])[:limit]

    for f in files:
        json_path = os.path.join(folder, f)
        media_path = json_path.replace(".json", media_ext)

        with open(json_path, "r") as jf:
            data = json.load(jf)

        meta = data.get("metadata") or data
        record = {
            "media_path": media_path,
            "json_path": json_path,
            "title": meta.get("title"),
            "description": meta.get("description"),
            "alt_text": meta.get("alt"),
            "hashtags": meta.get("hashtags"),
            "link": meta.get("link"),
        }

        records.append(record)

    return records


def load_board_meta(account, board_id: str) -> dict:
    meta_path = os.path.join("boards", account["alias"], board_id, "board.json")
    if not os.path.isfile(meta_path):
        return {"id": board_id, "name": board_id}

    with open(meta_path, "r", encoding="utf-8") as f:
        return json.load(f)


def list_account_board_ids(account) -> list[str]:
    base_dir = os.path.join("boards", account["alias"])
    if not os.path.isdir(base_dir):
        return []

    board_ids = []
    for board_id in sorted(os.listdir(base_dir)):
        meta_path = os.path.join(base_dir, board_id, "board.json")
        if os.path.isfile(meta_path):
            board_ids.append(board_id)

    return board_ids


def _remove_images_in_dir(dir_path: str) -> int:
    if not os.path.isdir(dir_path):
        return 0
    removed = 0
    for name in os.listdir(dir_path):
        if not name.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
            continue
        path = os.path.join(dir_path, name)
        if os.path.isfile(path):
            os.remove(path)
            removed += 1
    return removed


def publish_generated_board(account, board_id: str, media_kind: str = "image"):
    meta = load_board_meta(account, board_id)
    print("\n=== ▶ Публикация доски:", meta.get("name"), f"({board_id}) ===")
    profile_id = get_pinterest_account_id(account)

    # 2) собираем записи из папки generated/
    pins = build_pin_records_from_generated(account, board_id, media_kind=media_kind)

    print(f"Найдено {len(pins)} записей для публикации")

    published = []

    failed = 0
    # 3) публикация
    for pin in pins:
        try:
            media_url = late_upload_media(account, pin["media_path"])

            media_type = "video" if media_kind == "video" else "image"
            post = late_publish_pin(
                account=account,
                pinterest_account_id=profile_id,
                board_id=board_id,
                title=pin.get("title") or "",
                description=(pin.get("description") or "") + "\n\n" + " ".join(pin.get("hashtags") or []),
                media_url=media_url,
                link=pin.get("link"),  # ← None или строка
                media_type=media_type,
            )

            pin["published"] = post
            pin["media_url"] = media_url
            published.append(pin)

            print("✔ Успешно опубликовано:", pin["title"])
            for path in (pin.get("media_path"), pin.get("json_path")):
                if path and os.path.isfile(path):
                    os.remove(path)
            print("🧹 Удалены файлы пина после публикации")

        except Exception as e:
            print("❌ Ошибка публикации:", e)
            failed += 1

    if pins and failed == 0:
        refs_dir = os.path.join("boards", account["alias"], board_id)
        removed_refs = _remove_images_in_dir(refs_dir)
        gen_gemini_dir = os.path.join("generated_gemini", account["alias"], board_id)
        removed_gen_gemini = _remove_images_in_dir(gen_gemini_dir)
        gen_openai_dir = os.path.join("generated", account["alias"], board_id)
        removed_gen_openai = _remove_images_in_dir(gen_openai_dir)
        if removed_refs or removed_gen_gemini or removed_gen_openai:
            print(
                "🧹 Удалены изображения после публикации: "
                f"refs={removed_refs}, gemini={removed_gen_gemini}, openai={removed_gen_openai}"
            )

    return published

if __name__ == "__main__":
    account = accounts.get_account_from_env()
    for board_id in list_account_board_ids(account):
        publish_generated_board(account, board_id)
