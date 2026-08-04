#!/usr/bin/env python3
"""
GSPro - PC Server v1.12
================================
Uses hardware scancodes via SendInput for Unreal Engine compatibility.
Pre-focuses app window at startup for faster first keystroke.
"""

import asyncio, functools, json, os, socket, struct, subprocess, sys, threading, time, traceback, uuid, webbrowser
import ctypes, ctypes.wintypes
import http.server
import urllib.request, urllib.error, urllib.parse
from datetime import datetime, timedelta

# ── Redirect stdout/stderr for windowless PyInstaller execution ────────────────
if sys.stdout is None or sys.stderr is None:
    local_app_data = os.environ.get('LOCALAPPDATA', os.path.expanduser('~'))
    app_data_dir = os.path.join(local_app_data, "GSProControlBox")
    os.makedirs(app_data_dir, exist_ok=True)
    log_file = os.path.join(app_data_dir, "server.log")
    try:
        f = open(log_file, "a", encoding="utf-8", buffering=1)
        sys.stdout = f
        sys.stderr = f
    except:
        class DummyWriter:
            def write(self, x): pass
            def flush(self): pass
        sys.stdout = DummyWriter()
        sys.stderr = DummyWriter()

# ═══════════════════════════════════
#  CONFIGURATION — edit these
# ═══════════════════════════════════
TARGET_WINDOW   = "gspro"            # Window title of your app
PORT            = 8082              # WebSocket port
HTTP_PORT       = 8083              # HTTP port (serves the app)
HTML_UPDATE_URL = "https://raw.githubusercontent.com/Mickey202505/gspro-control-box/refs/heads/main/gspro.html"
SERVER_VERSION = "1.12"
VERSION_CHECK_URL = "https://raw.githubusercontent.com/Mickey202505/gspro-control-box/refs/heads/main/version.txt"
RELEASES_URL = "https://github.com/Mickey202505/gspro-control-box/releases/latest"

# ── License & Analytics configuration ──────────────────────────────────────────
GOOGLE_FORM_URL   = "https://docs.google.com/forms/d/e/1FAIpQLSfE5mbcW1-PP8qMsuTHlipa9QtCbZgy6F-nVgSSlvRSzZBllw/formResponse"
ENTRY_LICENSE_ID  = "entry.256271637"
ENTRY_EVENT_TYPE  = "entry.1911664682"
ENTRY_LAUNCH_CNT  = "entry.65335459"
ANNOUNCEMENT_URL  = "https://raw.githubusercontent.com/Mickey202505/gspro-control-box/refs/heads/main/announcement.json"
MESSAGE_URL       = "https://raw.githubusercontent.com/Mickey202505/gspro-control-box/refs/heads/main/message.json"

# ── License & Telemetry helper functions ──────────────────────────────────────
# Use LocalAppData for writable files to avoid "Program Files" permission issues
try:
    # 1. Establish the dedicated workspace directory in Local AppData
    local_app_data = os.environ.get('LOCALAPPDATA', os.path.expanduser('~'))
    app_data_dir = os.path.join(local_app_data, "GSProControlBox")
    os.makedirs(app_data_dir, exist_ok=True)
    
    launcher_path = sys.executable if getattr(sys, 'frozen', False) else os.path.abspath(__file__)
    launcher_dir = os.path.dirname(launcher_path)
    if launcher_dir not in sys.path: sys.path.insert(0, launcher_dir)
    WORKING_DIR = launcher_dir
    
    print(f"\n--- New Session: {datetime.now()} ---")
    print(f"Launch Path: {launcher_path}")

    # 3. "Work from there" - Set the local workspace as the active directory
    os.chdir(app_data_dir)
except Exception as e:
    ctypes.windll.user32.MessageBoxW(0, f"Critical Path Error:\n{e}", "Startup Error", 0x10)
    sys.exit(1)

LOCAL_HTML_PATH = os.path.join(WORKING_DIR, "gspro.html")
LICENSE_FILE    = os.path.join(app_data_dir, "gspro_license.json")
MACROS_FILE     = os.path.join(app_data_dir, "gspro_macros.json")

SHOTS_DIR          = os.path.join(app_data_dir, "GolfShotData")
SHOT_SESSIONS_DIR  = os.path.join(SHOTS_DIR, "sessions")
SHOT_DELETED_DIR   = os.path.join(SHOTS_DIR, "deleted_archive")
for _sd_dir in (SHOTS_DIR, SHOT_SESSIONS_DIR, SHOT_DELETED_DIR):
    try:
        os.makedirs(_sd_dir, exist_ok=True)
    except Exception as e:
        print(f"  [!] Could not create shot data folder {_sd_dir}: {e}")

# ── Smart Caddie (Phase 2 + Phase 3, §2.3) ────────────────────────────────────
# Runs inside this process — no new .exe, per the design doc. See
# smart_caddie.py for the OCR pipeline, club profiles, and recommendation
# engine. PHASE3_ENABLED is a soft feature flag: Phase 3 is "deferred
# until Phase 2 is proven in real play" (§5.1) — flip to True once the
# mini-map OCR regions have been calibrated and Phase 2 has run in real
# rounds. Leaving it False makes the whole pipeline behave exactly like
# Lite (§4), silently skipping every §5 lie/stance step.
PHASE3_ENABLED = os.environ.get("GSPRO_PHASE3_ENABLED", "0") == "1"
try:
    import smart_caddie
    smart_caddie.init_paths(app_data_dir, SHOT_SESSIONS_DIR)
except Exception as e:
    smart_caddie = None
    print(f"  [!] Smart Caddie module failed to load: {e}")

# ── Macro recording state ─────────────────────────────────────────────────────
macro_armed           = False   # Tablet pressed Record — waiting for F9
_shotdata_process    = None  # Popen handle for the launched Shot Data app, so a
                             # second tap of the button doesn't spawn a duplicate
                             # while one is already open
macro_recording       = False   # F9 pressed once — actively capturing keys
macro_recorded_events = []      # Captured {key/mouse, delay} list
_macro_ws_ref         = None    # WebSocket to notify on stop
_macro_hook_handle    = None    # Windows keyboard hook handle
_macro_mouse_hook_handle = None # Windows mouse hook handle
_macro_last_time      = None    # Timestamp of last event
_macro_hook_thread_id = None    # Thread ID of hook thread
_main_loop            = None    # asyncio event loop (set at startup)

# Virtual-key → name map for recording (extend as needed)
VK_NAME = {
    0x08:'backspace', 0x09:'tab',    0x0D:'enter',  0x1B:'escape',
    0x20:'space',     0x25:'left',   0x26:'up',     0x27:'right',  0x28:'down',
    0x30:'0', 0x31:'1', 0x32:'2', 0x33:'3', 0x34:'4',
    0x35:'5', 0x36:'6', 0x37:'7', 0x38:'8', 0x39:'9',
    0x41:'a', 0x42:'b', 0x43:'c', 0x44:'d', 0x45:'e',
    0x46:'f', 0x47:'g', 0x48:'h', 0x49:'i', 0x4A:'j',
    0x4B:'k', 0x4C:'l', 0x4D:'m', 0x4E:'n', 0x4F:'o',
    0x50:'p', 0x51:'q', 0x52:'r', 0x53:'s', 0x54:'t',
    0x55:'u', 0x56:'v', 0x57:'w', 0x58:'x', 0x59:'y', 0x5A:'z',
    0x70:'f1',  0x71:'f2',  0x72:'f3',  0x73:'f4',
    0x74:'f5',  0x75:'f6',  0x76:'f7',  0x77:'f8',
    0x78:'f9',  0x79:'f10', 0x7A:'f11', 0x7B:'f12',
}
VK_F9 = 0x78

WH_KEYBOARD_LL = 13
WH_MOUSE_LL    = 14
WM_KEYDOWN     = 0x0100
WM_MOUSEMOVE   = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_RBUTTONDOWN = 0x0204
WM_MBUTTONDOWN = 0x0207

class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [('vkCode',      ctypes.wintypes.DWORD),
                ('scanCode',    ctypes.wintypes.DWORD),
                ('flags',       ctypes.wintypes.DWORD),
                ('time',        ctypes.wintypes.DWORD),
                ('dwExtraInfo', ctypes.POINTER(ctypes.c_ulong))]

class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [('pt',          ctypes.wintypes.POINT),
                ('mouseData',   ctypes.wintypes.DWORD),
                ('flags',       ctypes.wintypes.DWORD),
                ('time',        ctypes.wintypes.DWORD),
                ('dwExtraInfo', ctypes.POINTER(ctypes.c_ulong))]

_LowLevelKeyboardProc = ctypes.WINFUNCTYPE(
    ctypes.c_long, ctypes.c_int, ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM)
_LowLevelMouseProc = ctypes.WINFUNCTYPE(
    ctypes.c_long, ctypes.c_int, ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM)

def _make_hook_proc():
    def hook_proc(nCode, wParam, lParam):
        global macro_armed, macro_recording, macro_recorded_events
        global _macro_last_time, _macro_ws_ref, _macro_hook_handle

        if nCode >= 0 and wParam == WM_KEYDOWN:
            kb   = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            vk   = kb.vkCode
            now  = time.time()

            if vk == VK_F9:
                if macro_armed and not macro_recording:
                    # First F9 — start capturing
                    macro_recording       = True
                    macro_armed           = False
                    macro_recorded_events = []
                    _macro_last_time      = now
                    print("  [MACRO] F9 pressed — recording STARTED")
                    # Notify tablet
                    if _macro_ws_ref and _main_loop:
                        asyncio.run_coroutine_threadsafe(
                            _macro_ws_ref.send(json.dumps({"type": "macro_recording_started"})),
                            _main_loop)
                    # Suppress F9 from reaching other apps
                    return 1

                elif macro_recording:
                    # Second F9 — stop capturing
                    macro_recording = False
                    events          = list(macro_recorded_events)
                    print(f"  [MACRO] F9 pressed — recording STOPPED ({len(events)} events)")
                    _stop_keyboard_hook()
                    # Send events back to tablet
                    if _macro_ws_ref and _main_loop:
                        asyncio.run_coroutine_threadsafe(
                            _macro_ws_ref.send(json.dumps(
                                {"type": "macro_record_done", "events": events})),
                            _main_loop)
                    return 1   # Suppress F9

            elif macro_recording:
                key_name = VK_NAME.get(vk)
                if key_name:
                    delay = round(now - _macro_last_time, 3) if _macro_last_time else 0.05
                    _macro_last_time = now
                    macro_recorded_events.append({"type": "key", "key": key_name, "delay": delay})
                    print(f"  [MACRO] Captured: {key_name}  (+{delay}s)")

        return ctypes.windll.user32.CallNextHookEx(None, nCode, wParam, ctypes.c_long(lParam))
    return hook_proc

_hook_proc_ref       = None   # Must keep a reference to prevent GC
_mouse_hook_proc_ref = None   # Must keep a reference to prevent GC

def _make_mouse_hook_proc():
    def mouse_hook_proc(nCode, wParam, lParam):
        global macro_recording, macro_recorded_events, _macro_last_time
        if nCode >= 0 and macro_recording:
            ms  = ctypes.cast(lParam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
            now = time.time()
            delay = round(now - _macro_last_time, 3) if _macro_last_time else 0.05

            if wParam == WM_MOUSEMOVE:
                macro_recorded_events.append({
                    "type": "mouse_move",
                    "x": ms.pt.x, "y": ms.pt.y,
                    "delay": delay
                })
                _macro_last_time = now

            elif wParam in (WM_LBUTTONDOWN, WM_RBUTTONDOWN, WM_MBUTTONDOWN):
                btn = {WM_LBUTTONDOWN: "left", WM_RBUTTONDOWN: "right", WM_MBUTTONDOWN: "middle"}[wParam]
                macro_recorded_events.append({
                    "type": "mouse_click",
                    "button": btn,
                    "x": ms.pt.x, "y": ms.pt.y,
                    "delay": delay
                })
                _macro_last_time = now
                print(f"  [MACRO] Captured: mouse_{btn}_click @ ({ms.pt.x},{ms.pt.y})  (+{delay}s)")

        return ctypes.windll.user32.CallNextHookEx(None, nCode, wParam, ctypes.c_long(lParam))
    return mouse_hook_proc

def _start_keyboard_hook():
    global _macro_hook_handle, _macro_mouse_hook_handle, _hook_proc_ref, _mouse_hook_proc_ref, macro_armed, _macro_hook_thread_id

    def hook_thread():
        global _macro_hook_handle, _macro_mouse_hook_handle, _hook_proc_ref, _mouse_hook_proc_ref, _macro_hook_thread_id
        _macro_hook_thread_id = ctypes.windll.kernel32.GetCurrentThreadId()

        # Install keyboard hook
        _hook_proc_ref = _LowLevelKeyboardProc(_make_hook_proc())
        _macro_hook_handle = ctypes.windll.user32.SetWindowsHookExW(
            WH_KEYBOARD_LL, _hook_proc_ref, None, 0)
        if not _macro_hook_handle:
            print("  [!] Failed to install keyboard hook")
            return

        # Install mouse hook
        _mouse_hook_proc_ref = _LowLevelMouseProc(_make_mouse_hook_proc())
        _macro_mouse_hook_handle = ctypes.windll.user32.SetWindowsHookExW(
            WH_MOUSE_LL, _mouse_hook_proc_ref, None, 0)
        if not _macro_mouse_hook_handle:
            print("  [!] Failed to install mouse hook (mouse events won't be recorded)")
        else:
            print("  [MACRO] Mouse hook installed")

        print("  [MACRO] Keyboard hook installed — waiting for F9")
        msg = ctypes.wintypes.MSG()
        while True:
            ret = ctypes.windll.user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret <= 0:
                break
            if msg.message == 0x0012:  # WM_QUIT
                break
            ctypes.windll.user32.TranslateMessage(ctypes.byref(msg))
            ctypes.windll.user32.DispatchMessageW(ctypes.byref(msg))
        print("  [MACRO] Hook thread exited")

    threading.Thread(target=hook_thread, daemon=True).start()

def _stop_keyboard_hook():
    global _macro_hook_handle, _macro_mouse_hook_handle, _macro_hook_thread_id
    if _macro_mouse_hook_handle:
        ctypes.windll.user32.UnhookWindowsHookEx(_macro_mouse_hook_handle)
        _macro_mouse_hook_handle = None
        print("  [MACRO] Mouse hook removed")
    if _macro_hook_handle:
        ctypes.windll.user32.UnhookWindowsHookEx(_macro_hook_handle)
        _macro_hook_handle = None
        print("  [MACRO] Keyboard hook removed")
    if _macro_hook_thread_id:
        ctypes.windll.user32.PostThreadMessageW(_macro_hook_thread_id, 0x0012, 0, 0)
        _macro_hook_thread_id = None

def load_macros():
    try:
        if os.path.exists(MACROS_FILE):
            with open(MACROS_FILE, "r") as f:
                return json.load(f)
    except Exception as e:
        print(f"  [!] Failed to load macros: {e}")
    return {}

def save_macros_to_disk(macros):
    try:
        with open(MACROS_FILE, "w") as f:
            json.dump(macros, f, indent=2)
    except Exception as e:
        print(f"  [!] Failed to save macros: {e}")

# ── Shot Data: native CSV file picker + permanent session backups ──────────────
class _OPENFILENAMEW(ctypes.Structure):
    _fields_ = [
        ("lStructSize",       ctypes.wintypes.DWORD),
        ("hwndOwner",         ctypes.wintypes.HWND),
        ("hInstance",         ctypes.wintypes.HINSTANCE),
        ("lpstrFilter",       ctypes.wintypes.LPCWSTR),
        ("lpstrCustomFilter", ctypes.wintypes.LPWSTR),
        ("nMaxCustFilter",    ctypes.wintypes.DWORD),
        ("nFilterIndex",      ctypes.wintypes.DWORD),
        ("lpstrFile",         ctypes.wintypes.LPWSTR),
        ("nMaxFile",          ctypes.wintypes.DWORD),
        ("lpstrFileTitle",    ctypes.wintypes.LPWSTR),
        ("nMaxFileTitle",     ctypes.wintypes.DWORD),
        ("lpstrInitialDir",   ctypes.wintypes.LPCWSTR),
        ("lpstrTitle",        ctypes.wintypes.LPCWSTR),
        ("Flags",             ctypes.wintypes.DWORD),
        ("nFileOffset",       ctypes.wintypes.WORD),
        ("nFileExtension",    ctypes.wintypes.WORD),
        ("lpstrDefExt",       ctypes.wintypes.LPCWSTR),
        ("lCustData",         ctypes.wintypes.LPARAM),
        ("lpfnHook",          ctypes.c_void_p),
        ("lpTemplateName",    ctypes.wintypes.LPCWSTR),
        ("pvReserved",        ctypes.c_void_p),
        ("dwReserved",        ctypes.wintypes.DWORD),
        ("FlagsEx",           ctypes.wintypes.DWORD),
    ]

OFN_FILEMUSTEXIST = 0x00001000
OFN_EXPLORER      = 0x00080000
OFN_NOCHANGEDIR   = 0x00000008

CSIDL_DESKTOPDIRECTORY = 0x0010
SHGFP_TYPE_CURRENT     = 0

def get_real_desktop_path():
    """Asks Windows for the actual Desktop folder location instead of
    assuming ~\\Desktop. If OneDrive (or any other 'Known Folder Move'
    redirection) has moved the Desktop — commonly to
    ...\\OneDrive\\Desktop — this returns that real location, same as
    File Explorer shows."""
    try:
        buf = ctypes.create_unicode_buffer(260)
        result = ctypes.windll.shell32.SHGetFolderPathW(0, CSIDL_DESKTOPDIRECTORY, 0, SHGFP_TYPE_CURRENT, buf)
        if result == 0 and buf.value:
            return buf.value
    except Exception as e:
        print(f"  [!] get_real_desktop_path error: {e}")
    return os.path.join(os.path.expanduser("~"), "Desktop")

def browse_for_csv_file():
    """Blocking call (run via to_thread) — pops the native Windows 'Open File'
    dialog starting on the Desktop, so the user can click the CSV icon GSPro
    creates there. Returns the chosen path, or None if cancelled."""
    buf = ctypes.create_unicode_buffer(1024)
    desktop_dir = get_real_desktop_path()
    ofn = _OPENFILENAMEW()
    ofn.lStructSize = ctypes.sizeof(_OPENFILENAMEW)
    ofn.lpstrFilter = "CSV Files\0*.csv\0All Files\0*.*\0\0"
    ofn.lpstrFile = ctypes.cast(buf, ctypes.wintypes.LPWSTR)
    ofn.nMaxFile = 1024
    ofn.lpstrInitialDir = desktop_dir if os.path.isdir(desktop_dir) else None
    ofn.lpstrTitle = "Select your GSPro shot data CSV"
    ofn.Flags = OFN_FILEMUSTEXIST | OFN_EXPLORER | OFN_NOCHANGEDIR
    try:
        ok = ctypes.windll.comdlg32.GetOpenFileNameW(ctypes.byref(ofn))
    except Exception as e:
        print(f"  [!] CSV dialog error: {e}")
        return None
    return buf.value if ok else None

def read_csv_file_text(path):
    """Reads a CSV file's raw text, trying a few common encodings."""
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read()
        except (UnicodeDecodeError, LookupError):
            continue
    with open(path, "rb") as f:
        return f.read().decode("utf-8", errors="replace")

def show_desktop():
    """Minimizes all open windows (non-toggling — always shows, never re-restores),
    revealing the Desktop so the user can see/click GSPro's exported CSV icon(s)."""
    try:
        hwnd = ctypes.windll.user32.FindWindowW("Shell_TrayWnd", None)
        if hwnd:
            WM_COMMAND = 0x0111
            MIN_ALL_CMD = 419  # "Minimize All Windows" tray command id
            ctypes.windll.user32.SendMessageW(hwnd, WM_COMMAND, MIN_ALL_CMD, 0)
            return True
    except Exception as e:
        print(f"  [!] show_desktop error: {e}")
    return False

def open_browser_robust(url):
    """webbrowser.open() can fail silently in frozen/--noconsole builds (it
    relies on subprocess/registry lookups that don't always behave the same
    way once bundled). Try it first, then fall back to the Windows shell's
    own 'open this' handler, which is generally more reliable here."""
    try:
        if webbrowser.open(url):
            print(f"  [DEBUG] webbrowser.open succeeded for {url}")
            return True
        print("  [!] webbrowser.open returned False, trying os.startfile fallback")
    except Exception as e:
        print(f"  [!] webbrowser.open raised: {e}, trying os.startfile fallback")
    try:
        os.startfile(url)
        print(f"  [DEBUG] os.startfile succeeded for {url}")
        return True
    except Exception as e:
        print(f"  [!] os.startfile fallback also failed: {e}")
    return False

def launch_shot_data_app():
    """Launch the Shot Data module as a real subprocess - gspro_shotdata.exe
    if it's been built (PyInstaller, see gspro_shotdata.spec), otherwise
    'python main.py' for development, both looked for alongside this
    server script. Replaces the previous behaviour of opening a browser
    mirror of gspro.html's own (deprecated) embedded shot-data pages.
    Returns the Popen handle on success, or None if nothing to launch
    was found or the launch itself failed.
    """
    exe_path = os.path.join(WORKING_DIR, "gspro_shotdata", "gspro_shotdata.exe")
    script_path = os.path.join(WORKING_DIR, "main.py")
    try:
        if os.path.exists(exe_path):
            print(f"  [DEBUG] launch_shot_data_app: launching {exe_path}")
            return subprocess.Popen([exe_path], cwd=os.path.dirname(exe_path))
        if os.path.exists(script_path):
            print(f"  [DEBUG] launch_shot_data_app: launching python {script_path}")
            return subprocess.Popen([sys.executable, script_path], cwd=os.path.dirname(script_path))
        print(f"  [!] launch_shot_data_app: neither {exe_path} nor {script_path} found")
        return None
    except Exception as e:
        print(f"  [!] launch_shot_data_app failed: {e}")
        return None

def resolve_lnk_target(lnk_path):
    """Minimal Windows .lnk (Shell Link) parser — extracts the target file
    path without requiring pywin32/COM. Handles the common case of a local
    shortcut (LocalBasePath + CommonPathSuffix in the LinkInfo structure).
    Returns None if the file isn't a recognizable .lnk or can't be parsed."""
    try:
        with open(lnk_path, "rb") as f:
            data = f.read()
        if len(data) < 76 or data[0:4] != b"\x4C\x00\x00\x00":
            return None
        link_flags = struct.unpack_from("<I", data, 20)[0]
        HAS_LINK_TARGET_ID_LIST = 0x01
        HAS_LINK_INFO           = 0x02
        offset = 76
        if link_flags & HAS_LINK_TARGET_ID_LIST:
            id_list_size = struct.unpack_from("<H", data, offset)[0]
            offset += 2 + id_list_size
        if not (link_flags & HAS_LINK_INFO):
            return None
        li = offset  # start of LinkInfo structure
        info_flags          = struct.unpack_from("<I", data, li + 8)[0]
        local_base_offset   = struct.unpack_from("<I", data, li + 16)[0]
        common_suffix_offset = struct.unpack_from("<I", data, li + 24)[0]

        def read_cstr(start):
            end = data.index(b"\x00", start)
            return data[start:end].decode("mbcs", errors="replace")

        base_path = read_cstr(li + local_base_offset) if (info_flags & 0x1 and local_base_offset) else ""
        suffix = read_cstr(li + common_suffix_offset) if common_suffix_offset else ""
        target = base_path + suffix
        return target or None
    except Exception as e:
        print(f"  [!] resolve_lnk_target error for {lnk_path}: {e}")
        return None

def list_desktop_export_files():
    """Finds GSPro export data on the Desktop in either form: a real .csv
    sitting directly there, or a .lnk shortcut that points to a .csv stored
    elsewhere. Returns (display_filename, real_path_to_read) pairs — the
    display filename is always the thing actually on the Desktop, so
    deleting it later only removes the icon/shortcut, never the underlying
    data file a shortcut points to."""
    desktop_dir = get_real_desktop_path()
    out = []
    try:
        for fname in os.listdir(desktop_dir):
            lower = fname.lower()
            fpath = os.path.join(desktop_dir, fname)
            if lower.endswith(".csv"):
                out.append((fname, fpath))
            elif lower.endswith(".lnk"):
                target = resolve_lnk_target(fpath)
                if target and target.lower().endswith(".csv") and os.path.exists(target):
                    out.append((fname, target))
    except Exception as e:
        print(f"  [!] Failed to list desktop export files: {e}")
    return out

def list_desktop_csv_files():
    return [name for name, _ in list_desktop_export_files()]

def read_desktop_csvs():
    """Reads every GSPro export currently on the Desktop (.csv files and
    .lnk shortcuts pointing to .csv files). There's no reliable,
    dependency-free way to know which icon(s) the user actually clicked, so
    we treat 'everything on the Desktop right now' as the selection — the UI
    tells the user to make sure only the files they want are there before
    pressing Data Import Completed."""
    files = []
    for display_name, real_path in list_desktop_export_files():
        try:
            files.append({"filename": display_name, "content": read_csv_file_text(real_path)})
        except Exception as e:
            print(f"  [!] Failed to read {display_name} ({real_path}): {e}")
    return files

def delete_desktop_files(filenames):
    desktop_dir = get_real_desktop_path()
    deleted, errors = [], []
    for fname in (filenames or []):
        fpath = os.path.join(desktop_dir, os.path.basename(fname))
        try:
            if os.path.exists(fpath):
                os.remove(fpath)
                deleted.append(fname)
        except Exception as e:
            errors.append(fname)
            print(f"  [!] Failed to delete {fname}: {e}")
    return deleted, errors


def save_shot_session(session_name, shots, deleted_shots, summary):
    """Writes a timestamped, never-overwritten backup of a cleaned shot
    session, plus a separate recoverable archive of any rows the user
    deleted during mishit cleanup."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = "".join(c for c in (session_name or "Session") if c.isalnum() or c in (" ", "_", "-")).strip() or "Session"
    session_file = os.path.join(SHOT_SESSIONS_DIR, f"{ts}_{safe_name}.json")
    payload = {
        "sessionName": session_name,
        "savedAt": datetime.now().isoformat(),
        "shotCount": len(shots or []),
        "summary": summary or {},
        "shots": shots or [],
    }
    try:
        with open(session_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
    except Exception as e:
        print(f"  [!] Failed to save shot session: {e}")
        return None

    if deleted_shots:
        deleted_file = os.path.join(SHOT_DELETED_DIR, f"{ts}_{safe_name}_deleted.json")
        try:
            with open(deleted_file, "w", encoding="utf-8") as f:
                json.dump({
                    "sessionName": session_name,
                    "deletedAt": datetime.now().isoformat(),
                    "shots": deleted_shots
                }, f, indent=2)
        except Exception as e:
            print(f"  [!] Failed to archive deleted shots: {e}")

    return os.path.basename(session_file)

def list_shot_sessions():
    sessions = []
    try:
        for fname in os.listdir(SHOT_SESSIONS_DIR):
            if not fname.endswith(".json"):
                continue
            fpath = os.path.join(SHOT_SESSIONS_DIR, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                sessions.append({
                    "file": fname,
                    "sessionName": data.get("sessionName", fname),
                    "savedAt": data.get("savedAt", ""),
                    "shotCount": data.get("shotCount", 0),
                })
            except Exception:
                continue
    except Exception as e:
        print(f"  [!] Failed to list shot sessions: {e}")
    sessions.sort(key=lambda s: s.get("savedAt", ""), reverse=True)
    return sessions

def load_shot_session(filename):
    fpath = os.path.join(SHOT_SESSIONS_DIR, os.path.basename(filename or ""))
    if not os.path.exists(fpath):
        return None
    try:
        with open(fpath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"  [!] Failed to load shot session: {e}")
        return None

cached_announcement = None
cached_dev_message = None
cached_update_info = None  # {"latest_version": "1.12"} once check_for_server_update()
                           # finds something newer than SERVER_VERSION - sent to every
                           # newly-connected tablet, same pattern as the two above.
cached_html = None

def report_to_google_sheets(license_id, event_type, launch_count):
    """Submits analytics telemetry in a separate background thread."""
    def post_thread():
        try:
            data = urllib.parse.urlencode({
                ENTRY_LICENSE_ID: license_id,
                ENTRY_EVENT_TYPE: event_type,
                ENTRY_LAUNCH_CNT: str(launch_count)
            }).encode('utf-8')
            req = urllib.request.Request(GOOGLE_FORM_URL, data=data, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                pass
        except Exception:
            pass # Silent failure to prevent server crashes if offline

    threading.Thread(target=post_thread, daemon=True).start()

def load_or_create_license():
    """Initializes local license file, increments launch count, and posts analytics."""
    event_type = "LAUNCH"
    if not os.path.exists(LICENSE_FILE):
        license_id = f"GS-{str(uuid.uuid4())[:8].upper()}"
        license_data = {
            "license_id": license_id,
            "install_date": datetime.now().isoformat(),
            "launch_count": 1,
            "last_launch": datetime.now().isoformat()
        }
        event_type = "INSTALL"
        print(f"  [LICENSE] Generated new license: {license_id}")
    else:
        try:
            with open(LICENSE_FILE, "r") as f:
                license_data = json.load(f)
            license_data["launch_count"] = license_data.get("launch_count", 0) + 1
            license_data["last_launch"] = datetime.now().isoformat()
        except Exception:
            # Fallback in case of corruption
            license_data = {
                "license_id": f"GS-{str(uuid.uuid4())[:8].upper()}",
                "install_date": datetime.now().isoformat(),
                "launch_count": 1,
                "last_launch": datetime.now().isoformat()
            }
            event_type = "INSTALL"

    # Save local file
    try:
        with open(LICENSE_FILE, "w") as f:
            json.dump(license_data, f, indent=4)
    except Exception as e:
        print(f"  [!] Failed to save local license: {e}")

    # Log to Google Sheets
    report_to_google_sheets(
        license_data["license_id"],
        event_type,
        license_data["launch_count"]
    )
    
    return license_data

def fetch_announcement_if_due(license_data):
    """Fetches the 1-year announcement from GitHub if the installation is older than 365 days."""
    global cached_announcement
    try:
        install_date_str = license_data.get("install_date")
        if not install_date_str:
            return
        
        install_date = datetime.fromisoformat(install_date_str)
        if datetime.now() - install_date >= timedelta(days=365):
            print("  [LICENSE] 1-Year anniversary reached! Fetching announcement...")
            req = urllib.request.Request(ANNOUNCEMENT_URL, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=4.0) as resp:
                if resp.status == 200:
                    cached_announcement = json.loads(resp.read().decode('utf-8'))
                    print("  [LICENSE] Successfully retrieved live announcement from GitHub.")
    except Exception as e:
        print(f"  [LICENSE] Anniversary notice active, but offline or unable to fetch GitHub note.")

def fetch_github_message():
    """Fetches a general developer message/notification from GitHub."""
    global cached_dev_message
    try:
        req = urllib.request.Request(MESSAGE_URL, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=4.0) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode('utf-8'))
                # Check for the consolidated "update" key first
                if "update" in data:
                    cached_dev_message = data["update"]
                elif data.get("message"):
                    cached_dev_message = data
                    print("  [SERVER] Successfully retrieved developer message from GitHub.")
    except Exception:
        pass # Silent skip if no message file exists or offline

def show_first_run_message():
    """Displays a welcome message box on the first run of the application."""
    print("  [LICENSE] Triggering first-run welcome message...")
    message = (
        "Welcome to Gspro Control Box 365!\n\n"
        "If you have any issues, bugs, or want to suggest any improvements, "
        "please contact me at the email below:\n\n"
        "controlbox365@outlook.com"
    )
    title = "GSPro Control Box 365"
    ctypes.windll.user32.MessageBoxW(0, message, title, 0x00000000 | 0x00040000) # MB_OK | MB_TOPMOST

def get_svg_logo():
    """Returns the SVG logo markup for the launcher page."""
    return """
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" style="width:120px; height:120px; margin-bottom:20px;">
      <rect width="512" height="512" rx="96" ry="96" fill="#0d2b4e"/>
      <rect x="96" y="90" width="30" height="220" rx="4" ry="4" fill="#ffffff"/>
      <rect x="386" y="90" width="30" height="220" rx="4" ry="4" fill="#ffffff"/>
      <path d="M126 130 Q256 50 386 130" stroke="#ffffff" stroke-width="8" fill="none" stroke-linecap="round"/>
      <rect x="60" y="242" width="392" height="16" rx="4" ry="4" fill="#ffffff"/>
      <text x="256" y="430" font-family="Arial, sans-serif" font-size="96" font-weight="bold" fill="#ffffff" text-anchor="middle" letter-spacing="14">GSPRO</text>
    </svg>"""

# ═══════════════════════════════════
# ═══════════════════════════════════

# ── Dependency check ─────────────────────────────────────────────────────────
try:
    import qrcode, websockets
    from websockets.server import serve as ws_serve
except ImportError:
    msg = "Missing dependencies! Please run:\npip install websockets qrcode[pil] pillow pyperclip"
    ctypes.windll.user32.MessageBoxW(0, msg, "Startup Error", 0x10) # 0x10 = MB_ICONERROR
    sys.exit(1)

try:    import pyperclip; HAS_CLIP = True
except: HAS_CLIP = False

# ── Win32 SendInput structures ────────────────────────────────────────────────
PUL = ctypes.POINTER(ctypes.c_ulong)

class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk",         ctypes.wintypes.WORD),
                ("wScan",       ctypes.wintypes.WORD),
                ("dwFlags",     ctypes.wintypes.DWORD),
                ("time",        ctypes.wintypes.DWORD),
                ("dwExtraInfo", PUL)]

class INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT),
                ("mi", ctypes.c_ubyte * 28),
                ("hi", ctypes.c_ubyte * 28)]

class INPUT(ctypes.Structure):
    _fields_ = [("type",  ctypes.wintypes.DWORD),
                ("union", INPUT_UNION)]

# ── Hardware scancode table ───────────────────────────────────────────────────
SCANCODES = {
    'a':(0x1E,False),'b':(0x30,False),'c':(0x2E,False),'d':(0x20,False),
    'e':(0x12,False),'f':(0x21,False),'g':(0x22,False),'h':(0x23,False),
    'i':(0x17,False),'j':(0x24,False),'k':(0x25,False),'l':(0x26,False),
    'm':(0x32,False),'n':(0x31,False),'o':(0x18,False),'p':(0x19,False),
    'q':(0x10,False),'r':(0x13,False),'s':(0x1F,False),'t':(0x14,False),
    'u':(0x16,False),'v':(0x2F,False),'w':(0x11,False),'x':(0x2D,False),
    'y':(0x15,False),'z':(0x2C,False),
    '0':(0x0B,False),'1':(0x02,False),'2':(0x03,False),'3':(0x04,False),
    '4':(0x05,False),'5':(0x06,False),'6':(0x07,False),'7':(0x08,False),
    '8':(0x09,False),'9':(0x0A,False),
    'left':(0x4B,True),'right':(0x4D,True),'up':(0x48,True),'down':(0x50,True),
    'enter':(0x1C,False),'space':(0x39,False),'escape':(0x01,False),
    'tab':(0x0F,False),'backspace':(0x0E,False),
    'shift':(0x2A,False),'ctrl':(0x1D,False),'alt':(0x38,False),
    'f1':(0x3B,False),'f3':(0x3D,False),'f5':(0x3F,False),'f8':(0x42,False),'f9':(0x43,False),
    'f2':(0x3C,False),'f4':(0x3E,False),'f6':(0x40,False),'f7':(0x41,False),
    'f10':(0x44,False),'f11':(0x57,False),'f12':(0x58,False),
    '-':(0x0C,False),'+':(0x0D,False),',':(0x33,False),'.':(0x34,False),'/':(0x35,False),
    '[':(0x1A,False),']':(0x1B,False),
}

KEYEVENTF_SCANCODE    = 0x0008
KEYEVENTF_KEYUP       = 0x0002
KEYEVENTF_EXTENDEDKEY = 0x0001

def send_scan(scancode, is_extended=False, hold_ms=100):
    extra = ctypes.pointer(ctypes.c_ulong(0))
    press_flags = KEYEVENTF_SCANCODE | (KEYEVENTF_EXTENDEDKEY if is_extended else 0)
    rel_flags = press_flags | KEYEVENTF_KEYUP

    ii_dn = INPUT_UNION(); ii_dn.ki = KEYBDINPUT(0, scancode, press_flags, 0, extra)
    ii_up = INPUT_UNION(); ii_up.ki = KEYBDINPUT(0, scancode, rel_flags, 0, extra)

    ctypes.windll.user32.SendInput(1, ctypes.pointer(INPUT(1, ii_dn)), ctypes.sizeof(INPUT))
    time.sleep(hold_ms / 1000)
    for _ in range(3):
        ctypes.windll.user32.SendInput(1, ctypes.pointer(INPUT(1, ii_up)), ctypes.sizeof(INPUT))
        time.sleep(0.01)

def send_chord(*keys):
    scans = []
    extra = ctypes.pointer(ctypes.c_ulong(0))

    for key in keys:
        k = key.lower().strip()
        if k not in SCANCODES:
            print(f"  [!] No scancode for chord key: {key}")
            return False
        scans.append(SCANCODES[k])

    for scancode, is_extended in scans:
        flags = KEYEVENTF_SCANCODE | (KEYEVENTF_EXTENDEDKEY if is_extended else 0)
        ii = INPUT_UNION()
        ii.ki = KEYBDINPUT(0, scancode, flags, 0, extra)
        ctypes.windll.user32.SendInput(1, ctypes.pointer(INPUT(1, ii)), ctypes.sizeof(INPUT))
        time.sleep(0.01)

    for scancode, is_extended in reversed(scans):
        flags = KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP | (KEYEVENTF_EXTENDEDKEY if is_extended else 0)
        ii = INPUT_UNION()
        ii.ki = KEYBDINPUT(0, scancode, flags, 0, extra)
        ctypes.windll.user32.SendInput(1, ctypes.pointer(INPUT(1, ii)), ctypes.sizeof(INPUT))
        time.sleep(0.01)

    return True

def send_physical_key(key):
    k = key.lower().strip()
    if k in SCANCODES:
        sc, ext = SCANCODES[k]
        send_scan(sc, ext)
        print(f"  [OK] Scancode: {k}")
        return True
    print(f"  [!] No scancode for: {key}")
    return False

def send_text(text):
    print(f"  [>] Sending text: '{text}'")
    if HAS_CLIP and len(text) > 1:
        try:
            pyperclip.copy(text)
            time.sleep(0.03)
            send_chord('ctrl', 'v')
            print(f"  [OK] Pasted: '{text}'")
            return True
        except Exception as e:
            print(f"  [!] Clipboard error: {e}")
    for ch in text:
        send_physical_key(ch)
        time.sleep(0.03)
    return True


def parse_and_send_chord(value):
    parts = [p.strip() for p in value.split('+') if p.strip()]
    if not parts:
        return False
    return send_chord(*parts)

# ── Async wrappers for blocking operations ─────────────────────────────────────
try:
    to_thread = asyncio.to_thread
except AttributeError:
    async def to_thread(func, *args, **kwargs):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, functools.partial(func, *args, **kwargs))

async def async_focus_game():
    return await to_thread(focus_game)

def minimize_console():
    try:
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            # 6 = SW_MINIMIZE
            ctypes.windll.user32.ShowWindow(hwnd, 6)
            return True
    except Exception as e:
        print(f"  [!] Failed to minimize console: {e}")
    return False

async def async_minimize_console():
    return await to_thread(minimize_console)

async def async_send_physical_key(key):
    return await to_thread(send_physical_key, key)

async def async_send_text(text):
    return await to_thread(send_text, text)

async def async_send_chord(*keys):
    return await to_thread(send_chord, *keys)

async def async_parse_and_send_chord(value):
    return await to_thread(parse_and_send_chord, value)

# ── Focus game window ─────────────────────────────────────────────────────────
def focus_game():
    hwnd = [None]
    title_found = [None]

    def cb(h, _):
        if ctypes.windll.user32.IsWindowVisible(h):
            t = ctypes.create_unicode_buffer(256)
            ctypes.windll.user32.GetWindowTextW(h, t, 256)
            title = t.value.strip()
            if (TARGET_WINDOW.lower() in title.lower() and
                    'launcher' not in title.lower() and
                    title):
                hwnd[0] = h
                title_found[0] = title
                return False
        return True

    PFUNC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    ctypes.windll.user32.EnumWindows(PFUNC(cb), 0)

    if hwnd[0]:
        ctypes.windll.user32.ShowWindow(hwnd[0], 9)
        ctypes.windll.user32.SetForegroundWindow(hwnd[0])
        ctypes.windll.user32.BringWindowToTop(hwnd[0])
        time.sleep(0.1)
        return True

    return False

# ── Focus OBS window ──────────────────────────────────────────────────────────
def focus_obs():
    hwnd = [None]
    def cb(h, _):
        if ctypes.windll.user32.IsWindowVisible(h):
            t = ctypes.create_unicode_buffer(256)
            ctypes.windll.user32.GetWindowTextW(h, t, 256)
            title = t.value.strip()
            if ('obs' in title.lower() and title):
                hwnd[0] = h
                return False
        return True

    PFUNC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    ctypes.windll.user32.EnumWindows(PFUNC(cb), 0)

    if hwnd[0]:
        ctypes.windll.user32.ShowWindow(hwnd[0], 9)
        ctypes.windll.user32.SetForegroundWindow(hwnd[0])
        ctypes.windll.user32.BringWindowToTop(hwnd[0])
        time.sleep(0.1)
        return True
    return False

async def async_focus_obs():
    return await to_thread(focus_obs)

# Pre-focus game window at startup
def pre_focus_game():
    """Pre-focus the game window so first keystroke is fast"""
    print("  [>] Looking for game window...")
    for i in range(5):  # Try 5 times over 2 seconds
        if focus_game():
            print(f"  [OK] Game window pre-focused")
            return True
        time.sleep(0.4)
    print(f"  [!] Game window not found. Make sure '{TARGET_WINDOW}' is running.")
    return False

# ── HTTP server ───────────────────────────────────────────────────────────────
class AppHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        path_parts = self.path.split('?')
        path_base = path_parts[0]

        if path_base in ("/", "/app", "/index.html", "/gspro.html"):
            if not cached_html:
                fetch_html_content() # Only fetch if not already cached
            if cached_html:
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(cached_html)))
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                self.wfile.write(cached_html)
                print(f"  [HTTP] App served to {self.client_address[0]}")
            else:
                self.send_error_msg("Error: GSPro interface not yet cached from GitHub.")
        else:
            self.send_response(404)
            self.end_headers()

    def send_error_msg(self, msg):
        body = f"<h2>{msg}</h2>".encode()
        self.send_response(404)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a): pass

def check_for_server_update():
    """Checks GitHub for a newer server version and prints a notice if found. Never auto-installs."""
    try:
        req = urllib.request.Request(VERSION_CHECK_URL, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=3.0) as response:
            if response.status == 200:
                latest_version = response.read().decode('utf-8').strip()
                if latest_version and latest_version != SERVER_VERSION:
                    print("=" * 56)
                    print(f"  [UPDATE AVAILABLE] You're on v{SERVER_VERSION} - v{latest_version} is out!")
                    print(f"  Download: {RELEASES_URL}")
                    print("=" * 56)
                    return latest_version
    except Exception as e:
        print(f"  [!] Version check skipped: {e}")
    return None

def fetch_html_content():
    """Always serves from the local gspro.html — GitHub fetch disabled.
    The local file is the authoritative version."""
    global cached_html
    if os.path.exists(LOCAL_HTML_PATH):
        try:
            mtime = os.path.getmtime(LOCAL_HTML_PATH)
            size = os.path.getsize(LOCAL_HTML_PATH)
            print(f"  [DEBUG] Reading {LOCAL_HTML_PATH} | size={size} bytes | modified={datetime.fromtimestamp(mtime)}")
            with open(LOCAL_HTML_PATH, "rb") as f:
                data = f.read()
            if b"<html" in data.lower():
                cached_html = data
                print(f"  [SERVER] Loaded local interface: {LOCAL_HTML_PATH}")
                return cached_html
        except Exception as e:
            print(f"  [!] Failed to read local gspro.html: {e}")
    print("  [!] WARNING: Could not load gspro.html from disk")
    return cached_html

async def background_update_task(license_data):
    """Periodically refreshes announcements and dev messages in the background."""
    while True:
        await to_thread(fetch_github_message)
        await to_thread(fetch_announcement_if_due, license_data)
        await asyncio.sleep(600)

def run_http():
    try:
        http.server.HTTPServer(("0.0.0.0", HTTP_PORT), AppHandler).serve_forever()
    except OSError as e:
        print(f"  [!] HTTP error: {e}")

# ── Smart Caddie request handler (§4.3, §4.12) ────────────────────────────────
def _find_game_hwnd():
    """Reuses the same window-matching logic as focus_game(), but just
    returns the hwnd instead of focusing, since OCR capture doesn't need
    the window brought to front (it's captured via ClientToScreen either
    way) — though we do focus it first via async_focus_game() in the
    caller so the mini-map/HUD is actually visible for OCR."""
    hwnd = [None]

    def cb(h, _):
        if ctypes.windll.user32.IsWindowVisible(h):
            t = ctypes.create_unicode_buffer(256)
            ctypes.windll.user32.GetWindowTextW(h, t, 256)
            title = t.value.strip()
            if (TARGET_WINDOW.lower() in title.lower() and
                    'launcher' not in title.lower() and title):
                hwnd[0] = h
                return False
        return True

    PFUNC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    ctypes.windll.user32.EnumWindows(PFUNC(cb), 0)
    return hwnd[0]


async def handle_smart_caddie_request(websocket):
    """§4.3 user flow: prerequisite check -> OCR -> recommendation ->
    push caddie_recommendation JSON to the tablet."""
    mapping = await to_thread(smart_caddie.load_bag_mapping)
    matrix = await to_thread(smart_caddie.load_wedge_matrix)
    profiles = await to_thread(smart_caddie.build_club_profiles)
    clean_counts = smart_caddie.clean_shot_counts_per_club(profiles)

    prereq = smart_caddie.caddie_prerequisite_check(mapping, matrix, clean_counts)
    if prereq["blocked"]:
        await websocket.send(json.dumps({
            "type": "caddie_recommendation", "recommendation_type": "blocked",
            "blocked": True, "message": prereq["message"], "club": None,
            "shape": None, "aim_offset_yards": None, "accuracy_pct": None,
        }))
        return

    await async_focus_game()
    hwnd = await to_thread(_find_game_hwnd)
    if not hwnd:
        await websocket.send(json.dumps({
            "type": "caddie_recommendation", "recommendation_type": "error",
            "message": "Couldn't find the GSPro window to capture — is it running?"}))
        return

    ocr_data = await to_thread(smart_caddie.run_full_ocr_scan, hwnd, PHASE3_ENABLED)
    if ocr_data is None:
        await websocket.send(json.dumps({
            "type": "caddie_recommendation", "recommendation_type": "error",
            "message": "Screen capture failed — check Pillow is installed."}))
        return

    recommendation = await to_thread(
        smart_caddie.compute_recommendation, ocr_data, mapping, matrix, profiles, PHASE3_ENABLED, prereq)
    await to_thread(smart_caddie.log_recommendation, recommendation)
    print(f"  [CADDIE] {recommendation.get('message', '')}")
    await websocket.send(json.dumps(recommendation))


# ── WebSocket handler ─────────────────────────────────────────────────────────
async def ws_handler(websocket):
    addr = websocket.remote_address
    print(f"\n  [WS] Tablet connected: {addr[0]}")
    
    # Minimize the server's console window
    await async_minimize_console()
    
    # Ensure game window is focused when tablet connects
    await async_focus_game()
    
    try:
        await websocket.send(json.dumps({"type":"connected","message":f"Connected to {socket.gethostname()}"}))
        
        # Send 1-year anniversary announcement if available
        if cached_announcement:
            await websocket.send(json.dumps({
                "type": "license_announcement",
                "title": cached_announcement.get("anniversary_title", "Happy 1-Year Anniversary!"),
                "message": cached_announcement.get("anniversary_message", ""),
                "button_text": cached_announcement.get("support_button_text", "Support"),
                "url": cached_announcement.get("support_url", "")
            }))
            
        # Send general developer message if available
        if cached_dev_message:
            await websocket.send(json.dumps({
                "type": "dev_message",
                "id": cached_dev_message.get("id", "1"), # Used by HTML to show only once
                "title": cached_dev_message.get("title", "Update"),
                "message": cached_dev_message.get("message", ""),
                "button_text": cached_dev_message.get("button_text", "OK"),
                "url": cached_dev_message.get("url", "")
            }))

        # Update-available notice, if check_for_server_update() found a
        # newer version at startup - was previously only printed to the
        # server's console, which most users never see since this runs
        # in the background. Never auto-installs; just tells the tablet
        # UI so it can show a "download update" prompt.
        if cached_update_info:
            await websocket.send(json.dumps({
                "type": "update_available",
                "current_version": SERVER_VERSION,
                "latest_version": cached_update_info["latest_version"],
                "releases_url": RELEASES_URL,
            }))
        
        async for raw in websocket:
            try:
                data = json.loads(raw)
                t = data.get("type","")

                if t == "ping":
                    await websocket.send(json.dumps({"type":"pong"}))

                elif t in ("gameplay", "gameplay_special"):
                    action = data.get("action","")
                    print(f"  [<] {t}: '{action}'")
                    await async_focus_game()  # Quick focus before each keystroke
                    if '+' in action and len(action) > 1:
                        await async_parse_and_send_chord(action)
                    elif action.lower().strip() in SCANCODES:
                        await async_send_physical_key(action)
                    else:
                        await async_send_text(action)
                    await websocket.send(json.dumps({"type":"gameplay_ack","message":f"Sent: {action}"}))

                elif t == "bag_mapping":
                    slot = data.get("slot")
                    club = data.get("club","")
                    print(f"  [<] Bag slot {slot} = '{club}'")
                    await async_focus_game()
                    await async_send_text(club)
                    await websocket.send(json.dumps({"type":"bag_mapping_saved","slot":slot,"club":club}))

                elif t == "settings":
                    m = data.get("settings",{}).get("bagMapping",{})
                    print(f"  [<] Bag saved: {len(m)} clubs")
                    if smart_caddie:
                        await to_thread(smart_caddie.save_bag_mapping, m)
                    await websocket.send(json.dumps({"type":"settings_saved"}))

                elif t == "bag_clear":
                    await websocket.send(json.dumps({"type":"bag_cleared"}))

                # ── Smart Caddie: bag mapping / wedge matrix server mirror ──
                # §4.13 correction — these previously lived only in the
                # tablet's localStorage. The Caddie prerequisite check
                # (§4.3.1) runs server-side, so the server now keeps its
                # own persisted copy, kept in sync whenever the tablet saves.
                elif t == "sync_bag_mapping":
                    m = data.get("mapping", {})
                    ok = await to_thread(smart_caddie.save_bag_mapping, m) if smart_caddie else False
                    await websocket.send(json.dumps({"type": "bag_mapping_synced", "ok": ok}))

                elif t == "sync_wedge_matrix":
                    wm = data.get("matrix", {})
                    ok = await to_thread(smart_caddie.save_wedge_matrix, wm) if smart_caddie else False
                    await websocket.send(json.dumps({"type": "wedge_matrix_synced", "ok": ok}))

                elif t == "request_smart_caddie":
                    if not smart_caddie:
                        await websocket.send(json.dumps({
                            "type": "caddie_recommendation", "recommendation_type": "error",
                            "message": "Smart Caddie module isn't available on this server build."}))
                    else:
                        await handle_smart_caddie_request(websocket)

                elif t == "caddie_closed":
                    pass  # §4.3 — informational only, nothing to clean up server-side yet

                elif t == "obs":
                    action = data.get("action", "")
                    print(f"  [<] OBS: '{action}'")
                    obs_focused = await async_focus_obs()
                    if not obs_focused:
                        print("  [!] OBS window not found. Attempting to send hotkey anyway...")
                    if await async_parse_and_send_chord(action):
                        await websocket.send(json.dumps({"type":"obs_ack","message":f"Sent OBS: {action}"}))
                    else:
                        await websocket.send(json.dumps({"type":"obs_error","message":f"Unknown OBS action: {action}"}))
                    if obs_focused:
                        await asyncio.sleep(0.05)
                        await async_focus_game()

                elif t == "club_control":
                    action = data.get("action", "")
                    print(f"  [<] club_control: '{action}'")
                    await async_focus_game()
                    if action == 'up':
                        await async_send_physical_key('up')
                    elif action == 'down':
                        await async_send_physical_key('down')
                    elif action == 'sync_bag':
                        print("  [OK] Sync bag command received")
                    await websocket.send(json.dumps({"type":"club_control_ack","action":action}))

                elif t == "key":
                    key = data.get("key", "")
                    print(f"  [<] key: '{key}'")
                    await async_send_physical_key(key)

                elif t == "start_macro_record":
                    global macro_armed, macro_recording, macro_recorded_events, _macro_ws_ref
                    macro_armed           = True
                    macro_recording       = False
                    macro_recorded_events = []
                    _macro_ws_ref         = websocket
                    _stop_keyboard_hook()          # clean up any previous hook
                    _start_keyboard_hook()         # install fresh hook
                    print("  [MACRO] ARMED — press F9 on PC to start recording, F9 again to stop")
                    await websocket.send(json.dumps({"type": "macro_armed"}))

                elif t == "cancel_macro_record":
                    macro_armed     = False
                    macro_recording = False
                    macro_recorded_events = []
                    _macro_ws_ref   = None
                    _stop_keyboard_hook()
                    print("  [MACRO] Recording cancelled")

                elif t == "save_macro":
                    name     = data.get("name", "New Macro")
                    events   = data.get("events", [])
                    macros   = load_macros()
                    macro_id = str(uuid.uuid4())[:8]
                    macros[macro_id] = {"id": macro_id, "name": name, "events": events}
                    save_macros_to_disk(macros)
                    print(f"  [MACRO] Saved: '{name}' ({len(events)} events)")
                    await websocket.send(json.dumps({"type": "macros_list", "macros": macros}))

                elif t == "delete_macro":
                    macro_id = data.get("id", "")
                    macros   = load_macros()
                    if macro_id in macros:
                        del macros[macro_id]
                        save_macros_to_disk(macros)
                        print(f"  [MACRO] Deleted: {macro_id}")
                    await websocket.send(json.dumps({"type": "macros_list", "macros": macros}))

                elif t == "run_macro":
                    macro_id = data.get("id", "")
                    macros   = load_macros()
                    macro    = macros.get(macro_id)
                    if macro:
                        print(f"  [MACRO] Running: '{macro.get('name')}'")
                        await async_focus_game()
                        for event in macro.get("events", []):
                            ev_type = event.get("type", "key")
                            delay   = event.get("delay", 0.05)
                            await asyncio.sleep(max(delay, 0.03))

                            if ev_type == "mouse_move":
                                x, y = event.get("x", 0), event.get("y", 0)
                                sw = ctypes.windll.user32.GetSystemMetrics(0)
                                sh = ctypes.windll.user32.GetSystemMetrics(1)
                                ax = int(x * 65535 / sw)
                                ay = int(y * 65535 / sh)
                                ctypes.windll.user32.mouse_event(0x8001, ax, ay, 0, 0)
                                print(f"  [MACRO] mouse_move → ({x},{y})")

                            elif ev_type == "mouse_click":
                                x, y   = event.get("x", 0), event.get("y", 0)
                                button = event.get("button", "left")
                                sw = ctypes.windll.user32.GetSystemMetrics(0)
                                sh = ctypes.windll.user32.GetSystemMetrics(1)
                                ax = int(x * 65535 / sw)
                                ay = int(y * 65535 / sh)
                                ctypes.windll.user32.mouse_event(0x8001, ax, ay, 0, 0)
                                await asyncio.sleep(0.03)
                                if button == "right":
                                    ctypes.windll.user32.mouse_event(0x0008, 0, 0, 0, 0)
                                    await asyncio.sleep(0.05)
                                    ctypes.windll.user32.mouse_event(0x0010, 0, 0, 0, 0)
                                elif button == "middle":
                                    ctypes.windll.user32.mouse_event(0x0020, 0, 0, 0, 0)
                                    await asyncio.sleep(0.05)
                                    ctypes.windll.user32.mouse_event(0x0040, 0, 0, 0, 0)
                                else:
                                    ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
                                    await asyncio.sleep(0.05)
                                    ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)
                                print(f"  [MACRO] mouse_{button}_click @ ({x},{y})")

                            else:
                                key = event.get("key", "")
                                if key:
                                    await async_send_physical_key(key)

                        await websocket.send(json.dumps({"type": "macro_run_done", "id": macro_id}))
                    else:
                        print(f"  [MACRO] Not found: {macro_id}")

                elif t == "get_macros":
                    macros = load_macros()
                    await websocket.send(json.dumps({"type": "macros_list", "macros": macros}))

                elif t == "browse_csv":
                    print("  [<] browse_csv: opening native file picker...")
                    path = await to_thread(browse_for_csv_file)
                    if not path:
                        await websocket.send(json.dumps({"type": "csv_browse_cancelled"}))
                    else:
                        try:
                            content = await to_thread(read_csv_file_text, path)
                            await websocket.send(json.dumps({
                                "type": "csv_loaded",
                                "filename": os.path.basename(path),
                                "content": content
                            }))
                            print(f"  [>] csv_loaded: {os.path.basename(path)}")
                        except Exception as e:
                            await websocket.send(json.dumps({"type": "csv_browse_error", "message": str(e)}))

                elif t == "show_desktop":
                    print("  [<] show_desktop: minimizing all windows...")
                    await to_thread(show_desktop)

                elif t == "open_releases_page":
                    # Tapping "Download" on the update-available notice
                    # opens the Releases page in a browser ON THE PC, not
                    # the tablet - the installer has to run on the PC, so
                    # opening it on whatever device is showing gspro.html
                    # (often a phone/tablet that can't run a .exe at all)
                    # wouldn't actually get the file where it's needed.
                    print("  [<] open_releases_page: opening on PC")
                    await to_thread(open_browser_robust, RELEASES_URL)

                elif t == "request_pc_shotdata":
                    global _shotdata_process
                    if _shotdata_process is not None and _shotdata_process.poll() is None:
                        print("  [<] request_pc_shotdata: already running, skipping re-launch")
                    else:
                        proc = await to_thread(launch_shot_data_app)
                        if proc is not None:
                            _shotdata_process = proc
                            print(f"  [<] request_pc_shotdata: launched Shot Data (pid {proc.pid})")

                            async def _watch_shotdata_exit(p, ws):
                                await to_thread(p.wait)
                                print("  [<] Shot Data app closed")
                                try:
                                    await ws.send(json.dumps({"type": "pc_shotdata_app_closed"}))
                                except Exception:
                                    pass  # tablet may have already disconnected - nothing to notify

                            asyncio.ensure_future(_watch_shotdata_exit(proc, websocket))
                        else:
                            print("  [!] request_pc_shotdata: could not launch Shot Data app")
                            await websocket.send(json.dumps({
                                "type": "pc_shotdata_error",
                                "message": "Could not find gspro_shotdata.exe or main.py to launch."
                            }))

                elif t == "pc_shotdata_closed":
                    print("  [<] pc_shotdata_closed: tablet placeholder dismissed")

                elif t == "load_desktop_csvs":
                    print(f"  [<] load_desktop_csvs: scanning {get_real_desktop_path()}")
                    found = await to_thread(list_desktop_export_files)
                    for name, real_path in found:
                        print(f"  [DEBUG] Found: {name} -> {real_path}")
                    files = await to_thread(read_desktop_csvs)
                    print(f"  [>] desktop_csvs_loaded: {len(files)} file(s)")
                    await websocket.send(json.dumps({"type": "desktop_csvs_loaded", "files": files}))

                elif t == "delete_desktop_csvs":
                    deleted, errors = await to_thread(delete_desktop_files, data.get("filenames", []))
                    print(f"  [SHOTS] Deleted from Desktop: {deleted} (errors: {errors})")
                    await websocket.send(json.dumps({"type": "desktop_csvs_deleted", "deleted": deleted, "errors": errors}))

                elif t == "save_shot_session":
                    fname = await to_thread(
                        save_shot_session,
                        data.get("sessionName", "Session"),
                        data.get("shots", []),
                        data.get("deletedShots", []),
                        data.get("summary", {})
                    )
                    print(f"  [SHOTS] Session saved: {fname}")
                    await websocket.send(json.dumps({"type": "shot_session_saved", "file": fname}))

                elif t == "list_shot_sessions":
                    sessions = await to_thread(list_shot_sessions)
                    await websocket.send(json.dumps({"type": "shot_sessions_list", "sessions": sessions}))

                elif t == "load_shot_session":
                    sdata = await to_thread(load_shot_session, data.get("file", ""))
                    await websocket.send(json.dumps({"type": "shot_session_loaded", "data": sdata}))

                elif t == "quit_server":
                    print("\n" + "!"*60)
                    print("  [!!!] QUIT SIGNAL RECEIVED FROM TABLET")
                    print("  [!!!] TERMINATING PROCESS AND CLOSING WINDOW...")
                    print("!"*60 + "\n")
                    # Hard exit to force the CMD window to close instantly
                    os._exit(0)

                elif t == "hud_mouse_move":
                    dx = data.get("dx",0); dy = data.get("dy",0)
                    ctypes.windll.user32.mouse_event(0x0001, int(dx), int(dy), 0, 0)

                elif t == "hud_click":
                    btn = data.get("button", "left")
                    if btn == "right":
                        ctypes.windll.user32.mouse_event(0x0008, 0, 0, 0, 0) # MOUSEEVENTF_RIGHTDOWN
                        time.sleep(0.05)
                        ctypes.windll.user32.mouse_event(0x0010, 0, 0, 0, 0) # MOUSEEVENTF_RIGHTUP
                    else:
                        ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0) # MOUSEEVENTF_LEFTDOWN
                        time.sleep(0.05)
                        ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0) # MOUSEEVENTF_LEFTUP
                    await websocket.send(json.dumps({"type":"hud_click_ack"}))

            except json.JSONDecodeError:
                pass
            except Exception as e:
                print(f"  [!] Error: {e}")

    except websockets.exceptions.ConnectionClosed:
        print(f"  [WS] Disconnected: {addr[0]}")
    except Exception as e:
        print(f"  [!] WebSocket error: {e}")

# ── Main ──────────────────────────────────────────────────────────────────────
async def main():
    global _main_loop
    _main_loop = asyncio.get_running_loop()
    # Detect best local IP using socket enumeration (no psutil needed)
    def get_best_ip():
        import struct
        candidates = []
        try:
            # Get all IPs this machine has by connecting to multiple targets
            for target in ("8.8.8.8", "192.168.0.1", "192.168.1.1", "10.0.0.1"):
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    s.connect((target, 80))
                    ip = s.getsockname()[0]
                    s.close()
                    if ip and not ip.startswith("127."):
                        candidates.append(ip)
                except:
                    pass
        except:
            pass

        if not candidates:
            return "127.0.0.1"

        # Prefer 192.168.x.x over 10.x.x.x over others (WiFi is usually 192.168)
        for ip in candidates:
            if ip.startswith("192.168."):
                return ip
        for ip in candidates:
            if ip.startswith("10."):
                return ip
        return candidates[0]

    ip = get_best_ip()

    # Pre-focus game window before starting server
    print(f"\n{'='*56}")
    print(f"  GSPro Server  v{SERVER_VERSION} - [STABLE BUILD]")
    print(f"  Behavior: QR in CMD only. No browser popup.")
    print(f"{'='*56}")
    global cached_update_info
    _latest = await to_thread(check_for_server_update)
    if _latest:
        cached_update_info = {"latest_version": _latest}
    pre_focus_game()

    # Initialize Licensing & Telemetry Tracking
    try:
        license_data = await to_thread(load_or_create_license)

        if license_data:
            # Start background tasks only if license data is valid
            asyncio.create_task(background_update_task(license_data))
            asyncio.create_task(to_thread(fetch_announcement_if_due, license_data))
            asyncio.create_task(to_thread(fetch_github_message))
            count = license_data.get("launch_count", 0)
        else:
            count = 0

        # Show first-time use message
        if count == 1:
            threading.Thread(target=show_first_run_message, daemon=True).start()
        else:
            print(f"  [LICENSE] Launch count is {count}. Skipping welcome message.")
    except Exception as e:
        print(f"  [!] License/analytics setup error: {e}")

    # Populate HTML cache synchronously BEFORE starting HTTP server,
    # so no browser request can ever arrive before we have something to serve.
    fetch_html_content()

    threading.Thread(target=run_http, daemon=True).start()
    await asyncio.sleep(0.3)

    app_url = f"http://{ip}:{HTTP_PORT}/?ws={ip}"

    print(f"  Interface: {'READY' if cached_html else 'OFFLINE/ERROR'}")
    print(f"  Window target: '{TARGET_WINDOW}'")
    sys.stdout.flush()
    print(f"\n  Scan this QR with your tablet camera to open the app:\n")
    sys.stdout.flush()
    try:
        q = qrcode.QRCode(version=1, box_size=5, border=3)
        q.add_data(app_url)
        q.make(fit=True)
        sys.stdout.flush()
        try:
            q.print_ascii(invert=True)
        except UnicodeEncodeError:
            # Console codepage can't render the block characters - fall back to a basic matrix
            matrix = q.get_matrix()
            for row in matrix:
                print("  " + "".join("##" if cell else "  " for cell in row))
        sys.stdout.flush()
    except Exception as e:
        print(f"  (QR error: {e})")
        sys.stdout.flush()

    print(f"\n  OR type in browser: {app_url}")
    print(f"  PC IP: {ip}")
    sys.stdout.flush()

    print(f"\n  Ctrl+C to stop.\n")
    sys.stdout.flush()

    try:
        async with ws_serve(ws_handler, "0.0.0.0", PORT):
            print(f"  [WS] Ready on port {PORT}")
            await asyncio.Future()
    except OSError as e:
        if e.errno == 10048:
            msg = f"GSPro Control Box is already running.\n\nPlease check your system tray or Task Manager.\n\nPort {PORT} is currently blocked."
            ctypes.windll.user32.MessageBoxW(0, msg, "Port Conflict", 0x10)
        else:
            raise e

if __name__ == "__main__":
    try:    asyncio.run(main())
    except KeyboardInterrupt: print("\n  Stopped.\n")
    except Exception as e:
        msg = f"A fatal error occurred:\n{str(e)}\n\n{traceback.format_exc()}"
        print(msg)
        # Only show popup if it's a real crash, helps with --noconsole debugging
        ctypes.windll.user32.MessageBoxW(0, msg, "Fatal Error", 0x10)