"""Самодостаточный HTML-каталог: данные и картинки встроены, внешних ресурсов нет."""
from __future__ import annotations

import base64
import json
from pathlib import Path

from .build_index import DOC_TYPE_LABELS

TEMPLATE = Path(__file__).with_name("templates") / "catalog.html"
PLACEHOLDER = "/*__REGISTRY_DATA__*/null"
_MIME = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif"}


def _data_uri(path: str, data: bytes) -> str:
    mime = _MIME.get(path.rsplit(".", 1)[-1].lower())
    if mime is None:
        raise ValueError(f"неподдерживаемый формат изображения: {path}")
    return f"data:{mime};base64," + base64.b64encode(data).decode("ascii")


def render_catalog(registry: dict, images: dict[str, bytes]) -> str:
    payload = {
        "source": registry["source"],
        "stats": registry["stats"],
        "warnings": registry["warnings"],
        "pending": registry.get("pending") or [],
        "marks": registry["marks"],
        "doc_type_labels": DOC_TYPE_LABELS,
        "images": {path: _data_uri(path, data) for path, data in images.items()},
    }
    data = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
    template = TEMPLATE.read_text(encoding="utf-8")
    if PLACEHOLDER not in template:
        raise RuntimeError("в шаблоне каталога нет места для данных")
    return template.replace(PLACEHOLDER, data)
