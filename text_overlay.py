from PIL import Image

def crop_to_content(input_path: str, output_path: str, padding: int = 10):
    img = Image.open(input_path).convert("RGBA")

    # bbox по непрозрачным пикселям
    bbox = img.getbbox()
    if not bbox:
        raise ValueError("No visible content found")

    left, top, right, bottom = bbox

    # добавляем небольшой padding
    left = max(0, left - padding)
    top = max(0, top - padding)
    right = min(img.width, right + padding)
    bottom = min(img.height, bottom + padding)

    cropped = img.crop((left, top, right, bottom))
    cropped.save(output_path, format="PNG")

    print(f"✔ Cropped text layer saved to {output_path}")


if __name__ == "__main__":
    crop_to_content(
        input_path="text_layer.png",
        output_path="text_layer.png",
        padding=10
    )
