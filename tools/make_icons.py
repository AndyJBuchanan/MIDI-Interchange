"""Make every app icon file from the master artwork: python tools/make_icons.py

Needs Pillow and numpy (pip install pillow numpy); the app and the builds don't, because
the outputs are committed. Run it again whenever assets/icon/icon.png changes.

Master: assets/icon/icon.png   1024 x 1024 RGBA, transparent around the rounded square,
                               square centred and filling the canvas. Edit this file.
Output: assets/icon/MIDI Interchange.icns     macOS bundle icon (midi_interchange.spec)
        assets/icon/MIDI Interchange.ico      Windows exe + installer icon (spec, installer.iss)
        midi_interchange/resources/app_icon.png      window icon, Windows/Linux (ui/app_icon.py)
        midi_interchange/resources/app_icon_mac.png  Dock icon when run from source on macOS

Windows icons fill the canvas; macOS icons follow Apple's grid (the square is 824 of 1024 px
with a soft shadow), so it sits at the same size as other apps in the Dock and Finder.

New artwork drawn on black, with no transparency: python tools/make_icons.py --import art.png
makes the black outside the rounded square transparent (edges kept smooth), crops and centres
the square, writes it as the master and then makes the icons. Check the master by eye after.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ICON_DIR = os.path.join(ROOT, "assets", "icon")
RES_DIR = os.path.join(ROOT, "midi_interchange", "resources")
NAME = "MIDI Interchange"

OUTSIDE_BELOW = 128      # brightest channel below this, joined to a corner = background
MASTER = os.path.join(ICON_DIR, "icon.png")
MASTER_PX = 1024
MAC_BODY, MAC_CANVAS = 824, 1024
ICO_SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]


def cut_out(src: Image.Image) -> Image.Image:
    """The artwork with the black around its rounded square made transparent, cropped square."""
    rgb = np.asarray(src.convert("RGB")).astype(np.float32)
    bright = rgb.max(axis=2)
    dark = bright < OUTSIDE_BELOW
    # Flood fill from the four corners through dark pixels: the background, not the black inside.
    h, w = dark.shape
    outside = np.zeros_like(dark)
    stack = [(y, x) for y, x in ((0, 0), (0, w - 1), (h - 1, 0), (h - 1, w - 1)) if dark[y, x]]
    while stack:
        y, x = stack.pop()
        if outside[y, x] or not dark[y, x]:
            continue
        outside[y, x] = True
        if y > 0: stack.append((y - 1, x))
        if y < h - 1: stack.append((y + 1, x))
        if x > 0: stack.append((y, x - 1))
        if x < w - 1: stack.append((y, x + 1))
    if outside[h // 2, w // 2]:
        raise SystemExit("make_icons: the background reached the middle; is the border unbroken?")
    # Black-to-alpha on the background, so the border's anti-aliased edge stays smooth.
    alpha = np.where(outside, bright / 255.0, 1.0)
    colour = np.where(outside[..., None], rgb / np.maximum(alpha, 1e-6)[..., None], rgb)
    rgba = np.dstack([np.clip(colour, 0, 255), alpha * 255]).astype(np.uint8)
    img = Image.fromarray(rgba, "RGBA")
    box = img.getchannel("A").point(lambda a: 255 if a > 8 else 0).getbbox()
    img = img.crop(box)
    side = max(img.size)
    square = Image.new("RGBA", (side, side))
    square.paste(img, ((side - img.width) // 2, (side - img.height) // 2))
    return square


def mac_grid(art: Image.Image) -> Image.Image:
    """The art at Apple's icon grid size on a 1024 canvas, with the standard soft drop shadow."""
    body = art.resize((MAC_BODY, MAC_BODY), Image.LANCZOS)
    off = (MAC_CANVAS - MAC_BODY) // 2
    shadow_a = Image.new("L", (MAC_CANVAS, MAC_CANVAS))
    shadow_a.paste(body.getchannel("A"), (off, off + 12))
    shadow_a = shadow_a.filter(ImageFilter.GaussianBlur(14)).point(lambda a: int(a * 0.3))
    canvas = Image.new("RGBA", (MAC_CANVAS, MAC_CANVAS), (0, 0, 0, 0))
    canvas.putalpha(shadow_a)
    canvas.alpha_composite(body, (off, off))
    return canvas


def write_icns(mac: Image.Image, path: str) -> None:
    if sys.platform != "darwin" or not shutil.which("iconutil"):
        print(f"skipped {path}: needs macOS iconutil")
        return
    with tempfile.TemporaryDirectory() as tmp:
        iconset = os.path.join(tmp, "icon.iconset")
        os.mkdir(iconset)
        for pt in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                px = pt * scale
                suffix = "" if scale == 1 else "@2x"
                mac.resize((px, px), Image.LANCZOS).save(os.path.join(iconset, f"icon_{pt}x{pt}{suffix}.png"))
        subprocess.run(["iconutil", "-c", "icns", iconset, "-o", path], check=True)
    print("wrote", path)


def main(argv: list[str]) -> int:
    if argv[:1] == ["--import"] and len(argv) == 2:
        art = cut_out(Image.open(argv[1])).resize((MASTER_PX, MASTER_PX), Image.LANCZOS)
        art.save(MASTER, optimize=True)
        print("wrote", MASTER)
    elif argv:
        raise SystemExit("usage: python tools/make_icons.py [--import artwork-on-black.png]")
    master = Image.open(MASTER).convert("RGBA")
    if master.size != (MASTER_PX, MASTER_PX):
        raise SystemExit(f"make_icons: {MASTER} must be {MASTER_PX} x {MASTER_PX}, got {master.size}")
    full = master
    mac = mac_grid(master)
    os.makedirs(RES_DIR, exist_ok=True)

    write_icns(mac, os.path.join(ICON_DIR, f"{NAME}.icns"))
    ico = os.path.join(ICON_DIR, f"{NAME}.ico")
    full.save(ico, sizes=[(s, s) for s in ICO_SIZES])
    print("wrote", ico)
    for img, name in ((full, "app_icon.png"), (mac, "app_icon_mac.png")):
        p = os.path.join(RES_DIR, name)
        img.resize((512, 512), Image.LANCZOS).save(p, optimize=True)
        print("wrote", p)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
