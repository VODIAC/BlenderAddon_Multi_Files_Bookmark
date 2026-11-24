"""Check command-line .blend startup (the Windows file association path)."""

import os
from pathlib import Path
import time
import traceback

import bpy


root = Path(os.environ["MBB_TEST_ROOT"])
mode = os.environ["MBB_TEST_STARTUP"]
assert Path(bpy.utils.user_resource("CONFIG")).resolve() == (root / "config").resolve()
addon = __import__("Multi_Files_Bookmark", fromlist=["_read_registry"])
bpy.context.preferences.use_preferences_save = False
started = time.monotonic()


def verify():
    try:
        tabs = addon._clean_registry(addon._read_registry())["tabs"]
        elapsed = time.monotonic() - started
        assert elapsed < 20, tabs
        if elapsed < 3 or not tabs or (mode == "resident" and not addon._live_group):
            return 0.1
        assert len(tabs) == 1, tabs
        tab = tabs[0]
        if mode == "blank":
            assert addon._is_untitled_tab(tab), tab
        else:
            assert Path(tab["filepath"]).resolve() == (root / "Startup.blend").resolve(), tab
            assert not addon._is_untitled_tab(tab), tab
        assert bool(addon._live_group) == (mode == "resident")
        assert addon._current_registry_tab()["tab_id"] == tab["tab_id"]
        assert addon._dock_tab_is_active(tab)
        (root / "startup-result.txt").write_text(f"PASS {mode}", encoding="utf-8")
    except Exception:
        (root / "startup-result.txt").write_text(traceback.format_exc(), encoding="utf-8")
    bpy.ops.wm.quit_blender("EXEC_DEFAULT")
    return None


bpy.app.timers.register(verify, first_interval=0.1)
