"""
Generate all icon sizes for the ESPAI hub from the master 1024x1024 PNG.

The source image has a solid black outer background.  Before resizing we
flood-fill from every edge pixel inward, making the outer background
transparent so the badge sits cleanly on any sidebar/theme colour.
The badge's own dark interior is preserved — the cream/teal border stops
the fill from leaking inside the badge.
"""
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).parent.parent.parent
out  = ROOT / "hub/frontend/static/img"
out.mkdir(parents=True, exist_ok=True)


def make_transparent(source: Image.Image, threshold: int = 30) -> Image.Image:
    """
    BFS flood-fill from all image edges to find the outer background
    (pixels where R, G, B are all below `threshold`), then set their
    alpha to 0.  Everything inside the badge border is left untouched.
    """
    img  = source.convert("RGBA")
    data = np.array(img, dtype=np.uint8)
    R, G, B = data[:, :, 0].astype(int), data[:, :, 1].astype(int), data[:, :, 2].astype(int)

    is_bg   = (R < threshold) & (G < threshold) & (B < threshold)
    h, w    = data.shape[:2]
    visited = np.zeros((h, w), dtype=bool)
    queue   = deque()

    # Seed from all four edges
    for y in range(h):
        for x in (0, w - 1):
            if is_bg[y, x] and not visited[y, x]:
                visited[y, x] = True
                queue.append((y, x))
    for x in range(w):
        for y in (0, h - 1):
            if is_bg[y, x] and not visited[y, x]:
                visited[y, x] = True
                queue.append((y, x))

    while queue:
        y, x = queue.popleft()
        for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and not visited[ny, nx] and is_bg[ny, nx]:
                visited[ny, nx] = True
                queue.append((ny, nx))

    data[visited, 3] = 0
    return Image.fromarray(data, "RGBA")


src = make_transparent(Image.open(ROOT / "design/brand/logo-1024.png"))
print(f"  transparent mask applied")

# Save the transparency-masked master for reference
src.save(ROOT / "design/brand/logo-1024-transparent.png")
print(f"  design/brand/logo-1024-transparent.png saved")

sizes = {
    "logo-512.png":         512,
    "logo-256.png":         256,
    "logo-192.png":         192,   # Android / PWA manifest
    "apple-touch-icon.png": 180,   # iOS home screen
    "logo-128.png":         128,
    "logo-nav.png":         112,   # sidebar @2x (displayed at 56 css-px)
    "logo-64.png":           64,
    "favicon-32.png":        32,
    "favicon-16.png":        16,
}

for name, size in sizes.items():
    img = src.resize((size, size), Image.LANCZOS)
    img.save(out / name)
    print(f"  {name:30s} {size}x{size}")

# Multi-size .ico — ICO supports transparency natively
src.resize((32, 32), Image.LANCZOS).save(
    out / "favicon.ico", format="ICO", sizes=[(32, 32), (16, 16)]
)
print(f"  {'favicon.ico':30s} 32+16")
print("Done.")
