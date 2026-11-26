from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent


def draw_brand_icon(size: int, opaque_bg: bool = False) -> Image.Image:
    if opaque_bg:
        img = Image.new("RGB", (size, size), (30, 58, 95))
    else:
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = 0 if opaque_bg else int(size * 0.06)
    rad = 0 if opaque_bg else int(size * 0.22)
    # Navy rounded square background
    if opaque_bg:
        d.rectangle([0, 0, size, size], fill=(30, 58, 95))
    else:
        d.rounded_rectangle([pad, pad, size - pad, size - pad], radius=rad, fill=(30, 58, 95, 255))

    # Open book motif + subtle gold bookmark/cross accent
    cx, cy = size // 2, size // 2
    bw = int(size * 0.56)
    bh = int(size * 0.42)
    left = cx - bw // 2
    top = cy - bh // 2 + int(size * 0.03)
    mid = cx
    right = cx + bw // 2
    bot = top + bh

    # Left & right pages
    d.rounded_rectangle([left, top, mid - int(size * 0.015), bot], radius=int(size * 0.04), fill=(248, 250, 252, 255))
    d.rounded_rectangle([mid + int(size * 0.015), top, right, bot], radius=int(size * 0.04), fill=(241, 245, 249, 255))

    # Page text lines
    line_h = max(2, int(size * 0.028))
    for i in range(3):
        ly = top + int(bh * (0.26 + i * 0.22))
        d.rounded_rectangle(
            [left + int(bw * 0.09), ly, mid - int(bw * 0.09), ly + line_h],
            radius=line_h // 2,
            fill=(148, 163, 184, 255),
        )
        d.rounded_rectangle(
            [mid + int(bw * 0.09), ly, right - int(bw * 0.09), ly + line_h],
            radius=line_h // 2,
            fill=(148, 163, 184, 255),
        )

    # Gold ribbon bookmark
    rb_w = max(4, int(size * 0.07))
    rb_h = int(size * 0.16)
    d.polygon(
        [
            (mid - rb_w // 2, top - int(size * 0.05)),
            (mid + rb_w // 2, top - int(size * 0.05)),
            (mid + rb_w // 2, top + rb_h),
            (mid, top + int(rb_h * 0.72)),
            (mid - rb_w // 2, top + rb_h),
        ],
        fill=(245, 158, 11, 255),
    )
    return img


def main() -> None:
    pub = ROOT / "frontend" / "public"
    pub.mkdir(parents=True, exist_ok=True)
    draw_brand_icon(192).save(pub / "icon-192.png")
    draw_brand_icon(512).save(pub / "icon-512.png")
    # Opaque 180x180 apple-touch-icon so iOS home screen never renders black corners
    draw_brand_icon(180, opaque_bg=True).save(pub / "apple-touch-icon.png")

    assets = ROOT / "packaging" / "windows"
    assets.mkdir(parents=True, exist_ok=True)
    icon_256 = draw_brand_icon(256)
    icon_256.save(assets / "app_icon.png")
    icon_256.save(assets / "app_icon.ico", format="ICO", sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])

    android_res = ROOT / "android" / "app" / "src" / "main" / "res" / "drawable"
    android_res.mkdir(parents=True, exist_ok=True)
    draw_brand_icon(192).save(android_res / "ic_launcher.png")
    print("Generated PWA, Windows ICO, and Android icons successfully.")


if __name__ == "__main__":
    main()
