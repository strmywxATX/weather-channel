"""Build the elevation image the globe uses for its soft relief shading. Runs once; the result is kept on the published site.

Usage: python scripts/build_relief.py <output folder>

Source: Terrain Tiles (Mapzen/AWS open data, "terrarium" encoding), zoom 6, about 1 to 2 km per pixel.
Output: elev.png covering lon -170..-40, lat 5..80 at 24 pixels per degree.
        Elevation in metres = R*256 + G - 1000.
"""
import io
import math
import os
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import requests
from PIL import Image
from scipy.ndimage import map_coordinates, uniform_filter

OUT = sys.argv[1]
os.makedirs(OUT, exist_ok=True)
Z, W, E, S, N, PPD = 6, -170, -40, 5, 80, 24
n = 2 ** Z
xt = lambda lon: (lon + 180) / 360 * n
yt = lambda lat: (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n
x0, x1, y0, y1 = int(xt(W)), int(xt(E)), int(yt(N)), int(yt(S))
session = requests.Session()


def get(xy):
    x, y = xy
    for attempt in range(3):
        try:
            r = session.get(f"https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{Z}/{x}/{y}.png", timeout=60)
            r.raise_for_status()
            a = np.asarray(Image.open(io.BytesIO(r.content)).convert("RGB"), dtype=np.float32)
            return x, y, a[..., 0] * 256 + a[..., 1] + a[..., 2] / 256 - 32768
        except Exception:
            if attempt == 2:
                raise


mosaic = np.zeros(((y1 - y0 + 1) * 256, (x1 - x0 + 1) * 256), np.float32)
tiles = [(x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)]
with ThreadPoolExecutor(12) as ex:
    for x, y, e in ex.map(get, tiles):
        mosaic[(y - y0) * 256:(y - y0 + 1) * 256, (x - x0) * 256:(x - x0 + 1) * 256] = e
mosaic = uniform_filter(mosaic, 2)

lons = W + (np.arange((E - W) * PPD) + 0.5) / PPD
lats = N - (np.arange((N - S) * PPD) + 0.5) / PPD
px = ((lons + 180) / 360 * n - x0) * 256 - 0.5
py = ((1 - np.arcsinh(np.tan(np.radians(lats))) / np.pi) / 2 * n - y0) * 256 - 0.5
PY, PX = np.meshgrid(py, px, indexing="ij")
elev = map_coordinates(mosaic, [PY, PX], order=1, mode="nearest")
v = np.clip(elev + 1000, 0, 65535).astype(np.uint16)
rgb = np.zeros(v.shape + (3,), np.uint8)
rgb[..., 0] = v >> 8
rgb[..., 1] = v & 255
Image.fromarray(rgb, "RGB").save(os.path.join(OUT, "elev.png"), optimize=True)
print("relief built", v.shape, "max elevation", float(elev.max()), "tiles", len(tiles))
