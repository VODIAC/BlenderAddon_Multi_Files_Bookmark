"""Run in an isolated Blender GUI with --enable-event-simulate."""

import importlib
import os
from pathlib import Path
import sys
import traceback

import addon_utils
import bpy


root = Path(os.environ["MBB_TEST_ROOT"])
assert Path(bpy.utils.user_resource("CONFIG")).resolve() == (root / "config").resolve()
source = Path(os.environ["MBB_TEST_SOURCE"])
sys.path.insert(0, str(source.parent))
addon = addon_utils.enable(source.name, default_set=True)
assert addon is importlib.import_module(source.name)
bpy.context.preferences.use_preferences_save = False
prefs = addon._addon_preferences()
prefs.cache_directory = str(root / "cache")
bpy.context.preferences.view.smooth_view = 0
window = bpy.context.window_manager.windows[0]
area = next(a for a in window.screen.areas if a.type == "VIEW_3D")
region = next(r for r in area.regions if r.type == "WINDOW")
configs = bpy.context.window_manager.keyconfigs
calls = []


def simulate(key="BUTTON4MOUSE", x=None, y=None):
    x = region.x + region.width // 2 if x is None else x
    y = region.y + region.height // 2 if y is None else y
    window.event_simulate(type=key, value="PRESS", x=x, y=y)
    window.event_simulate(type=key, value="RELEASE", x=x, y=y)


def bindings(name, key):
    return [i.idname for i in configs.user.keymaps[name].keymap_items if i.active and i.type == key]


def checks():
    simulate("ESC")
    yield 0.3
    assert prefs.prioritize_shortcuts is False
    addon._switch_bookmark_relative = lambda _context, delta: calls.append(delta) or {"FINISHED"}
    base = next(i for i in configs.user.keymaps["3D View"].keymap_items if i.idname == "view3d.view_selected")
    base.type = "BUTTON4MOUSE"
    configs.update()
    assert bindings("3D View", "BUTTON4MOUSE")[0] == "view3d.view_selected"
    simulate()
    yield 0.3
    assert calls == [], calls

    prefs.prioritize_shortcuts = True
    yield 1.0
    assert bindings("3D View", "BUTTON4MOUSE")[:2] == [addon.DOCK_SHORTCUT_OPERATOR_ID, "view3d.view_selected"]
    simulate()
    yield 0.3
    assert calls == [-1], calls

    prefs.shortcut_scope = "PANEL"
    addon._overlay_mouse_abs = (-100000, -100000)
    simulate()
    yield 0.3
    assert calls == [-1], calls
    prefs.shortcut_scope = "GLOBAL"

    _, _, original = addon._keymap_item_for_target("shortcut_prev", configs.user)
    original.type = "BUTTON6MOUSE"
    configs.user.keymaps["3D View"].keymap_items.new("view3d.view_selected", "BUTTON6MOUSE", "PRESS")
    configs.update()
    yield 1.0
    assert bindings("3D View", "BUTTON4MOUSE")[0] == "view3d.view_selected"
    assert bindings("3D View", "BUTTON6MOUSE")[0] == addon.DOCK_SHORTCUT_OPERATOR_ID
    simulate("BUTTON6MOUSE")
    yield 0.3
    assert calls == [-1, -1], calls

    _, _, original = addon._keymap_item_for_target("shortcut_prev", configs.user)
    original.active = False
    yield 1.0
    assert bindings("3D View", "BUTTON6MOUSE")[0] == "view3d.view_selected"
    _, _, original = addon._keymap_item_for_target("shortcut_prev", configs.user)
    original.active = True
    yield 1.0
    assert bindings("3D View", "BUTTON6MOUSE")[0] == addon.DOCK_SHORTCUT_OPERATOR_ID
    prefs.prioritize_shortcuts = False
    yield 0.3
    assert not addon._priority_keymaps
    assert not bpy.app.timers.is_registered(addon._priority_keymap_timer)
    assert bindings("3D View", "BUTTON6MOUSE")[0] == "view3d.view_selected"
    _, _, original = addon._keymap_item_for_target("shortcut_prev", configs.user)
    assert original.type == "BUTTON6MOUSE" and original.active

    view = bpy.context.preferences.view
    description = prefs.bl_rna.properties["prioritize_shortcuts"].description
    assert description == addon.SHORTCUT_PRIORITY_DESCRIPTION
    view.use_translate_interface = True
    view.use_translate_tooltips = True
    for lang in ("en_US", "zh_HANS"):
        view.language = lang
        yield 0.2
        assert bpy.app.translations.locale == lang
        tip = bpy.app.translations.pgettext_tip(description)
        label = bpy.app.translations.pgettext_iface(addon.SHORTCUT_PRIORITY_LABEL)
        assert (tip == description) == (lang == "en_US"), (lang, tip)
        assert (label == addon.SHORTCUT_PRIORITY_LABEL) == (lang == "en_US"), (lang, label)


steps = checks()


def run():
    try:
        return next(steps)
    except StopIteration:
        report = "PASS Blender " + bpy.app.version_string
    except Exception:
        report = traceback.format_exc()
    (root / "shortcut-result.txt").write_text(report, encoding="utf-8")
    bpy.ops.wm.quit_blender("EXEC_DEFAULT")
    return None


bpy.app.timers.register(run, first_interval=2.5)
