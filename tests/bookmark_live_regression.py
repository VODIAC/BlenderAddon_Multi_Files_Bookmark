"""Exercise the resident mode in an isolated interactive Blender instance."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import traceback

import addon_utils
import bpy


root = Path(os.environ["MBB_TEST_ROOT"])
assert Path(bpy.utils.user_resource("CONFIG")).resolve() == (root / "config").resolve()
assert Path(tempfile.gettempdir()).resolve() == (root / "tmp").resolve()
module = os.environ.get("MBB_TEST_MODULE", "Multi_Files_Bookmark")
is_worker = bool(os.environ.get("MBB_LIVE_PROJECT_GROUP"))
if is_worker or addon_utils.check(module)[1]:
    addon = __import__(module, fromlist=["processes"])
else:
    addon = addon_utils.enable(module, default_set=True)
assert addon is not None
prefs = addon._addon_preferences()
bpy.context.preferences.use_preferences_save = False
status = root / (f"worker-{os.getpid()}.txt" if is_worker else "result.txt")
original_popen = subprocess.Popen


def launch_with_test_hook(args, *rest, **kwargs):
    if "--python-expr" in args and kwargs.get("env", {}).get("MBB_LIVE_PROJECT_GROUP"):
        args = [*args, "--python", __file__]
        with (root / "blender.log").open("ab") as output:
            return original_popen(args, *rest, stdout=output, stderr=output, **kwargs)
    return original_popen(args, *rest, **kwargs)


addon.processes.subprocess.Popen = launch_with_test_hook
if not is_worker:
    assert (root / "a" / "Same.blend").is_file()
    assert (root / "b" / "Same.blend").is_file()
    prefs.cache_directory = str(root / "cache")
    bpy.context.preferences.filepaths.temporary_directory = str(root / "autosave") + os.sep
    bpy.context.preferences.filepaths.use_auto_save_temporary_files = True
    bpy.context.preferences.filepaths.auto_save_time = 1
    bpy.context.preferences.edit.use_global_undo = True
    bpy.context.preferences.view.show_splash = False
state = {"step": 0, "started": time.monotonic(), "pids": [], "foreground": {}, "last_sample": None}


def report(message):
    with status.open("a", encoding="utf-8") as handle:
        handle.write(f"{message}\n")


def advance(message):
    report(message)
    state["step"] += 1
    state["started"] = time.monotonic()


def mark_autosave_edit(name):
    bpy.context.scene["mbb_autosave_test"] = name
    # Updating a custom property from Python alone does not mark the file dirty.
    assert bpy.ops.ed.undo_push(message="Autosave test edit") == {"FINISHED"}
    assert bpy.data.is_dirty


def run():
    try:
        now = time.monotonic()
        sample = state["last_sample"]
        if sample:
            previous_time, previous_pid = sample
            state["foreground"][previous_pid] = state["foreground"].get(previous_pid, 0) + now - previous_time
        state["last_sample"] = (now, addon.processes.foreground_pid())
        step = state["step"]
        assert time.monotonic() - state["started"] < 100, f"Timeout at step {step}"
        if step == 0:
            if not addon._current_registry_tab():
                return 0.15
            assert not prefs.use_live_projects
            assert bpy.app.timers.is_registered(addon._foreground_autosave_timer)
            assert ("*", addon.LIVE_MODE_DESCRIPTION) in addon.TRANSLATIONS["zh_HANS"]
            prefs.use_live_projects = True
            advance("Default single-process mode, timer and translation verified")
        elif step == 1:
            group = addon._live_group
            if not group or not group.ready(group.tab_id)[1]:
                return 0.15
            assert not bpy.app.timers.is_registered(addon._foreground_autosave_timer)
            if any("overlay_router" in op.bl_idname.lower() for window in bpy.context.window_manager.windows for op in window.modal_operators):
                return 0.25
            if addon.processes.foreground_pid() != os.getpid():
                return 0.25
            assert bpy.ops.ed.undo_push(message="Start test") == {"FINISHED"}
            bpy.context.scene["mbb_live_test"] = 3
            bpy.ops.ed.undo_push(message="Test first change")
            bpy.context.scene["mbb_live_test"] = 7
            bpy.ops.ed.undo_push(message="Test second change")
            assert bpy.ops.ed.undo() == {"FINISHED"}
            assert bpy.context.scene["mbb_live_test"] == 3
            state["source"] = group.tab_id
            state["working"] = bpy.data.filepath
            state["registry"] = addon._registry_path()
            paths = [str(root / folder / "Same.blend") for folder in ("a", "b")]
            assert addon._open_live_paths(bpy.context, paths, True, False) == {"FINISHED"}
            state["paths"] = paths
            advance("Started two same-name tabs after undoing one change")
        elif step == 2:
            if addon._live_transition:
                return 0.25
            group = addon._live_group
            tab = addon._find_tab_by_any_path(state["paths"][1])
            pid, hwnds = group.ready(tab["tab_id"])
            if not hwnds:
                raise AssertionError(group.read(f"result-{tab['tab_id']}"))
            state["pids"].append(pid)
            state["b"] = tab
            state["b_pid"] = pid
            assert Path(tab["cache_filepath"]).is_file()
            assert addon.processes.foreground_pid() == pid
            assert not addon.processes.any_visible(addon.processes.windows(os.getpid()))
            # Change the cache folder from a worker, not the session's first process.
            group.write(f"test-{tab['tab_id']}", {"change_cache": True, "switch": state["source"]})
            advance("Worker opened a distinct cache; only its project window is visible")
        elif step == 3:
            if addon.processes.foreground_pid() != os.getpid() or addon._live_group.read("active").get("tab_id") != state["source"]:
                return 0.25
            assert bpy.data.filepath == state["working"]
            new_cache = root / "moved-cache"
            assert Path(prefs.cache_directory) == new_cache
            assert addon._registry_path() == state["registry"]
            assert Path(state["working"]).is_file()
            assert Path(state["b"]["cache_filepath"]).is_file()
            assert (root / "cache" / "unrelated.blend").read_bytes() == b"not a cache"
            assert addon._is_resident_cache(state["working"])
            assert Path(addon._live_cache_settings_path()).is_file()
            assert Path(addon._thumbnail_path_for("", tab_id=state["source"])).parent == new_cache / "screenshot"
            assert bpy.context.scene["mbb_live_test"] == 3
            assert bpy.ops.ed.redo() == {"FINISHED"}
            assert bpy.context.scene["mbb_live_test"] == 7
            assert bpy.ops.ed.undo() == {"FINISHED"}
            assert bpy.context.scene["mbb_live_test"] == 3
            mark_autosave_edit("root")
            tab = addon._find_tab_by_any_path(state["paths"][0])
            assert addon._switch_live_tab(tab["tab_id"], load_ui=False) == {"FINISHED"}
            advance("The original project retained both native Undo and Redo without a reload")
        elif step == 4:
            if addon._live_transition:
                return 0.25
            group = addon._live_group
            tab = addon._find_tab_by_any_path(state["paths"][0])
            pid, hwnds = group.ready(tab["tab_id"])
            assert hwnds, group.read(f"result-{tab['tab_id']}")
            state["pids"].append(pid)
            state["a"] = tab
            assert tab["cache_filepath"] != state["b"]["cache_filepath"]
            assert Path(tab["cache_filepath"]).parent == root / "moved-cache"
            assert addon.processes.foreground_pid() == pid
            state["a_pid"] = pid
            advance("Both same-name projects use different working caches, including Load UI off")
        elif step == 5:
            ids = {"root": os.getpid(), "a": state["a_pid"], "b": state["b_pid"]}
            assert len(set(ids.values())) == 3
            assert addon.processes.foreground_pid() == ids["a"], "Keep the isolated test worker in front until autosave is verified"
            snapshots = {name: list((root / "autosave").glob(f"*_{pid}_autosave.blend")) for name, pid in ids.items()}
            if not all(snapshots.values()):
                return 0.25
            for name, files in snapshots.items():
                assert len(files) == 1, (name, files)
                shutil.copy2(files[0], root / f"recovery-{name}.blend")
            for name in ("root", "b"):
                assert state["foreground"].get(ids[name], 0) < 60, state["foreground"]
            foreground = {name: round(state["foreground"].get(pid, 0), 2) for name, pid in ids.items()}
            advance(f"All three native autosaves found; foreground seconds: {foreground}")
            addon._live_group.write(f"test-{state['a']['tab_id']}", {"save": True, "close": True})
        elif step == 6:
            group = addon._live_group
            tab_id = group.read("active").get("tab_id")
            if addon._find_tab_by_any_path(state["paths"][0]) or tab_id == state["source"]:
                return 0.25
            if group.read(f"close-{state['a']['tab_id']}"):
                return 0.25
            group.write(f"test-{tab_id}", {"restore": True})
            advance("Manual Save to Origin and close requested in the foreground worker")
        elif step == 7:
            group = addon._live_group
            restored = addon._find_tab_by_any_path(state["paths"][0])
            if restored is None or not group.ready(restored["tab_id"])[1]:
                return 0.25
            assert (root / "a" / "saved.txt").read_text() == "OK"
            assert (root / "a" / "Same.blend").is_file()
            assert (root / "b" / "Same.blend").is_file()
            advance("Ctrl+Shift+T path restored the closed project's cache in a fresh worker")
        else:
            report("PASS")
            return None
        return 0.25
    except Exception:
        report(traceback.format_exc())
        addon._live_group and addon._live_group.reveal_all()
        return None


def worker_step():
    try:
        group = addon._live_group
        if "mbb_autosave_test" not in bpy.context.scene:
            assert not bpy.app.timers.is_registered(addon._foreground_autosave_timer)
            mark_autosave_edit(Path(addon._live_tab(group.tab_id)["filepath"]).parent.name)
        message = f"test-{group.tab_id}"
        command = group.read(message)
        if not command:
            return 0.25
        group.forget(message)
        if command.get("change_cache"):
            working_path = bpy.data.filepath
            registry_path = addon._registry_path()
            (root / "cache" / "unrelated.blend").write_bytes(b"not a cache")
            addon._ensure_ui_color_presets(prefs)
            old_preset = Path(addon._ui_color_presets_path())
            assert old_preset.is_file()
            prefs.cache_directory = str(root / "moved-cache")
            assert Path(addon._cache_dir()) == root / "moved-cache"
            assert Path(addon._ui_color_presets_path()).read_bytes() == old_preset.read_bytes()
            assert bpy.data.filepath == working_path
            assert addon._registry_path() == registry_path
        if command.get("switch"):
            assert addon._switch_live_tab(command["switch"]) == {"FINISHED"}
        if command.get("save"):
            before = bpy.data.filepath
            a = root / "a" / "Same.blend"
            b = root / "b" / "Same.blend"
            a_data, b_data = a.read_bytes(), b.read_bytes()
            bpy.context.scene["mbb_save_test"] = 17
            assert bpy.ops.wm.mbb_save_original_project("EXEC_DEFAULT", filepath=str(a)) == {"FINISHED"}
            assert bpy.data.filepath == before
            assert a.read_bytes() != a_data and b.read_bytes() == b_data
            (root / "a" / "saved.txt").write_text("OK")
        if command.get("close"):
            assert addon._close_live_tabs({group.tab_id}) == {"FINISHED"}
        if command.get("restore"):
            assert addon._restore_live_tabs(bpy.context) == {"FINISHED"}
    except Exception:
        report(traceback.format_exc())
        return None
    return 0.25


bpy.app.timers.register(worker_step if is_worker else run, first_interval=0.5, persistent=True)
