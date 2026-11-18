"""Проекты в автоматическом режиме анонимизации: workflow/_anonymizer/<проект>/.

«Туда»: оригинал юриста → документ-NN.anon.md общим словарём проекта.
«Обратно»: черновики/*.docx → готово/ с реальными данными в тексте; имя файла
остаётся с метками (restore_draft).

Состояние проекта (словарь движка, таблица имён, хэши restore) — один файл
_служебное/состояние.b64: base64 от JSON, чтобы случайный поиск по тексту не
находил в нём реальные названия. Оригиналы тоже хранятся под нейтральными
именами: исходное имя файла часто содержит название контрагента.
Пишет только единый watcher (один процесс под DaemonLock).
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

if str(Path(__file__).parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent))

import prepare as prep  # noqa: E402
from anonymizer import Anonymizer, restore_reverse  # noqa: E402
from project_layout import (  # noqa: E402,F401  (реэкспорт для watcher-переходника)
    AGENT_FILES, ANALYTIC, ANON_SUFFIX, DRAFTS, NOT_PROCESSED, ORIGINALS, READY,
    SERVICE, STATE_FILE, SUPPORTED, is_agent_file, is_project_name,
)
from quality import quality_report  # noqa: E402

STATE_VERSION = 1
# Метка движка: [КОМПАНИЯ_1], [ИНН_ЮЛ_1_10цифр] (тот же вид, что quality._PH).
PLACEHOLDER_RE = re.compile(r"\[[A-ZА-ЯЁ_]+_\d+[^\]\[]*\]")
_NEUTRAL_RE = re.compile(r"^документ-(\d+)$")
TEXT_DRAFT_EXTS = {".md", ".txt", ".docx"}
_BAD_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def find_projects(anon_root: Path) -> list[Path]:
    if not anon_root.is_dir():
        return []
    return sorted(p for p in anon_root.iterdir() if p.is_dir() and is_project_name(p.name))


def ensure_layout(project: Path) -> None:
    for sub in (Path(ANALYTIC), Path(DRAFTS), Path(READY),
                Path(SERVICE) / ORIGINALS, Path(SERVICE) / NOT_PROCESSED):
        (project / sub).mkdir(parents=True, exist_ok=True)


def _empty_state() -> dict:
    return {"version": STATE_VERSION, "dictionary": None, "names": {}, "restored": {}}


def load_state(project: Path) -> dict:
    path = project / SERVICE / STATE_FILE
    if not path.exists():
        return _empty_state()
    data = json.loads(base64.b64decode(path.read_bytes()).decode("utf-8"))
    if data.get("version") != STATE_VERSION:
        raise ValueError(f"неподдерживаемая версия состояния проекта: {data.get('version')}")
    return data


_REPLACE_ATTEMPTS = 10
_REPLACE_DELAY = 0.05  # сек; суммарно до ~0,5 с


def _replace_retrying(src: str, dst: Path) -> None:
    """os.replace с повтором: на Windows антивирус или индексатор на миг держит
    только что записанный файл состояния, и замена получает «Отказано в доступе».
    Только для служебных файлов проекта; оригиналы юриста так не переносятся —
    там блокировка (файл открыт в Word) означает «подождать до следующего прохода»."""
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == _REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(_REPLACE_DELAY)


def _atomic_write(path: Path, data: bytes) -> None:
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        _replace_retrying(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def save_state(project: Path, state: dict) -> None:
    path = project / SERVICE / STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(path, base64.b64encode(json.dumps(state, ensure_ascii=False).encode("utf-8")))


def reverse_mapping(state: dict) -> dict[str, str]:
    """Метка → оригинал: формат, который ждут prep._restore_text/_restore_docx.
    У метки ФИО может быть несколько падежных форм — восстанавливается первая."""
    dictionary = state.get("dictionary") or {}
    return restore_reverse(dictionary.get("map") or {})


def pending_originals(folder: Path) -> bool:
    """Есть ли кандидат-оригинал (дешёвая проверка до stable_files с ожиданием)."""
    if not folder.is_dir():
        return False
    return any(
        p.is_file() and p.suffix.lower() in SUPPORTED and not is_agent_file(p.name)
        and not p.name.startswith((".", "~$"))
        for p in folder.iterdir()
    )


def _unique(folder: Path, name: str) -> Path:
    target = folder / name
    n = 2
    while target.exists():
        target = folder / f"{Path(name).stem} ({n}){Path(name).suffix}"
        n += 1
    return target


def _next_document(state: dict) -> str:
    nums = [int(m.group(1)) for name in state["names"] if (m := _NEUTRAL_RE.match(name))]
    return f"документ-{max(nums, default=0) + 1:02d}"


def _docx_text(path: Path) -> str:
    import docx  # python-docx

    doc = docx.Document(str(path))
    parts = [p.text for p in doc.paragraphs]
    parts += [c.text for t in doc.tables for r in t.rows for c in r.cells]
    for section in doc.sections:
        for part in (section.header, section.footer):
            parts += [p.text for p in part.paragraphs]
    return "\n".join(parts)


def _draft_text(path: Path) -> str:
    if path.suffix.lower() == ".docx":
        return _docx_text(path)
    return path.read_text(encoding="utf-8", errors="replace")


def process_original(project: Path, path: Path, profile: str) -> dict:
    """Обезличить оригинал юриста общим словарём проекта (спека, п. 2)."""
    state = load_state(project)
    known = set((state["dictionary"] or {}).get("map", {}).values())

    # Черновик агента, оказавшийся в корне, — не оригинал: его место в черновики/.
    # Но только если в нём нет реальных данных: иначе это правленая юристом версия.
    if known and path.suffix.lower() in TEXT_DRAFT_EXTS:
        try:
            draft_text = _draft_text(path)
            found = set(PLACEHOLDER_RE.findall(draft_text))
            probe = Anonymizer.from_state(state["dictionary"],
                                          exclude_labels=prep.PROFILES["full"])
            clean = probe.anonymize(draft_text) == draft_text
        except Exception:  # noqa: BLE001 - нечитаемый файл разберёт обычный путь ниже
            found, clean = set(), False
        if found & known and clean:
            # os.replace, не shutil.move: у move при сбое переименования есть откат на
            # copy+unlink, а заблокированный файл тогда копировался бы на каждом проходе.
            try:
                os.replace(path, _unique(project / DRAFTS, path.name))
            except OSError:  # файл открыт в Word — следующий проход
                return {"status": "waiting", "document": None, "anon": None, "verdict": None}
            return {"status": "misplaced_draft", "document": None, "anon": None, "verdict": None}

    # Резерв номера, затем перенос оригинала под нейтральное имя: если файл открыт
    # в Word и не двигается, ничего не создано — следующий проход начнёт заново.
    document = _next_document(state)
    state["names"][document] = path.name
    save_state(project, state)
    target = _unique(project / SERVICE / ORIGINALS, document + path.suffix.lower())
    try:
        os.replace(path, target)  # не shutil.move: без отката на copy+unlink (копия оригинала)
    except OSError:
        del state["names"][document]
        save_state(project, state)
        return {"status": "waiting", "document": None, "anon": None, "verdict": None}

    anon_name = document + ANON_SUFFIX
    try:
        text = prep.to_markdown(target)
        if len(text.strip()) < prep.MIN_TEXT_CHARS:
            raise prep.PrepareError("не удалось извлечь текст")
        engine = Anonymizer.from_state(state["dictionary"],
                                       exclude_labels=prep.PROFILES[profile])
        masked = engine.anonymize(text)
        state["dictionary"] = engine.export_state()
        save_state(project, state)
        (project / anon_name).write_text(masked, encoding="utf-8")
    except Exception:  # noqa: BLE001 - любой сбой = «не обработано»: оригинал не остаётся в оригиналы/ без .anon.md
        (project / anon_name).unlink(missing_ok=True)
        os.replace(target, _unique(project / SERVICE / NOT_PROCESSED,
                                   document + path.suffix.lower()))
        return {"status": "failed", "document": document, "anon": None, "verdict": None}
    return {"status": "processed", "document": document, "anon": anon_name,
            "verdict": quality_report(masked)["verdict"]}


def reject_unsupported(project: Path, path: Path) -> str | None:
    """Неподдерживаемый формат: в не-обработано/ под нейтральным номером, имя — в состоянии.

    None — файл занят (открыт в программе), повтор на следующем проходе.
    """
    state = load_state(project)
    document = _next_document(state)
    state["names"][document] = path.name
    save_state(project, state)
    try:
        os.replace(path, _unique(project / SERVICE / NOT_PROCESSED,
                                 document + path.suffix.lower()))
    except OSError:
        del state["names"][document]
        save_state(project, state)
        return None
    return document


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_filename(name: str) -> str:
    """Имя файла из черновика приводим к допустимому для Windows: недопустимые
    символы («/», прямые кавычки) заменяем на «_»."""
    cleaned = _BAD_FILENAME.sub("_", name).rstrip(" .")
    return cleaned or "документ.docx"


def needs_restore(project: Path, draft: Path) -> bool:
    record = load_state(project)["restored"].get(draft.name)
    return record is None or record.get("source_hash") != file_hash(draft)


def restore_draft(project: Path, draft: Path) -> dict:
    """черновики/<имя>.docx → готово/<то же имя>.docx с реальными данными в тексте (спека, п. 3).

    Имя файла остаётся с метками (решение юриста 2026-10-08): восстановленное имя
    было бы видно агенту в любом листинге файлов. Юрист переименует файл при отправке.
    Правленый юристом результат не перезаписывается — пишется «… (2).docx».
    """
    state = load_state(project)
    mapping = reverse_mapping(state)
    ready_dir = project / READY
    ready_dir.mkdir(parents=True, exist_ok=True)
    wanted = safe_filename(draft.name)
    record = state["restored"].get(draft.name) or {}

    previous = ready_dir / record["ready_name"] if record.get("ready_name") else None
    if previous is not None and previous.exists() and file_hash(previous) == record.get("ready_hash"):
        target = previous  # наш прежний результат, юрист его не правил
    else:
        target = _unique(ready_dir, wanted)  # новый результат или правка юриста — не затираем

    fd, tmp_name = tempfile.mkstemp(prefix=".tmp-", suffix=".docx", dir=ready_dir)
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        prep._restore_docx(draft, mapping, tmp)
        try:
            os.replace(tmp, target)
        except PermissionError:  # результат открыт в Word — следующий проход
            return {"status": "waiting", "ready": None, "leftovers": 0}
    finally:
        if tmp.exists():
            tmp.unlink()

    leftovers = len(PLACEHOLDER_RE.findall(_docx_text(target)))
    state["restored"][draft.name] = {
        "source_hash": file_hash(draft),
        "ready_name": target.name,
        "ready_hash": file_hash(target),
        "restored_at": dt.datetime.now().isoformat(timespec="seconds"),
    }
    save_state(project, state)
    return {"status": "restored", "ready": target.name, "leftovers": leftovers}
