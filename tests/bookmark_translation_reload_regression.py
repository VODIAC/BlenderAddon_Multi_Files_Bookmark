'''Verify translation registration after updating an isolated add-on in Blender.'''

import os
from pathlib import Path
import shutil
import sys

import addon_utils
import bpy


root = Path(os.environ['MBB_TEST_ROOT'])
assert Path(bpy.utils.user_resource('CONFIG')).resolve() == (root / 'config').resolve()
installed = root / 'scripts' / 'addons' / 'Multi_Files_Bookmark'
source = Path(os.environ['MBB_TEST_SOURCE'])
sys.path.insert(0, str(installed.parent))
bpy.context.preferences.use_preferences_save = False
addon = addon_utils.enable(installed.name, default_set=True)
assert addon is not None
view = bpy.context.preferences.view
view.use_translate_interface = True
view.use_translate_tooltips = True
view.language = 'zh_HANS'
label = addon.SHORTCUT_PRIORITY_LABEL
description = addon.SHORTCUT_PRIORITY_DESCRIPTION
tr = bpy.app.translations
assert tr.locale == 'zh_HANS'
assert tr.pgettext_iface(label) == label, 'Fixture must start with stale translations'
assert tr.pgettext_tip(description) == description
addon_utils.disable(installed.name)

for name in ('translation.py', '__init__.py'):
    target = installed / name
    old_mtime = target.stat().st_mtime
    shutil.copyfile(source / name, target)
    os.utime(target, (old_mtime + 2, old_mtime + 2))

addon = addon_utils.enable(installed.name, default_set=True)
assert addon is not None
prop = addon._addon_preferences().bl_rna.properties['prioritize_shortcuts']
assert prop.name == label and prop.description == description
for lang in ('zh_HANS', 'en_US', 'zh_HANS'):
    view.language = lang
    assert tr.locale == lang
    ctx = prop.translation_context
    translated_label = tr.pgettext_iface(prop.name, ctx)
    translated_tip = tr.pgettext_tip(prop.description, ctx)
    assert (translated_label == label) == (lang == 'en_US'), (lang, translated_label)
    assert (translated_tip == description) == (lang == 'en_US'), (lang, translated_tip)

print('PASS: checkbox RNA label and tooltip after add-on reload (zh_HANS -> en_US -> zh_HANS)')
