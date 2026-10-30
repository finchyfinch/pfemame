#!/usr/bin/env python3
"""
remove_background.py
--------------------
Makes the background of every .png in the same folder transparent,
preserving foreground colours and smoothing anti-aliased edges.

Algorithm
---------
1. Flood-fill from the four image corners to find the background colour.
2. Build a greyscale distance map: each pixel's distance from that colour in
   RGB space (0 = exact match, 255 = totally different).
3. Apply a tolerance threshold — pixels closer than TOLERANCE become fully
   transparent; pixels further than TOLERANCE + EDGE_FEATHER become fully
   opaque; pixels in between get a proportionally blended alpha so that
   anti-aliased edge pixels are handled smoothly.
4. Re-save each file in-place (original is overwritten).

Tuning
------
TOLERANCE    – how different a pixel can be from the background colour and
               still be removed.  Raise if fringe colour is being left behind;
               lower if foreground pixels are disappearing.  (0–255, default 30)
EDGE_FEATHER – width of the semi-transparent blend zone around edges.
               Raise for smoother blending; lower for crisper cuts. (default 20)
"""

import os
import sys
from pathlib import Path
from collections import deque

try:
    from PIL import Image
    import numpy as np
except ImportError:
    sys.exit(
        "Missing dependencies.  Install them with:\n"
        "    pip install Pillow numpy"
    )

# ── tuneable constants ────────────────────────────────────────────────────────
TOLERANCE    = 30   # max colour distance to be considered background
EDGE_FEATHER = 20   # blend zone width (pixels) for anti-aliased edges
# ─────────────────────────────────────────────────────────────────────────────


def sample_background_colour(rgb: np.ndarray) -> np.ndarray:
    """
    Sample the background colour by averaging a small patch from each corner.
    Returns a float32 array of shape (3,).
    """
    h, w = rgb.shape[:2]
    patch = 5  # pixels
    corners = [
        rgb[:patch,  :patch],   # top-left
        rgb[:patch,  -patch:],  # top-right
        rgb[-patch:, :patch],   # bottom-left
        rgb[-patch:, -patch:],  # bottom-right
    ]
    samples = np.concatenate([c.reshape(-1, 3) for c in corners], axis=0)
    return samples.mean(axis=0).astype(np.float32)


def colour_distance(rgb: np.ndarray, colour: np.ndarray) -> np.ndarray:
    """
    Euclidean distance in RGB space from each pixel to `colour`.
    Returns a float32 array of shape (H, W).
    Max possible value is sqrt(3 * 255^2) ≈ 441.67; we scale to 0-255.
    """
    diff = rgb.astype(np.float32) - colour  # (H, W, 3)
    dist = np.sqrt((diff ** 2).sum(axis=2))  # (H, W)
    return np.clip(dist / 441.67 * 255.0, 0, 255)


def build_alpha(dist_map: np.ndarray, tolerance: int, feather: int) -> np.ndarray:
    """
    Convert a distance map to an alpha channel (uint8, 0=transparent, 255=opaque).
    - dist <= tolerance              → alpha = 0   (background)
    - dist >= tolerance + feather    → alpha = 255 (foreground)
    - between                        → linear blend
    """
    low  = float(tolerance)
    high = float(tolerance + feather)
    alpha = np.clip((dist_map - low) / (high - low), 0.0, 1.0)
    return (alpha * 255).astype(np.uint8)


def flood_mask_background(dist_map: np.ndarray, tolerance: int) -> np.ndarray:
    """
    BFS flood-fill from corners to mark which background pixels are *connected*
    to the image border.  This stops interior background-coloured regions
    (e.g. a white circle on a white background) from being erased.

    Returns a boolean mask (True = reachable background).
    """
    h, w = dist_map.shape
    visited = np.zeros((h, w), dtype=bool)
    queue   = deque()

    # Seed from all four edges
    for y in range(h):
        for x in (0, w - 1):
            if not visited[y, x] and dist_map[y, x] <= tolerance:
                visited[y, x] = True
                queue.append((y, x))
    for x in range(w):
        for y in (0, h - 1):
            if not visited[y, x] and dist_map[y, x] <= tolerance:
                visited[y, x] = True
                queue.append((y, x))

    while queue:
        y, x = queue.popleft()
        for dy, dx in ((-1,0),(1,0),(0,-1),(0,1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and not visited[ny, nx]:
                if dist_map[ny, nx] <= tolerance + EDGE_FEATHER:
                    visited[ny, nx] = True
                    queue.append((ny, nx))

    return visited


def remove_background(path: Path) -> None:
    img = Image.open(path).convert("RGBA")
    rgb_arr = np.array(img)[:, :, :3]   # (H, W, 3) uint8

    bg_colour  = sample_background_colour(rgb_arr)
    dist_map   = colour_distance(rgb_arr, bg_colour)

    # Only erase pixels reachable from the border (flood-fill mask)
    reachable  = flood_mask_background(dist_map, TOLERANCE)

    # Within the reachable zone, build a smooth alpha
    alpha_map  = build_alpha(dist_map, TOLERANCE, EDGE_FEATHER)

    # Pixels NOT reachable stay fully opaque regardless of colour
    alpha_map[~reachable] = 255

    rgba = np.array(img)
    rgba[:, :, 3] = alpha_map

    result = Image.fromarray(rgba, "RGBA")
    result.save(path, "PNG")
    print(f"  ✓  {path.name}")


def main():
    script_dir = Path(__file__).resolve().parent
    png_files  = sorted(script_dir.glob("*.png"))

    if not png_files:
        print("No .png files found in the script's folder.")
        return

    print(f"Processing {len(png_files)} PNG file(s) in: {script_dir}\n")
    errors = []
    for p in png_files:
        try:
            remove_background(p)
        except Exception as exc:
            errors.append((p.name, exc))
            print(f"  ✗  {p.name}  —  {exc}")

    print(f"\nDone.  {len(png_files) - len(errors)}/{len(png_files)} file(s) updated.")
    if errors:
        print(f"{len(errors)} file(s) had errors (see above).")


if __name__ == "__main__":
    main()
