#!/usr/bin/env python3
"""Создание и версионирование досье проверки контрагента.

Санитизация имени, раскладка папки досье, версионирование (_02/_03),
пути подпапок и целевого DOCX. Юридический анализ — в SKILL.md; здесь
только механика файловой системы.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# Имя папки-корня досье под workflow/. Настраивается env CV_DOSSIER_DIR
# Старые имена остаются алиасами поиска; новый канонический корень — служебный.
DEFAULT_DOSSIER_SUBDIR = "_counterparty"


def dossier_subdir() -> str:
    return os.environ.get("CV_DOSSIER_DIR", "").strip() or DEFAULT_DOSSIER_SUBDIR


# Значение на импорт (обратная совместимость); актуальное имя — dossier_subdir().
WORKFLOW_SUBDIR = dossier_subdir()

# Существующий корень досье распознаётся терпимо к имени папки (префиксы
# "! ", "_", регистр, ё/е, ед./мн. число): старые русские имена и
# `_counterparty` считаются одним корнем, чтобы не плодить параллельные досье.
_ROOT_ALIASES = {
    "counterparty",
    "проверка контрагентов",
    "проверка контрагента",
    "проверки контрагентов",
}


def _norm_root_name(name: str) -> str:
    s = name.strip().lower().lstrip("!_-#. ").replace("ё", "е")
    return re.sub(r"[^a-zа-я0-9]+", " ", s).strip()


def find_dossier_root(workflow_dir) -> "Path | None":
    """Найти существующий корень досье под workflow/ (терпимо к имени папки).

    Приоритет — точное совпадение с настроенным именем; иначе — папка, чьё
    нормализованное имя входит в `_ROOT_ALIASES` (включая старые русские имена).
    None, если ничего похожего нет.
    """
    workflow_dir = Path(workflow_dir)
    if not workflow_dir.is_dir():
        return None
    exact = workflow_dir / dossier_subdir()
    if exact.is_dir():
        return exact
    for p in sorted(workflow_dir.iterdir()):
        if p.is_dir() and _norm_root_name(p.name) in _ROOT_ALIASES:
            return p
    return None


SUBFOLDERS = {
    "registry": "01_Реестр",
    "authority": "02_Полномочия",
    "financial": "03_Финансы",
    "litigation": "04_Суды",
    "insolvency": "05_Банкротство_Федресурс",
    "enforcement": "06_Исполнительные_производства",
    "sanctions": "07_Санкции",
    "regulatory": "08_Лицензии_Регуляторика",
    "other": "09_Прочее",
}

_FORBIDDEN_RE = re.compile(r'[<>:"/\\|?*]')          # запрещённые для ФС
_QUOTES_RE = re.compile(r'[«»""„‟"''\'()]')  # типографика/кавычки/скобки


class CaseFolderError(Exception):
    pass


def sanitize_name(name: str) -> str:
    if not name or not name.strip():
        raise CaseFolderError("пустое наименование контрагента")
    s = _QUOTES_RE.sub(" ", name.strip())
    s = _FORBIDDEN_RE.sub(" ", s)
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_.")
    if not s:
        raise CaseFolderError(f"после санитизации имя пустое: {name!r}")
    return s


def build_folder_name(name: str, date: dt.date) -> str:
    return f"{date:%Y.%m.%d}_{sanitize_name(name)}"


def file_name(name: str, date: dt.date, doc_type: str, ext: str) -> str:
    return f"{date:%Y.%m.%d}_{sanitize_name(name)}_{sanitize_name(doc_type)}.{ext.lstrip('.')}"


def _default_base() -> Path:
    """Корень досье в workflow/ основного чекаута (в т. ч. из worktree).

    Если под workflow/ уже есть корень досье (в т. ч. под другим именем,
    включая прежнее `! проверка контрагента`) — переиспользуется он, чтобы не плодить
    параллельную папку и чтобы RECHECK/COMPARE находил прежние досье.
    """
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        workflow_dir = Path(out).parent / "workflow"
    except Exception:
        workflow_dir = Path.cwd() / "workflow"
    existing = find_dossier_root(workflow_dir)
    return existing if existing is not None else (workflow_dir / dossier_subdir())


def create_case(name, *, date=None, base=None, continue_same=False) -> dict:
    date = date or dt.date.today()
    base = Path(base) if base is not None else _default_base()
    base.mkdir(parents=True, exist_ok=True)

    folder = build_folder_name(name, date)
    target = base / folder
    reused = target.exists() and continue_same
    if target.exists() and not continue_same:
        n = 2
        while (base / f"{folder}_{n:02d}").exists():
            n += 1
        folder = f"{folder}_{n:02d}"
        target = base / folder

    target.mkdir(parents=True, exist_ok=True)
    docx_name = f"{folder}_Лист_проверки.docx"
    return {
        "name": name,
        "folder": folder,
        "base": str(base),
        "root": str(target),
        "subfolders": {k: str(target / v) for k, v in SUBFOLDERS.items()},
        "report_docx": str(target / docx_name),
        "created": not reused,
    }


def ensure_subfolder(case: dict, key: str) -> str:
    if key not in SUBFOLDERS:
        raise CaseFolderError(f"неизвестная подпапка: {key}")
    p = Path(case["subfolders"][key])
    p.mkdir(parents=True, exist_ok=True)
    return str(p)


def selftest() -> int:
    import tempfile
    ok = 0
    with tempfile.TemporaryDirectory() as td:
        assert sanitize_name('ООО «Ромашка»') == "ООО_Ромашка", sanitize_name('ООО «Ромашка»')
        assert sanitize_name('A/B:C*?D') == "A_B_C_D", sanitize_name('A/B:C*?D')
        ok += 1
        try:
            sanitize_name("   ")
            raise AssertionError("пустое имя должно падать")
        except CaseFolderError:
            ok += 1

        d = dt.date(2026, 8, 28)
        assert build_folder_name("Ромашка ООО", d) == "2026.08.28_Ромашка_ООО"
        assert file_name("Ромашка", d, "ЕГРЮЛ", "pdf") == "2026.08.28_Ромашка_ЕГРЮЛ.pdf"
        ok += 1

        c1 = create_case("Ромашка ООО", date=d, base=td)
        assert Path(c1["root"]).is_dir() and c1["created"] is True
        assert c1["report_docx"].endswith("2026.08.28_Ромашка_ООО_Лист_проверки.docx")
        ok += 1

        c2 = create_case("Ромашка ООО", date=d, base=td)          # тот же день, новая проверка
        assert c2["folder"].endswith("_02"), c2["folder"]
        ok += 1

        c3 = create_case("Ромашка ООО", date=d, base=td, continue_same=True)
        assert c3["root"] == c1["root"] and c3["created"] is False   # продолжение той же
        ok += 1

        sub = ensure_subfolder(c1, "registry")
        assert Path(sub).is_dir() and sub.endswith("01_Реестр")
        try:
            ensure_subfolder(c1, "нет-такой")
            raise AssertionError("неизвестная подпапка должна падать")
        except CaseFolderError:
            ok += 1

        # base в карточке дела совпадает с переданным корнем
        assert c1["base"] == str(Path(td)), c1["base"]
        ok += 1

        # find_dossier_root: терпимое распознавание существующего корня по имени
        wf = Path(td) / "wf"
        (wf / "! проверка контрагента").mkdir(parents=True)
        assert find_dossier_root(wf) == wf / "! проверка контрагента", find_dossier_root(wf)
        (wf / "_counterparty").mkdir()
        assert find_dossier_root(wf) == wf / "_counterparty"   # точное имя в приоритете
        assert find_dossier_root(Path(td) / "нет-папки") is None
        ok += 1

        # _norm_root_name: старое русское имя и `_counterparty` — один корень
        assert _norm_root_name("! проверка контрагента") in _ROOT_ALIASES
        assert _norm_root_name("Проверка Контрагентов") in _ROOT_ALIASES
        assert _norm_root_name("_counterparty") in _ROOT_ALIASES
        assert _norm_root_name("Договоры 2026") not in _ROOT_ALIASES
        ok += 1
    print(f"SELFTEST OK: {ok} проверок пройдено")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("create")
    p.add_argument("--name", required=True)
    p.add_argument("--date")             # YYYY-MM-DD
    p.add_argument("--base")
    p.add_argument("--continue", dest="cont", action="store_true")
    sub.add_parser("selftest")
    return ap


def run(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "selftest":
        return selftest()
    try:
        date = dt.date.fromisoformat(args.date) if args.date else None
    except ValueError as e:
        raise CaseFolderError(f"неверный --date (ожидается YYYY-MM-DD): {args.date}") from e
    case = create_case(args.name, date=date, base=args.base, continue_same=args.cont)
    print(json.dumps(case, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    try:
        return run(sys.argv[1:])
    except CaseFolderError as e:
        print(f"ОШИБКА: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
