from pathlib import Path
import yaml

def load_yaml(path):
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))

def dump_yaml(path, data):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
