import os
import shutil
import subprocess
import sys
import minecraft_launcher_lib

APPDATA_BASE = os.path.join(
    os.getenv("APPDATA", os.path.expanduser("~")) if os.name == "nt" else os.path.expanduser("~"),
    ".purplelauncher",
)
MINECRAFT_DIR = os.path.join(APPDATA_BASE, "game_files")
os.makedirs(MINECRAFT_DIR, exist_ok=True)

CUSTOM_PROFILE_NAME = "PurpleVisuals (Fabric 26.2)"
TARGET_MC_VERSION = "26.2"


def get_resource_path(relative_path):
    base_path = getattr(sys, "_MEIPASS", os.path.abspath("."))
    return os.path.join(base_path, relative_path)


def sync_purple_mods(on_status=None):
    source_mods = get_resource_path(os.path.join("runtime", "mods"))
    target_mods = os.path.join(MINECRAFT_DIR, "mods")
    os.makedirs(target_mods, exist_ok=True)

    if not os.path.exists(source_mods):
        return

    if on_status:
        on_status("Синхронизация визуалов PurpleVisuals...")

    valid_jars = {f for f in os.listdir(source_mods) if f.endswith(".jar")}

    for existing in os.listdir(target_mods):
        if existing.endswith(".jar") and existing not in valid_jars:
            try:
                os.remove(os.path.join(target_mods, existing))
            except Exception:
                pass

    for filename in valid_jars:
        src_file = os.path.join(source_mods, filename)
        dst_file = os.path.join(target_mods, filename)
        if not os.path.exists(dst_file) or os.path.getsize(src_file) != os.path.getsize(dst_file):
            shutil.copy2(src_file, dst_file)


def get_versions_by_loader(loader_type="Vanilla"):
    if loader_type == "Установленные":
        installed = [CUSTOM_PROFILE_NAME]
        try:
            for v in minecraft_launcher_lib.utils.get_installed_versions(MINECRAFT_DIR):
                if v["id"] not in installed:
                    installed.append(v["id"])
        except Exception:
            pass
        return installed

    versions = [CUSTOM_PROFILE_NAME] if loader_type == "Vanilla" else []
    try:
        all_mc = minecraft_launcher_lib.utils.get_version_list()

        if loader_type == "Vanilla":
            versions.extend([v["id"] for v in all_mc])

        elif loader_type == "Fabric":
            raw_fabric = minecraft_launcher_lib.fabric.get_all_minecraft_versions()
            supported = {item["version"] if isinstance(item, dict) else item for item in raw_fabric}
            versions.extend([v["id"] for v in all_mc if v["id"] in supported])

        elif loader_type == "Quilt":
            raw_quilt = minecraft_launcher_lib.quilt.get_all_minecraft_versions()
            supported = {item["version"] if isinstance(item, dict) else item for item in raw_quilt}
            versions.extend([v["id"] for v in all_mc if v["id"] in supported])

        elif loader_type == "Forge":
            legacy_skip = {
                "1.1", "1.2.1", "1.2.2", "1.2.3", "1.2.4", "1.2.5",
                "1.3.2", "1.4.0", "1.4.1", "1.4.2", "1.4.3", "1.4.4", "1.4.5", "1.4.6", "1.4.7",
            }
            forge_list = minecraft_launcher_lib.forge.list_forge_versions()
            supported = {fv.split("-")[0] for fv in forge_list} - legacy_skip
            versions.extend([v["id"] for v in all_mc if v["id"] in supported])

        elif loader_type == "NeoForge":
            all_neo = minecraft_launcher_lib.neoforge.list_neoforge_versions()
            for v in all_mc:
                if v["type"] != "release":
                    continue
                vid = v["id"]
                if vid in ("1.20", "1.20.1"):
                    continue
                prefix = vid.removeprefix("1.")
                if any(nv == prefix or nv.startswith(prefix + ".") or nv.startswith(prefix + "-") for nv in all_neo):
                    versions.append(vid)

    except Exception:
        versions.extend(["26.2", "1.21.11", "1.21.4", "1.21.1", "1.20.4", "1.20.1", "1.16.5", "1.12.2"])
    return versions


def find_installed_id(mc_version, keyword):
    for v in minecraft_launcher_lib.utils.get_installed_versions(MINECRAFT_DIR):
        vid = v["id"].lower()
        if keyword in vid and mc_version.lower() in vid:
            return v["id"]
    return None


def start_minecraft(selected_version, loader_type="Vanilla", username="Player", ram_gb=4, on_status=None, on_progress=None):
    max_val = 100

    def set_status(text):
        if on_status:
            on_status(text)

    def set_max(new_max):
        nonlocal max_val
        max_val = new_max if new_max > 0 else 100

    def set_progress(current):
        if on_progress:
            on_progress(min(current / max_val, 1.0))

    callback = {"setStatus": set_status, "setProgress": set_progress, "setMax": set_max}
    launch_id = selected_version

    if selected_version == CUSTOM_PROFILE_NAME:
        set_status("Проверка Fabric 26.2...")
        fabric_id = find_installed_id(TARGET_MC_VERSION, "fabric")
        if not fabric_id:
            set_status("Установка PurpleVisuals (Fabric 26.2)...")
            minecraft_launcher_lib.fabric.install_fabric(TARGET_MC_VERSION, MINECRAFT_DIR, callback=callback)
            fabric_id = find_installed_id(TARGET_MC_VERSION, "fabric")
        sync_purple_mods(on_status=set_status)
        launch_id = fabric_id or TARGET_MC_VERSION

    elif loader_type == "Установленные":
        launch_id = selected_version

    elif loader_type == "Fabric":
        fabric_id = find_installed_id(selected_version, "fabric")
        if not fabric_id:
            set_status(f"Установка Fabric {selected_version}...")
            minecraft_launcher_lib.fabric.install_fabric(selected_version, MINECRAFT_DIR, callback=callback)
            fabric_id = find_installed_id(selected_version, "fabric")
        launch_id = fabric_id

    elif loader_type == "Quilt":
        quilt_id = find_installed_id(selected_version, "quilt")
        if not quilt_id:
            set_status(f"Установка Quilt {selected_version}...")
            minecraft_launcher_lib.quilt.install_quilt(selected_version, MINECRAFT_DIR, callback=callback)
            quilt_id = find_installed_id(selected_version, "quilt")
        launch_id = quilt_id

    elif loader_type == "Forge":
        forge_id = find_installed_id(selected_version, "forge")
        if not forge_id:
            forge_ver = minecraft_launcher_lib.forge.find_forge_version(selected_version)
            if not forge_ver:
                raise RuntimeError(f"Forge для {selected_version} не найден")
            set_status(f"Установка Forge {forge_ver}...")
            minecraft_launcher_lib.forge.install_forge_version(forge_ver, MINECRAFT_DIR, callback=callback)
            forge_id = find_installed_id(selected_version, "forge")
        launch_id = forge_id

    elif loader_type == "NeoForge":
        neo_id = find_installed_id(selected_version, "neoforge")
        if not neo_id:
            set_status(f"Установка NeoForge {selected_version}...")
            all_neo = minecraft_launcher_lib.neoforge.list_neoforge_versions()
            prefix = selected_version.removeprefix("1.")
            matched = [nv for nv in all_neo if nv == prefix or nv.startswith(prefix + ".") or nv.startswith(prefix + "-")]
            if not matched:
                raise RuntimeError(f"NeoForge для {selected_version} не найден")
            latest_neo = matched.pop(0)
            minecraft_launcher_lib.neoforge.install_neoforge_version(latest_neo, MINECRAFT_DIR, callback=callback)
            neo_id = find_installed_id(selected_version, "neoforge")
        launch_id = neo_id

    else:
        set_status(f"Проверка файлов {selected_version}...")
        minecraft_launcher_lib.install.install_minecraft_version(selected_version, MINECRAFT_DIR, callback=callback)
        launch_id = selected_version

    options = {
        "username": username,
        "uuid": "00000000-0000-0000-0000-000000000000",
        "token": "",
        "jvmArguments": [f"-Xmx{ram_gb}G", "-Xms1G"],
    }

    set_status(f"Запуск {launch_id}...")
    command = minecraft_launcher_lib.command.get_minecraft_command(launch_id, MINECRAFT_DIR, options)
    subprocess.Popen(command)
