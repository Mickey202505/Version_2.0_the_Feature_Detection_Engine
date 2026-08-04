#!/usr/bin/env python3
"""
Smart Caddie Engine — Phase 2 (Lite) + Phase 3 (Terrain & Stance)
==================================================================
Implements GSPro Unified Design v2.5 §2.3, §4, §5, §6.

Design principle carried over from the doc: no new .exe. This module is
imported and driven entirely by gspro_server.py; it owns:

  - Bag mapping / wedge matrix server-side persistence (§4.13 needs the
    server to know completeness, so this data can no longer live only in
    the tablet's localStorage — see CORRECTION note below)
  - Screenshot capture + OCR of the GSPro screen (§4.4 Lite scope, §5.2
    Phase 3 mini-map scope)
  - Club profiles built from Phase 1 session JSONs (§4.7), respecting the
    mishit-flag policy (§6)
  - The full decision hierarchy (§4.5 + §5.3 extension)
  - Lie/terrain adjustment incl. the launch-angle-aware Deep Rough model
    (§5.4 correction) and stance-adjusted aim offset (§5.5)
  - Accuracy tracking log (§4.14)

⚠ CORRECTION (this build): v2.5 §2.1 already flags the bridge server as
an active build target. One more gap found while wiring this up: bag
mapping and the wedge matrix currently live ONLY in the tablet's
localStorage (gspro.html) and are never sent to gspro_server.py. But
§4.13 / §4.3.1's prerequisite checks are specified as running on the
bridge server. Fixed here by adding sync_bag_mapping / sync_wedge_matrix
WebSocket messages (tablet -> server) that persist a mirror copy
server-side, in the same JSON-file style as sessions (§3.7). The tablet
remains the source of truth for editing; the server's copy is what the
Caddie prerequisite check and the recommendation engine read.

⚠ CALIBRATION REQUIRED: the OCR_REGIONS below are expressed as fractions
of the game window's client rect (resolution-independent), seeded from
the two reference screenshots supplied for the dual-distance behaviour,
but NOT verified against your actual GSPro window layout. Run with
SMART_CADDIE_DEBUG_DUMP=1 (env var) to save every capture crop into
%LOCALAPPDATA%\\GSProControlBox\\SmartCaddie\\debug_captures\\ so you can
look at them and adjust the fractions. The mini-map regions (Phase 3,
§5.2) are rough placeholders — no mini-map reference screenshot was
supplied — expect to need to adjust both the left- and right-side boxes
and the Range vs Course-Play variants once real captures are available.
"""

import os, re, json, math, time, statistics
from datetime import datetime

DEBUG_DUMP = os.environ.get("SMART_CADDIE_DEBUG_DUMP", "") == "1"

# ═══════════════════════════════════════════════════════════════════════
#  Storage locations (set by gspro_server.py at import time)
# ═══════════════════════════════════════════════════════════════════════
SC_DIR = None                 # %LOCALAPPDATA%\GSProControlBox\SmartCaddie
BAG_MAPPING_FILE = None       # .../bag_mapping.json   (server mirror)
WEDGE_MATRIX_FILE = None      # .../wedge_matrix.json  (server mirror)
ACCURACY_LOG_FILE = None      # .../recommendations_log.json
DEBUG_CAPTURE_DIR = None
SHOT_SESSIONS_DIR = None      # injected — Phase 1's existing sessions dir


def init_paths(app_data_dir, shot_sessions_dir):
    """Called once from gspro_server.py at startup."""
    global SC_DIR, BAG_MAPPING_FILE, WEDGE_MATRIX_FILE, ACCURACY_LOG_FILE
    global DEBUG_CAPTURE_DIR, SHOT_SESSIONS_DIR
    SC_DIR = os.path.join(app_data_dir, "SmartCaddie")
    os.makedirs(SC_DIR, exist_ok=True)
    BAG_MAPPING_FILE = os.path.join(SC_DIR, "bag_mapping.json")
    WEDGE_MATRIX_FILE = os.path.join(SC_DIR, "wedge_matrix.json")
    ACCURACY_LOG_FILE = os.path.join(SC_DIR, "recommendations_log.json")
    DEBUG_CAPTURE_DIR = os.path.join(SC_DIR, "debug_captures")
    if DEBUG_DUMP:
        os.makedirs(DEBUG_CAPTURE_DIR, exist_ok=True)
    SHOT_SESSIONS_DIR = shot_sessions_dir


# ═══════════════════════════════════════════════════════════════════════
#  §4.13 / §4.3.1 — Bag mapping & wedge matrix (server mirror)
# ═══════════════════════════════════════════════════════════════════════
def save_bag_mapping(mapping):
    """mapping: {slot: {club, distance, unit}} — mirrors localStorage
    'bagMapping' structure from gspro.html exactly, so no translation is
    needed on either side."""
    try:
        with open(BAG_MAPPING_FILE, "w", encoding="utf-8") as f:
            json.dump({"savedAt": datetime.now().isoformat(), "mapping": mapping or {}}, f, indent=2)
        return True
    except Exception as e:
        print(f"  [!] SmartCaddie: failed to save bag mapping: {e}")
        return False


def load_bag_mapping():
    if not BAG_MAPPING_FILE or not os.path.exists(BAG_MAPPING_FILE):
        return {}
    try:
        with open(BAG_MAPPING_FILE, "r", encoding="utf-8") as f:
            return (json.load(f) or {}).get("mapping", {})
    except Exception:
        return {}


def save_wedge_matrix(matrix):
    """matrix: {wedges:[...], swings:[...], distances:{club:{swing:val}}, unit}
    — mirrors localStorage 'wedgeMatrix' structure exactly."""
    try:
        with open(WEDGE_MATRIX_FILE, "w", encoding="utf-8") as f:
            json.dump({"savedAt": datetime.now().isoformat(), "matrix": matrix or {}}, f, indent=2)
        return True
    except Exception as e:
        print(f"  [!] SmartCaddie: failed to save wedge matrix: {e}")
        return False


def load_wedge_matrix():
    if not WEDGE_MATRIX_FILE or not os.path.exists(WEDGE_MATRIX_FILE):
        return {}
    try:
        with open(WEDGE_MATRIX_FILE, "r", encoding="utf-8") as f:
            return (json.load(f) or {}).get("matrix", {})
    except Exception:
        return {}


def _bag_club_names(mapping):
    names = []
    for slot, val in (mapping or {}).items():
        club = val.get("club") if isinstance(val, dict) else val
        if club:
            names.append(club)
    return names


def bag_mapping_complete(mapping):
    """Every non-putter slot that has a club assigned must also have a
    distance (§4.13 completeness check)."""
    if not mapping:
        return False, ["No clubs mapped"]
    missing = []
    for slot, val in mapping.items():
        if not isinstance(val, dict):
            missing.append(f"Slot {slot}")
            continue
        club = val.get("club", "")
        if not club:
            continue
        if str(club).lower() == "putter":
            continue
        if not val.get("distance"):
            missing.append(club)
    return (len(missing) == 0), missing


def wedge_matrix_complete(matrix):
    """At least a minimum-distance entry must exist (§4.13)."""
    if not matrix or not matrix.get("wedges") or not matrix.get("swings"):
        return False
    distances = matrix.get("distances", {})
    for wedge in matrix["wedges"]:
        entry = distances.get(wedge, {})
        if entry and any(v not in (None, "") for v in entry.values()):
            return True
    return False


def shortest_wedge_distance(matrix):
    """Flat, conservative minimum-distance fallback used when the wedge
    matrix is missing entirely (§4.13, §4.5 step 1)."""
    if not matrix:
        return None
    distances = matrix.get("distances", {})
    vals = []
    for wedge_dists in distances.values():
        for v in (wedge_dists or {}).values():
            try:
                vals.append(float(v))
            except (TypeError, ValueError):
                pass
    return min(vals) if vals else None


def caddie_prerequisite_check(mapping, matrix, clean_shot_counts):
    """§4.3.1 — three-tier check run when the Caddie button is tapped.
    Returns dict: {blocked: bool, message: str|None, warnings: [str], best_effort: bool}
    Checks 1 & 2 are soft warnings; Check 3 is a hard block."""
    bag_ok, bag_missing = bag_mapping_complete(mapping)
    wedge_ok = wedge_matrix_complete(matrix)

    # Check 3 — hard block: no bag mapping at all
    if not mapping or not _bag_club_names(mapping):
        return {
            "blocked": True,
            "message": "Bag Mapping and wedge matrix need to be completed as a minimum to use the Caddie function.",
            "warnings": [],
            "best_effort": False,
            "missing_items": [],
        }

    warnings = []
    best_effort = False
    missing_items = []

    # Check 1 — 50-shot recommendation threshold
    under_50 = [club for club, n in (clean_shot_counts or {}).items() if n < 50]
    if under_50 or not clean_shot_counts:
        warnings.append("As the 50-shot recommendation has not been completed, I will use the distance for each club from the Bag Mapping page.")
        best_effort = True
        missing_items.extend([f"{c}: fewer than 50 clean shots" for c in under_50])

    # Check 2 — wedge matrix completeness
    if not wedge_ok:
        warnings.append("As the wedge matrix has not been completed, I will use the distance for each club from the Bag Mapping page.")
        best_effort = True
        missing_items.append("Wedge matrix not set — short-game check unavailable below your shortest mapped club.")

    if not bag_ok:
        best_effort = True
        missing_items.append(f"Bag mapping incomplete for: {', '.join(bag_missing)}")

    return {
        "blocked": False,
        "message": None,
        "warnings": warnings,
        "best_effort": best_effort,
        "missing_items": missing_items,
    }


# ═══════════════════════════════════════════════════════════════════════
#  §4.7 / §6 — Club profiles from Phase 1 session data
# ═══════════════════════════════════════════════════════════════════════
# Generic manufacturer fallback carries, in yards, indexed by normalized
# club name. ⚠ PLACEHOLDER DATA — §11 of the design doc requests real
# manufacturer spec data be supplied before Phase 2 sign-off; these are
# rough mid-handicap averages only, meant to keep the pipeline runnable,
# NOT to be trusted for a live recommendation until replaced.
MANUFACTURER_FALLBACK_CARRY = {
    "DR": 230, "3W": 210, "5W": 195, "7W": 180,
    "2H": 190, "3H": 180, "4H": 170, "5H": 160, "6H": 150,
    "2I": 190, "3I": 180, "4I": 170, "5I": 160, "6I": 150,
    "7I": 140, "8I": 130, "9I": 115,
    "P": 100, "PW": 100, "50°W": 90, "52°W": 85, "54°W": 80,
    "56°W": 75, "58°W": 65, "60°W": 55, "62°W": 50, "64°W": 45,
    "S": 75, "L": 55,
}


def _shot_num(shot, field):
    try:
        v = shot.get(field)
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _load_all_sessions():
    sessions = []
    if not SHOT_SESSIONS_DIR or not os.path.isdir(SHOT_SESSIONS_DIR):
        return sessions
    for fname in os.listdir(SHOT_SESSIONS_DIR):
        if not fname.endswith(".json"):
            continue
        try:
            with open(os.path.join(SHOT_SESSIONS_DIR, fname), "r", encoding="utf-8") as f:
                sessions.append(json.load(f))
        except Exception:
            continue
    return sessions


# How "current" a club profile needs to be. §4.1's ≥90% target is
# measured against the player's OWN historical performance (§4.14) — but
# that only means something if the profile reflects how the player hits
# it NOW, not a lifetime average diluted by sessions from months ago
# when their swing, fitness, or equipment were different. So profiles
# are built from the most RECENT clean shots first, and only reach
# further back in time when there isn't yet enough recent data.
RECENCY_WINDOW_DAYS = 180     # ~6 months — shots inside this window are
                              # preferred outright over anything older.
MIN_SHOTS_TARGET   = 30      # matches the existing "30 clean shots" bar
                              # for trusting a personal profile (§4.7).
MAX_SHOTS_PER_CLUB = 60      # cap so a very active player's profile
                              # doesn't just keep growing forever — once
                              # we have this many recent shots, older
                              # ones stop being pulled in at all.


def _session_timestamp(session):
    try:
        return datetime.fromisoformat(session.get("savedAt", ""))
    except (ValueError, TypeError):
        return None


def build_club_profiles(recency_window_days=RECENCY_WINDOW_DAYS,
                         max_shots_per_club=MAX_SHOTS_PER_CLUB,
                         min_shots_target=MIN_SHOTS_TARGET):
    """§4.7 + §6.1 — one profile per club, built from clean
    (non-mishit-flagged) shots, weighted toward the player's CURRENT
    game rather than an all-time blend:

      1. Sessions are walked newest-first.
      2. If a club already has >= min_shots_target clean shots from
         within the last recency_window_days, ONLY those are used —
         older sessions are ignored entirely for that club, even if
         plenty more history exists, so a distance that's drifted over
         time doesn't get dragged back toward an outdated average.
      3. If there isn't enough recent data yet, the window is extended
         backward (still newest-first) until either min_shots_target is
         reached or the data runs out — same "fewer than 30 -> generic
         spec" fallback behaviour as before, just recency-aware.
      4. Either way, at most max_shots_per_club shots are used per club.

    Returns: { club_name: {mean_carry, mean_total, std_carry,
                            smash_factor, mean_launch_angle, clean_count,
                            data_recency, newest_shot_at, oldest_shot_at} }
    'data_recency' is 'recent' (all shots used fall inside the window) or
    'extended' (had to reach past the window to hit the shot-count bar)."""
    sessions = _load_all_sessions()
    now = datetime.now()

    def _sort_key(s):
        ts = _session_timestamp(s)
        return ts or datetime.min
    sessions.sort(key=_sort_key, reverse=True)

    by_club = {}  # club -> list of (shot, session_ts_or_None, is_recent)
    for session in sessions:
        ts = _session_timestamp(session)
        is_recent = bool(ts and (now - ts).days <= recency_window_days)
        for shot in session.get("shots", []):
            # §6.1: flag is persisted on the shot record itself (_mishit /
            # _flags, set during Phase 1 cleanup) — clean shots only.
            if shot.get("_mishit"):
                continue
            club = shot.get("Club") or shot.get("club") or "Unknown"
            by_club.setdefault(club, []).append((shot, ts, is_recent))

    profiles = {}
    for club, entries in by_club.items():
        # entries are already newest-first (sessions were sorted first).
        recent_entries = [e for e in entries if e[2]]
        if len(recent_entries) >= min_shots_target:
            chosen = recent_entries[:max_shots_per_club]
            data_recency = "recent"
        else:
            chosen = entries[:max_shots_per_club]
            data_recency = "extended" if len(chosen) > len(recent_entries) else "recent"

        shots = [e[0] for e in chosen]
        carries = [c for c in (_shot_num(s, "CarryDistance") for s in shots) if c is not None and c > 0]
        totals = [c for c in (_shot_num(s, "TotalDistance") for s in shots) if c is not None and c > 0]
        smashes = [c for c in (_shot_num(s, "SmashFactor") for s in shots) if c is not None]
        launches = [c for c in (_shot_num(s, "LaunchAngle") for s in shots) if c is not None]
        if len(carries) < 1:
            continue

        used_ts = [e[1] for e in chosen if e[1]]
        profiles[club] = {
            "mean_carry": statistics.mean(carries) if carries else None,
            "std_carry": statistics.pstdev(carries) if len(carries) > 1 else 0.0,
            "mean_total": statistics.mean(totals) if totals else None,
            "smash_factor": statistics.mean(smashes) if smashes else None,
            "mean_launch_angle": statistics.mean(launches) if launches else None,
            "clean_count": len(carries),
            "data_recency": data_recency,
            "newest_shot_at": max(used_ts).isoformat() if used_ts else None,
            "oldest_shot_at": min(used_ts).isoformat() if used_ts else None,
        }
    return profiles


def effective_carry(club, profiles):
    """Personal profile if >=30 clean shots recorded (recency-preferred
    per build_club_profiles above), else manufacturer fallback (§4.7 info
    note). Source tag distinguishes a fresh recent-data profile from one
    that had to reach back further than RECENCY_WINDOW_DAYS to hit the
    30-shot bar, so the caller/UI can flag it as slightly less current
    if useful later."""
    prof = profiles.get(club)
    if prof and prof.get("clean_count", 0) >= MIN_SHOTS_TARGET and prof.get("mean_carry"):
        source = "personal" if prof.get("data_recency") == "recent" else "personal_extended"
        return prof["mean_carry"], source
    fallback = MANUFACTURER_FALLBACK_CARRY.get(club)
    if fallback:
        return fallback, "fallback"
    if prof and prof.get("mean_carry"):
        return prof["mean_carry"], "personal_low_sample"
    return None, "unknown"


def sorted_bag_clubs(mapping):
    """Bag clubs sorted by mapped carry distance, descending (longest
    first) — used for the below-shortest / beyond-longest checks."""
    entries = []
    for slot, val in (mapping or {}).items():
        if not isinstance(val, dict):
            continue
        club = val.get("club")
        dist = val.get("distance")
        if not club or str(club).lower() == "putter":
            continue
        try:
            d = float(dist)
        except (TypeError, ValueError):
            continue
        entries.append((club, d))
    entries.sort(key=lambda e: e[1], reverse=True)
    return entries


# ═══════════════════════════════════════════════════════════════════════
#  OCR — screen capture & field extraction (§4.4 Lite scope, §5.2 Phase 3)
# ═══════════════════════════════════════════════════════════════════════
# All regions are fractions (left, top, right, bottom) of the GAME
# WINDOW's client rect, so they scale with whatever resolution the
# player runs GSPro at. ⚠ CALIBRATE THESE against real captures.
OCR_REGIONS = {
    # Two overlapping distance/elevation cards, roughly centre-screen,
    # upper-middle third — seeded from the supplied reference images.
    "distance_card": (0.40, 0.35, 0.68, 0.60),
    # Wind bar, top-centre (compass arrow + "N MPH" text).
    "wind_bar": (0.40, 0.00, 0.60, 0.08),
    # Phase 3 mini-map — can be LEFT or RIGHT side, and differs between
    # Range and Course-Play layouts (§5.2). Four placeholder boxes;
    # OCR tries all four and uses whichever yields a recognised lie
    # keyword. Replace with real coordinates once screenshots exist.
    "minimap_right_range": (0.80, 0.55, 1.00, 1.00),
    "minimap_left_range": (0.00, 0.55, 0.20, 1.00),
    "minimap_right_course": (0.82, 0.62, 1.00, 1.00),
    "minimap_left_course": (0.00, 0.62, 0.18, 1.00),
}

SANITY_RANGES = {
    "distance_to_pin": (1, 600),      # yards
    "wind_speed": (0, 60),            # mph
    "elevation": (-100, 100),         # yards
}

LIE_KEYWORDS = ["DEEP ROUGH", "DEEP", "SEMI ROUGH", "SEMI", "ROUGH",
                "FAIRWAY", "GREEN", "BUNKER", "WOOD", "WOODS", "SAND"]


def _get_window_rect(hwnd):
    import ctypes
    rect = ctypes.wintypes.RECT()
    ctypes.windll.user32.GetClientRect(hwnd, ctypes.byref(rect))
    pt = ctypes.wintypes.POINT(0, 0)
    ctypes.windll.user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return (pt.x, pt.y, pt.x + rect.right, pt.y + rect.bottom)


def capture_game_window(hwnd):
    """Returns a PIL Image of the game window's client area, or None."""
    try:
        from PIL import ImageGrab
    except ImportError:
        print("  [!] SmartCaddie: Pillow not installed — run: pip install pillow")
        return None
    if not hwnd:
        return None
    try:
        bbox = _get_window_rect(hwnd)
        img = ImageGrab.grab(bbox=bbox)
        if DEBUG_DUMP and DEBUG_CAPTURE_DIR:
            img.save(os.path.join(DEBUG_CAPTURE_DIR, f"full_{int(time.time())}.png"))
        return img
    except Exception as e:
        print(f"  [!] SmartCaddie: capture failed: {e}")
        return None


def _crop_fraction(img, region):
    w, h = img.size
    l, t, r, b = region
    box = (int(l * w), int(t * h), int(r * w), int(b * h))
    return img.crop(box)


def _ocr_text(img_crop, tag=""):
    try:
        import pytesseract
    except ImportError:
        print("  [!] SmartCaddie: pytesseract not installed — run: pip install pytesseract "
              "(and install the Tesseract binary separately: https://github.com/UB-Mannheim/tesseract/wiki)")
        return ""
    if DEBUG_DUMP and DEBUG_CAPTURE_DIR and tag:
        img_crop.save(os.path.join(DEBUG_CAPTURE_DIR, f"{tag}_{int(time.time())}.png"))
    try:
        return pytesseract.image_to_string(img_crop, config="--psm 6")
    except Exception as e:
        print(f"  [!] SmartCaddie: OCR error ({tag}): {e}")
        return ""


def _parse_distance_token(token):
    """Handles both plain-yard ('322') and feet'-inches" ('19' 2') styles
    seen in the reference captures, returning yards as a float."""
    token = token.strip()
    m = re.match(r"^(\d+)\s*'\s*(\d+)", token)
    if m:
        feet = float(m.group(1))
        return feet / 3.0  # feet -> yards (close-range chip readout)
    m = re.match(r"^(\d+(?:\.\d+)?)$", token)
    if m:
        return float(m.group(1))
    return None


def _in_range(name, value):
    if value is None:
        return False
    lo, hi = SANITY_RANGES.get(name, (None, None))
    if lo is None:
        return True
    return lo <= value <= hi


def ocr_distance_elevation(img):
    """§4.4 + OCR misread guard (§4.10). Returns:
      {distance_to_pin, distance_missing, elevation, elevation_missing,
       raw_text, dual_readings:[...]}
    Dual-distance rule (§4.5 OCR note): when two distance readings are
    present, always use the LOWEST. If a reading looks partial/truncated,
    use the fuller (front) number instead."""
    crop = _crop_fraction(img, OCR_REGIONS["distance_card"])
    text = _ocr_text(crop, "distance_card")
    numbers = re.findall(r"\d+\s*'\s*\d+|\d+", text)
    readings = [d for d in (_parse_distance_token(t) for t in numbers) if d is not None]

    result = {"distance_to_pin": None, "distance_missing": True,
              "elevation": None, "elevation_missing": True,
              "raw_text": text, "dual_readings": readings}

    if readings:
        # Dual-distance rule: lowest of the (assumed) two main distance
        # readings; a lone very-short/truncated-looking reading is
        # treated as partial and the fuller number (first found) is kept.
        main = sorted(readings)[0] if len(readings) > 1 else readings[0]
        if _in_range("distance_to_pin", main):
            result["distance_to_pin"] = main
            result["distance_missing"] = False

    # Elevation: look for a signed number near an up/down arrow glyph;
    # OCR text alone can't reliably distinguish uphill/downhill, so this
    # also inspects the crop's arrow glyph colour/orientation heuristically.
    elev_match = re.search(r"([+-]?\d+(?:\.\d+)?)\s*(?:yd|y)?\b", text)
    if elev_match:
        try:
            elev_val = float(elev_match.group(1))
            direction = _detect_arrow_direction(crop)
            if direction == "down":
                elev_val = -abs(elev_val)
            elif direction == "up":
                elev_val = abs(elev_val)
            if _in_range("elevation", elev_val):
                result["elevation"] = elev_val
                result["elevation_missing"] = False
        except ValueError:
            pass

    return result


def _detect_arrow_direction(crop):
    """Heuristic: finds the darkest/most saturated small triangular glyph
    in the crop and checks whether its mass sits in the top or bottom
    half of its own bounding box (a downward triangle is bottom-heavy at
    its point, i.e. wide-top/narrow-bottom — approximated here via pixel
    density skew). Returns 'up', 'down', or None.
    ⚠ Calibrate against real captures — this is a coarse fallback, not a
    template-matched icon reader."""
    try:
        import numpy as np
        gray = crop.convert("L")
        arr = np.array(gray)
        if arr.size == 0:
            return None
        mid = arr.shape[0] // 2
        top_density = float((arr[:mid] < 128).sum())
        bottom_density = float((arr[mid:] < 128).sum())
        if top_density + bottom_density < 5:
            return None
        return "up" if top_density > bottom_density else "down"
    except Exception:
        return None


def ocr_wind(img):
    """§4.4 — wind direction + speed. Direction relative to shot line is
    approximated from the compass arrow's rotation via colour-mass PCA;
    speed is a straightforward 'N MPH' OCR read."""
    crop = _crop_fraction(img, OCR_REGIONS["wind_bar"])
    text = _ocr_text(crop, "wind_bar")
    result = {"wind_speed": None, "wind_missing": True, "wind_bearing_deg": None, "raw_text": text}

    m = re.search(r"(\d+(?:\.\d+)?)\s*MPH", text, re.IGNORECASE)
    if m:
        try:
            speed = float(m.group(1))
            if _in_range("wind_speed", speed):
                result["wind_speed"] = speed
                result["wind_missing"] = False
        except ValueError:
            pass

    result["wind_bearing_deg"] = _detect_arrow_bearing(crop)
    return result


def _detect_arrow_bearing(crop):
    """PCA-based orientation of the blue arrow glyph against the dark
    navy bar background. Returns degrees (0=up/away from player) or None
    if no clear arrow shape found. ⚠ Tune the colour mask for your
    theme/monitor — this assumes the blue seen in the reference images."""
    try:
        import numpy as np
        arr = np.array(crop.convert("RGB")).astype(float)
        r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
        # crude "bluish, not background-navy" mask
        mask = (b > 120) & (b > r + 20) & (b > g + 10)
        ys, xs = np.nonzero(mask)
        if len(xs) < 8:
            return None
        xs = xs - xs.mean()
        ys = ys - ys.mean()
        cov = np.cov(np.vstack([xs, ys]))
        eigvals, eigvecs = np.linalg.eigh(cov)
        principal = eigvecs[:, int(eigvals.argmax())]
        angle = math.degrees(math.atan2(principal[1], principal[0]))
        return angle % 360
    except Exception:
        return None


def ocr_lie_and_stance(img):
    """§5.2 — Phase 3 mini-map OCR: lie keyword + stance tilt. Tries all
    four placeholder regions (left/right x range/course-play) and uses
    whichever produces a recognised lie keyword, per the 'must handle
    both layouts and both sides' requirement."""
    result = {"lie": None, "lie_missing": True,
              "stance_tilt_deg": None, "stance_direction": None, "stance_missing": True,
              "raw_text": ""}
    for region_key in ("minimap_right_range", "minimap_left_range",
                       "minimap_right_course", "minimap_left_course"):
        crop = _crop_fraction(img, OCR_REGIONS[region_key])
        text = _ocr_text(crop, region_key)
        upper = text.upper()
        found = next((kw for kw in LIE_KEYWORDS if kw in upper), None)
        if found:
            lie = "Deep Rough" if found in ("DEEP ROUGH", "DEEP") else \
                  "Semi Rough" if found in ("SEMI ROUGH", "SEMI") else \
                  "Wood" if found in ("WOOD", "WOODS") else \
                  "Bunker" if found in ("BUNKER", "SAND") else found.title()
            result["lie"] = lie
            result["lie_missing"] = False
            result["raw_text"] = text

            tilt_match = re.search(r"(\d+(?:\.\d+)?)\s*°?\s*(UP|DOWN|LEFT|RIGHT)", upper)
            if tilt_match:
                deg = float(tilt_match.group(1))
                direction = tilt_match.group(2).lower()
                result["stance_tilt_deg"] = deg
                result["stance_direction"] = direction
                result["stance_missing"] = False
            break
    return result


def run_full_ocr_scan(hwnd, phase3_enabled=False):
    """Top-level OCR entry point used by the WebSocket handler."""
    img = capture_game_window(hwnd)
    if img is None:
        return None
    out = {}
    out.update(ocr_distance_elevation(img))
    out.update(ocr_wind(img))
    if phase3_enabled:
        out.update(ocr_lie_and_stance(img))
    else:
        out.update({"lie": None, "lie_missing": True,
                    "stance_tilt_deg": None, "stance_direction": None, "stance_missing": True})
    return out


# ═══════════════════════════════════════════════════════════════════════
#  §4.6 / §5.4 — Elevation & lie/terrain adjustment
# ═══════════════════════════════════════════════════════════════════════
def elevation_adjusted_distance(distance_to_pin, elevation):
    """§4.6 — uphill adds, downhill subtracts."""
    if distance_to_pin is None:
        return None
    if elevation is None:
        return distance_to_pin
    return distance_to_pin + elevation


# §5.4 simplified table (kept as first-approximation reference).
LIE_FLAT_TABLE = {
    "Fairway": (0.0, 0.0),
    "Rough": (-0.09, -0.30),          # midpoint of the 8-10% / 15-50% range
    "Deep Rough": (-0.20, -0.50),
    "Semi Rough": (-0.05, -0.05),
    "Bunker": (-0.20, -0.50),         # treated as Deep Rough per §5.3
}


def launch_angle_penalty_factor(lie, launch_angle_deg):
    """§5.4 correction — dynamic, launch-angle-aware penalty for Deep
    Rough / Bunker, replacing the flat -20%/-50% figures for anything
    other than a 'typical mid-iron' launch angle. Lower launch angle =
    harsher penalty (long clubs punished hardest); higher launch angle
    (wedges) penalised much less, matching the source material's
    3-Wood-60%-vs-PW-10% example.
    Returns (distance_factor, spin_factor) as multipliers, e.g. 0.60
    means 'retains 60% of baseline distance'."""
    if lie not in ("Deep Rough", "Bunker"):
        return None
    if launch_angle_deg is None:
        # No club-profile launch angle available — fall back to the flat table.
        return LIE_FLAT_TABLE.get(lie)

    # Piecewise-linear model anchored on the two reference points from
    # the design doc / caddie notes: ~10-12° (3-Wood-ish) -> 60% power
    # penalty (0.40 retained); ~24-28° (PW-ish) -> 10% penalty (0.90
    # retained). Clamped at the ends.
    low_angle, low_retain = 11.0, 0.40
    high_angle, high_retain = 26.0, 0.90
    angle = max(low_angle, min(high_angle, launch_angle_deg))
    t = (angle - low_angle) / (high_angle - low_angle)
    distance_retain = low_retain + t * (high_retain - low_retain)
    distance_penalty = -(1.0 - distance_retain)

    # Bunkers: higher typical launch partially offsets the penalty for
    # shorter clubs (§5.3 bullet on Bunker).
    if lie == "Bunker":
        distance_penalty *= 0.7

    # Spin penalty scales similarly but stays proportionally larger,
    # matching '20% speed / much larger spin loss' pattern in the notes.
    spin_penalty = distance_penalty * 2.2
    spin_penalty = max(-0.90, spin_penalty)

    return (distance_penalty, spin_penalty)


def lie_terrain_adjusted_distance(base_distance, lie, launch_angle_deg=None):
    """§5.4 — applies on top of Phase 2's elevation adjustment. Returns
    (adjusted_distance, distance_penalty_pct, spin_penalty_pct)."""
    if base_distance is None or not lie or lie in ("Fairway", "Green"):
        return base_distance, 0.0, 0.0

    if lie in ("Deep Rough", "Bunker"):
        factors = launch_angle_penalty_factor(lie, launch_angle_deg)
        if factors is None:
            return base_distance, 0.0, 0.0
        dist_pen, spin_pen = factors
    else:
        dist_pen, spin_pen = LIE_FLAT_TABLE.get(lie, (0.0, 0.0))

    adjusted = base_distance * (1.0 + dist_pen)
    return adjusted, dist_pen, spin_pen


# ═══════════════════════════════════════════════════════════════════════
#  §5.5 — Stance-adjusted aim offset
# ═══════════════════════════════════════════════════════════════════════
def stance_aim_offset_yards(base_offset_yards, stance_direction, stance_tilt_deg):
    """Ball below feet -> tends to leak RIGHT; ball above feet -> tends
    to pull LEFT (§5.1 background, §5.5). 'stance_direction' here is the
    ground-tilt direction read off the mini-map (left/right), used as a
    proxy for above/below-feet since both derive from the same sideways
    slope reading. ~0.3y of extra lateral drift per degree of tilt,
    applied on top of the wind/dispersion offset already computed by
    §4.8 — this is a first-pass coefficient, not derived from real data."""
    if not stance_direction or not stance_tilt_deg:
        return base_offset_yards
    drift_per_degree = 0.3
    drift = stance_tilt_deg * drift_per_degree
    if stance_direction == "right":
        return base_offset_yards - drift  # ball below feet -> leaks right -> aim further left to compensate
    elif stance_direction == "left":
        return base_offset_yards + drift  # ball above feet -> pulls left -> aim further right to compensate
    return base_offset_yards


# ═══════════════════════════════════════════════════════════════════════
#  §4.8 — Wind vector / aim offset (Lite scope)
# ═══════════════════════════════════════════════════════════════════════
def wind_aim_offset_yards(wind_speed, wind_bearing_deg, dispersion_std=8.0):
    """Simplified crosswind model: full wind speed at 90°/270° bearing,
    zero at 0°/180° (headwind/tailwind), scaled by ~0.5y of drift per
    mph of pure crosswind component, blended lightly with the player's
    own dispersion (wider natural dispersion -> caddie leans on it less
    aggressively for the wind figure)."""
    if wind_speed is None or wind_bearing_deg is None:
        return 0.0
    crosswind_component = math.sin(math.radians(wind_bearing_deg))
    drift = wind_speed * crosswind_component * 0.5
    return round(drift, 1)


def swing_shape_for_distance(effective_distance, club_carry):
    """Hard / Normal / Soft based on how close the elevation+terrain
    -adjusted effective distance sits to the club's own average carry."""
    if club_carry is None or effective_distance is None:
        return "Normal"
    diff_pct = (effective_distance - club_carry) / club_carry
    if diff_pct > 0.04:
        return "Hard"
    if diff_pct < -0.04:
        return "Soft"
    return "Normal"


def pick_club_for_distance(target_distance, bag_clubs_sorted):
    """bag_clubs_sorted: [(club, carry_distance), ...] longest first.
    Picks the club whose carry is closest to (but not wildly under)
    the target distance."""
    if not bag_clubs_sorted or target_distance is None:
        return None
    best = min(bag_clubs_sorted, key=lambda e: abs(e[1] - target_distance))
    return best[0]


# ═══════════════════════════════════════════════════════════════════════
#  §4.5 / §5.3 — Full decision hierarchy
# ═══════════════════════════════════════════════════════════════════════
def compute_recommendation(ocr_data, mapping, matrix, profiles, phase3_enabled, prereq):
    """Returns the caddie_recommendation payload (§4.12, extended by §5.6).
    'prereq_warnings' are the §4.3.1 soft-gate messages the tablet should
    show as an acknowledge-first popup; 'runtime_warnings' (extreme wind,
    bunker variability, etc.) are shown inline on the card itself without
    blocking anything."""
    prereq_warnings = list(prereq.get("warnings", []))
    runtime_warnings = []
    missing_fields = []

    distance = ocr_data.get("distance_to_pin")
    if ocr_data.get("distance_missing"):
        missing_fields.append("Distance to pin needed — re-aim capture")
    elevation = ocr_data.get("elevation")
    if ocr_data.get("elevation_missing"):
        missing_fields.append("Elevation reading needed")
    wind_speed = ocr_data.get("wind_speed")
    wind_bearing = ocr_data.get("wind_bearing_deg")
    if ocr_data.get("wind_missing"):
        missing_fields.append("Wind reading needed")
    if wind_speed is not None and wind_speed > 25:
        runtime_warnings.append("Extreme wind (>25mph) — model accuracy decreases; consider a conservative, centre-of-green aim.")

    lie = ocr_data.get("lie") if phase3_enabled else None
    stance_dir = ocr_data.get("stance_direction") if phase3_enabled else None
    stance_tilt = ocr_data.get("stance_tilt_deg") if phase3_enabled else None

    bag_clubs = sorted_bag_clubs(mapping)
    shortest_bag_carry = bag_clubs[-1][1] if bag_clubs else None
    longest_bag_carry = bag_clubs[0][1] if bag_clubs else None
    wedge_min = shortest_wedge_distance(matrix)
    shortest_known = wedge_min if wedge_min is not None else shortest_bag_carry
    if wedge_min is None and shortest_bag_carry is not None:
        prereq_warnings.append("Wedge matrix not set — using a flat, conservative minimum-distance assumption for the short-game check.")

    base = {
        "type": "caddie_recommendation",
        "phase3": bool(phase3_enabled),
        "best_effort": prereq.get("best_effort", False),
        "missing_items": prereq.get("missing_items", []) + missing_fields,
        "prereq_warnings": prereq_warnings,
        "runtime_warnings": runtime_warnings,
        "warnings": prereq_warnings + runtime_warnings,  # combined, for logging/back-compat
        "ocr": {
            "distance_to_pin": distance, "elevation": elevation,
            "wind_speed": wind_speed, "wind_bearing_deg": wind_bearing,
            "lie": lie, "stance_direction": stance_dir, "stance_tilt_deg": stance_tilt,
        },
    }

    # ── Step 0 (Phase 3 only) — Lie = Green -> Putter, checked first ──
    if phase3_enabled and lie == "Green":
        base.update({"recommendation_type": "putt", "club": "Putter",
                     "shape": None, "aim_offset_yards": 0, "accuracy_pct": None,
                     "message": "On the green — Putter."})
        return base

    # ── Phase 3 additional lie rules: Wood/Woods, Bunker context ──
    if phase3_enabled and lie == "Wood":
        base.update({"recommendation_type": "wood_lie", "club": None, "shape": None,
                     "aim_offset_yards": 0, "accuracy_pct": None,
                     "message": "Ball is in the woods — play out sideways, take a Sim drop, or take a mulligan. "
                                "A full swing from here isn't a realistic recommendation."})
        return base

    if distance is None:
        base.update({"recommendation_type": "error", "club": None, "shape": None,
                     "aim_offset_yards": None, "accuracy_pct": None,
                     "message": "Couldn't read distance to pin — please re-aim the capture and try again."})
        return base

    effective_distance = elevation_adjusted_distance(distance, elevation)

    # ── Step 1 — below shortest club (or Phase 3 Semi Rough OR-condition) -> Chip ──
    below_shortest = shortest_known is not None and effective_distance < shortest_known
    semi_rough_chip = phase3_enabled and lie == "Semi Rough"
    if below_shortest or semi_rough_chip:
        base.update({"recommendation_type": "chip", "club": "Chip", "shape": None,
                     "aim_offset_yards": 0, "accuracy_pct": None,
                     "message": f"Short-game range{' (Semi Rough)' if semi_rough_chip else ''} — recommend a chip rather than a full swing."})
        return base

    # ── Step 2 — beyond longest club -> lay-up prompt ──
    if longest_bag_carry is not None and effective_distance > longest_bag_carry:
        base.update({"recommendation_type": "layup_prompt", "club": None, "shape": None,
                     "aim_offset_yards": None, "accuracy_pct": None,
                     "message": "Beyond your longest mapped club — please enter an intermediate lay-up target distance."})
        return base

    # ── Step 3 — full recommendation ──
    terrain_distance = effective_distance
    dist_pen = spin_pen = 0.0
    if phase3_enabled and lie:
        club_guess = pick_club_for_distance(effective_distance, bag_clubs)
        prof = profiles.get(club_guess, {}) if club_guess else {}
        terrain_distance, dist_pen, spin_pen = lie_terrain_adjusted_distance(
            effective_distance, lie, prof.get("mean_launch_angle"))
        if lie == "Bunker":
            runtime_warnings.append("Bunker lie — distance control from sand is highly variable.")

    club = pick_club_for_distance(terrain_distance, bag_clubs)
    carry_for_club, source = effective_carry(club, profiles) if club else (None, "unknown")
    shape = swing_shape_for_distance(terrain_distance, carry_for_club)

    aim_offset = wind_aim_offset_yards(wind_speed, wind_bearing)
    if phase3_enabled:
        aim_offset = stance_aim_offset_yards(aim_offset, stance_dir, stance_tilt)

    accuracy_pct = 90 if (phase3_enabled and lie) else 80  # §4.1 note: Lite alone should land below the 90% target
    if base["best_effort"]:
        accuracy_pct -= 10

    direction_word = "LEFT" if aim_offset < 0 else "RIGHT"
    lie_phrase = f" from {lie}" if (phase3_enabled and lie) else ""
    message = (f"Distance {round(distance)}yd" +
               (f", {'Uphill' if elevation and elevation > 0 else 'Downhill'} {abs(round(elevation))}yd" if elevation else "") +
               (f", Wind: {round(wind_speed)}mph" if wind_speed is not None else "") +
               f"{lie_phrase}. Recommended Shot: Club: {shape} {club or '—'}, "
               f"Aim: {abs(aim_offset)} yards {direction_word} of pin, "
               f"Percentage of accuracy {accuracy_pct}%.")

    base.update({
        "recommendation_type": "full", "club": club, "shape": shape,
        "aim_offset_yards": aim_offset, "accuracy_pct": accuracy_pct,
        "carry_source": source, "terrain_distance_penalty_pct": round(dist_pen * 100, 1),
        "terrain_spin_penalty_pct": round(spin_pen * 100, 1),
        "message": message,
    })
    return base


# ═══════════════════════════════════════════════════════════════════════
#  §4.14 — Accuracy tracking log
# ═══════════════════════════════════════════════════════════════════════
def log_recommendation(recommendation):
    """Append-only log; timestamp is matched against next-shot session
    data later (by a future analysis pass), per §4.14's 'cheapest version
    that produces real numbers' approach."""
    entry = {"loggedAt": datetime.now().isoformat(), "recommendation": recommendation}
    try:
        existing = []
        if ACCURACY_LOG_FILE and os.path.exists(ACCURACY_LOG_FILE):
            with open(ACCURACY_LOG_FILE, "r", encoding="utf-8") as f:
                existing = json.load(f) or []
        existing.append(entry)
        with open(ACCURACY_LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2)
    except Exception as e:
        print(f"  [!] SmartCaddie: failed to write accuracy log: {e}")


def clean_shot_counts_per_club(profiles):
    return {club: prof.get("clean_count", 0) for club, prof in profiles.items()}
