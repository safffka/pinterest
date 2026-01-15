import os
import base64
import json
import requests
import accounts
import prompts
import settings



OPENAI_KEY = (
    settings.get_setting("openai_api_key", env_var="OPENAI_API_KEY") or ""
).strip()





# ================== 1) ОПИСАНИЕ ИЗОБРАЖЕНИЯ ==================

def describe_image(image_path: str) -> str:
    """
    GPT-4.1 Vision описание картинки
    """
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()

    payload = {
        "model": "gpt-4.1",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64}"}
                    },
                    {
                        "type": "text",
                        "text": (
                            "Describe this image in 3–4 sentences. Focus strictly on: "
                            "mood, colors, outfit, fashion style, background, "
                            "lighting, composition. Describe it as an aesthetic Pinterest photo."
                        )
                    }
                ]
            }
        ]
    }

    r = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENAI_KEY}",
            "Content-Type": "application/json"
        },
        json=payload,
        timeout=60
    )
    r.raise_for_status()

    return r.json()["choices"][0]["message"]["content"]


# ================== 2) ГЕНЕРАЦИЯ ИЗОБРАЖЕНИЯ ==================

def generate_image_from_description(description: str) -> bytes:
    """
    GPT-Image-1 по улучшенному prompt
    """

    prompt = prompts.render_prompt("openai_image_prompt", description=description)

    payload = {
        "model": "gpt-image-1",
        "prompt": prompt,
        "size": "1024x1024"
    }

    r = requests.post(
        "https://api.openai.com/v1/images/generations",
        headers={"Authorization": f"Bearer {OPENAI_KEY}"},
        json=payload,
        timeout=90
    )
    r.raise_for_status()
    b64 = r.json()["data"][0]["b64_json"]
    return base64.b64decode(b64)


# ================== 3) ГЕНЕРАЦИЯ SEO-МЕТАДАННЫХ ==================

def generate_seo_metadata(board_name: str, description: str) -> dict:
    """
    Делает:
    - SEO title
    - Pinterest description
    - 10 хештегов
    - alt-text
    """
    payload = {
        "model": "gpt-4.1",
        "messages": [
            {
                "role": "user",
                "content": (
                    f"Board: {board_name}\n\n"
                    f"Image style description: {description}\n\n"
                    "Generate Pinterest metadata:\n"
                    "- short SEO title (max 60 chars)\n"
                    "- Pinterest pin description (1–2 sentences)\n"
                    "- 10 aesthetic hashtags\n"
                    "- alt-text (1 sentence)\n"
                    "Return JSON keys: title, pin_description, hashtags, alt"
                )
            }
        ]
    }

    r = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENAI_KEY}",
            "Content-Type": "application/json"
        },
        json=payload,
        timeout=40
    )
    r.raise_for_status()

    return json.loads(r.json()["choices"][0]["message"]["content"])


# ================== 4) PIPELINE ДЛЯ 1 КАРТИНКИ ==================

def process_single_image(image_path: str, out_dir: str, board_name: str, index: int):
    print(f"\n📸 Обработка изображения {index}: {image_path}")

    # 1. Описание
    try:
        description = describe_image(image_path)
    except Exception as e:
        print(f"❌ Ошибка описания изображения: {image_path} ({e})")
        return None, None
    print("📝 Описание:", description)

    # 2. Генерация новой картинки
    print("🎨 Генерация нового изображения…")
    try:
        new_img_bytes = generate_image_from_description(description)
    except Exception as e:
        print(f"❌ Ошибка генерации изображения: {image_path} ({e})")
        return None, None

    # 3. Генерация SEO-текста
    try:
        metadata = generate_seo_metadata(board_name, description)
    except Exception as e:
        print(f"❌ Ошибка генерации метаданных: {board_name} ({e})")
        return None, None

    # 4. Сохранение
    os.makedirs(out_dir, exist_ok=True)

    img_path = os.path.join(out_dir, f"{index}.jpg")
    json_path = os.path.join(out_dir, f"{index}.json")

    try:
        with open(img_path, "wb") as f:
            f.write(new_img_bytes)
    except Exception as e:
        print(f"❌ Ошибка сохранения изображения: {img_path} ({e})")
        return None, None

    try:
        with open(json_path, "w") as f:
            json.dump(
                {
                    "original_description": description,
                    "metadata": metadata,
                },
                f,
                indent=2,
                ensure_ascii=False,
            )
    except Exception as e:
        print(f"❌ Ошибка сохранения метаданных: {json_path} ({e})")
        return img_path, None

    print("✔ Новая картинка:", img_path)
    print("✔ Метаданные:", json_path)

    return img_path, json_path


# ================== 5) ОБРАБОТКА ВСЕЙ ДОСКИ ==================

def process_board(board_id: str, board_name: str, input_folder: str, output_folder: str, limit=5):
    if not os.path.isdir(input_folder):
        raise RuntimeError(f"❌ Папка не найдена: {input_folder}")

    files = sorted([
        f for f in os.listdir(input_folder)
        if f.lower().endswith((".jpg", ".jpeg", ".png"))
    ])

    files = files[:limit]

    print(f"\n=== ▶ Генерация по доске: {board_name} ({board_id}) ===")
    if not files:
        print(f"⚠ Нет референсов для {board_name} ({board_id}), пропускаю")
        return
    print("Найдено файлов:", files)

    for i, f in enumerate(files, start=1):
        process_single_image(os.path.join(input_folder, f), output_folder, board_name, i)


def list_account_boards(account) -> list[dict]:
    base_dir = os.path.join("boards", account["alias"])
    if not os.path.isdir(base_dir):
        return []

    boards = []
    for board_id in sorted(os.listdir(base_dir)):
        board_dir = os.path.join(base_dir, board_id)
        if not os.path.isdir(board_dir):
            continue

        meta_path = os.path.join(board_dir, "board.json")
        if not os.path.isfile(meta_path):
            continue

        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

        boards.append(
            {
                "id": meta.get("id", board_id),
                "name": meta.get("name", board_id),
                "input_dir": board_dir,
            }
        )

    return boards


def process_account(account, limit=5):
    boards = list_account_boards(account)
    if not boards:
        print("❌ Boards not found for account:", account["alias"])
        return

    for b in boards:
        output_dir = os.path.join("generated", account["alias"], b["id"])
        process_board(
            board_id=b["id"],
            board_name=b["name"],
            input_folder=b["input_dir"],
            output_folder=output_dir,
            limit=limit,
        )


# ================== 6) ЗАПУСК ==================

if __name__ == "__main__":
    account = accounts.get_account_from_env()
    process_account(account, limit=5)
