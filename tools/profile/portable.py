#!/usr/bin/env python3
"""Перенос пользовательского профиля между машинами.

move   — скопировать профиль на внешний путь (флешка / Яндекс.Диск) и
         запомнить его в <repo>/.profile-path.
export — упаковать профиль в zip (оффлайн-перенос).
import — распаковать профиль из zip.

Синхронизацию между машинами делает сам облачный диск; свой синк не пишется.
Исходный профиль при move не удаляется (безопасность) — удалить вручную.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import zipfile
from pathlib import Path

# Поддержка прямого запуска `python tools/.../<mod>.py` (repo root в sys.path)
if __name__ == "__main__" and __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _root = _Path(__file__).resolve().parents[2]
    if str(_root) not in _sys.path:
        _sys.path.insert(0, str(_root))

from tools.profile.profile_lib import profile_root, repo_root


def move_profile(dest: Path) -> Path:
    dest = Path(dest)
    src = profile_root()
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dest, dirs_exist_ok=True)
    (repo_root() / ".profile-path").write_text(str(dest), encoding="utf-8")
    return dest


def export_zip(dest_zip: Path) -> Path:
    dest_zip = Path(dest_zip)
    dest_zip.parent.mkdir(parents=True, exist_ok=True)
    src = profile_root()
    with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in src.rglob("*"):
            if f.is_file():
                zf.write(f, f.relative_to(src))
    return dest_zip


def import_zip(src_zip: Path, dest: Path | None = None) -> Path:
    target = Path(dest) if dest else profile_root()
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(src_zip) as zf:
        zf.extractall(target)
    return target


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Перенос профиля")
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("move"); m.add_argument("--dest", required=True)
    e = sub.add_parser("export"); e.add_argument("--dest", required=True)
    i = sub.add_parser("import"); i.add_argument("--src", required=True); i.add_argument("--dest")
    args = ap.parse_args(argv)
    if args.cmd == "move":
        d = move_profile(Path(args.dest))
        print(f"Профиль скопирован в {d}. Указатель .profile-path обновлён.")
        print("Исходную папку profile/ можно удалить вручную после проверки.")
    elif args.cmd == "export":
        print(f"Профиль упакован в {export_zip(Path(args.dest))}.")
    elif args.cmd == "import":
        t = import_zip(Path(args.src), Path(args.dest) if args.dest else None)
        print(f"Профиль распакован в {t}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
