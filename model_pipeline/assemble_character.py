import bpy
import os
import mathutils
import math
import json
import time
from datetime import datetime

# ==============================================================================
# ⚙️ CONFIGURATION
# ==============================================================================

if not bpy.data.is_saved: raise Exception("⚠️ ERROR: Save .blend file first!")
blend_dir = os.path.dirname(bpy.data.filepath)

# Paths
PIPELINE_ROOT = blend_dir
SOURCE_DIR = os.path.join(PIPELINE_ROOT, "0_source_models")
ANIM_DIR = os.path.join(PIPELINE_ROOT, "1_anim_library")

# Relative path to raw_assets (one folder up)
REPO_RAW_ASSETS_DIR = os.path.abspath(os.path.join(PIPELINE_ROOT, "..", "raw_assets"))

# Log file for incremental builds
BUILD_LOG_FILE = os.path.join(PIPELINE_ROOT, "build_manifest.json")

# Force Rebuild (Set to True to ignore the log and rebuild everything)
FORCE_REBUILD = False

# --- MODEL CONFIGURATION ---
DEFAULT_CONFIG = {"gender": "M", "extra_arm_angle": 0.0}

MODEL_CONFIG = {
    "leib":          {"gender": "M", "extra_arm_angle": 0.0},
    "katinka":       {"gender": "F", "extra_arm_angle": 0.0},
    "marco":         {"gender": "M", "extra_arm_angle": 7.0}
}

# --- ANIMATION MAPPING ---
ANIMATION_TARGETS = {
    "idle": "idle.fbx",
    "walk": "walk.fbx",
    "run": "run.fbx",
    "jump_up": "jump_up.fbx",
    "falling_idle": "falling_idle.fbx",
    "landing": "falling_to_idle.fbx",
    "walk_backwards": "walk_backwards.fbx",
    "strafe_left": "strafe_left.fbx",
    "strafe_right": "strafe_right.fbx",
    "glide": "glide.fbx",
    "cast": "cast.fbx"
}

# ==============================================================================
# 🛠️ HELPER FUNCTIONS
# ==============================================================================

def get_file_timestamp(filepath):
    """Returns the modification timestamp of a file."""
    if not os.path.exists(filepath): return 0
    return os.path.getmtime(filepath)

def load_manifest():
    """Loads the build history from JSON."""
    if os.path.exists(BUILD_LOG_FILE):
        try:
            with open(BUILD_LOG_FILE, 'r') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_manifest(data):
    """Saves the build history to JSON."""
    with open(BUILD_LOG_FILE, 'w') as f:
        json.dump(data, f, indent=4)

def clean_scene():
    """Resets the scene."""
    if bpy.context.active_object and bpy.context.active_object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()
    for col in [bpy.data.actions, bpy.data.armatures, bpy.data.meshes, bpy.data.materials, bpy.data.images]:
        for item in col:
            try: col.remove(item)
            except: pass

def setup_mounting_point(armature, mesh_obj):
    """Creates a projectile mounting point."""
    if "projectile_point" in bpy.data.objects: return
    hand_bone = armature.pose.bones.get("mixamorig:RightHand") or armature.pose.bones.get("RightHand")
    bpy.ops.object.empty_add(type='PLAIN_AXES', radius=0.2)
    mt_point = bpy.context.active_object
    mt_point.name = "projectile_point"
    mt_point.parent = armature

    if hand_bone:
        mt_point.parent_type = 'BONE'
        mt_point.parent_bone = hand_bone.name
        mt_point.location = (0, 0.15, 0) 
        mt_point.rotation_euler = (0, 1.57, 0)
    else:
        if mesh_obj:
            bbox_corners = [mesh_obj.matrix_world @ mathutils.Vector(corner) for corner in mesh_obj.bound_box]
            height = max(v.z for v in bbox_corners) - min(v.z for v in bbox_corners)
            mt_point.location = (0, 0, min(v.z for v in bbox_corners) + (height * 0.75))

def fix_arm_spacing(armature, action, angle):
    """Applies X-axis rotation offset to upper arms."""
    if angle == 0: return

    rad = math.radians(angle)
    rot_adj = mathutils.Euler((rad, 0, 0), 'XYZ')

    frame_start = int(action.frame_range[0])
    frame_end = int(action.frame_range[1])
    
    # Only print every few frames to reduce noise
    print(f"    - Fix Arms ({angle}deg) on '{action.name}'")

    for f in range(frame_start, frame_end + 1):
        bpy.context.scene.frame_set(f)
        
        pb_l = armature.pose.bones.get("mixamorig:LeftArm") or armature.pose.bones.get("LeftArm")
        pb_r = armature.pose.bones.get("mixamorig:RightArm") or armature.pose.bones.get("RightArm")
        
        if pb_l:
            pb_l.rotation_mode = 'QUATERNION'
            pb_l.rotation_quaternion = pb_l.rotation_quaternion @ rot_adj.to_quaternion()
            pb_l.keyframe_insert(data_path="rotation_quaternion", frame=f)

        if pb_r:
            pb_r.rotation_mode = 'QUATERNION'
            pb_r.rotation_quaternion = pb_r.rotation_quaternion @ rot_adj.to_quaternion()
            pb_r.keyframe_insert(data_path="rotation_quaternion", frame=f)

def find_animation_file(base_filename, gender):
    """Locates the animation file based on gender prefix."""
    target_file = f"{gender}_{base_filename}"
    path = os.path.join(ANIM_DIR, target_file)
    if os.path.exists(path):
        return path
    
    if gender == "F":
        fallback_file = f"M_{base_filename}"
        fallback_path = os.path.join(ANIM_DIR, fallback_file)
        if os.path.exists(fallback_path):
            return fallback_path
    return None

def needs_update(model_name, current_state, manifest):
    """Checks if the model needs to be rebuilt."""
    if FORCE_REBUILD: return True
    if model_name not in manifest: return True
    
    last_build = manifest[model_name]
    
    # 1. Check Source Model Time
    if current_state['source_mtime'] != last_build.get('source_mtime'):
        print(f"    ⚠️ Source model file changed.")
        return True
        
    # 2. Check Config (e.g. arm angle changed in script)
    if current_state['config'] != last_build.get('config'):
        print(f"    ⚠️ Configuration changed.")
        return True
        
    # 3. Check Animation Files
    for anim_name, anim_data in current_state['animations'].items():
        if anim_name not in last_build.get('animations', {}):
            print(f"    ⚠️ New animation added: {anim_name}")
            return True
        
        last_anim_mtime = last_build['animations'][anim_name].get('mtime')
        if anim_data['mtime'] != last_anim_mtime:
            print(f"    ⚠️ Animation file changed: {anim_name}")
            return True
            
    return False

# ==============================================================================
# 🚀 CORE PIPELINE
# ==============================================================================

def process_model(filename, manifest):
    """Main processing pipeline for a single model with logging."""
    model_path = os.path.join(SOURCE_DIR, filename)
    model_name = os.path.splitext(filename)[0]
    
    # Get config
    config = MODEL_CONFIG.get(model_name, DEFAULT_CONFIG)
    gender = config.get("gender", "M")
    
    # --- PHASE 1: GATHER CURRENT STATE ---
    # We collect all data *before* touching Blender, to decide if we run.
    
    current_state = {
        "build_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source_file": filename,
        "source_mtime": get_file_timestamp(model_path),
        "config": config,
        "animations": {}
    }
    
    # Resolve all animation paths and timestamps
    for target_name, base_filename in ANIMATION_TARGETS.items():
        anim_path = find_animation_file(base_filename, gender)
        if anim_path:
            current_state['animations'][target_name] = {
                "file": os.path.basename(anim_path),
                "mtime": get_file_timestamp(anim_path)
            }

    # --- PHASE 2: CHECK AGAINST MANIFEST ---
    if not needs_update(model_name, current_state, manifest):
        print(f"⏭️  Skipping {model_name} (Up to date)")
        return False # Did not update

    print(f"\n🚀 Building: {model_name}...")
    clean_scene()
    extra_angle = config.get("extra_arm_angle", 0.0)

    # --- PHASE 3: BLENDER OPERATIONS ---
    try:
        if filename.lower().endswith(".fbx"):
            bpy.ops.import_scene.fbx(filepath=model_path, automatic_bone_orientation=True)
        elif filename.lower().endswith(".glb"):
            bpy.ops.import_scene.gltf(filepath=model_path)
    except Exception as e:
        print(f"  ❌ FATAL: Could not import model: {e}")
        return False
    
    armature = next((obj for obj in bpy.data.objects if obj.type == 'ARMATURE'), None)
    mesh = next((obj for obj in bpy.data.objects if obj.type == 'MESH'), None)
    
    if not armature:
        print(f"  ❌ ERROR: No armature found.")
        return False

    bpy.context.view_layer.objects.active = armature
    bpy.ops.object.mode_set(mode='OBJECT')
    setup_mounting_point(armature, mesh)

    if not armature.animation_data:
        armature.animation_data_create()

    # Import and Link Animations
    for target_name, anim_info in current_state['animations'].items():
        # Re-resolve path (safe because we checked existance in Phase 1)
        # Note: We use the logic again to be 100% sure we load the right one
        base_filename = ANIMATION_TARGETS[target_name]
        anim_path = find_animation_file(base_filename, gender)

        try:
            bpy.ops.import_scene.fbx(filepath=anim_path, automatic_bone_orientation=True)
            temp_objects = bpy.context.selected_objects
            temp_armature = next((o for o in temp_objects if o.type == 'ARMATURE'), None)
            
            if temp_armature and temp_armature.animation_data and temp_armature.animation_data.action:
                action = temp_armature.animation_data.action
                action.name = target_name
                armature.animation_data.action = action
                
                if extra_angle > 0:
                    fix_arm_spacing(armature, action, extra_angle)

                track = armature.animation_data.nla_tracks.new()
                track.name = target_name
                track.strips.new(action.name, int(action.frame_range[0]), action)
                
            bpy.ops.object.delete() 
            print(f"  ✅ Added: {target_name}")
            
        except Exception as e:
            print(f"  ⚠️ Error processing {target_name}: {e}")

    # Export
    if not os.path.exists(REPO_RAW_ASSETS_DIR):
        print(f"  ❌ ERROR: Repo directory missing: {REPO_RAW_ASSETS_DIR}")
        return False

    target_path = os.path.join(REPO_RAW_ASSETS_DIR, f"{model_name}.glb")
    bpy.ops.export_scene.gltf(
        filepath=target_path, export_format='GLB', use_selection=False,
        export_yup=True, export_animations=True, export_nla_strips=True, export_def_bones=True
    )
    print(f"  🎉 Exported: {target_path}")
    
    # Update manifest data only on success
    manifest[model_name] = current_state
    return True # Updated

# ==============================================================================
# 🏃‍♂️ EXECUTION
# ==============================================================================
print("\n" + "="*60 + "\n🎬 START SMART PIPELINE (Incremental Build)\n" + "="*60)

manifest = load_manifest()
updates_made = False

if os.path.exists(SOURCE_DIR):
    files = [f for f in os.listdir(SOURCE_DIR) if f.lower().endswith(('.fbx', '.glb'))]
    if not files: print(f"⚠️ No models found in: {SOURCE_DIR}")
    else:
        for f in files:
            if process_model(f, manifest):
                updates_made = True
        
        # Always clean at end
        clean_scene()
        
        if updates_made:
            save_manifest(manifest)
            print("\n💾 Build manifest updated.")
        else:
            print("\n✨ Everything is up to date.")
            
        print("\n✅ DONE!")
else:
    print(f"❌ SOURCE DIR NOT FOUND: {SOURCE_DIR}")