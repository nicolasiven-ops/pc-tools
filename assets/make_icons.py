"""Generate the flat .ico app icons used by the PyInstaller builds.

Run from the repo root (needs Pillow: `pip install Pillow`):

    python assets/make_icons.py

Writes:
  * pc-tools.ico                 -> white power symbol on a blue rounded square
  * lol-autopick/lol-autopick.ico -> gold crossed swords on a Hextech-navy square

The .exe builds reference these via PyInstaller's --icon flag, so re-run this
script and rebuild if you want to tweak the artwork.
"""

from PIL import Image, ImageDraw

S = 256
ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def _canvas(bg):
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([6, 6, S - 6, S - 6], radius=46, fill=bg)
    return img, d


def _thick_line(d, p0, p1, width, fill):
    """A line with round caps (PIL lines are butt-capped by default)."""
    d.line([p0, p1], fill=fill, width=width)
    r = width / 2
    for (x, y) in (p0, p1):
        d.ellipse([x - r, y - r, x + r, y + r], fill=fill)


def make_pc_tools(path):
    img, d = _canvas((45, 108, 223, 255))           # blue
    cx = cy = 128
    R = 66
    white = (255, 255, 255, 255)
    # Open ring with a gap at the top (PIL angles: 0=right, 90=bottom, 270=top).
    d.arc([cx - R, cy - R, cx + R, cy + R], start=292, end=248, fill=white, width=24)
    # Vertical bar poking through the gap.
    _thick_line(d, (cx, cy - 92), (cx, cy - 22), 24, white)
    img.save(path, sizes=ICO_SIZES)


def _sword_layer(gold, edge):
    """One sword pointing up, centred on an SxS transparent layer."""
    layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    cx = 128
    top, tip_len, guard_y, handle_bottom = 38, 34, 168, 206
    bw, gw, gh, hw, pr = 24, 80, 16, 16, 13
    blade = [
        (cx, top),
        (cx - bw / 2, top + tip_len),
        (cx - bw / 2, guard_y),
        (cx + bw / 2, guard_y),
        (cx + bw / 2, top + tip_len),
    ]
    d.polygon(blade, fill=gold, outline=edge)
    d.rounded_rectangle(
        [cx - gw / 2, guard_y, cx + gw / 2, guard_y + gh], radius=6, fill=gold, outline=edge
    )
    d.rounded_rectangle(
        [cx - hw / 2, guard_y + gh, cx + hw / 2, handle_bottom], radius=5, fill=gold, outline=edge
    )
    d.ellipse([cx - pr, handle_bottom - pr, cx + pr, handle_bottom + pr], fill=gold, outline=edge)
    return layer


def make_lol(path):
    img, _ = _canvas((10, 20, 40, 255))              # Hextech navy
    gold, edge = (200, 170, 110, 255), (120, 90, 40, 255)
    sword = _sword_layer(gold, edge)
    img.alpha_composite(sword.rotate(40, resample=Image.BICUBIC, center=(128, 128)))
    img.alpha_composite(sword.rotate(-40, resample=Image.BICUBIC, center=(128, 128)))
    img.save(path, sizes=ICO_SIZES)


if __name__ == "__main__":
    make_pc_tools("pc-tools.ico")
    make_lol("lol-autopick/lol-autopick.ico")
    print("wrote pc-tools.ico and lol-autopick/lol-autopick.ico")
