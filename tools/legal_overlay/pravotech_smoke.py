"""Safe, file-based Pravotech capability smoke with an explicit paid-call gate."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from .registry import ProviderRegistry


MAX_MESSAGE_BYTES = 64 * 1024


def load_message(path: Path) -> tuple[str, dict[str, Any]]:
    raw = path.read_bytes()
    if not raw or len(raw) > MAX_MESSAGE_BYTES:
        raise ValueError("message file must contain between 1 byte and 64 KiB")
    try:
        message = raw.decode("utf-8-sig").strip()
    except UnicodeDecodeError as exc:
        raise ValueError("message file must be valid UTF-8") from exc
    if not message:
        raise ValueError("message file is empty")
    if "\ufffd" in message or "???" in message:
        raise ValueError("message contains signs of encoding damage")
    cyrillic_chars = sum("\u0400" <= char <= "\u04ff" for char in message)
    if cyrillic_chars < 20:
        raise ValueError("message must contain at least 20 Cyrillic characters")
    return message, {
        "status": "utf8_preflight_passed",
        "path": str(path.resolve()),
        "bytes": len(raw),
        "characters": len(message),
        "cyrillic_characters": cyrillic_chars,
        "question_marks": message.count("?"),
        "sha256": hashlib.sha256(message.encode("utf-8")).hexdigest(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("message_file", type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm-paid-call", action="store_true")
    args = parser.parse_args(argv)

    message, preflight = load_message(args.message_file)
    print(json.dumps(preflight, ensure_ascii=False, indent=2))
    if not args.execute:
        return 0
    if not args.confirm_paid_call:
        parser.error("--execute requires --confirm-paid-call")

    adapter = ProviderRegistry.from_default_config().adapter("pravotech-consultant")
    result = adapter.call_tool(
        "consultation",
        {"message": message, "_confirm_paid_call": True},
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
