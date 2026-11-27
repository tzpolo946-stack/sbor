import json
import os
import tempfile
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import minecraft_launcher_lib

API_BASE = "".join(["ht", "tps:", "//a", "pi.", "mod", "rin", "th.", "com", "/v2"])
HEADERS = {"User-Agent": "PurpleLauncher/1.0 (PurpleVisuals)"}


def get_session():
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
    session.mount("https://", HTTPAdapter(max_retries=retries))
    session.headers.update(HEADERS)
    return session


def search_projects(query="", project_type="mod", mc_version="", loader=""):
    facets = [[f"project_type:{project_type}"]]

    clean_ver = mc_version.replace("PurpleVisuals (Fabric ", "").replace(")", "").strip()
    if clean_ver and "Загрузка" not in clean_ver:
        facets.append([f"versions:{clean_ver}"])

    if project_type in ("mod", "modpack") and loader in ("Fabric", "Forge", "NeoForge", "Quilt"):
        facets.append([f"categories:{loader.lower()}"])

    params = {
        "query": query,
        "facets": json.dumps(facets),
        "limit": 20,
        "index": "downloads" if not query else "relevance",
    }

    session = get_session()
    resp = session.get(f"{API_BASE}/search", params=params, timeout=25)
    resp.raise_for_status()
    return resp.json().get("hits", [])


def install_project(project_id, project_type, mc_version, loader, minecraft_dir, on_status=None):
    session = get_session()
    clean_ver = mc_version.replace("PurpleVisuals (Fabric ", "").replace(")", "").strip()
    params = {}
    if clean_ver and "Загрузка" not in clean_ver:
        params["game_versions"] = json.dumps([clean_ver])
    if project_type in ("mod", "modpack") and loader in ("Fabric", "Forge", "NeoForge", "Quilt"):
        params["loaders"] = json.dumps([loader.lower()])

    resp = session.get(f"{API_BASE}/project/{project_id}/version", params=params, timeout=25)
    resp.raise_for_status()
    versions = resp.json()

    if not versions:
        resp = session.get(f"{API_BASE}/project/{project_id}/version", timeout=25)
        resp.raise_for_status()
        versions = resp.json()

    if not versions:
        raise RuntimeError("Не найден подходящий файл для этой версии Minecraft")

    target_ver = versions[0]
    files = target_ver.get("files", [])
    primary_file = next((f for f in files if f.get("primary")), files[0] if files else None)
    if not primary_file:
        raise RuntimeError("Файл для скачивания отсутствует")

    url = primary_file["url"]
    filename = primary_file["filename"]

    if project_type == "modpack" or filename.endswith(".mrpack"):
        if on_status:
            on_status(f"Скачивание сборки {filename}...")
        tmp_path = os.path.join(tempfile.gettempdir(), filename)
        with session.get(url, stream=True, timeout=45) as r:
            r.raise_for_status()
            with open(tmp_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)

        if on_status:
            on_status("Распаковка и установка сборки Modrinth...")
        callback = {"setStatus": lambda t: on_status(t) if on_status else None}
        minecraft_launcher_lib.mrpack.install_mrpack(tmp_path, minecraft_dir, callback=callback)
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        return f"Сборка {filename} установлена! Выбери её в «Установленные»."

    folder_name = "resourcepacks" if project_type == "resourcepack" else "mods"
    dest_dir = os.path.join(minecraft_dir, folder_name)
    os.makedirs(dest_dir, exist_ok=True)
    dest_path = os.path.join(dest_dir, filename)

    if on_status:
        on_status(f"Скачивание {filename}...")
    with session.get(url, stream=True, timeout=45) as r:
        r.raise_for_status()
        with open(dest_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)

    return f"Установлено в {folder_name}: {filename}"