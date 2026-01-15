import base64
import json
import os
import random
import time
from typing import Optional

import requests
from PIL import Image, ImageFont
import accounts
import prompts
import settings

# ================== CONFIG ==================

GEMINI_API_KEY = settings.get_setting("gemini_api_key", env_var="GEMINI_API_KEY") or ""
BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
PROMO_BASE_URL = "https://Solomoon-agency.com"

VISION_MODEL = "gemini-2.5-flash"

IMAGE_MODEL = "gemini-2.5-flash-image"


RATE_LIMIT_SLEEP = (0.6, 1.2)

# ================== RETRY ==================

def retry_call(fn, max_retries=10, base_delay=2, max_delay=30):
    for attempt in range(1, max_retries + 1):
        try:
            return fn()
        except (requests.exceptions.HTTPError, GeminiEmptyResponse) as e:
            if attempt == max_retries:
                print("❌ Retries exhausted")
                raise

            delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
            delay += random.uniform(0, 1)
            print(
                f"⏳ Gemini unstable ({type(e).__name__}), "
                f"retry {attempt}/{max_retries} in {delay:.1f}s"
            )
            time.sleep(delay)


# ================== HTTP ==================

def _post_gemini(model: str, endpoint_suffix: str, payload: dict, timeout: int = 60) -> dict:
    url = f"{BASE_URL}/{model}:{endpoint_suffix}"
    headers = {
        "x-goog-api-key": GEMINI_API_KEY,
        "Content-Type": "application/json",
    }

    r = requests.post(url, headers=headers, json=payload, timeout=timeout)

    if not r.ok:
        print(f"❌ Gemini API error ({r.status_code}): {r.text}")
        r.raise_for_status()

    time.sleep(random.uniform(*RATE_LIMIT_SLEEP))
    return r.json()

# ================== UTILS ==================

def mutate_url(url: str) -> str:
    ts = int(time.time() * 1000)
    rnd = random.randint(1000, 9999)
    return f"{url}?_={ts}{rnd}"

def get_default_ttf(size: int):
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except:
        return ImageFont.load_default()


class GeminiEmptyResponse(Exception):
    pass

def _safe_get_parts(resp: dict):
    cand = resp.get("candidates", [{}])[0]
    content = cand.get("content")

    if not content:
        raise GeminiEmptyResponse("Gemini returned no content")

    parts = content.get("parts")
    if not parts:
        raise GeminiEmptyResponse("Gemini returned empty parts")

    return parts

# ================== GEMINI ==================

def gemini_describe_image(image_path: str) -> str:
    mime_type = "image/png" if image_path.lower().endswith(".png") else "image/jpeg"

    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()

    payload = {
        "contents": [{
            "role": "user",
            "parts": [
                {"inlineData": {"mimeType": mime_type, "data": b64}},
                {"text": (
                    "Analyze this Pinterest-style fashion photo and describe ONLY its aesthetic style: "
                    "mood, color palette, textures, fashion style, lighting, framing, background. "
                    "Return 4–6 sentences. Do NOT mention brands or list objects."
                )}
            ]
        }]
    }

    resp = retry_call(lambda: _post_gemini(VISION_MODEL, "generateContent", payload))
    parts = _safe_get_parts(resp)

    return " ".join(p["text"] for p in parts if "text" in p).strip()

def gemini_generate_similar_image(style_description: str) -> bytes:
    payload = {
        "contents": [{
            "parts": [{
                "text": prompts.render_prompt(
                    "gemini_image_prompt",
                    style_description=style_description,
                )
            }]
        }],
        "generationConfig": {
            "responseModalities": ["IMAGE"],
            "imageConfig": {"aspectRatio": "1:1"}
        }
    }

    resp = retry_call(lambda: _post_gemini(IMAGE_MODEL, "generateContent", payload, 120))
    parts = _safe_get_parts(resp)

    for p in parts:
        if "inlineData" in p:
            return base64.b64decode(p["inlineData"]["data"])

    raise RuntimeError("❌ Image not found in Gemini response")

def gemini_generate_promo_image(style_description: str) -> bytes:
    payload = {
        "contents": [{
            "parts": [{
                "text": prompts.render_prompt(
                    "gemini_promo_prompt",
                    style_description=style_description,
                )
            }]
        }],
        "generationConfig": {
            "responseModalities": ["IMAGE"],
            "imageConfig": {"aspectRatio": "1:1"}
        }
    }

    resp = retry_call(
        lambda: _post_gemini(IMAGE_MODEL, "generateContent", payload, 120)
    )
    parts = _safe_get_parts(resp)

    for p in parts:
        if "inlineData" in p:
            return base64.b64decode(p["inlineData"]["data"])

    raise RuntimeError("❌ Promo image not found")

def gemini_generate_metadata(board_name: str, style_description: str) -> dict:
    payload = {
        "contents": [{
            "role": "user",
            "parts": [{
                "text": f"""
Board: {board_name}

Style:
{style_description}

Return valid JSON with:
title, description, hashtags (list), alt
"""
            }]
        }]
    }

    resp = retry_call(lambda: _post_gemini(VISION_MODEL, "generateContent", payload))
    parts = _safe_get_parts(resp)

    raw = " ".join(p["text"] for p in parts if "text" in p)
    start, end = raw.find("{"), raw.rfind("}")
    return json.loads(raw[start:end + 1])

def build_promo_metadata(board_name: str, promo_url: str) -> dict:
    return {
        "title": "Удалённая работа для девушек",
        "description": (
            "Работа для девушек из Украины. Полностью удалённый формат.\n\n"
            f"👉 Подробнее: {promo_url}"
        ),
        "hashtags": [
            "удаленнаяработа",
            "работаонлайн",
            "remotejob",
            "freelance",
            "длядевушек"
        ],
        "alt": "Работай из любой точки мира и будь независимой",
        "link": promo_url
    }


# ================== PIPELINE ==================

def process_single_image(
    image_path: str,
    out_dir: str,
    board_name: str,
    index: int,
    base_style: Optional[str] = None
):
    os.makedirs(out_dir, exist_ok=True)

    img_path = os.path.join(out_dir, f"{index}.jpg")
    json_path = os.path.join(out_dir, f"{index}.json")

    try:
        style = base_style or gemini_describe_image(image_path)
    except Exception as e:
        print(f"❌ Ошибка описания изображения: {image_path} ({e})")
        return

    if not os.path.exists(img_path):
        try:
            img = gemini_generate_similar_image(style)
        except Exception as e:
            print(f"❌ Ошибка генерации изображения: {image_path} ({e})")
            return
        with open(img_path, "wb") as f:
            f.write(img)
        print(f"✔ Image {index} generated")

    if not os.path.exists(json_path):
        try:
            meta = gemini_generate_metadata(board_name, style)
        except Exception as e:
            print(f"❌ Ошибка генерации метаданных: {board_name} ({e})")
            return
        with open(json_path, "w") as f:
            json.dump({"style": style, "metadata": meta}, f, indent=2, ensure_ascii=False)
        print(f"✔ Metadata {index} generated")


def overlay_text_block(
    background_path: str,
    text_block_path: str,
    output_path: str,
    position: str = "top",   # "top" | "center"
    scale: float = 0.6,
):
    """
    Вставляет готовую текстовую картинку на промо-пин
    """

    bg = Image.open(background_path).convert("RGBA")
    txt = Image.open(text_block_path).convert("RGBA")

    BW, BH = bg.size

    # --- масштаб ---
    new_w = int(BW * scale)
    ratio = new_w / txt.width
    new_h = int(txt.height * ratio)
    txt = txt.resize((new_w, new_h), Image.LANCZOS)

    # --- позиция ---
    if position == "top":
        x = (BW - new_w) // 2
        y = int(BH*0.001)
    elif position == "center":
        x = (BW - new_w) // 2
        y = (BH - new_h) // 2
    else:
        raise ValueError("position must be top or center")

    bg.alpha_composite(txt, (x, y))
    bg.convert("RGB").save(output_path, quality=95)

def process_board(
    board_id: str,
    board_name: str,
    input_dir: str,
    output_dir: str,
    limit: int = 5,
):

    os.makedirs(output_dir, exist_ok=True)

    files = sorted(
        f for f in os.listdir(input_dir)
        if f.lower().endswith((".jpg", ".jpeg", ".png"))
    )[:limit]

    print(f"\n=== ▶ {board_name} ({board_id}) ({len(files)} files) ===")
    if not files:
        print(f"⚠ Нет референсов для {board_name} ({board_id}), пропускаю")
        return

    # --------------------------------------------------
    # 1️⃣ BASE STYLE (CACHE)
    # --------------------------------------------------
    style_cache_path = os.path.join(output_dir, "_base_style.txt")

    if os.path.exists(style_cache_path):
        with open(style_cache_path, "r", encoding="utf-8") as f:
            base_style = f.read().strip()
        print("⏭ base_style loaded from cache")
    else:
        try:
            base_style = gemini_describe_image(os.path.join(input_dir, files[0]))
        except Exception as e:
            print(f"❌ Ошибка base_style для {board_name}: {e}")
            return
        with open(style_cache_path, "w", encoding="utf-8") as f:
            f.write(base_style)
        print("✔ base_style cached")

    # --------------------------------------------------
    # 2️⃣ 4 Обычных пина
    # --------------------------------------------------
    for i, filename in enumerate(files[:4], start=1):
        process_single_image(
            image_path=os.path.join(input_dir, filename),
            out_dir=output_dir,
            board_name=board_name,
            index=i,
            base_style=base_style,
        )

    # --------------------------------------------------
    # 3️⃣ PROMO PIN (BACKGROUND → TEXT OVERLAY)
    # --------------------------------------------------
    promo_raw_path = os.path.join(output_dir, "promo_raw.jpg")
    promo_final_path = os.path.join(output_dir, "5.jpg")
    promo_json_path = os.path.join(output_dir, "5.json")

    # --- 3.1 Генерация фона (без текста) ---
    if not os.path.exists(promo_raw_path):
        print("📢 Generating promo background (no text)")
        try:
            promo_img = gemini_generate_promo_image(base_style)
        except Exception as e:
            print(f"❌ Ошибка генерации promo фона: {board_name} ({e})")
            return
        with open(promo_raw_path, "wb") as f:
            f.write(promo_img)
        print("✔ promo_raw.jpg saved")
    else:
        print("⏭ promo_raw.jpg exists, skip")

    # --- 3.2 Наложение текста ---
    try:
        overlay_text_block(
            background_path=promo_raw_path,
            text_block_path="text_layer.png",
            output_path=promo_final_path,
            position="top",
            scale=0.6,
        )
    except Exception as e:
        print(f"❌ Ошибка наложения текста: {board_name} ({e})")
        return

    print("✔ 5.jpg generated")

    # --------------------------------------------------
    # 4️⃣ PROMO METADATA (LINK В ТЕКСТЕ)
    # --------------------------------------------------
    promo_url = mutate_url(PROMO_BASE_URL)
    promo_meta = build_promo_metadata(board_name, promo_url)

    try:
        with open(promo_json_path, "w", encoding="utf-8") as f:
            json.dump(promo_meta, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"❌ Ошибка сохранения promo метаданных: {board_name} ({e})")
        return

    print("✔ 5.json saved (link in description)")
    try:
        os.remove(promo_raw_path)
    except Exception as e:
        print(f"❌ Ошибка удаления promo_raw: {promo_raw_path} ({e})")


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


def process_account(account, limit: int = 5):
    boards = list_account_boards(account)
    if not boards:
        print("❌ Boards not found for account:", account["alias"])
        return

    for b in boards:
        output_dir = os.path.join("generated_gemini", account["alias"], b["id"])
        process_board(
            board_id=b["id"],
            board_name=b["name"],
            input_dir=b["input_dir"],
            output_dir=output_dir,
            limit=limit,
        )

# ================== RUN ==================

if __name__ == "__main__":
    account = accounts.get_account_from_env()
    process_account(account)
