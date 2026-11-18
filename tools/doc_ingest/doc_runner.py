# -*- coding: utf-8 -*-
"""
tools/doc_ingest/doc_runner.py

Старый Word (.doc, Word 97–2003) → текст, офлайн, без Word COM и облака.
markitdown 0.0.2 такие файлы не читает (UnsupportedFormatException), Word COM
в этой среде зависает на модальных окнах, LibreOffice не установлен, а antiword
из Git for Windows падает (segfault) — поэтому свой разбор по MS-DOC поверх olefile.

Как читается текст (MS-DOC, раздел 2.4.1):
  1. FIB в начале потока WordDocument: флаги (шифрование, какой из 0Table/1Table),
     длины поддокументов (ccpText, ccpFtn, …) и адрес CLX (fcClx/lcbClx).
  2. CLX в потоке таблиц: пропускаем Prc, берём Pcdt → PlcPcd (piece table).
  3. Каждый кусок — диапазон CP и смещение в WordDocument: сжатый (cp1252, байт
     на символ) или UTF-16LE. Куски склеиваются в порядке CP, а не в порядке байт
     в потоке: после быстрого сохранения порядок в потоке другой.
  4. Специальные символы: коды полей (инструкция между 0x13 и 0x14 убирается,
     результат до 0x15 остаётся), метки ячеек 0x07, разрывы, якоря объектов.

Таблицы упрощаются: ячейки через « | », строка таблицы — строка текста. Признак
конца строки таблицы хранится в свойствах абзаца, которые здесь не разбираются,
поэтому пустая ячейка может сдвинуть разметку — ставится [ТАБЛИЦА УПРОЩЕНА].

Python API:
    from tools.doc_ingest.doc_runner import convert
    result = convert("Список участников.doc")   # {"markdown": str, "metadata": dict}
"""
from __future__ import annotations

import re
import struct
import time
from pathlib import Path

import olefile

OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
WORD_IDENT = 0xA5EC
NFIB_WORD97 = 0x00C1
FLAG_ENCRYPTED = 0x0100
FLAG_TABLE1 = 0x0200
CLX_PAIR_INDEX = 33  # fcClx/lcbClx в FibRgFcLcb97
FC_COMPRESSED = 0x40000000
FC_OFFSET_MASK = 0x3FFFFFFF

# Поддокументы в порядке CP (FibRgLw97: ccpText, ccpFtn, ccpHdd, резерв, ccpAtn, …).
SUBDOCUMENTS = (
    (3, None),
    (4, "Сноски"),
    (5, "Колонтитулы"),
    (7, "Примечания"),
    (8, "Концевые сноски"),
    (9, "Надписи"),
    (10, "Надписи в колонтитулах"),
)

_FIELD_BEGIN, _FIELD_SEP, _FIELD_END = "\x13", "\x14", "\x15"
_CHAR_MAP = str.maketrans({
    "\r": "\n",      # конец абзаца
    "\x0b": "\n",    # разрыв строки
    "\x0c": "\n",    # разрыв страницы/раздела
    "\x0e": "\n",    # разрыв колонки
    "\x1e": "-",     # неразрывный дефис
    "\x1f": None,    # мягкий перенос
})
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f]")  # якоря рисунков, сносок, примечаний


def _olefile_version() -> str:
    return getattr(olefile, "__version__", "unknown")


def _drop_field_instructions(text: str) -> str:
    """Оставить результат поля, убрать инструкцию; поля бывают вложенными."""
    out: list[str] = []
    stack: list[bool] = []  # True — внутри инструкции поля
    for ch in text:
        if ch == _FIELD_BEGIN:
            stack.append(True)
        elif ch == _FIELD_SEP:
            if stack:
                stack[-1] = False
        elif ch == _FIELD_END:
            if stack:
                stack.pop()
        elif not any(stack):
            out.append(ch)
    return "".join(out)


def _clean(text: str) -> str:
    text = _drop_field_instructions(text)
    text = re.sub(r"\x07{2,}", "\n", text)  # конец ячейки + конец строки таблицы
    text = text.replace("\x07", " | ").translate(_CHAR_MAP)
    text = _CONTROL.sub("", text)
    return "\n".join(line.rstrip() for line in text.splitlines()).strip()


def _piece_table(table: bytes, fc_clx: int, lcb_clx: int) -> tuple[list[int], list[int]]:
    """CP-границы и FcCompressed каждого куска из CLX."""
    clx = table[fc_clx:fc_clx + lcb_clx]
    if len(clx) != lcb_clx or not lcb_clx:
        raise ValueError("CLX за пределами потока таблиц")
    pos = 0
    while pos < len(clx) and clx[pos] == 0x01:  # Prc: clxt, cbGrpprl, grpprl
        (cb,) = struct.unpack_from("<h", clx, pos + 1)
        if cb < 0:
            raise ValueError("Prc в CLX повреждён")
        pos += 3 + cb
    if pos >= len(clx) or clx[pos] != 0x02:
        raise ValueError("в CLX нет Pcdt (piece table)")
    (lcb,) = struct.unpack_from("<I", clx, pos + 1)
    plc = clx[pos + 5:pos + 5 + lcb]
    if len(plc) != lcb or (lcb - 4) % 12:
        raise ValueError("PlcPcd повреждён")
    n = (lcb - 4) // 12
    cps = list(struct.unpack_from(f"<{n + 1}I", plc, 0))
    fcs = [struct.unpack_from("<I", plc, 4 * (n + 1) + 8 * i + 2)[0] for i in range(n)]
    return cps, fcs


def _document_text(word: bytes, cps: list[int], fcs: list[int]) -> str:
    parts: list[str] = []
    for i, fc in enumerate(fcs):
        count = cps[i + 1] - cps[i]
        if count <= 0:
            continue
        offset = fc & FC_OFFSET_MASK  # бит 31 зарезервирован
        if fc & FC_COMPRESSED:
            start = offset // 2
            raw, codec = word[start:start + count], "cp1252"
        else:
            start = offset
            raw, codec = word[start:start + 2 * count], "utf-16-le"
        if len(raw) != (count if codec == "cp1252" else 2 * count):
            raise ValueError("кусок текста за пределами потока WordDocument")
        parts.append(raw.decode(codec, errors="replace"))
    return "".join(parts)


def extract(path: str | Path) -> tuple[str, list[str]]:
    """Вернуть (текст, предупреждения). ValueError — файл не читается этим способом."""
    p = Path(path)
    if not olefile.isOleFile(str(p)):
        raise ValueError(f"{p.name}: не составной файл OLE (не Word 97–2003)")
    with olefile.OleFileIO(str(p)) as ole:
        if not ole.exists("WordDocument"):
            raise ValueError(f"{p.name}: в файле OLE нет потока WordDocument — это не документ Word")
        word = ole.openstream("WordDocument").read()
        if len(word) < 0x22:
            raise ValueError(f"{p.name}: FIB обрезан")
        ident, nfib = struct.unpack_from("<HH", word, 0)
        (flags,) = struct.unpack_from("<H", word, 0x0A)
        if ident != WORD_IDENT:
            raise ValueError(f"{p.name}: неверная сигнатура FIB")
        if flags & FLAG_ENCRYPTED:
            raise ValueError(f"{p.name}: документ зашифрован (пароль) — текст не извлекается")
        if nfib < NFIB_WORD97:
            raise ValueError(f"{p.name}: формат Word 6/95 не поддержан — пересохранить в .docx")
        table_name = "1Table" if flags & FLAG_TABLE1 else "0Table"
        if not ole.exists(table_name):
            raise ValueError(f"{p.name}: нет потока {table_name}")
        table = ole.openstream(table_name).read()

    # FibBase (32 байта) → csw + fibRgW → cslw + fibRgLw → cbRgFcLcb + fibRgFcLcbBlob.
    (csw,) = struct.unpack_from("<H", word, 0x20)
    lw_at = 0x22 + 2 * csw + 2
    (cslw,) = struct.unpack_from("<H", word, lw_at - 2)
    fclcb_at = lw_at + 4 * cslw + 2
    (cb_fclcb,) = struct.unpack_from("<H", word, fclcb_at - 2)
    if (cslw <= max(i for i, _ in SUBDOCUMENTS) or cb_fclcb <= CLX_PAIR_INDEX
            or len(word) < fclcb_at + 8 * (CLX_PAIR_INDEX + 1)):
        raise ValueError(f"{p.name}: FIB короче Word 97")
    fc_clx, lcb_clx = struct.unpack_from("<II", word, fclcb_at + 8 * CLX_PAIR_INDEX)

    cps, fcs = _piece_table(table, fc_clx, lcb_clx)
    full = _document_text(word, cps, fcs)

    sections: list[str] = []
    warnings: list[str] = []
    cp, has_tables = 0, False
    for index, heading in SUBDOCUMENTS:
        ccp = max(struct.unpack_from("<i", word, lw_at + 4 * index)[0], 0)
        raw = full[cp:cp + ccp]
        has_tables = has_tables or "\x07" in raw
        chunk = _clean(raw)
        cp += ccp
        if heading is None:
            sections.append(chunk)
        elif chunk:
            sections.append(f"## {heading}\n\n{chunk}")
    if has_tables:
        warnings.append(
            "[ТАБЛИЦА УПРОЩЕНА] ячейки через « | », строка таблицы — строка текста; "
            "границы строк и пустые ячейки сверить с оригиналом"
        )
    if cp > len(full):
        warnings.append("[НЕ РАСПОЗНАНО] piece table короче длины текста из FIB — часть текста потеряна")
    return "\n\n".join(sections).strip(), warnings


def convert(path: str | Path) -> dict:
    """Извлечь текст .doc. Возвращает {"markdown", "metadata"} как markitdown_runner."""
    p = Path(path).resolve()
    if not p.is_file():
        raise FileNotFoundError(f"Файл не найден: {p}")
    started = time.time()
    text, warnings = extract(p)
    return {
        "markdown": text,
        "metadata": {
            "source": p.name,
            "source_path": str(p),
            "extension": p.suffix.lower(),
            "size_bytes": p.stat().st_size,
            "backend": "olefile-doc",
            "backend_version": _olefile_version(),
            "duration_sec": round(time.time() - started, 3),
            "char_count": len(text),
            "line_count": text.count("\n") + 1,
            "warnings": warnings,
        },
    }
