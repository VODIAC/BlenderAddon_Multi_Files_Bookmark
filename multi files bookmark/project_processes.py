"""Windows process and window coordination for resident Blender projects."""

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid


ENV_GROUP = "MBB_LIVE_PROJECT_GROUP"
ENV_TAB = "MBB_LIVE_PROJECT_TAB"
SUPPORTED = sys.platform == "win32"

if SUPPORTED:
    _user = ctypes.WinDLL("user32", use_last_error=True)
    _callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def _api(name, result, *args):
        fn = getattr(_user, name)
        fn.restype = result
        fn.argtypes = args
        return fn

    _enum = _api("EnumWindows", wintypes.BOOL, _callback, wintypes.LPARAM)
    _pid = _api("GetWindowThreadProcessId", wintypes.DWORD, wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    _class = _api("GetClassNameW", ctypes.c_int, wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    _owner = _api("GetWindow", wintypes.HWND, wintypes.HWND, wintypes.UINT)
    _foreground = _api("GetForegroundWindow", wintypes.HWND)
    _activate = _api("SetForegroundWindow", wintypes.BOOL, wintypes.HWND)
    _visible = _api("IsWindowVisible", wintypes.BOOL, wintypes.HWND)
    _minimized = _api("IsIconic", wintypes.BOOL, wintypes.HWND)
    _show = _api("ShowWindowAsync", wintypes.BOOL, wintypes.HWND, ctypes.c_int)
    _cursor = _api("GetCursorPos", wintypes.BOOL, ctypes.POINTER(wintypes.POINT))
    _client = _api("ScreenToClient", wintypes.BOOL, wintypes.HWND, ctypes.POINTER(wintypes.POINT))
    _client_rect = _api("GetClientRect", wintypes.BOOL, wintypes.HWND, ctypes.POINTER(wintypes.RECT))


def owner_pid(hwnd):
    if not SUPPORTED or not hwnd:
        return 0
    pid = wintypes.DWORD()
    _pid(hwnd, ctypes.byref(pid))
    return pid.value


def foreground_pid():
    return owner_pid(_foreground()) if SUPPORTED else 0


def windows(pid):
    if not SUPPORTED or not pid:
        return []
    found = []
    name = ctypes.create_unicode_buffer(128)

    @_callback
    def collect(hwnd, _):
        if owner_pid(hwnd) == pid and not _owner(hwnd, 4):  # GW_OWNER
            _class(hwnd, name, len(name))
            if name.value == "GHOST_WindowClass":
                found.append(hwnd)
        return True

    _enum(collect, 0)
    return found


def reveal(hwnds):
    for hwnd in hwnds:
        if not _visible(hwnd):
            _show(hwnd, 8)  # SW_SHOWNA


def hide(hwnds):
    for hwnd in hwnds:
        if _visible(hwnd):
            _show(hwnd, 0)  # SW_HIDE


def focus(hwnds):
    if not hwnds:
        return False
    hwnd = hwnds[0]
    reveal(hwnds)
    if _minimized(hwnd):
        _show(hwnd, 9)  # SW_RESTORE
    return bool(_activate(hwnd))


def any_visible(hwnds):
    return any(_visible(hwnd) for hwnd in hwnds)


def cursor_in_current_window():
    hwnd = _foreground()
    if owner_pid(hwnd) != os.getpid():
        return (-1, -1)
    point = wintypes.POINT()
    rect = wintypes.RECT()
    if _cursor(ctypes.byref(point)) and _client(hwnd, ctypes.byref(point)) and _client_rect(hwnd, ctypes.byref(rect)):
        return point.x, rect.bottom - 1 - point.y
    return (-1, -1)


def read(path):
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def write_text(path, text):
    path = Path(path)
    temp = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        temp.write_text(text, encoding="utf-8", newline="")
        for attempt in range(5):
            try:
                os.replace(temp, path)
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.01)
    finally:
        temp.unlink(missing_ok=True)


def write(path, value):
    write_text(path, json.dumps(value, ensure_ascii=False))


class Group:
    def __init__(self, directory, tab_id):
        self.directory = Path(directory)
        self.tab_id = tab_id
        self.config = self.read("group")
        self.cache_settings = {"directory": self.config.get("cache", ""), "previous": []}
        self.refresh_cache_settings()
        self.children = {}

    @classmethod
    def create(cls, tab_id, registry_path, cache_directory):
        directory = tempfile.mkdtemp(prefix="mbb-live-")
        write(Path(directory) / "group.json", {"registry": registry_path, "cache": cache_directory})
        group = cls(directory, tab_id)
        os.environ[ENV_GROUP] = directory
        os.environ[ENV_TAB] = tab_id
        return group

    @classmethod
    def from_environment(cls):
        directory, tab_id = os.environ.get(ENV_GROUP), os.environ.get(ENV_TAB)
        if SUPPORTED and directory and tab_id:
            group = cls(directory, tab_id)
            if group.config.get("registry") and group.config.get("cache"):
                return group
        return None

    def rebind(self, tab_id):
        self.tab_id = tab_id
        os.environ[ENV_TAB] = tab_id

    def refresh_cache_settings(self):
        settings = self.read("cache-settings")
        if settings.get("directory"):
            self.cache_settings = settings
        return self.cache_settings

    def read(self, name):
        return read(self.directory / f"{name}.json")

    def write(self, name, data):
        write(self.directory / f"{name}.json", data)

    def forget(self, name):
        (self.directory / f"{name}.json").unlink(missing_ok=True)

    def ready(self, tab_id):
        data = self.read(f"ready-{tab_id}")
        pid = data.get("pid", 0)
        hwnds = windows(pid)
        return pid, hwnds if data.get("hwnd") in hwnds else []

    def publish(self):
        hwnds = windows(os.getpid())
        if not hwnds:
            return False
        self.write(f"ready-{self.tab_id}", {"pid": os.getpid(), "hwnd": hwnds[0]})
        return True

    def reveal_all(self):
        for path in self.directory.glob("ready-*.json"):
            reveal(self.ready(path.stem[6:])[1])

    def launch(self, binary, module, tab_id, job):
        self.forget(f"ready-{tab_id}")
        self.forget(f"result-{tab_id}")
        self.write(f"job-{tab_id}", job)
        env = dict(os.environ, **{ENV_GROUP: str(self.directory), ENV_TAB: tab_id})
        expression = (
            "import addon_utils; "
            f"(addon_utils.enable({module!r}, default_set=True) "
            f"if not addon_utils.check({module!r})[1] else __import__({module!r}, fromlist=['_start_live_worker']))"
            "._start_live_worker()"
        )
        child = subprocess.Popen(
            [binary, "--python-exit-code", "1", "--python-expr", expression],
            env=env, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        self.children[tab_id] = child
        return child
