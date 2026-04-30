# MIT License

import re
import os
import bpy
import copy
import json
import pathlib
import threading
import traceback
import collections
import requests.exceptions
import csv
from concurrent.futures import ThreadPoolExecutor

from datetime import datetime, timezone
from collections import OrderedDict

from . import common as Common
from pathlib import Path
from .register import register_wrap
from .. import globs
# from ..googletrans import Translator  # TODO Remove this
from ..extern_tools.google_trans_new.google_trans_new import google_translator
from .translations import t, get_language_from_settings

from mmd_tools_local import translations as mmd_translations

dictionary = {}
dictionary_google = {}

_RE_NON_LATIN = re.compile(r'[\u3000-\u303f\u3040-\u309f\u30a0-\u30ff\uff00-\uff9f\u4e00-\u9faf\u3400-\u4dbf\uac00-\ud7af\u1100-\u11ff]+')
_RE_JP  = re.compile(r'[\u3040-\u309f\u30a0-\u30ff]')
_RE_KO  = re.compile(r'[\uac00-\ud7af\u1100-\u11ff]')
_RE_CJK = re.compile(r'[\u4e00-\u9faf\u3400-\u4dbf]')

main_dir = pathlib.Path(os.path.dirname(__file__)).parent.resolve()
resources_dir = os.path.join(str(main_dir), "resources")
dictionary_file = os.path.join(resources_dir, "dictionary.json")
dictionary_google_file = os.path.join(resources_dir, "dictionary_google.json")

def get_cats_dir(context):
    prefs = context.preferences.addons["cats-blender-plugin"].preferences
    
    if prefs.custom_shapekeys_export_dir: 
        return prefs.custom_shapekeys_export_dir
    
    # Fallback to default cats directory
    return os.path.join(bpy.utils.user_resource('DATAFILES'), "cats") 

@register_wrap
class TranslateShapekeyButton(bpy.types.Operator):
    bl_idname = 'cats_translate.shapekeys'
    bl_label = t('TranslateShapekeyButton.label')
    bl_description = t('TranslateShapekeyButton.desc')
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    def execute(self, context):
        saved_data = Common.SavedData()

        cats_dir = context.scene.custom_translate_csv_export_dir
        if not cats_dir:
            # Fallback to default dir
            cats_dir = get_cats_dir(context)  
            
        # Check if dir exists or can be created
        if not os.path.exists(cats_dir):
            try:
                os.makedirs(cats_dir) 
            except OSError:
                self.report({'ERROR'}, "Unable to create export folder. Please manually set the export directory")
                return {'CANCELLED'}
                
        if not os.path.exists(cats_dir) or not os.access(cats_dir, os.W_OK):  
            self.report({'ERROR'}, "Unable to write to export folder. Please manually set the export directory")
            return {'CANCELLED'}
            
        skip_locked_shape_keys = bpy.context.scene.skip_locked_shape_keys
        if context.scene.export_translate_csv:
            
            blend_path = bpy.context.blend_data.filepath
            if not blend_path:
                self.report({'ERROR'}, "Please save blend first!")
                return {'CANCELLED'}
            
            to_translate = []
            for mesh in Common.get_meshes_objects(mode=2):
                if Common.has_shapekeys(mesh):
                    for key in mesh.data.shape_keys.key_blocks:
                        if can_translate_shape_key(key, skip_locked_shape_keys):
                            to_translate.append(key.name)

            update_dictionary(to_translate, translating_shapes=True, self=self)
            Common.update_shapekey_orders()
            
            shapekeys = []
            i = 0
            for mesh in Common.get_meshes_objects(mode=2):
                if Common.has_shapekeys(mesh):
                    for key in mesh.data.shape_keys.key_blocks:
                        if can_translate_shape_key(key, skip_locked_shape_keys):
                            original_name = key.name
                            key.name, translated = translate(key.name, add_space=True, translating_shapes=True)
                
                            if translated:
                                i += 1
                                shapekeys.append({
                                    'mesh/object': mesh.name,
                                    'original': original_name,
                                    'translated': key.name
                                })

            blend_name = os.path.splitext(os.path.basename(blend_path))[0] 
            export_path = os.path.join(str(cats_dir), blend_name + "_shapekeys.csv")
            
            with open(export_path, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['mesh/object', 'original', 'translated'])
                for key in shapekeys:
                    writer.writerow([key['mesh/object'], key['original'], key['translated']])

        else:
            to_translate = []
            for mesh in Common.get_meshes_objects(mode=2):
                if Common.has_shapekeys(mesh):
                    for shapekey in mesh.data.shape_keys.key_blocks:
                        if can_translate_shape_key(shapekey, skip_locked_shape_keys) and shapekey.name not in to_translate:
                            to_translate.append(shapekey.name)

            update_dictionary(to_translate, translating_shapes=True, self=self)

            Common.update_shapekey_orders()

            i = 0
            for mesh in Common.get_meshes_objects(mode=2):
                if Common.has_shapekeys(mesh):
                    for shapekey in mesh.data.shape_keys.key_blocks:
                        if can_translate_shape_key(shapekey, skip_locked_shape_keys):
                            shapekey.name, translated = translate(shapekey.name, add_space=True, translating_shapes=True)
                            if translated:
                                i += 1

        Common.ui_refresh()

        saved_data.load()

        self.report({'INFO'}, t('TranslateShapekeyButton.success', number=str(i)))
        return {'FINISHED'}


@register_wrap
class TranslateBonesButton(bpy.types.Operator):
    bl_idname = 'cats_translate.bones'
    bl_label = t('TranslateBonesButton.label')
    bl_description = t('TranslateBonesButton.desc')
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    def execute(self, context):
        saved_data = Common.SavedData()

        cats_dir = context.scene.custom_translate_csv_export_dir
        if not cats_dir:
            # Fallback to default dir
            cats_dir = get_cats_dir(context)  
            
        # Check if dir exists or can be created
        if not os.path.exists(cats_dir):
            try:
                os.makedirs(cats_dir) 
            except OSError:
                self.report({'ERROR'}, "Unable to create export folder. Please manually set the export directory")
                return {'CANCELLED'}
                
        if not os.path.exists(cats_dir) or not os.access(cats_dir, os.W_OK):  
            self.report({'ERROR'}, "Unable to write to export folder. Please manually set the export directory")
            return {'CANCELLED'}
            
        if context.scene.export_translate_csv:
            
            blend_path = bpy.context.blend_data.filepath
            if not blend_path:
                self.report({'ERROR'}, "Please save blend first!")
                return {'CANCELLED'}
            
            to_translate = []
            for armature in Common.get_armature_objects():
                for bone in armature.data.bones:
                    to_translate.append(bone.name)

            update_dictionary(to_translate, self=self)
            
            bones = []
            i = 0
            for armature in Common.get_armature_objects():
                for bone in armature.data.bones:
                    original_name = bone.name
                    bone.name, translated = translate(bone.name)
                    if translated:
                        i += 1
                        bones.append({
                            'armature': armature.name,
                            'original': original_name,
                            'translated': bone.name
                        })

            blend_name = os.path.splitext(os.path.basename(blend_path))[0] 
            export_path = os.path.join(str(cats_dir), blend_name + "_bones.csv")
            
            with open(export_path, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['armature', 'original', 'translated'])
                for bone in bones:
                    writer.writerow([bone['armature'], bone['original'], bone['translated']])

        else:
            to_translate = []
            for armature in Common.get_armature_objects():
                for bone in armature.data.bones:
                    if bone.name not in to_translate:
                        to_translate.append(bone.name)

            update_dictionary(to_translate, self=self)

            i = 0
            for armature in Common.get_armature_objects():
                for bone in armature.data.bones:
                    original_name = bone.name
                    bone.name, translated = translate(bone.name)
                    if translated:
                        i += 1

        Common.ui_refresh()

        saved_data.load()

        self.report({'INFO'}, t('TranslateBonesButton.success', number=str(i)))
        return {'FINISHED'}


@register_wrap
class TranslateObjectsButton(bpy.types.Operator):
    bl_idname = 'cats_translate.objects'
    bl_label = t('TranslateObjectsButton.label')
    bl_description = t('TranslateObjectsButton.desc')
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    def execute(self, context):
        saved_data = Common.SavedData()

        cats_dir = context.scene.custom_translate_csv_export_dir
        if not cats_dir:
            # Fallback to default dir
            cats_dir = get_cats_dir(context)

        # Check if dir exists or can be created
        if not os.path.exists(cats_dir):
            try:
                os.makedirs(cats_dir)
            except OSError:
                self.report({'ERROR'}, "Unable to create export folder. Please manually set the export directory")
                return {'CANCELLED'}

        if not os.path.exists(cats_dir) or not os.access(cats_dir, os.W_OK):
            self.report({'ERROR'}, "Unable to write to export folder. Please manually set the export directory")
            return {'CANCELLED'}

        if context.scene.export_translate_csv:
            blend_path = bpy.context.blend_data.filepath
            if not blend_path:
                self.report({'ERROR'}, "Please save blend first!")
                return {'CANCELLED'}

            to_translate = []
            for obj in Common.get_objects():
                to_translate.append(obj.name)

            update_dictionary(to_translate, self=self)

            objects_translations = []
            i = 0
            for obj in Common.get_objects():
                original_name = obj.name
                obj.name, translated = translate(obj.name)
                if translated:
                    i += 1
                    objects_translations.append({
                        'object': obj.name,
                        'original': original_name,
                        'translated': obj.name
                    })

            blend_name = os.path.splitext(os.path.basename(blend_path))[0]
            export_path = os.path.join(str(cats_dir), blend_name + "_objects.csv")

            with open(export_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['object', 'original', 'translated'])
                for translation in objects_translations:
                    writer.writerow([translation['object'], translation['original'], translation['translated']])

        else:
            to_translate = []
            for obj in Common.get_objects():
                if obj.name not in to_translate:
                    to_translate.append(obj.name)

            update_dictionary(to_translate, self=self)

            i = 0
            for obj in Common.get_objects():
                original_name = obj.name
                obj.name, translated = translate(obj.name)
                if translated:
                    i += 1

        Common.ui_refresh()

        saved_data.load()

        self.report({'INFO'}, t('TranslateObjectsButton.success', number=str(i)))
        return {'FINISHED'}


@register_wrap
class TranslateMaterialsButton(bpy.types.Operator):
    bl_idname = 'cats_translate.materials'
    bl_label = t('TranslateMaterialsButton.label')
    bl_description = t('TranslateMaterialsButton.desc')
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    def execute(self, context):
        saved_data = Common.SavedData()

        cats_dir = context.scene.custom_translate_csv_export_dir
        if not cats_dir:
            # Fallback to default dir
            cats_dir = get_cats_dir(context)

        # Check if dir exists or can be created
        if not os.path.exists(cats_dir):
            try:
                os.makedirs(cats_dir)
            except OSError:
                self.report({'ERROR'}, "Unable to create export folder. Please manually set the export directory")
                return {'CANCELLED'}

        if not os.path.exists(cats_dir) or not os.access(cats_dir, os.W_OK):
            self.report({'ERROR'}, "Unable to write to export folder. Please manually set the export directory")
            return {'CANCELLED'}

        if context.scene.export_translate_csv:
            blend_path = bpy.context.blend_data.filepath
            if not blend_path:
                self.report({'ERROR'}, "Please save blend first!")
                return {'CANCELLED'}

            to_translate = []
            for mesh in Common.get_meshes_objects(mode=2):
                for matslot in mesh.material_slots:
                    to_translate.append(matslot.name)

            update_dictionary(to_translate, self=self)

            materials_translations = []
            i = 0
            for mesh in Common.get_meshes_objects(mode=2):
                for matslot in mesh.material_slots:
                    original_name = matslot.name
                    matslot.material.name, translated = translate(matslot.material.name)
                    if translated:
                        i += 1
                        materials_translations.append({
                            'mesh': mesh.name,
                            'original': original_name,
                            'translated': matslot.material.name
                        })

            blend_name = os.path.splitext(os.path.basename(blend_path))[0]
            export_path = os.path.join(str(cats_dir), blend_name + "_materials.csv")

            with open(export_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['mesh', 'original', 'translated'])
                for translation in materials_translations:
                    writer.writerow([translation['mesh'], translation['original'], translation['translated']])

        else:
            to_translate = []
            for mesh in Common.get_meshes_objects(mode=2):
                for matslot in mesh.material_slots:
                    if matslot.name not in to_translate:
                        to_translate.append(matslot.name)

            update_dictionary(to_translate, self=self)

            i = 0
            for mesh in Common.get_meshes_objects(mode=2):
                for matslot in mesh.material_slots:
                    original_name = matslot.name
                    matslot.material.name, translated = translate(matslot.material.name)
                    if translated:
                        i += 1

        Common.ui_refresh()

        saved_data.load()

        self.report({'INFO'}, t('TranslateMaterialsButton.success', number=str(i)))
        return {'FINISHED'}


# @register_wrap
# class TranslateTexturesButton(bpy.types.Operator):
#     bl_idname = 'cats_translate.textures'
#     bl_label = t('TranslateTexturesButton.label')
#     bl_description = t('TranslateTexturesButton.desc')
#     bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}
#
#     def execute(self, context):
#         # It currently seems to do nothing. This should probably only added when the folder textures really get translated. Currently only the materials are important
#         self.report({'INFO'}, t('TranslateTexturesButton.success_alt'))
#         return {'FINISHED'}
#
#         translator = google_translator()
#
#         to_translate = []
#         for ob in Common.get_objects():
#             if ob.type == 'MESH':
#                 for matslot in ob.material_slots:
#                     for texslot in bpy.data.materials[matslot.name].texture_slots:
#                         if texslot:
#                             print(texslot.name)
#                             to_translate.append(texslot.name)
#
#         translated = []
#         try:
#             translations = translator.translate(to_translate, lang_tgt='en')
#         except SSLError:
#             self.report({'ERROR'}, t('TranslateTexturesButton.error.noInternet'))
#             return {'FINISHED'}
#
#         for translation in translations:
#             translated.append(translation)
#
#         i = 0
#         for ob in Common.get_objects():
#             if ob.type == 'MESH':
#                 for matslot in ob.material_slots:
#                     for texslot in bpy.data.materials[matslot.name].texture_slots:
#                         if texslot:
#                             bpy.data.textures[texslot.name].name = translated[i]
#                             i += 1
#
#         Common.unselect_all()
#
#         self.report({'INFO'}, t('TranslateTexturesButton.success', number=str(i)))
#         return {'FINISHED'}


@register_wrap
class TranslateAllButton(bpy.types.Operator):
    bl_idname = 'cats_translate.all'
    bl_label = t('TranslateAllButton.label')
    bl_description = t('TranslateAllButton.desc')
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    _thread = None
    _timer = None
    _error = None
    _bones_list = None
    _shapes_list = None
    _objects_list = None
    _materials_list = None

    def execute(self, context):
        if context.scene.export_translate_csv:
            if not bpy.data.filepath:
                self.report({'ERROR'}, "Please save the blend file before exporting translations.")
                return {'CANCELLED'}

        skip_locked = bpy.context.scene.skip_locked_shape_keys

        # Collect all names on the main thread (bpy access required)
        self._bones_list = []
        if Common.get_armature():
            for armature in Common.get_armature_objects():
                for bone in armature.data.bones:
                    if bone.name not in self._bones_list:
                        self._bones_list.append(bone.name)

        self._shapes_list = []
        for mesh in Common.get_meshes_objects(mode=2):
            if Common.has_shapekeys(mesh):
                for sk in mesh.data.shape_keys.key_blocks:
                    if can_translate_shape_key(sk, skip_locked) and sk.name not in self._shapes_list:
                        self._shapes_list.append(sk.name)

        self._objects_list = []
        for obj in Common.get_objects():
            if obj.name not in self._objects_list:
                self._objects_list.append(obj.name)

        self._materials_list = []
        for mesh in Common.get_meshes_objects(mode=2):
            for matslot in mesh.material_slots:
                if matslot.name not in self._materials_list:
                    self._materials_list.append(matslot.name)

        self._error = None
        self._thread = threading.Thread(target=self._run_translations, daemon=True)
        self._thread.start()

        wm = context.window_manager
        self._timer = wm.event_timer_add(0.1, window=context.window)
        wm.modal_handler_add(self)
        context.workspace.status_text_set("CATS: Translating...")
        return {'RUNNING_MODAL'}

    def _run_translations(self):
        try:
            if self._bones_list:
                update_dictionary(self._bones_list, self=None)
            if self._shapes_list:
                update_dictionary(self._shapes_list, translating_shapes=True, self=None)
            if self._objects_list:
                update_dictionary(self._objects_list, self=None)
            if self._materials_list:
                update_dictionary(self._materials_list, self=None)
        except Exception as e:
            self._error = str(e)

    def modal(self, context, event):
        if event.type == 'TIMER':
            if not self._thread.is_alive():
                return self._finish(context)
        return {'PASS_THROUGH'}

    def _finish(self, context):
        wm = context.window_manager
        wm.event_timer_remove(self._timer)
        context.workspace.status_text_set(None)

        if self._error:
            self.report({'ERROR'}, self._error)
            return {'CANCELLED'}

        # Apply translations on the main thread
        saved_data = Common.SavedData()
        skip_locked = bpy.context.scene.skip_locked_shape_keys
        i = 0

        for armature in Common.get_armature_objects():
            for bone in armature.data.bones:
                bone.name, translated = translate(bone.name)
                if translated:
                    i += 1

        for mesh in Common.get_meshes_objects(mode=2):
            if Common.has_shapekeys(mesh):
                for sk in mesh.data.shape_keys.key_blocks:
                    if can_translate_shape_key(sk, skip_locked):
                        sk.name, translated = translate(sk.name, add_space=True, translating_shapes=True)
                        if translated:
                            i += 1

        for obj in Common.get_objects():
            obj.name, translated = translate(obj.name)
            if translated:
                i += 1

        for mesh in Common.get_meshes_objects(mode=2):
            for matslot in mesh.material_slots:
                matslot.material.name, translated = translate(matslot.material.name)
                if translated:
                    i += 1

        Common.update_shapekey_orders()
        Common.ui_refresh()
        saved_data.load()

        self.report({'INFO'}, t('TranslateAllButton.success'))
        return {'FINISHED'}


# Loads the dictionaries at the start of blender
def load_translations():
    global dictionary
    dictionary = OrderedDict()
    temp_dict = OrderedDict()
    dict_found = False

    # Load internal dictionary
    try:
        with open(dictionary_file, encoding="utf8") as file:
            temp_dict = json.load(file, object_pairs_hook=collections.OrderedDict)
            dict_found = True
            # print('DICTIONARY LOADED!')
    except FileNotFoundError:
        print('DICTIONARY NOT FOUND!')
        pass
    except json.decoder.JSONDecodeError:
        print("ERROR FOUND IN DICTIONARY")
        pass

    # Load local google dictionary and add it to the temp dict
    try:
        with open(dictionary_google_file, encoding="utf8") as file:
            global dictionary_google
            dictionary_google = json.load(file, object_pairs_hook=collections.OrderedDict)

            if 'created' not in dictionary_google \
                    or 'translations' not in dictionary_google \
                    or 'translations_full' not in dictionary_google:
                reset_google_dict()
            else:
                for name, trans in dictionary_google.get('translations').items():
                    if not name:
                        continue

                    if name in temp_dict.keys():
                        print(name, 'ALREADY IN INTERNAL DICT!')
                        continue

                    temp_dict[name] = trans

            # print('GOOGLE DICTIONARY LOADED!')
    except FileNotFoundError:
        print('GOOGLE DICTIONARY NOT FOUND!')
        reset_google_dict()
        pass
    except json.decoder.JSONDecodeError:
        print("ERROR FOUND IN GOOOGLE DICTIONARY")
        reset_google_dict()
        pass

    # Sort temp dictionary by lenght and put it into the global dict
    for key in sorted(temp_dict, key=lambda k: len(k), reverse=True):
        dictionary[key] = temp_dict[key]

    # for key, value in dictionary.items():
    #     print('"' + key + '" - "' + value + '"')

    return dict_found


def _get_google_target_lang():
    # Map plugin language codes to Google Translate codes; fall back to English
    lang = get_language_from_settings() or 'en_US'
    mapping = {'zh_CN': 'zh-cn', 'ko_KR': 'ko', 'ja_JP': 'ja', 'en_US': 'en'}
    prefix = lang.split('_')[0] + '_' + lang.split('_')[1] if '_' in lang else lang
    return mapping.get(prefix, 'en')


def _detect_source_lang(text):
    if _RE_JP.search(text):
        return 'ja'
    if _RE_KO.search(text):
        return 'ko'
    if _RE_CJK.search(text):
        return 'zh-cn'
    return 'en'


def update_dictionary(to_translate_list, translating_shapes=False, self=None):
    global dictionary, dictionary_google

    target_lang = _get_google_target_lang()

    use_google_only = False
    if translating_shapes and bpy.context.scene.use_google_only:
        use_google_only = True

    # When target language is not English, bypass local English dictionary entirely
    if target_lang != 'en':
        use_google_only = True

    # Check if single string is given and put it into an array
    if type(to_translate_list) is str:
        to_translate_list = [to_translate_list]

    google_input = []

    # Translate everything
    for to_translate in to_translate_list:
        length = len(to_translate)
        translated_count = 0

        to_translate = fix_jp_chars(to_translate)

        # Translate shape keys with Google Translator only, if the user chose this
        if use_google_only:
            # For English target, only process non-Latin chars; all other targets accept any input
            if target_lang == 'en' and not _RE_NON_LATIN.search(to_translate):
                continue

            # Skip if already in the target language
            if _detect_source_lang(to_translate) == target_lang:
                continue

            # Skip cache when targeting non-English — cache entries may be stale English
            translated = False
            if target_lang == 'en':
                for key, value in dictionary_google.get('translations_full').items():
                    if to_translate == key and value:
                        translated = True

            if not translated:
                google_input.append(to_translate)

        # Translate with internal dictionary
        else:
            for key, value in dictionary.items():
                if key in to_translate:
                    if value:
                        to_translate = to_translate.replace(key, value)
                    else:
                        continue

                    # Check if string is fully translated
                    translated_count += len(key)
                    if translated_count >= length:
                        break

            # If not fully translated, translate the rest with Google
            if translated_count < length:
                match = _RE_NON_LATIN.findall(to_translate)
                if match:
                    for name in match:
                        if name not in google_input and name not in dictionary.keys():
                            google_input.append(name)

    if not google_input:
        # print('NO GOOGLE TRANSLATIONS')
        return

    # Translate the rest with Google Translate (parallel requests)
    print('GOOGLE DICT UPDATE!')

    def _translate_one(text):
        tries = 0
        while True:
            try:
                tr = google_translator(url_suffix='com')
                return tr.translate(text, lang_src=_detect_source_lang(text), lang_tgt=target_lang).strip()
            except AttributeError:
                tries += 1
                if tries >= 3:
                    raise

    try:
        workers = min(10, len(google_input))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            translations = list(executor.map(_translate_one, google_input))
    except (requests.exceptions.ConnectionError, ConnectionRefusedError):
        print('CONNECTION TO GOOGLE FAILED!')
        if self:
            self.report({'ERROR'}, t('update_dictionary.error.cantConnect'))
        return
    except (json.JSONDecodeError, TypeError) as e:
        if self:
            print(traceback.format_exc())
            self.report({'ERROR'}, 'Google Translate API has changed or returned an invalid response or you'
                                '\ncould have been banned. Cats translated what it could with the local dictionary,'
                                '\nbut you will need to update the translation module or try again later.')
        print('GOOGLE TRANSLATE API ERROR:', str(e))
        return
    except RuntimeError as e:
        error = Common.html_to_text(str(e))
        if self:
            if 'Please try your request again later' in error:
                self.report({'ERROR'}, t('update_dictionary.error.temporaryBan') + t('update_dictionary.error.catsTranslated'))
                print('YOU GOT BANNED BY GOOGLE!')
                return
            if 'Error 403' in error:
                self.report({'ERROR'}, t('update_dictionary.error.cantAccess') + t('update_dictionary.error.catsTranslated'))
                print('NO PERMISSION TO USE GOOGLE TRANSLATE!')
                return
            self.report({'ERROR'}, t('update_dictionary.error.errorMsg') + t('update_dictionary.error.catsTranslated') + '\n' + '\nGoogle: ' + error)
        print('', 'You got an error message from Google:', error, '')
        return
    except AttributeError:
        if self:
            self.report({'ERROR'}, t('update_dictionary.error.apiChanged'))
        print('ERROR: GOOGLE API CHANGED!')
        print(traceback.format_exc())
        return

    # Update the dictionaries
    for i, translation in enumerate(translations):
        name = google_input[i]

        if use_google_only:
            dictionary_google['translations_full'][name] = translation
        else:
            # Capitalize words
            translation_words = translation.split(' ')
            translation_words = [word.capitalize() for word in translation_words]
            translation = ' '.join(translation_words)

            dictionary[name] = translation
            dictionary_google['translations'][name] = translation

        print(google_input[i], '->', translation)

    # Sort dictionary
    temp_dict = copy.deepcopy(dictionary)
    dictionary = OrderedDict()
    for key in sorted(temp_dict, key=lambda k: len(k), reverse=True):
        dictionary[key] = temp_dict[key]

    # Save the google dict locally
    save_google_dict()

    print('DICTIONARY UPDATE SUCCEEDED!')
    return


def translate(to_translate, add_space=False, translating_shapes=False):
    global dictionary

    pre_translation = to_translate
    length = len(to_translate)
    translated_count = 0

    # Figure out whether to use google only or not
    use_google_only = False
    if translating_shapes and bpy.context.scene.use_google_only:
        use_google_only = True
    if _get_google_target_lang() != 'en':
        use_google_only = True

    # Add space for shape keys
    addition = ''
    if add_space:
        addition = ' '

    # Convert half chars into full chars
    to_translate = fix_jp_chars(to_translate)

    # Translate shape keys with Google Translator only, if the user chose this
    if use_google_only:
        for key, value in dictionary_google.get('translations_full').items():
            if to_translate == key and value:
                to_translate = value

    # Translate with internal dictionary
    else:
        for key, value in dictionary.items():
            if key in to_translate:
                # If string is empty, don't replace it. This will be done at the end
                if not value:
                    continue

                to_translate = to_translate.replace(key, addition + value)

                # Check if string is fully translated
                translated_count += len(key)
                if translated_count >= length:
                    break

    to_translate = to_translate.replace('.L', '_L').replace('.R', '_R').replace('  ', ' ').replace('し', '').replace('っ', '').strip()

    # print('"' + pre_translation + '"')
    # print('"' + to_translate + '"')

    return to_translate, pre_translation != to_translate


def fix_jp_chars(name):
    for values in mmd_translations.jp_half_to_full_tuples:
        if values[0] in name:
            name = name.replace(values[0], values[1])
    return name


def reset_google_dict():
    global dictionary_google
    dictionary_google = OrderedDict()

    now_utc = datetime.now(timezone.utc).strftime(globs.time_format)

    dictionary_google['created'] = now_utc
    dictionary_google['translations'] = {}
    dictionary_google['translations_full'] = {}

    save_google_dict()
    print('GOOGLE DICT RESET')


def save_google_dict():
    with open(dictionary_google_file, 'w', encoding="utf8") as outfile:
        json.dump(dictionary_google, outfile, ensure_ascii=False, indent=4)


# Check if shape key meets translation conditions
def can_translate_shape_key(shapekey, skip_locked_shape_keys):
    if skip_locked_shape_keys:
        if not shapekey.lock_shape:
            if 'vrc.' not in shapekey.name:
                return True
    else:
        if 'vrc.' not in shapekey.name:
            return True
    return False