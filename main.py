from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from skyfield.api import load, wgs84
from sgp4.api import SatrecArray, jday
from contextlib import asynccontextmanager
import numpy as np
import asyncio
import time

TLE_URL = "https://celestrak.org/NORAD/elements/gp.php?GROUP=starlink&FORMAT=tle"
TLE_FILE = "starlink.tle"
REFRESH_HOURS = 8
CACHE_SECONDS = 1.0

# Observer location — Berkeley, CA
OBS_LAT = 37.8715
OBS_LON = -122.2730
OBS_ELEV_M = 52
PASS_HOURS_AHEAD = 12
MIN_PEAK_ELEVATION_DEG = 20
PASS_CACHE_SECONDS = 300
MAX_PASSES_RETURNED = 50

state = {
    "satellites": [],
    "sat_array": None,
    "names": [],
    "ts": load.timescale(),
    "cache": {"t": 0, "data": None},
    "passes_cache": {"t": 0, "data": None},
}


def _download_tle(path):
    """Fetch TLE with a real User-Agent (Celestrak blocks default urllib)."""
    import urllib.request
    req = urllib.request.Request(
        TLE_URL,
        headers={"User-Agent": "starlink-tracker/1.0 (self-hosted homelab)"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read()
    with open(path, "wb") as f:
        f.write(data)
    print(f"Downloaded TLE: {len(data)} bytes")


def load_sats(reload=False):
    import os
    if reload or not os.path.exists(TLE_FILE):
        _download_tle(TLE_FILE)
    sats = load.tle_file(TLE_FILE, reload=False)
    state["satellites"] = sats
    state["names"] = [s.name for s in sats]
    state["sat_array"] = SatrecArray([s.model for s in sats])
    state["cache"] = {"t": 0, "data": None}
    state["passes_cache"] = {"t": 0, "data": None}
    print(f"Loaded {len(sats)} satellites")


async def refresh_loop():
    while True:
        await asyncio.sleep(REFRESH_HOURS * 3600)
        try:
            load_sats(reload=True)
        except Exception as e:
            print(f"TLE refresh failed: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_sats(reload=False)
    task = asyncio.create_task(refresh_loop())
    yield
    task.cancel()


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


def compute_positions():
    """Vectorized SGP4 propagation for all sats at current time."""
    t = state["ts"].now()
    jd = np.array([t.whole])
    fr = np.array([t.ut1_fraction])
    e, r, v = state["sat_array"].sgp4(jd, fr)  # r shape: (n_sats, 1, 3) TEME km

    # Build a Skyfield position from TEME vectors to get subpoint
    from skyfield.positionlib import Geocentric
    pos_km = r[:, 0, :].T  # shape (3, n_sats)
    geo = Geocentric(pos_km / 1.4959787e8, t=t)  # AU
    # Simpler: use wgs84.geographic_position_of with a Geocentric built from km
    # Skyfield expects AU internally, so convert.
    subpoints = wgs84.geographic_position_of(geo)
    lats = subpoints.latitude.degrees
    lons = subpoints.longitude.degrees
    alts = subpoints.elevation.km

    return [
        {"name": n, "lat": float(la), "lon": float(lo), "alt_km": float(al)}
        for n, la, lo, al in zip(state["names"], lats, lons, alts)
    ]


@app.get("/positions")
def positions():
    now = time.time()
    if state["cache"]["data"] is None or now - state["cache"]["t"] > CACHE_SECONDS:
        data = compute_positions()
        state["cache"] = {"t": now, "data": data}
    data = state["cache"]["data"]
    return {"count": len(data), "satellites": data}





_eph = None
def _get_ephemeris():
    global _eph
    if _eph is None:
        _eph = load('de421.bsp')
    return _eph


def _sun_altitude_deg(observer, t):
    eph = _get_ephemeris()
    obs_pos = eph['earth'] + observer
    return obs_pos.at(t).observe(eph['sun']).apparent().altaz()[0].degrees


def _is_visible(sat, observer, t, sun_alt_deg):
    """Sat must be sunlit and observer must be in civil twilight or darker."""
    if sun_alt_deg > -6:
        return False
    return sat.at(t).is_sunlit(_get_ephemeris())


@app.get("/passes")
def passes():
    now = time.time()
    pc = state["passes_cache"]
    if pc["data"] is not None and now - pc["t"] < PASS_CACHE_SECONDS:
        return pc["data"]

    from skyfield.api import wgs84 as _wgs84
    observer = _wgs84.latlon(OBS_LAT, OBS_LON, elevation_m=OBS_ELEV_M)
    ts = state["ts"]
    t0 = ts.now()
    t1 = ts.tt_jd(t0.tt + PASS_HOURS_AHEAD / 24.0)

    # STEP 1: coarse vectorized filter — sample every 60s, keep sats that ever exceed 10 deg altitude
    step_min = 1.0
    n_steps = int(PASS_HOURS_AHEAD * 60 / step_min) + 1
    jd_whole = np.full(n_steps, t0.whole)
    jd_frac = t0.ut1_fraction + (np.arange(n_steps) * step_min * 60.0) / 86400.0
    e, r, v = state["sat_array"].sgp4(jd_whole, jd_frac)  # r: (n_sats, n_steps, 3) TEME km

    # Observer position in ECEF (approx TEME for coarse filter — good enough to prune)
    obs_lat_rad = np.radians(OBS_LAT)
    obs_lon_rad = np.radians(OBS_LON)
    R_earth = 6378.137
    obs_ecef = np.array([
        R_earth * np.cos(obs_lat_rad) * np.cos(obs_lon_rad),
        R_earth * np.cos(obs_lat_rad) * np.sin(obs_lon_rad),
        R_earth * np.sin(obs_lat_rad),
    ])
    # Vector from observer to satellite
    rel = r - obs_ecef[None, None, :]  # (n_sats, n_steps, 3)
    # Elevation angle: dot(rel, obs_up) / |rel|
    up = obs_ecef / np.linalg.norm(obs_ecef)
    rel_norm = np.linalg.norm(rel, axis=2)
    elev_sin = np.einsum('ijk,k->ij', rel, up) / rel_norm
    max_elev_sin = elev_sin.max(axis=1)
    # Keep sats reaching at least the min peak elevation (coarse threshold, be lenient)
    candidate_idx = np.where(max_elev_sin > np.sin(np.radians(MIN_PEAK_ELEVATION_DEG - 5)))[0]

    # STEP 2: precise find_events on the shortlist — collect raw events only
    raw = []  # list of (sat_idx, rise_t, peak_t, set_t)
    for idx in candidate_idx:
        sat = state["satellites"][idx]
        try:
            times, events = sat.find_events(observer, t0, t1, altitude_degrees=10.0)
        except Exception:
            continue
        i = 0
        while i < len(events) - 2:
            if events[i] == 0 and events[i+1] == 1 and events[i+2] == 2:
                raw.append((idx, times[i], times[i+1], times[i+2]))
                i += 3
            else:
                i += 1

    if not raw:
        results = []
    else:
        # STEP 3: bulk visibility filter — first prune by sun altitude at peak
        from skyfield.api import Time
        eph = _get_ephemeris()
        earth = eph['earth']
        sun = eph['sun']
        obs_pos = earth + observer

        peak_ts_list = [r[2] for r in raw]
        # Build a batched Time by stacking julian dates
        peak_tt = np.array([t.tt for t in peak_ts_list])
        batched = ts.tt_jd(peak_tt)
        sun_alt = obs_pos.at(batched).observe(sun).apparent().altaz()[0].degrees
        night_mask = sun_alt <= -6

        # STEP 4: for the night-time subset, compute peak altitude and sunlit-ness in bulk
        results = []
        night_indices = np.where(night_mask)[0]
        if len(night_indices) > 0:
            # Group by satellite so we can propagate each sat once for its peak times
            for i in night_indices:
                sat_idx, rise_t, peak_t, set_t = raw[i]
                sat = state["satellites"][sat_idx]
                topo = (sat - observer).at(peak_t)
                alt, az, _ = topo.altaz()
                if alt.degrees < MIN_PEAK_ELEVATION_DEG:
                    continue
                if not sat.at(peak_t).is_sunlit(eph):
                    continue
                results.append({
                    "name": sat.name,
                    "rise_utc": rise_t.utc_iso(),
                    "peak_utc": peak_t.utc_iso(),
                    "set_utc": set_t.utc_iso(),
                    "peak_elevation_deg": round(alt.degrees, 1),
                    "peak_azimuth_deg": round(az.degrees, 1),
                    "duration_s": round((set_t.tt - rise_t.tt) * 86400),
                })

    # Sort by peak elevation descending (best passes first), then truncate
    results.sort(key=lambda r: -r["peak_elevation_deg"])
    top = results[:MAX_PASSES_RETURNED]
    # Then present in chronological order
    top.sort(key=lambda r: r["rise_utc"])
    data = {
        "count_total": len(results),
        "count_returned": len(top),
        "candidates_screened": int(len(candidate_idx)),
        "observer": {"lat": OBS_LAT, "lon": OBS_LON, "elevation_m": OBS_ELEV_M},
        "passes": top,
    }
    state["passes_cache"] = {"t": now, "data": data}
    return data

@app.get("/health")
def health():
    return {"ok": True, "sat_count": len(state["satellites"])}

import os
_static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
app.mount("/", StaticFiles(directory=_static_dir, html=True), name="static")
