# -*- coding: utf-8 -*-
"""
tools/doc_ingest/untrusted_scan.py

Эвристический сканер недоверенного ввода: ищет в документе то, что похоже на
команду агенту или спрятано от человека. Результат — строки для
`metadata.warnings`; пресейв показывает их юристу.

Что ищет:
- скрытый текст .docx: `w:vanish`/`w:specVanish`, белый шрифт без заливки,
  кегль меньше 2 пт (основной текст, колонтитулы, сноски);
- символы нулевой ширины и управления направлением текста;
- фразы-команды агенту на русском и английском.

Это защита второго эшелона: список фраз обходится. Основная защита — правило
`references/untrusted-input.md`. Сканер ничего не удаляет и не правит.

CLI:
    python -m tools.doc_ingest.untrusted_scan FILE
"""
from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
WARNING_PREFIX = "[ВОЗМОЖНАЯ ВСТРОЕННАЯ ИНСТРУКЦИЯ"
MAX_FRAGMENT = 80
MAX_FINDINGS = 10
MIN_HIDDEN_CHARS = 3
TINY_HALF_POINTS = 4  # w:sz в половинах пункта: < 4 == меньше 2 пт

INVISIBLE_CHARS = re.compile(
    "[​‌‍‎‏‪-‮⁠-⁤⁦-⁩﻿]"
)

_AGENT = r"(?:ассистент|ии|ai|нейросеть|модель|бот|агент|claude|chatgpt|gpt|llm|assistant|model)"
COMMAND_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"игнорир\w*\s+(?:все\s+)?(?:предыдущ|прежн|вышеуказ|ранее\s+данн)\w*",
        r"забудь\s+(?:все\s+)?(?:предыдущ|прежн|инструкц)\w*",
        r"(?:нов\w+|системн\w+)\s+(?:инструкц|промпт|указани)\w*\s+(?:для|агенту|ассистенту|модели|ии)",
        r"не\s+(?:сообщай|говори|показывай|упоминай)\s+(?:об\s+этом\s+)?(?:юристу|пользователю|человеку)",
        rf"\b{_AGENT}\b\s*[,:]\s*(?:пожалуйста\s+)?(?:отметь|пометь|считай|признай|укажи|оцени|игнорир\w*|отправь|перешли|удали|выполни|не\s+сообщай)",
        r"ignore\s+(?:all\s+)?(?:the\s+)?(?:previous|prior|above|earlier)\s+(?:instructions|prompts|messages)",
        r"disregard\s+(?:all\s+)?(?:the\s+)?(?:previous|prior|above)",
        r"\bsystem\s+prompt\b",
        r"\byou\s+are\s+now\s+(?:a|an|the)\b",
        r"do\s+not\s+(?:tell|inform|mention\s+(?:this\s+)?to)\s+the\s+(?:user|lawyer|human)",
        rf"\b{_AGENT}\b\s*[,:]\s*(?:please\s+)?(?:mark|treat|classify|rate|ignore|send|forward|delete|approve)",
        r"(?m)^\s*(?:system|assistant)\s*:\s*\S",
    )
]


def _fragment(text: str, start: int = 0, end: int | None = None) -> str:
    end = len(text) if end is None else end
    lo = max(0, start - 20)
    piece = re.sub(r"\s+", " ", text[lo:max(end, lo + 1) + 40]).strip()
    piece = INVISIBLE_CHARS.sub("", piece)
    return piece[:MAX_FRAGMENT] + ("…" if len(piece) > MAX_FRAGMENT else "")


def _warning(kind: str, fragment: str, place: str) -> str:
    return f"{WARNING_PREFIX}: {kind} — «{fragment}» ({place})]"


def scan_text(text: str, place: str = "текст") -> list[str]:
    """Фразы-команды и невидимые символы в извлечённом тексте."""
    out: list[str] = []
    text = text or ""
    invisible = INVISIBLE_CHARS.findall(text)
    if invisible:
        codes = ", ".join(sorted({f"U+{ord(c):04X}" for c in invisible}))
        first = INVISIBLE_CHARS.search(text)
        out.append(_warning(f"невидимые символы ({len(invisible)}: {codes})",
                            _fragment(text, first.start(), first.end()), place))
    clean = INVISIBLE_CHARS.sub("", text)
    for pattern in COMMAND_PATTERNS:
        for m in pattern.finditer(clean):
            out.append(_warning("фраза-команда агенту", _fragment(clean, m.start(), m.end()), place))
            if len(out) >= MAX_FINDINGS:
                return out
    return out


def _run_text(run: ET.Element) -> str:
    return "".join(t.text or "" for t in run.iter(f"{W}t"))


def _has_fill(props: ET.Element | None) -> bool:
    """Есть ли у ячейки или абзаца цветная заливка (не белая и не auto)."""
    if props is None:
        return False
    shd = props.find(f"{W}shd")
    fill = (shd.get(f"{W}fill") or "").upper() if shd is not None else ""
    return bool(fill) and fill not in ("FFFFFF", "AUTO")


def _runs_on_fill(root: ET.Element) -> set[int]:
    """id() прогонов, лежащих в ячейке или абзаце с цветной заливкой: белый текст там видим."""
    out: set[int] = set()
    for tc in root.iter(f"{W}tc"):
        if _has_fill(tc.find(f"{W}tcPr")):
            out.update(id(r) for r in tc.iter(f"{W}r"))
    for para in root.iter(f"{W}p"):
        if _has_fill(para.find(f"{W}pPr")):
            out.update(id(r) for r in para.iter(f"{W}r"))
    return out


def _hidden_reason(run: ET.Element, on_fill: bool = False) -> str | None:
    rpr = run.find(f"{W}rPr")
    if rpr is None:
        return None
    for tag in ("vanish", "specVanish"):
        el = rpr.find(f"{W}{tag}")
        if el is not None and el.get(f"{W}val", "true") not in ("0", "false", "off"):
            return "скрытый текст"
    color = rpr.find(f"{W}color")
    shaded = rpr.find(f"{W}shd") is not None or rpr.find(f"{W}highlight") is not None
    if color is not None and (color.get(f"{W}val") or "").upper() == "FFFFFF" and not (shaded or on_fill):
        return "белый шрифт"
    size = rpr.find(f"{W}sz")
    if size is not None:
        try:
            if int(size.get(f"{W}val", "99")) < TINY_HALF_POINTS:
                return "кегль меньше 2 пт"
        except ValueError:
            pass
    return None


DOCX_PARTS = re.compile(r"^word/(document|header\d*|footer\d*|footnotes|endnotes)\.xml$")


def scan_docx(path: str | Path) -> list[str]:
    """Скрытый от человека текст в .docx."""
    out: list[str] = []
    try:
        with zipfile.ZipFile(path) as zf:
            parts = [n for n in zf.namelist() if DOCX_PARTS.match(n)]
            for part in parts:
                root = ET.fromstring(zf.read(part))
                on_fill = _runs_on_fill(root)
                for p_idx, para in enumerate(root.iter(f"{W}p"), start=1):
                    hidden: dict[str, list[str]] = {}
                    for run in para.iter(f"{W}r"):
                        reason = _hidden_reason(run, id(run) in on_fill)
                        if reason:
                            hidden.setdefault(reason, []).append(_run_text(run))
                    for reason, texts in hidden.items():
                        text = "".join(texts).strip()
                        if len(text) >= MIN_HIDDEN_CHARS:
                            place = f"{part.split('/')[-1]}, абзац {p_idx}"
                            out.append(_warning(reason, _fragment(text), place))
                            if len(out) >= MAX_FINDINGS:
                                return out
    except (zipfile.BadZipFile, ET.ParseError, KeyError, OSError):
        return out
    return out


def scan(path: str | Path, markdown: str = "") -> list[str]:
    """Все находки по файлу и его извлечённому тексту; без дублей."""
    findings: list[str] = []
    if Path(path).suffix.lower() == ".docx":
        findings += scan_docx(path)
    findings += scan_text(markdown)
    seen: set[str] = set()
    return [f for f in findings if not (f in seen or seen.add(f))][:MAX_FINDINGS]


def main(argv=None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print(__doc__)
        return 2
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    path = Path(args[0])
    if path.suffix.lower() in {".md", ".txt"}:
        findings = scan(path, path.read_text(encoding="utf-8", errors="replace"))
    else:
        from tools.doc_ingest.router import convert  # noqa: PLC0415
        meta = convert(path).get("metadata", {})
        findings = [w for w in meta.get("warnings", []) if w.startswith(WARNING_PREFIX)]
    print("\n".join(findings) if findings else "находок нет")
    return 0


if __name__ == "__main__":
    sys.exit(main())
