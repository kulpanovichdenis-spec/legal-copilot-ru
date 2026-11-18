# -*- coding: utf-8 -*-
"""Хранилище корпоративного слоя: yaml-файлы компании, идентификаторы, аудит.

Каталог компании: <entities>/<slug>/ с файлами sources.yaml, rules.yaml,
profile.yaml, audit.jsonl и рабочей папкой _work/ (страницы PNG и OCR-текст,
регенерируемые). Аудит только дописывается (ТЗ §21).
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import os
import sys
import tempfile
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gov_schema as schema  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
REPLACE_ATTEMPTS = 6  # на Windows os.replace иногда падает: файл на миг занят антивирусом/индексатором
LOCK_TIMEOUT = 10.0  # сколько секунд ждать освобождения блокировки компании
LOCK_POLL = 0.05  # пауза между попытками взять блокировку
LOCK_STALE_AFTER = 60.0  # блокировка старше порога и без живого владельца считается брошенной
_HELD_LOCKS: dict[str, int] = {}  # блокировки, взятые этим процессом: путь -> глубина вложенности


class GovError(Exception):
    """Ошибка предметной области: валидация, отказ операции, нет файла."""


def _pid_alive(pid: int) -> bool:
    """Жив ли процесс с таким pid. На Windows сигнал 0 завершил бы процесс, поэтому там WinAPI."""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes  # noqa: PLC0415

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ctypes.get_last_error() == 5  # ERROR_ACCESS_DENIED: процесс есть, но чужой
        try:
            code = ctypes.c_ulong()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return code.value == 259  # STILL_ACTIVE
            return True
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _remove(path: Path) -> bool:
    """Удалить файл с повтором (на Windows он на миг может быть занят). True: файла больше нет."""
    for attempt in range(REPLACE_ATTEMPTS):
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return True
        except PermissionError:
            time.sleep(0.05 * (attempt + 1))
    return False


def default_entities_dir() -> Path:
    """profile/knowledge/corporate/entities (с учётом переносимого профиля)."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from tools.profile.profile_lib import profile_root  # noqa: PLC0415

    return profile_root() / "knowledge" / "corporate" / "entities"


def today() -> str:
    return dt.date.today().isoformat()


def now_iso() -> str:
    return dt.datetime.now().replace(microsecond=0).isoformat()


def next_id(prefix: str, items: list[dict], key: str) -> str:
    top = 0
    for item in items:
        try:
            top = max(top, int(str(item.get(key, "")).split("-")[-1]))
        except ValueError:
            continue
    return f"{prefix}-{top + 1:03d}"


# ---------- I7: --by (confirm, set-source-status --status current) ----------

_PLACEHOLDER_APPROVER_ZERO_WIDTH = "​‌‍‎‏⁠﻿ㅤ"
_PLACEHOLDER_APPROVER_DENYLIST = frozenset({"юрист", "lawyer", "agent", "агент", "claude"})


def is_placeholder_approver(name: str) -> bool:
    """True: --by похож на роль/плейсхолдер, а не на имя, которое юрист назвал сам.

    Общий гейт для confirm и set-source-status (--status current): отклоняет расхожие
    роли (юрист/lawyer/agent/агент/claude, регистр не важен, в т. ч. обёрнутые
    невидимыми/форматирующими символами) и значения совсем без букв. Настоящее имя,
    даже если оно случайно содержит невидимый символ, не отклоняется — проверяется весь
    очищенный текст целиком, а не подстрока.
    """
    cleaned = (name or "").strip()
    for ch in _PLACEHOLDER_APPROVER_ZERO_WIDTH:
        cleaned = cleaned.replace(ch, "")
    cleaned = cleaned.strip()
    if "<" in cleaned or ">" in cleaned:
        # шаблонная подстановка вида "<ФИО юриста>" из документации, а не имя, которое назвал юрист
        return True
    if not any(ch.isalpha() for ch in cleaned):
        return True
    # кавычки/ёлочки на краях не защищают роль от списка: «Юрист» — тот же плейсхолдер, что и Юрист
    return cleaned.strip("\"'«»“”").casefold() in _PLACEHOLDER_APPROVER_DENYLIST


class Entity:
    """Одна компания в слое entities/. Все записи идут через этот класс."""

    def __init__(self, entities_dir: Path, slug: str):
        if not schema.SLUG_RE.match(slug or ""):
            raise GovError(f"slug должен состоять из a-z, 0-9 и дефисов: {slug!r}")
        self.slug = slug
        self.dir = Path(entities_dir) / slug
        # sources.yaml хранит пути к документам относительно corporate/
        self.domain_dir = Path(entities_dir).parent

    # ---- пути ----
    @property
    def sources_path(self) -> Path:
        return self.dir / "sources.yaml"

    @property
    def rules_path(self) -> Path:
        return self.dir / "rules.yaml"

    @property
    def profile_path(self) -> Path:
        return self.dir / "profile.yaml"

    @property
    def audit_path(self) -> Path:
        return self.dir / "audit.jsonl"

    @property
    def work_dir(self) -> Path:
        return self.dir / "_work"

    @property
    def lock_path(self) -> Path:
        return self.dir / ".lock"

    def exists(self) -> bool:
        return self.dir.is_dir()

    def require(self) -> None:
        if not self.exists():
            raise GovError(f"компания не заведена: {self.dir} (сначала init-entity)")

    # ---- блокировка ----
    @contextlib.contextmanager
    def locked(self, timeout: float | None = None):
        """Эксклюзивная блокировка компании на весь цикл «прочитать, изменить, сохранить, записать в аудит».

        Без неё две одновременные команды читают одно состояние и вторая затирает запись первой.
        Блокировка: файл `.lock` в папке компании, создаётся атомарно (O_CREAT|O_EXCL), внутри pid
        владельца. Занято: ждём до `timeout` секунд (по умолчанию LOCK_TIMEOUT), затем GovError.
        Брошенную блокировку (процесс завершён, файл остался) берём себе, только если файл старше
        LOCK_STALE_AFTER секунд И владельца нет в живых: свежая блокировка могла быть создана
        мгновение назад, старая блокировка живого процесса просто долгая команда. Повторный вход
        в том же процессе (тот же каталог) блокировку не ждёт, снимается она на внешнем выходе.
        Команды CLI берут блокировку в одном месте, governance.run; здесь же берёт init.
        """
        self.require()
        key = os.path.normcase(str(self.lock_path.resolve()))
        if key in _HELD_LOCKS:
            _HELD_LOCKS[key] += 1
            try:
                yield
            finally:
                _HELD_LOCKS[key] -= 1
            return
        self._acquire_lock(LOCK_TIMEOUT if timeout is None else timeout)
        _HELD_LOCKS[key] = 1
        try:
            yield
        finally:
            del _HELD_LOCKS[key]
            # не снялась (файл занят) и владелец завершился: её возьмёт себе следующая команда как брошенную
            _remove(self.lock_path)

    def _acquire_lock(self, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except (FileExistsError, PermissionError):  # Windows: удаляемый файл на миг «занят»
                if self._reap_stale_lock():
                    continue
                if time.monotonic() >= deadline:
                    raise GovError(self._busy_message()) from None
                time.sleep(LOCK_POLL)
                continue
            try:
                os.write(fd, f"{os.getpid()}\n".encode("ascii"))
            finally:
                os.close(fd)
            return

    def _lock_owner(self) -> tuple[int, float] | None:
        """(pid владельца, возраст блокировки в секундах); None, если блокировки нет или её не прочитать."""
        try:
            age = time.time() - self.lock_path.stat().st_mtime
            head = self.lock_path.read_text(encoding="utf-8").split()
        except OSError:
            return None
        try:
            return int(head[0]), age
        except (IndexError, ValueError):
            return 0, age  # владелец не успел записать pid

    def _lock_is_stale(self) -> bool:
        owner = self._lock_owner()
        return owner is not None and owner[1] > LOCK_STALE_AFTER and not _pid_alive(owner[0])

    def _reap_stale_lock(self) -> bool:
        """Снять брошенную блокировку. True: снята, можно брать. Чистит один процесс за раз."""
        if not self._lock_is_stale():
            return False
        guard = self.dir / ".lock.reap"
        try:
            os.close(os.open(guard, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
        except OSError:
            with contextlib.suppress(OSError):  # метку чистильщика, умершего на середине, снимаем по возрасту
                if time.time() - guard.stat().st_mtime > LOCK_STALE_AFTER:
                    _remove(guard)
            return False
        try:
            # повторная проверка под меткой: блокировку могли снять и взять заново, свежую не трогаем
            return self._lock_is_stale() and _remove(self.lock_path)
        finally:
            _remove(guard)

    def _busy_message(self) -> str:
        owner = self._lock_owner()
        who = f" (pid {owner[0]}, занята {int(owner[1])} с)" if owner else ""
        return (f"другая команда работает с компанией {self.slug}: блокировка {self.lock_path.name}{who} "
                "не освободилась. Команды по одной компании выполняются по очереди: дождитесь "
                f"завершения и повторите. Файл брошенной блокировки инструмент снимает сам через "
                f"{int(LOCK_STALE_AFTER)} с, если процесса уже нет.")

    # ---- создание ----
    def init(self, name: str) -> None:
        if self.exists():
            raise GovError(f"компания уже заведена: {self.dir} (init-entity повторно не выполняется)")
        try:
            self.dir.mkdir(parents=True)  # атомарно: из двух одновременных init создаст одна
        except FileExistsError:
            raise GovError(f"компания уже заведена: {self.dir} (init-entity повторно не выполняется)") from None
        with self.locked():
            self.work_dir.mkdir()
            header = {"schema_version": schema.SCHEMA_VERSION, "entity_id": self.slug, "rev": 0}
            self._save(self.sources_path, {**header, "sources": []})
            self._save(self.rules_path, {**header, "rules": []})
            self._save(self.profile_path, {**header, "name": name, "facts": [], "assumptions": []})
            self.audit_path.write_text("", encoding="utf-8")

    # ---- чтение ----
    def _load(self, path: Path, collection: str) -> dict:
        if not path.exists():
            raise GovError(f"{path.name} не найден в {self.dir}")
        try:
            text = path.read_text(encoding="utf-8")
            data = yaml.safe_load(text)
        except (yaml.YAMLError, UnicodeDecodeError, OSError) as exc:
            # T2.2: битый yaml или файл не в UTF-8 (например, правлен вручную в чужой
            # кодировке) не должен ронять команду сырым traceback — назвать файл и
            # направить к восстановлению из копии/аудита, а не к ручной правке
            raise GovError(
                f"{path.name} повреждён; восстановите из копии/аудита, не правьте руками ({exc})"
            ) from exc
        if not isinstance(data, dict) or not isinstance(data.get(collection), list):
            raise GovError(f"{path.name}: ожидается объект с коллекцией {collection!r}")
        return data

    def load_sources(self) -> dict:
        return self._load(self.sources_path, "sources")

    def load_rules(self) -> dict:
        return self._load(self.rules_path, "rules")

    def load_profile(self) -> dict:
        data = self._load(self.profile_path, "facts")
        data.setdefault("assumptions", [])
        return data

    def sources_by_id(self) -> dict:
        return {s["source_id"]: s for s in self.load_sources()["sources"]}

    # ---- запись (каждое сохранение увеличивает rev) ----
    def _save(self, path: Path, data: dict) -> int:
        data["rev"] = int(data.get("rev", 0)) + 1
        data["updated"] = today()
        text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=100)
        # временный файл с уникальным именем: два одновременных сохранения не делят один `<файл>.tmp`
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(text)
            for attempt in range(REPLACE_ATTEMPTS):
                try:
                    os.replace(tmp, path)
                    break
                except PermissionError:
                    if attempt == REPLACE_ATTEMPTS - 1:
                        raise
                    time.sleep(0.05 * (attempt + 1))
        except BaseException:
            with contextlib.suppress(OSError):
                tmp.unlink()  # сбой сохранения не оставляет временных файлов; исходный файл цел
            raise
        return data["rev"]

    def save_sources(self, data: dict) -> int:
        return self._save(self.sources_path, data)

    def save_rules(self, data: dict) -> int:
        return self._save(self.rules_path, data)

    def save_profile(self, data: dict) -> int:
        return self._save(self.profile_path, data)

    # ---- аудит ----
    def audit(self, action: str, obj: str, *, actor: str = "agent", old=None, new=None,
              source: str | None = None, approval=None, rev: int | None = None,
              timestamp: str | None = None) -> None:
        event = {
            "timestamp": timestamp or now_iso(), "actor": actor, "action": action,
            "object": obj, "old_value": old, "new_value": new, "source": source,
            "approval": approval, "rev": rev,
        }
        with self.audit_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")

    def read_audit(self) -> list[dict]:
        if not self.audit_path.exists():
            return []
        lines = self.audit_path.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines if line.strip()]


def common_parser(*, need_slug: bool = True) -> argparse.ArgumentParser:
    """Общие параметры подкоманд (родительский парсер)."""
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument("--entities-dir",
                        help="каталог entities (по умолчанию profile/knowledge/corporate/entities)")
    parent.add_argument("--actor", default="agent", help="кто выполняет операцию (для аудита)")
    if need_slug:
        parent.add_argument("--slug", required=True, help="slug компании (a-z, 0-9, дефис)")
    return parent


def entity_from_args(args, *, must_exist: bool = True) -> Entity:
    base = Path(args.entities_dir) if args.entities_dir else default_entities_dir()
    entity = Entity(base, args.slug)
    if must_exist:
        entity.require()
    return entity
