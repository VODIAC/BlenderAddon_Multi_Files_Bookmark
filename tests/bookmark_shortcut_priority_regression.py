"""Run in an isolated Blender GUI with --enable-event-simulate."""

import importlib
import os
from pathlib import Path
import sys
import traceback
from types import SimpleNamespace

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


def simulate(key="BUTTON4MOUSE", x=None, y=None, **modifiers):
    x = region.x + region.width // 2 if x is None else x
    y = region.y + region.height // 2 if y is None else y
    window.event_simulate(type=key, value="PRESS", x=x, y=y, **modifiers)
    window.event_simulate(type=key, value="RELEASE", x=x, y=y, **modifiers)


def bindings(name, key):
    return [i.idname for i in configs.user.keymaps[name].keymap_items if i.active and i.type == key]


def checks():
    simulate("ESC")
    yield 0.3
    assert prefs.prioritize_shortcuts is False
    addon._switch_bookmark_relative = lambda _context, delta: calls.append(delta) or {"FINISHED"}
    assert bindings("3D View", "BUTTON4MOUSE")[0] == "view3d.view_selected"
    simulate()
    yield 0.3
    assert calls == [], calls

    prefs.prioritize_shortcuts = True
    yield 1.0
    assert bindings("3D View", "BUTTON4MOUSE")[:2] == [addon.DOCK_SHORTCUT_OPERATOR_ID, "view3d.view_selected"]
    area.spaces.active.region_3d.view_distance = 50
    simulate()
    yield 0.3
    assert calls == [], calls
    assert area.spaces.active.region_3d.view_distance < 50

    native = next(i for i in configs.user.keymaps["3D View"].keymap_items
                  if i.idname == "view3d.view_selected" and i.type == "BUTTON4MOUSE")
    native.active = False
    configs.update()
    simulate()
    yield 0.3
    assert calls.pop() == -1 and not calls
    native = next(i for i in configs.user.keymaps["3D View"].keymap_items
                  if i.idname == "view3d.view_selected" and i.type == "BUTTON4MOUSE")
    native.active = True
    configs.update()
    yield 1.0

    with bpy.context.temp_override(window=window, area=area, region=region):
        bpy.ops.wm.mbb_set_view_mode(mode="NAMES")
    yield 0.4
    area_id = addon._area_id(area)
    x, y, w, h = addon._overlay_dock_rects_by_area[area_id]
    simulate(x=int(x + w / 2), y=int(y + h / 2))
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
    configs.addon.keymaps.new(name="3D View", space_type="VIEW_3D").keymap_items.new(
        "view3d.view_selected", "BUTTON6MOUSE", "PRESS"
    )
    configs.update()
    yield 1.0
    assert bindings("3D View", "BUTTON4MOUSE")[0] == "view3d.view_selected"
    assert bindings("3D View", "BUTTON6MOUSE")[0] == addon.DOCK_SHORTCUT_OPERATOR_ID
    simulate("BUTTON6MOUSE")
    yield 0.3
    assert calls == [-1, -1], calls

    _, _, original = addon._keymap_item_for_target("shortcut_prev", configs.user)
    for key in sorted(addon.PROTECTED_SHORTCUT_KEYS):
        assert addon._may_match_without_modifiers(original)
        assert not addon._allow_shortcut_event(
            bpy.context, SimpleNamespace(type=key), "shortcut_prev", True
        )
    original.type = "LEFTMOUSE"
    original.any = True
    configs.update()
    yield 1.0
    assert not any(item.type == "LEFTMOUSE" for _, item in addon._priority_keymaps.values())
    bpy.context.view_layer.objects.active.select_set(False)
    simulate("LEFTMOUSE")
    yield 0.3
    assert bpy.context.view_layer.objects.active.select_get()
    assert calls == [-1, -1], calls
    thumbnail = next(hit for hit in addon._overlay_hitboxes_by_area[area_id] if hit["action"] == "view_thumbnails")
    x, y, w, h = thumbnail["rect"]
    simulate("LEFTMOUSE", int(x + w / 2), int(y + h / 2))
    yield 0.3
    assert addon._overlay_state_for_area(area) == "THUMBNAILS"
    assert calls == [-1, -1], calls

    _, _, original = addon._keymap_item_for_target("shortcut_prev", configs.user)
    original.type = "MIDDLEMOUSE"
    original.any = False
    original.ctrl = -1
    configs.update()
    yield 1.0
    assert not any(item.type == "MIDDLEMOUSE" for _, item in addon._priority_keymaps.values())
    simulate("MIDDLEMOUSE")
    yield 0.3
    assert calls == [-1, -1], calls
    prefs.prioritize_shortcuts = False
    simulate("MIDDLEMOUSE")
    simulate("LEFTMOUSE")
    yield 0.3
    assert calls == [-1, -1], calls
    prefs.prioritize_shortcuts = True

    _, _, original = addon._keymap_item_for_target("shortcut_prev", configs.user)
    original.map_type = "KEYBOARD"
    original.type = "SPACE"
    original.ctrl = 1
    configs.user.keymaps["3D View"].keymap_items.new("view3d.view_selected", "SPACE", "PRESS", ctrl=True)
    configs.update()
    yield 1.0
    assert any(item.type == "SPACE" for _, item in addon._priority_keymaps.values())
    x, y, w, h = addon._overlay_dock_rects_by_area[area_id]
    simulate("SPACE", int(x + w / 2), int(y + h / 2), ctrl=True)
    yield 0.3
    assert calls.pop() == -1 and calls == [-1, -1], calls
    _, _, original = addon._keymap_item_for_target("shortcut_prev", configs.user)
    original.map_type = "MOUSE"
    original.type = "BUTTON6MOUSE"
    original.ctrl = 0
    configs.update()
    yield 1.0

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
        warning = bpy.app.translations.pgettext_tip(addon.MBB_OT_shortcut_priority_warning.bl_description)
        assert (tip == description) == (lang == "en_US"), (lang, tip)
        assert (label == addon.SHORTCUT_PRIORITY_LABEL) == (lang == "en_US"), (lang, label)
        assert (warning == addon.SHORTCUT_PRIORITY_WARNING) == (lang == "en_US"), (lang, warning)


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
