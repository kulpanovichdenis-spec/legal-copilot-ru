#!/usr/bin/env python3
"""Страховка проектов анонимайзера (спека 2026-10-07, п. 5.2).

Хук перед действием агента: в workflow/_anonymizer/<проект>/ агенту можно
открыть только *.anon.md, case-context.md, deadlines.yaml, matter-timeline.yaml
в корне проекта и файлы в черновики/. Оригиналы, _служебное/, готово/ и прочие
подпапки закрыты. Решение — по тексту пути или команды, без чтения файлов.

    python tools/pre_anonymize/project_guard.py --runner claude|codex|cursor-read|cursor-shell

Не видит путь, собранный внутри кода скрипта, и документ, переданный в чат:
там действует только правило CLAUDE.md.
"""
from __future__ import annotations

import argparse
import json
import posixpath
import re
import sys
from dataclasses import dataclass
from pathlib import Path

if str(Path(__file__).parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent))

from project_layout import ANON_SUFFIX, DRAFTS, is_agent_file, is_project_name  # noqa: E402

DENY_TEXT = (
    "В проекте анонимайзера агенту доступны только *.anon.md, case-context.md, "
    "deadlines.yaml, matter-timeline.yaml в корне проекта и файлы в черновики/. "
    "Оригиналы, _служебное/ и готово/ закрыты (CLAUDE.md, «Конфиденциальность»). "
    "Если нужного документа нет среди *.anon.md, он ещё не обезличен: сообщите "
    "юристу, что нужно проверить watcher."
)
FAIL_TEXT = (
    "Страховка анонимайзера не смогла проверить путь, поэтому доступ к проекту "
    "закрыт. Сообщите юристу."
)
CD_TEXT = ("Не переходите в папку проекта анонимайзера (cd): укажите полные пути "
           "к *.anon.md или черновики/.")
INSIDE_TEXT = ("Команда запущена изнутри папки проекта анонимайзера. Запустите её из "
               "корня репозитория и укажите полные пути к *.anon.md или черновики/.")

# Путевое упоминание контейнера: «_anonymizer» + разделитель пути, либо
# «workflow<разделитель>_anonymizer» (в т. ч. голый контейнер — за ним конец токена).
# Точки после сегмента — Windows-алиас (`_anonymizer.`). «_anonymizer» без пути
# (шаблон поиска, текст сообщения) упоминанием пути не считается.
_ANON_PATH = re.compile(
    r"(?<![\w])_anonymizer\.*[\\/]+"
    r"|(?<![\w.-])workflow\.*[\\/]+_anonymizer\.*(?:[\\/]+|(?=$|[\s\"'`;|&<>()]))",
    re.IGNORECASE)
# Читающие/копирующие глаголы и флаги рекурсии: запрещены на голой папке проекта/контейнере.
# Запуск скриптов (python/py) не входит: путь, собранный внутри кода, — остаточный риск спеки.
_READ_VERBS = re.compile(
    r"(?<![\w.-])(grep|egrep|rg|findstr|select-string|sls|cat|type|gc|get-content|more|less|"
    r"head|tail|copy-item|cp|copy|xcopy|robocopy|move-item|mv|move|tar|compress-archive|"
    r"zip|7z)(?![\w-])|(?<!\S)(-r|-R|--recursive|-recurse|/s)(?!\S)",
    re.IGNORECASE)
# Границы инструкций; конвейер `|` — часть одной инструкции.
_STATEMENT_BREAK = re.compile(r";|&&|\|\||\n")
# Текст документации — только по однозначным маркерам шаблона: `<проект>`, `[^/]+`.
# Просто `[]{}$` — обычные символы масок и возможных имён папок.
_DOC_TEXT = re.compile(r"[<>]|\[\^")
# Голый контейнер `_anonymizer` как целый токен (в т. ч. `./_anonymizer`).
_BARE_ANON = re.compile(
    r"(?:(?<=^)|(?<=[\s\"'`;|&(]))(?:\.[\\/])*_anonymizer\.*(?=$|[\s\"'`;|&()])",
    re.IGNORECASE)
# Маска с расширением (`*.py`, `*.{md,txt}`): каталог workflow не захватывает.
_EXT_GLOB = re.compile(r"\.[A-Za-z0-9{},]{1,10}$")
_CD = re.compile(r"(?:^|[\s;&|(])(?:cd|chdir|pushd|sl|set-location|push-location)\s+",
                 re.IGNORECASE)
_COMMAND_BREAK = re.compile(r"[;&|\n]")


@dataclass(frozen=True)
class Decision:
    allow: bool
    reason: str = ""


ALLOW = Decision(True)


def _deny(project_dir: str | None = None) -> Decision:
    reason = DENY_TEXT
    if project_dir:
        try:
            names = sorted(p.name for p in Path(project_dir).glob("*" + ANON_SUFFIX))
        except OSError:
            names = []
        if names:
            shown = ", ".join(names[:20]) + (" …" if len(names) > 20 else "")
            reason += f" Доступно сейчас: {shown}."
    return Decision(False, reason)


def _normalized(path: str, cwd: str | None) -> tuple[str, list[str]]:
    p = path.replace("\\", "/")
    if cwd and not (p.startswith("/") or re.match(r"^[A-Za-z]:", p)):
        p = cwd.replace("\\", "/").rstrip("/") + "/" + p
    norm = posixpath.normpath(p)
    lead = "/" if norm.startswith("/") else ""
    return lead, _clean_segments(norm.split("/"))


def _clean_segments(segments: list[str]) -> list[str]:
    """Windows открывает `имя.` и `имя ` как `имя`: обрезаем хвостовые точки и пробелы."""
    out = []
    for s in segments:
        if s not in (".", ".."):
            s = s.rstrip(". ")
        if s and s != ".":
            out.append(s)
    return out


def _locate(path: str, cwd: str | None) -> tuple[str, str, list[str]] | None:
    """(папка проекта, имя проекта, остаток пути) для пути внутри проекта."""
    lead, parts = _normalized(path, cwd)
    low = [s.lower() for s in parts]
    for i in range(1, len(parts) - 1):
        if low[i] == "_anonymizer" and low[i - 1] == "workflow" and is_project_name(parts[i + 1]):
            return lead + "/".join(parts[: i + 2]), parts[i + 1], parts[i + 2:]
    return None


def _is_container(path: str, cwd: str | None) -> bool:
    _lead, parts = _normalized(path, cwd)
    low = [s.lower() for s in parts]
    return len(low) >= 2 and low[-1] == "_anonymizer" and low[-2] == "workflow"


def _inside_container(path: str, cwd: str | None) -> bool:
    """Сам контейнер workflow/_anonymizer или любой путь внутри него."""
    _lead, parts = _normalized(path, cwd)
    low = [s.lower() for s in parts]
    return any(low[i] == "_anonymizer" and low[i - 1] == "workflow"
               for i in range(1, len(low)))


def _allowed_rest(rest: list[str]) -> bool:
    if not rest:
        return False
    if rest[0].lower() == DRAFTS:
        return True
    return len(rest) == 1 and is_agent_file(rest[0])


def _anon_glob(glob: str | None) -> bool:
    return bool(glob) and not glob.startswith("!") and glob.lower().endswith(ANON_SUFFIX)


def _ends_with_workflow(path: str | None, cwd: str | None = None) -> bool:
    if not path:
        return False
    _lead, parts = _normalized(path, cwd)
    return bool(parts) and parts[-1].lower() == "workflow"


def _search_root_above_container(path: str | None, cwd: str | None) -> bool:
    """Корень поиска — workflow или выше него (на диске под ним есть контейнер)."""
    lead, parts = _normalized(path or ".", cwd)
    if parts and parts[-1].lower() == "workflow":
        return True
    try:
        return (Path(lead + "/".join(parts)) / "workflow" / "_anonymizer").is_dir()
    except OSError:
        return False


def _extension_glob(glob: str) -> bool:
    return bool(_EXT_GLOB.search(glob.replace("\\", "/").rsplit("/", 1)[-1]))


def decide_read(path: str, cwd: str | None) -> Decision:
    located = _locate(path, cwd)
    if located is None:
        return ALLOW
    project_dir, _project, rest = located
    if not rest:
        return ALLOW  # голая папка Read-ом не читается; файл в контейнере — не файл проекта
    return ALLOW if _allowed_rest(rest) else _deny(project_dir)


def decide_search(path: str | None, glob: str | None, cwd: str | None) -> Decision:
    if glob and "_anonymizer" in glob.lower() and not _anon_glob(glob):
        return _deny()  # --glob перекрывает .gitignore
    if glob and not _extension_glob(glob) and _search_root_above_container(path, cwd):
        return _deny()  # маска без расширения (`*`, `**/*`) захватывает каталог контейнера
    target = path or "."
    if _is_container(target, cwd):
        return ALLOW if _anon_glob(glob) else _deny()
    located = _locate(target, cwd)
    if located is None:
        return ALLOW
    project_dir, _project, rest = located
    if not rest:
        return ALLOW if _anon_glob(glob) else _deny(project_dir)
    return ALLOW if _allowed_rest(rest) else _deny(project_dir)


def _open_quote(text: str) -> str | None:
    quote = None
    for ch in text:
        if quote is None and ch in "\"'":
            quote = ch
        elif ch == quote:
            quote = None
    return quote


def _path_tail(command: str, end: int) -> str:
    """Остаток пути после «_anonymizer/» до конца аргумента."""
    quote = _open_quote(command[:end])
    out: list[str] = []
    for ch in command[end:]:
        if quote:
            if ch == quote:
                quote = None  # закрывающая кавычка, токен продолжается
            else:
                out.append(ch)
        elif ch in "\"'":
            quote = ch  # открывающая кавычка склеивается с токеном
        elif ch.isspace() or ch in ";|&<>()":
            break
        else:
            out.append(ch)
    return "".join(out)


def _is_cd_target(command: str, start: int) -> bool:
    """Путь в позиции start — аргумент cd/Set-Location той же команды."""
    return any(not _COMMAND_BREAK.search(command, m.end(), start)
               for m in _CD.finditer(command, 0, start))


def _statement_at(command: str, pos: int) -> str:
    """Инструкция (между `;`, `&&`, `||`, переводом строки), содержащая позицию."""
    start = 0
    for m in _STATEMENT_BREAK.finditer(command):
        if _open_quote(command[:m.start()]):
            continue  # разделитель внутри кавычек
        if m.start() >= pos:
            return command[start:m.start()]
        start = m.end()
    return command[start:]


def _container_mentions(command: str, cwd: str | None) -> list[re.Match]:
    """Путевые упоминания контейнера + голый `_anonymizer` (цель cd или cwd = workflow)."""
    found = list(_ANON_PATH.finditer(command))
    at_workflow = _ends_with_workflow(cwd)
    found += [m for m in _BARE_ANON.finditer(command)
              if at_workflow or _is_cd_target(command, m.start())]
    return found


def decide_command(command: str, cwd: str | None) -> Decision:
    if cwd and _inside_container(cwd, None):
        return Decision(False, INSIDE_TEXT)
    for m in _container_mentions(command, cwd):
        tail = posixpath.normpath(_path_tail(command, m.end()).replace("\\", "/"))
        if tail == ".." or tail.startswith("../"):
            continue  # вышли выше контейнера: не путь в проект
        segments = _clean_segments(tail.split("/"))
        if segments and _DOC_TEXT.search(segments[0]):
            continue  # текст документации (<проект>, [^/]+): не путь
        if _is_cd_target(command, m.start()):
            return Decision(False, CD_TEXT)  # cd в контейнер или куда-либо внутри него
        reads = _READ_VERBS.search(_statement_at(command, m.start()))
        if not segments:
            # сам контейнер: листинг проектов можно, читать и копировать — нельзя
            if reads:
                return _deny()
            continue
        project, rest = segments[0], segments[1:]
        if not is_project_name(project):
            continue  # _inbox/_ready (разовый режим)
        if not rest:
            # папка проекта: листинг можно (имена нейтральные), читать и копировать — нельзя
            if reads:
                return _deny()
            continue
        if not _allowed_rest(rest):
            return _deny()
    return ALLOW


RUNNERS = ("claude", "codex", "cursor-read", "cursor-shell")


def _guarded(raw: str, fn, *args) -> Decision:
    try:
        return fn(*args)
    except Exception:  # noqa: BLE001 - политика сбоя: проект закрыт, остальное открыто
        return Decision(False, FAIL_TEXT) if "_anonymizer" in raw.lower() else ALLOW


def decide_for(runner: str, data: dict, raw: str) -> Decision:
    tool_input = data.get("tool_input") or {}
    cwd = data.get("cwd")
    if runner == "claude":
        tool = data.get("tool_name")
        if tool == "Read":
            return _guarded(raw, decide_read, tool_input.get("file_path") or "", cwd)
        if tool == "Grep":
            return _guarded(raw, decide_search, tool_input.get("path"),
                            tool_input.get("glob"), cwd)
        if tool in ("Bash", "PowerShell"):
            return _guarded(raw, decide_command, tool_input.get("command") or "", cwd)
        return ALLOW
    if runner == "codex":
        command = tool_input.get("command")
        if isinstance(command, list):
            command = " ".join(str(part) for part in command)
        return _guarded(raw, decide_command, command, cwd) if command else ALLOW
    if runner == "cursor-read":
        return _guarded(raw, decide_read, data.get("file_path") or "", None)
    if runner == "cursor-shell":
        return _guarded(raw, decide_command, data.get("command") or "", cwd)
    raise ValueError(f"неизвестный раннер: {runner}")


def render(runner: str, decision: Decision) -> str | None:
    if runner in ("claude", "codex"):
        if decision.allow:
            return None
        return json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": decision.reason,
        }}, ensure_ascii=False)
    if decision.allow:
        return json.dumps({"permission": "allow"})
    return json.dumps({
        "permission": "deny",
        "user_message": "Страховка анонимайзера: доступ к файлу проекта закрыт.",
        "agent_message": decision.reason,
    }, ensure_ascii=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Страховка проектов анонимайзера")
    parser.add_argument("--runner", required=True, choices=RUNNERS)
    args = parser.parse_args(argv)
    raw = sys.stdin.buffer.read().decode("utf-8-sig", errors="replace")
    try:
        data = json.loads(raw) if raw.strip() else {}
        if not isinstance(data, dict):
            raise ValueError("ожидался JSON-объект")
    except ValueError:
        data = None
    if data is None:
        decision = Decision(False, FAIL_TEXT) if "_anonymizer" in raw.lower() else ALLOW
    else:
        decision = _guarded(raw, decide_for, args.runner, data, raw)
    out = render(args.runner, decision)
    if out:
        sys.stdout.buffer.write(out.encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
