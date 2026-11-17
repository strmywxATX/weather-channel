"""Collect live data for the GEO 1305 weather channel and write it to an output folder.

Usage: python scripts/fetch.py <output folder>

Each source is fetched independently. If one fails, its previous file is left in
place and the error is recorded in status.json, so the display keeps its last good data.

Sources
  rap.json     RAP analysis (NOAA, via the noaa-rap-pds open data bucket): 250 mb wind and 2 m temperature
  asos.json    ASOS/AWOS surface winds (Iowa Environmental Mesonet)
  radar.png    NEXRAD base reflectivity composite (Iowa Environmental Mesonet)
  station.json TXST Round Rock station, current conditions and the past 24 hours (TexMesonet, site 142)
"""
import datetime as dt
import io
import json
import math
import os
import sys
import tempfile
import time
import traceback

import numpy as np
import requests

OUT = sys.argv[1]
HERE = os.path.dirname(os.path.abspath(__file__))
os.makedirs(OUT, exist_ok=True)
S = requests.Session()
S.headers["User-Agent"] = "txst-geo1305-weather-channel (github.com/strmywxATX/weather-channel)"
UTC = dt.timezone.utc
NOW = dt.datetime.now(UTC)
status = {"run": NOW.strftime("%Y-%m-%dT%H:%MZ"), "sources": {}}

# Target grid for the globe: half-degree lat/lon box over North America. Row 0 is the north edge.
GRID = {"W": -170.0, "E": -40.0, "S": 5.0, "N": 80.0, "d": 0.5}


def save(name, obj):
    with open(os.path.join(OUT, name), "w") as f:
        json.dump(obj, f, separators=(",", ":"))


def run(name, fn):
    t0 = time.time()
    try:
        info = fn() or {}
        status["sources"][name] = {"ok": True, "seconds": round(time.time() - t0, 1), **info}
    except Exception as e:  # keep going: one bad source must not stop the others
        status["sources"][name] = {"ok": False, "error": repr(e), "trace": traceback.format_exc()[-1500:]}
    print(name, json.dumps(status["sources"][name])[:600], flush=True)


# ---------------------------------------------------------------- RAP analysis
def regrid(lats, lons, fields):
    """Inverse-distance blend of the 4 nearest model points onto GRID. Points far from the model domain are NaN."""
    from scipy.spatial import cKDTree

    def xyz(la, lo):
        la, lo = np.radians(la), np.radians(lo)
        return np.column_stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)])

    tree = cKDTree(xyz(lats.ravel(), lons.ravel()))
    glon = np.arange(GRID["W"], GRID["E"] + 1e-6, GRID["d"])
    glat = np.arange(GRID["N"], GRID["S"] - 1e-6, -GRID["d"])
    LO, LA = np.meshgrid(glon, glat)
    dist, idx = tree.query(xyz(LA.ravel(), LO.ravel()), k=4)
    w = 1.0 / np.maximum(dist, 1e-9) ** 2
    w /= w.sum(axis=1, keepdims=True)
    outside = dist[:, 0] * 6371.0 > 45.0
    out = []
    for f in fields:
        v = (f.ravel()[idx] * w).sum(axis=1)
        v[outside] = np.nan
        out.append(v)
    return len(glon), len(glat), out


def rap():
    import pygrib

    base = idx = None
    for back in range(0, 9):
        t = (NOW - dt.timedelta(hours=back)).replace(minute=0, second=0, microsecond=0)
        url = f"https://noaa-rap-pds.s3.amazonaws.com/rap.{t:%Y%m%d}/rap.t{t:%H}z.awip32f00.grib2"
        r = S.get(url + ".idx", timeout=30)
        if r.status_code == 200 and "UGRD:250 mb" in r.text:
            base, idx = url, r.text
            break
    if base is None:
        raise RuntimeError("no RAP analysis found in the last 9 hours")

    lines = [l.split(":") for l in idx.strip().splitlines()]
    offsets = sorted({int(l[1]) for l in lines})
    want = ("UGRD:250 mb", "VGRD:250 mb", "HGT:250 mb", "TMP:2 m above ground")
    starts = sorted({int(l[1]) for l in lines if f"{l[3]}:{l[4]}" in want})
    blob = b""
    for s0 in starts:
        later = [o for o in offsets if o > s0]
        rng = f"bytes={s0}-{later[0] - 1}" if later else f"bytes={s0}-"
        g = S.get(base, headers={"Range": rng}, timeout=120)
        g.raise_for_status()
        blob += g.content

    with tempfile.NamedTemporaryFile(suffix=".grib2", delete=False) as f:
        f.write(blob)
        path = f.name
    u = v = tk = hgt = None
    seen = []
    grbs = pygrib.open(path)
    for g in grbs:
        seen.append(f"{g.shortName}/{g.typeOfLevel}/{g.level}")
        if g.typeOfLevel == "isobaricInhPa" and g.level == 250 and g.shortName == "u":
            u, ref = g.values, g
        elif g.typeOfLevel == "isobaricInhPa" and g.level == 250 and g.shortName == "v":
            v = g.values
        elif g.typeOfLevel == "isobaricInhPa" and g.level == 250 and g.shortName in ("gh", "z"):
            hgt = g.values if g.shortName == "gh" else g.values / 9.80665
        elif g.typeOfLevel == "heightAboveGround" and g.level == 2:
            tk = g.values
    if u is None or v is None:
        raise RuntimeError(f"250 mb wind not found; messages were {seen}")
    lats, lons = ref.latlons()
    lons = (lons + 180.0) % 360.0 - 180.0

    # Model winds are relative to the model grid. Rotate them to true east/north.
    if ref.gridType == "lambert":
        lov = (ref["LoVInDegrees"] + 180.0) % 360.0 - 180.0
        rot = math.sin(math.radians(ref["Latin1InDegrees"])) * np.radians((lons - lov + 180.0) % 360.0 - 180.0)
        u, v = u * np.cos(rot) + v * np.sin(rot), -u * np.sin(rot) + v * np.cos(rot)

    fields = [np.asarray(u) * 1.94384, np.asarray(v) * 1.94384]
    names = ["u", "v"]
    if hgt is not None:
        fields.append(np.asarray(hgt))
        names.append("z")
    if tk is not None:
        fields.append((np.asarray(tk) - 273.15) * 9 / 5 + 32)
        names.append("t")
    nx, ny, out = regrid(lats, lons, fields)
    # Light smoothing of the wind (about one grid cell) so the isotach contours draw cleanly.
    from scipy.ndimage import gaussian_filter
    for i in [k for k, nm in enumerate(names) if nm != "t"]:
        a = out[i].reshape(ny, nx)
        ok = ~np.isnan(a)
        num = gaussian_filter(np.where(ok, a, 0.0), 1.0)
        den = gaussian_filter(ok.astype(float), 1.0)
        out[i] = np.where(ok, num / np.maximum(den, 1e-6), np.nan).ravel()
    ints = lambda a: [None if x != x else round(float(x), 1) for x in a.tolist()]
    valid = ref.validDate.replace(tzinfo=UTC).strftime("%Y-%m-%dT%H:%MZ")
    obj = {**GRID, "nx": nx, "ny": ny, "valid": valid}
    for nm, a in zip(names, out):
        obj[nm] = ints(a)  # u, v in knots; z = 250 mb height in metres; t in deg F
    save("rap.json", obj)
    spd = np.hypot(out[0], out[1])
    return {"valid": valid, "grid": ref.gridType, "max_250mb_kt": int(np.nanmax(spd)), "has_temp": tk is not None, "has_height": hgt is not None, "messages": seen}


# ---------------------------------------------------------------- ASOS winds
STATES = ("AL AZ AR CA CO CT DE FL GA ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD "
          "TN TX UT VT VA WA WV WI WY").split()


def asos():
    preferred = {s[0][1:] for s in json.load(open(os.path.join(HERE, "..", "data", "stations.json")))}
    obs, sample, failed = [], None, []
    for st in STATES:
        try:
            r = S.get(f"https://mesonet.agron.iastate.edu/api/1/currents.json?network={st}_ASOS", timeout=40)
            r.raise_for_status()
            rows = r.json().get("data", [])
        except Exception as e:
            failed.append(f"{st}: {e!r}"[:80])
            continue
        if rows and sample is None:
            sample = sorted(rows[0].keys())
        for o in rows:
            sk, dr, la, lo = o.get("sknt"), o.get("drct"), o.get("lat"), o.get("lon")
            if sk is None or la is None or lo is None or (dr is None and sk > 0):
                continue
            when = o.get("utc_valid") or ""
            try:
                age = (NOW - dt.datetime.fromisoformat(when.replace("Z", "+00:00")).astimezone(UTC)).total_seconds() / 60
                if age > 90:
                    continue
            except ValueError:
                pass
            d = math.radians(dr or 0)
            obs.append({"id": o.get("station"), "lat": round(la, 2), "lon": round(lo, 2),
                        "u": round(-sk * math.sin(d), 1), "v": round(-sk * math.cos(d), 1), "t": o.get("tmpf")})
        time.sleep(0.15)
    if not obs:
        raise RuntimeError(f"no ASOS observations; sample keys {sample}; failures {failed[:3]}")
    # Thin to a readable spacing, major airports first.
    obs.sort(key=lambda o: (o["id"] not in preferred, o["id"] or ""))
    keep = []
    for o in obs:
        c = math.cos(math.radians(o["lat"]))
        if all(math.hypot((o["lon"] - k["lon"]) * c, o["lat"] - k["lat"]) >= 1.6 for k in keep):
            keep.append(o)
    save("asos.json", {"time": NOW.strftime("%Y-%m-%dT%H:%MZ"), "stations": keep})
    return {"reports": len(obs), "plotted": len(keep), "sample_keys": sample, "failed_states": failed[:5]}


# ---------------------------------------------------------------- radar composite
def radar():
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None
    base = "https://mesonet.agron.iastate.edu/data/gis/images/4326/USCOMP/n0q_0"
    r = S.get(base + ".png", timeout=120)
    r.raise_for_status()
    im = Image.open(io.BytesIO(r.content))
    a = np.array(im)
    if a.ndim != 2:
        raise RuntimeError(f"expected a palette image, got mode {im.mode} shape {a.shape}")
    # n0q palette index to dBZ: index 0 is no data, then half-dBZ steps starting at -32.
    dbz = np.where(a > 0, a.astype(np.float32) * 0.5 - 32.5, 0)
    k = 5
    h, w = (dbz.shape[0] // k) * k, (dbz.shape[1] // k) * k
    small = dbz[:h, :w].reshape(h // k, k, w // k, k).max(axis=(1, 3))
    small = np.where(small >= 10, np.clip(small, 0, 95), 0).astype(np.uint8)
    Image.fromarray(small, "L").save(os.path.join(OUT, "radar.png"), optimize=True)
    d = 0.005
    when = None
    try:
        m = S.get(base + ".json", timeout=30).json()
        when = m.get("meta", {}).get("valid")
    except Exception:
        pass
    if not when:
        try:
            when = dt.datetime.strptime(r.headers["Last-Modified"], "%a, %d %b %Y %H:%M:%S %Z").strftime("%Y-%m-%dT%H:%MZ")
        except Exception:
            when = NOW.strftime("%Y-%m-%dT%H:%MZ")
    save("radar.json", {"W": -126.0, "N": 50.0, "E": -126.0 + w * d, "S": 50.0 - h * d, "time": when})
    return {"source_size": list(a.shape[::-1]), "size": [w // k, h // k], "time": when, "echo_pixels": int((small > 0).sum())}


# ---------------------------------------------------------------- TXST Round Rock station
def station():
    site = 142
    cur = S.get("https://www.texmesonet.org/api/CurrentData", timeout=60)
    cur.raise_for_status()
    cur = cur.json()
    rows = cur if isinstance(cur, list) else next((v for v in cur.values() if isinstance(v, list)), [])
    mine = next((o for o in rows if str(o.get("stationId", o.get("StationId", o.get("station_id", "")))) == str(site)
                 or "Round Rock" in str(o.get("name", o.get("stationName", o.get("station_name", ""))))), None)
    ser = S.get(f"https://www.texmesonet.org/api/AllChartingFieldsById/{site}/1440", timeout=60)
    ser.raise_for_status()
    ser = ser.json()
    save("station.json", {"time": NOW.strftime("%Y-%m-%dT%H:%MZ"), "current": mine, "units": cur.get("units") if isinstance(cur, dict) else None, "series": ser})
    shape = list(ser.keys())[:12] if isinstance(ser, dict) else (sorted(ser[0].keys()) if ser and isinstance(ser[0], dict) else str(type(ser)))
    return {"current_found": mine is not None, "current_keys": sorted(mine.keys()) if mine else (sorted(rows[0].keys()) if rows else None),
            "top_keys": list(cur.keys()) if isinstance(cur, dict) else "list", "series_shape": shape,
            "series_len": len(ser) if hasattr(ser, "__len__") else None}


# ---------------------------------------------------------------- NWS 7-day forecast for each campus
CAMPUSES = {"rr": (30.5646, -97.6528), "sm": (29.8884, -97.9384)}


def forecast():
    out, info = {}, {}
    for key, (la, lo) in CAMPUSES.items():
        pt = S.get(f"https://api.weather.gov/points/{la},{lo}", timeout=40, headers={"Accept": "application/geo+json"})
        pt.raise_for_status()
        fc = S.get(pt.json()["properties"]["forecast"], timeout=40, headers={"Accept": "application/geo+json"})
        fc.raise_for_status()
        periods = fc.json()["properties"]["periods"]
        out[key] = [{"name": p.get("name"), "day": p.get("isDaytime"), "temp": p.get("temperature"),
                     "text": p.get("shortForecast"), "pop": (p.get("probabilityOfPrecipitation") or {}).get("value"),
                     "wind": f'{p.get("windDirection", "")} {p.get("windSpeed", "")}'.strip()} for p in periods]
        info[key] = len(periods)
    save("forecast.json", {"time": NOW.strftime("%Y-%m-%dT%H:%MZ"), **out})
    return {"periods": info}


# ---------------------------------------------------------------- satellite loop, WPC fronts, SPC outlook (copied as images)
IMAGES = {
    "sat.gif": ["https://cdn.star.nesdis.noaa.gov/GOES19/ABI/SECTOR/sp/GEOCOLOR/GOES19-SP-GEOCOLOR-600x600.gif",
                "https://cdn.star.nesdis.noaa.gov/GOES19/ABI/CONUS/GEOCOLOR/GOES19-CONUS-GEOCOLOR-625x375.gif",
                "https://cdn.star.nesdis.noaa.gov/GOES16/ABI/SECTOR/sp/GEOCOLOR/GOES16-SP-GEOCOLOR-600x600.gif"],
    "wpc.gif": ["https://www.wpc.ncep.noaa.gov/noaa/noaad1.gif"],
    "spc.gif": ["https://www.spc.noaa.gov/products/outlook/day1otlk.gif", "https://www.spc.noaa.gov/products/outlook/day1otlk.png"],
}


def images():
    got, errors = {}, []
    for name, urls in IMAGES.items():
        for url in urls:
            try:
                r = S.get(url, timeout=120)
                if r.status_code == 200 and len(r.content) > 5000 and r.headers.get("Content-Type", "").startswith("image"):
                    with open(os.path.join(OUT, name), "wb") as f:
                        f.write(r.content)
                    got[name] = {"url": url, "kb": len(r.content) // 1024}
                    break
                errors.append(f"{url}: {r.status_code} {r.headers.get('Content-Type')}")
            except Exception as e:
                errors.append(f"{url}: {e!r}"[:160])
    save("images.json", {"time": NOW.strftime("%Y-%m-%dT%H:%MZ"), "have": sorted(got)})
    if len(got) < len(IMAGES):
        raise RuntimeError(f"got {sorted(got)}; problems: {errors}")
    return got


# ---------------------------------------------------------------- headlines
PRIORITY = ["Tornado Warning", "Severe Thunderstorm Warning", "Flash Flood Warning", "Hurricane Warning", "Tropical Storm Warning",
            "Blizzard Warning", "Ice Storm Warning", "Winter Storm Warning", "Tornado Watch", "Severe Thunderstorm Watch",
            "Extreme Heat Warning", "High Wind Warning", "Red Flag Warning", "Flood Warning", "Winter Storm Watch",
            "Winter Weather Advisory", "Freeze Warning", "Heat Advisory", "Wind Advisory", "Dense Fog Advisory"]


def headlines():
    items = []
    try:
        cfg = json.load(open(os.path.join(HERE, "..", "config.json")))
        items += [str(x) for x in cfg.get("headlines", []) if str(x).strip()]
    except Exception:
        pass
    r = S.get("https://api.weather.gov/alerts/active?status=actual&message_type=alert", timeout=90, headers={"Accept": "application/geo+json"})
    r.raise_for_status()
    by, tx = {}, {}
    for f in r.json().get("features", []):
        p = f.get("properties", {})
        ev = p.get("event")
        states = {u[:2] for u in (p.get("geocode", {}).get("UGC") or []) if len(u) >= 2}
        d = by.setdefault(ev, {"n": 0, "states": set()})
        d["n"] += 1
        d["states"] |= states
        if "TX" in states:
            tx[ev] = tx.get(ev, 0) + 1
    shown = 0
    for ev in PRIORITY:
        if ev in by and shown < 5:
            st = sorted(by[ev]["states"])
            where = ", ".join(st) if len(st) <= 6 else f"{len(st)} states"
            plural = ev if by[ev]["n"] == 1 else (ev[:-1] + "ies" if ev.endswith("y") else ev + ("es" if ev.endswith("ch") else "s"))
            items.append(f"{plural} in effect: {by[ev]['n']} ({where})")
            shown += 1
    if tx:
        ranked = sorted(tx, key=lambda e: PRIORITY.index(e) if e in PRIORITY else 99)[:4]
        items.append("In Texas: " + ", ".join(ranked))
    else:
        items.append("No active weather alerts in Texas")
    try:
        rap_ = json.load(open(os.path.join(OUT, "rap.json")))
        best = max(((math.hypot(u, v), k) for k, (u, v) in enumerate(zip(rap_["u"], rap_["v"])) if u is not None and v is not None and -140 <= rap_["W"] + (k % rap_["nx"]) * rap_["d"] <= -60))
        j, i = divmod(best[1], rap_["nx"])
        la, lo = rap_["N"] - j * rap_["d"], rap_["W"] + i * rap_["d"]
        items.append(f"Strongest 250 mb wind on the map: {round(best[0])} kt near {abs(la):.0f}°N, {abs(lo):.0f}°W")
    except Exception:
        pass
    try:
        st_ = json.load(open(os.path.join(OUT, "station.json")))
        temps = [float(v["airTemp"]) * 9 / 5 + 32 for v in st_["series"]["values"] if v.get("airTemp") not in (None, "")]
        if temps:
            items.append(f"TXST Round Rock, past 24 hours: high {round(max(temps))}°F, low {round(min(temps))}°F")
    except Exception:
        pass
    save("headlines.json", {"time": NOW.strftime("%Y-%m-%dT%H:%MZ"), "items": items})
    return {"count": len(items), "alert_types": len(by), "items": items}


run("rap", rap)
run("asos", asos)
run("radar", radar)
run("station", station)
run("forecast", forecast)
run("images", images)
run("headlines", headlines)
save("status.json", status)
