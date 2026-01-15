import base64
import os
import time
import requests
import subprocess
import json

import settings
import main1

# ================== CONFIG ==================

FREEPIK_API_KEY = settings.get_setting("freepik_api_key", env_var="FREEPIK_API_KEY") or ""
FREEPIK_BASE_URL = "https://api.freepik.com/v1/ai/image-to-video/kling-v2-5-pro"


# ================== UTILS ==================

def encode_image(image_path_or_url: str) -> str:
    if image_path_or_url.startswith("http://") or image_path_or_url.startswith("https://"):
        return image_path_or_url

    with open(image_path_or_url, "rb") as f:
        return base64.b64encode(f.read()).decode()


def freepik_headers() -> dict:
    return {
        "Content-Type": "application/json",
        "x-freepik-api-key": FREEPIK_API_KEY,
    }


# ================== API ==================

def create_video_task(
    image_path_or_url: str,
    prompt: str,
    negative_prompt: str = "",
    duration: str = "5",
    cfg_scale: float = 0.5,
    webhook_url: str | None = None,
) -> dict:
    payload = {
        "duration": duration,
        "image": encode_image(image_path_or_url),
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "cfg_scale": cfg_scale,
    }
    if webhook_url:
        payload["webhook_url"] = webhook_url

    r = requests.post(FREEPIK_BASE_URL, headers=freepik_headers(), json=payload, timeout=60)
    r.raise_for_status()
    return r.json()


def get_task_status(task_id: str) -> dict:
    url = f"{FREEPIK_BASE_URL}/{task_id}"
    r = requests.get(url, headers=freepik_headers(), timeout=60)
    r.raise_for_status()
    return r.json()


def extract_video_url(resp: dict) -> str | None:
    data = resp.get("data") or {}
    for key in ("video_url", "url"):
        if isinstance(data.get(key), str):
            return data[key]
    if isinstance(data.get("video"), dict):
        url = data["video"].get("url")
        if isinstance(url, str):
            return url
    if isinstance(data.get("output"), list) and data["output"]:
        first = data["output"][0]
        if isinstance(first, dict) and isinstance(first.get("url"), str):
            return first["url"]
    if isinstance(data.get("generated"), list) and data["generated"]:
        first = data["generated"][0]
        if isinstance(first, str):
            return first
    return None


def wait_for_completion(task_id: str, timeout_sec: int = 900, poll_interval: int = 5) -> dict:
    started = time.time()
    while time.time() - started < timeout_sec:
        resp = get_task_status(task_id)
        status = (resp.get("data") or {}).get("status")
        if status in ("COMPLETED", "FAILED"):
            return resp
        time.sleep(poll_interval)
    raise TimeoutError(f"Task timed out: {task_id}")


def download_video(video_url: str, out_path: str) -> None:
    r = requests.get(video_url, timeout=120)
    r.raise_for_status()
    with open(out_path, "wb") as f:
        f.write(r.content)


def overlay_text_on_video(
    input_mp4: str,
    output_mp4: str,
    text: str,
    font_path: str | None = None,
    font_size: int = 64,
    font_color: str = "white",
    box: bool = True,
    box_color: str = "black@0.35",
    x: str = "(w-text_w)/2",
    y: str = "h*0.08",
):
    font_arg = f":fontfile={font_path}" if font_path else ""
    drawtext = (
        f"drawtext=text='{text}':fontsize={font_size}:fontcolor={font_color}"
        f"{font_arg}:x={x}:y={y}"
    )
    if box:
        drawtext += f":box=1:boxcolor={box_color}:boxborderw=12"

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        input_mp4,
        "-vf",
        drawtext,
        "-codec:a",
        "copy",
        output_mp4,
    ]
    subprocess.run(cmd, check=True)


# ================== PIPELINE ==================

def animate_pin(
    image_path_or_url: str,
    out_mp4: str,
    prompt: str,
    negative_prompt: str = "",
    duration: str = "5",
    cfg_scale: float = 0.5,
    webhook_url: str | None = None,
):
    if not FREEPIK_API_KEY:
        raise RuntimeError("Freepik API key not set (freepik_api_key)")

    task = create_video_task(
        image_path_or_url=image_path_or_url,
        prompt=prompt,
        negative_prompt=negative_prompt,
        duration=duration,
        cfg_scale=cfg_scale,
        webhook_url=webhook_url,
    )
    task_id = (task.get("data") or {}).get("task_id")
    if not task_id:
        raise RuntimeError(f"Task id not found: {task}")

    print(f"🟡 Task created: {task_id}")
    result = wait_for_completion(task_id)
    status = (result.get("data") or {}).get("status")
    if status != "COMPLETED":
        raise RuntimeError(f"Task failed: {result}")

    video_url = extract_video_url(result)
    if not video_url:
        raise RuntimeError(f"Video URL not found: {result}")

    os.makedirs(os.path.dirname(out_mp4) or ".", exist_ok=True)
    download_video(video_url, out_mp4)
    print(f"✅ Done: {out_mp4}")


def load_board_style(account_alias: str, board_id: str) -> str:
    style_path = os.path.join("generated_gemini", account_alias, board_id, "_base_style.txt")
    if os.path.isfile(style_path):
        with open(style_path, "r", encoding="utf-8") as f:
            return f.read().strip()

    board_dir = os.path.join("boards", account_alias, board_id)
    if not os.path.isdir(board_dir):
        raise RuntimeError(f"Board directory not found: {board_dir}")

    files = [
        f for f in os.listdir(board_dir)
        if f.lower().endswith((".jpg", ".jpeg", ".png"))
    ]
    if not files:
        raise RuntimeError(f"No reference images found in: {board_dir}")

    style = main1.gemini_describe_image(os.path.join(board_dir, files[0]))
    os.makedirs(os.path.dirname(style_path), exist_ok=True)
    with open(style_path, "w", encoding="utf-8") as f:
        f.write(style)
    return style


def generate_clean_promo_image(style_description: str, out_path: str) -> str:
    img = main1.gemini_generate_promo_image(style_description)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(img)
    return out_path


def animate_promo_video_from_board(
    account_alias: str,
    board_id: str,
    out_mp4: str,
    promo_text: str = "Remote work for women",
    duration: str = "5",
    cfg_scale: float = 0.9,
):
    style = load_board_style(account_alias, board_id)
    clean_path = os.path.join("generated_gemini", account_alias, board_id, "promo_clean.jpg")
    generate_clean_promo_image(style, clean_path)

    prompt = (
        "subtle motion, slow camera zoom, gentle parallax, soft cinematic lighting; "
        "no text, no logos, clean empty space at top for text overlay"
    )
    negative = "text, logos, distorted text, unreadable letters, blurry text, heavy motion, extra text"

    tmp_mp4 = f"{out_mp4}.tmp.mp4"
    animate_pin(
        image_path_or_url=clean_path,
        out_mp4=tmp_mp4,
        prompt=prompt,
        negative_prompt=negative,
        duration=duration,
        cfg_scale=cfg_scale,
    )

    font_path = settings.get_setting("ffmpeg_font_path") or None
    overlay_text_on_video(
        input_mp4=tmp_mp4,
        output_mp4=out_mp4,
        text=promo_text,
        font_path=font_path,
        font_size=72,
        font_color="white",
        box=False,
        x="(w-text_w)/2",
        y="h*0.08",
    )
    os.remove(tmp_mp4)


def list_account_boards(account_alias: str) -> list[dict]:
    base_dir = os.path.join("boards", account_alias)
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
                "dir": board_dir,
            }
        )

    return boards


def process_account_videos(
    account_alias: str,
    promo_text: str = "Remote work for women",
    duration: str = "5",
    cfg_scale: float = 0.9,
):
    boards = list_account_boards(account_alias)
    if not boards:
        print("❌ Boards not found for account:", account_alias)
        return

    for b in boards:
        board_dir = b["dir"]
        ref_files = [
            f for f in os.listdir(board_dir)
            if f.lower().endswith((".jpg", ".jpeg", ".png"))
        ]
        if not ref_files:
            print(f"⚠ Нет референсов для {b['name']} ({b['id']}), пропускаю")
            continue

        out_dir = os.path.join("generated_videos", account_alias, b["id"])
        os.makedirs(out_dir, exist_ok=True)

        # 1) Base style for metadata
        base_style = load_board_style(account_alias, b["id"])

        # 2) 4 обычных видео по референсам
        for idx, filename in enumerate(ref_files[:4], start=1):
            src_path = os.path.join(board_dir, filename)
            out_mp4 = os.path.join(out_dir, f"{idx}.mp4")
            out_json = os.path.join(out_dir, f"{idx}.json")

            if not os.path.exists(out_mp4):
                prompt = (
                    "subtle motion, slow camera zoom, gentle parallax, "
                    "soft cinematic lighting; no text, no logos"
                )
                negative = "text, logos, distorted text, heavy motion"
                animate_pin(
                    image_path_or_url=src_path,
                    out_mp4=out_mp4,
                    prompt=prompt,
                    negative_prompt=negative,
                    duration=duration,
                    cfg_scale=cfg_scale,
                )

            if not os.path.exists(out_json):
                meta = main1.gemini_generate_metadata(b["name"], base_style)
                with open(out_json, "w", encoding="utf-8") as f:
                    json.dump({"metadata": meta}, f, indent=2, ensure_ascii=False)

        # 3) Promo video с текстом
        promo_video = os.path.join(out_dir, "5.mp4")
        promo_json = os.path.join(out_dir, "5.json")
        if not os.path.exists(promo_video):
            animate_promo_video_from_board(
                account_alias=account_alias,
                board_id=b["id"],
                out_mp4=promo_video,
                promo_text=promo_text,
                duration=duration,
                cfg_scale=cfg_scale,
            )

        if not os.path.exists(promo_json):
            promo_url = main1.mutate_url(main1.PROMO_BASE_URL)
            promo_meta = main1.build_promo_metadata(b["name"], promo_url)
            with open(promo_json, "w", encoding="utf-8") as f:
                json.dump({"metadata": promo_meta}, f, indent=2, ensure_ascii=False)


# ================== RUN ==================

if __name__ == "__main__":
    animate_pin(
        image_path_or_url="/Users/savage/PycharmProjects/pinterest/boards/Ballet_core/Ballet Clas.jpeg",
        out_mp4="pin.mp4",
        prompt="subtle motion, slow camera zoom, gentle parallax, soft cinematic lighting",
        negative_prompt="text, logos, heavy motion",
        duration="5",
        cfg_scale=0.5,
    )
