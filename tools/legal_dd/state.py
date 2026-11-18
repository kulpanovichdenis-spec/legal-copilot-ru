from pathlib import Path
from .utils import read_json, write_json

STATE_FILES = {
    "assets": [], "parties": [], "evidence": [], "facts": [], "checks": [],
    "findings": [], "decisions": [], "review-queue": [], "document-families": [], "contract-inputs": {}
}

def load_state(project_root, name):
    return read_json(Path(project_root)/"state"/f"{name}.json", STATE_FILES[name])

def save_state(project_root, name, value):
    write_json(Path(project_root)/"state"/f"{name}.json", value)

def upsert(items, key, value):
    target=value.get(key)
    for i,item in enumerate(items):
        if item.get(key)==target:
            items[i]=value
            return items
    items.append(value)
    return items
