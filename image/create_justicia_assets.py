"""Génère image/justicia.png — logo balance, dégradé orange → magenta (charte JusticIA)."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
SIZE = 256


def make_logo() -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    pad = 18
    draw.rounded_rectangle(
        [pad, pad, SIZE - pad, SIZE - pad],
        radius=36,
        fill=(18, 20, 28, 255),
        outline=(40, 44, 58, 255),
        width=2,
    )
    cx, cy = SIZE // 2, SIZE // 2 - 8
    # Barre centrale
    bw = max(4, SIZE // 48)
    draw.rectangle([cx - bw // 2, 52, cx + bw // 2, SIZE - 56], fill=(75, 78, 95, 255))
    # Bras de balance
    draw.line([56, cy, SIZE - 56, cy], fill=(95, 100, 120, 255), width=4)
    # Cordes
    draw.line([cx - 46, cy, cx - 46, cy + 38], fill=(95, 100, 120, 255), width=3)
    draw.line([cx + 46, cy, cx + 46, cy + 38], fill=(95, 100, 120, 255), width=3)
    # Plateaux : demi-cercles en dégradé simulé (bandes)
    def bowl(dx: int, cols: tuple[tuple[int, int, int], ...]) -> None:
        bx = cx + dx
        by = cy + 52
        rw, rh = 44, 22
        n = len(cols) - 1
        for i in range(rh):
            t = i / max(rh - 1, 1)
            r = int(cols[0][0] * (1 - t) + cols[-1][0] * t)
            g = int(cols[0][1] * (1 - t) + cols[-1][1] * t)
            b = int(cols[0][2] * (1 - t) + cols[-1][2] * t)
            draw.line([bx - rw, by - rh // 2 + i, bx + rw, by - rh // 2 + i], fill=(r, g, b, 255), width=1)

    bowl(
        -46,
        ((255, 95, 55), (255, 65, 120), (230, 50, 140)),
    )
    bowl(
        46,
        ((255, 130, 80), (220, 70, 160), (160, 70, 220)),
    )
    return img


if __name__ == "__main__":
    p = ROOT / "justicia.png"
    make_logo().save(p, "PNG")
    print(p)
