"""What this machine can do. No branch on the model name."""
from __future__ import annotations

import importlib.util


def capability_flags() -> dict[str, bool]:
    return {
        "can_write_files": True,
        "can_run_python": True,
        "can_parse_xlsx": importlib.util.find_spec("openpyxl") is not None,
        "can_open_local_html": True,
        "can_render_browser": False,
        "can_export_pdf": False,
    }
