#!/usr/bin/env python3
"""Сборка DOCX «Лист проверки контрагента» (2–4 стр.) по правилам report-rules.md.

python-docx, Times New Roman + eastAsia (кириллица). Документ собирается
программно (без болванки). Верификация — обратным извлечением текста.
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
import xml.etree.ElementTree as ET

try:
    from docx import Document
    from docx.shared import Pt, Cm
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
except Exception as e:  # pragma: no cover
    Document = None
    _IMPORT_ERR = e

FONT = "Times New Roman"
_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

VERDICTS = {
    "green": "🟢 ДОПУСТИМО",
    "yellow": "🟡 ДОПУСТИМО С УСЛОВИЯМИ",
    "red": "🔴 ВЫСОКИЙ РИСК",
}
RISK_EMOJI = {"green": "🟢", "yellow": "🟡", "red": "🔴", "manual": "⚪", "na": "N/A"}


class ReportError(Exception):
    pass


def _set_run(run, *, bold=False, size=11):
    run.font.name = FONT
    run.font.size = Pt(size)
    run.bold = bold
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        rPr.append(rFonts)
    for a in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rFonts.set(qn(a), FONT)


def _para(doc, text="", *, bold=False, size=11, align=None, space_after=6):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(space_after)
    if align is not None:
        p.alignment = align
    if text:
        _set_run(p.add_run(text), bold=bold, size=size)
    return p


def _heading(doc, text, *, size=13):
    _para(doc, text, bold=True, size=size, space_after=8)


def _kv_table(doc, rows, widths=(Cm(5.5), Cm(11.0))):
    t = doc.add_table(rows=len(rows), cols=2)
    t.autofit = False
    for i, w in enumerate(widths):
        for cell in t.columns[i].cells:
            cell.width = w
    for i, (k, v) in enumerate(rows):
        _set_run(t.rows[i].cells[0].paragraphs[0].add_run(str(k)), bold=True)
        _set_run(t.rows[i].cells[1].paragraphs[0].add_run("" if v is None else str(v)))
    return t


def _bullets(doc, items, *, empty="—"):
    if not items:
        _para(doc, empty)
        return
    for it in items:
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(3)
        p.paragraph_format.left_indent = Cm(0.6)
        _set_run(p.add_run(f"• {it}"))


def build_report(case_data: dict, out_path: str) -> str:
    if Document is None:
        raise ReportError(f"python-docx недоступен: {_IMPORT_ERR}")
    if not isinstance(case_data, dict):
        raise ReportError("case_data должен быть dict")

    doc = Document()
    s = doc.sections[0]
    s.page_width, s.page_height = Cm(21.0), Cm(29.7)
    s.left_margin = s.right_margin = Cm(2.0)
    s.top_margin = s.bottom_margin = Cm(2.0)
    st = doc.styles["Normal"]
    st.font.name = FONT
    st.font.size = Pt(11)
    rPr = st.element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        rPr.append(rFonts)
    for a in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rFonts.set(qn(a), FONT)

    c = case_data.get("contragent", {}) or {}
    _para(doc, "ЛИСТ ПРОВЕРКИ КОНТРАГЕНТА", bold=True, size=15,
          align=WD_ALIGN_PARAGRAPH.CENTER, space_after=10)

    _heading(doc, "Контрагент")
    _kv_table(doc, [
        ("Наименование", c.get("name")),
        ("ИНН / ОГРН / ID", c.get("ids")),
        ("Страна", c.get("country")),
        ("Дата проверки", case_data.get("check_date")),
    ])

    _heading(doc, "Параметры сделки")
    _bullets(doc, case_data.get("transaction", []))

    _heading(doc, "Итоговая оценка")
    v = (case_data.get("verdict") or "").lower()
    if v not in VERDICTS:
        raise ReportError(f"verdict должен быть green/yellow/red, дано: {v!r}")
    _para(doc, VERDICTS[v], bold=True, size=13)

    _heading(doc, "Таблица проверки")
    checks = case_data.get("checks", []) or []
    t = doc.add_table(rows=1 + len(checks), cols=3)
    t.autofit = False
    widths = (Cm(5.0), Cm(9.0), Cm(3.0))
    for i, w in enumerate(widths):
        for cell in t.columns[i].cells:
            cell.width = w
    for j, h in enumerate(("Проверка", "Результат", "Риск")):
        _set_run(t.rows[0].cells[j].paragraphs[0].add_run(h), bold=True)
    for i, row in enumerate(checks, start=1):
        _set_run(t.rows[i].cells[0].paragraphs[0].add_run(str(row.get("name", ""))))
        _set_run(t.rows[i].cells[1].paragraphs[0].add_run(str(row.get("result", ""))))
        risk = str(row.get("risk", "na")).lower()
        if risk not in RISK_EMOJI:
            raise ReportError(f"risk строки таблицы должен быть green/yellow/red/manual/na, дано: {risk!r}")
        _set_run(t.rows[i].cells[2].paragraphs[0].add_run(RISK_EMOJI[risk]))

    _heading(doc, "Выявленные риски")
    _bullets(doc, case_data.get("risks", []))
    _heading(doc, "Необходимо запросить")
    _bullets(doc, case_data.get("requests", []))
    _heading(doc, "Рекомендации")
    _bullets(doc, case_data.get("recommendations", []))
    _heading(doc, "Ограничения проверки")
    _bullets(doc, case_data.get("limitations", []))
    _heading(doc, "Источники")
    _bullets(doc, case_data.get("sources", []))

    doc.save(out_path)
    return out_path


def extract_docx_text(path: str) -> list[str]:
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml")
    root = ET.fromstring(xml)
    lines = []
    for p in root.iter(f"{{{_W}}}p"):
        txt = "".join(t.text or "" for t in p.iter(f"{{{_W}}}t"))
        if txt.strip():
            lines.append(txt)
    return lines


def selftest() -> int:
    import tempfile
    from pathlib import Path
    ok = 0
    case = {
        "contragent": {"name": 'ООО "Ромашка"', "ids": "ИНН 7700000000 / ОГРН 1147700000000",
                       "country": "РФ"},
        "check_date": "28.08.2026",
        "transaction": ["Поставка оборудования", "15 000 000 ₽", "Аванс 50% (7,5 млн ₽)"],
        "verdict": "yellow",
        "checks": [
            {"name": "Правоспособность", "result": "Действующее ЮЛ", "risk": "green"},
            {"name": "ФССП", "result": "ручная проверка", "risk": "manual"},
            {"name": "Лицензии", "result": "не требуется", "risk": "na"},
        ],
        "risks": ["Аванс 7,5 млн ₽ без обеспечения"],
        "requests": ["Устав", "Решение о назначении ЕИО"],
        "recommendations": ["Уменьшить аванс либо получить банковскую гарантию"],
        "limitations": ["ФССП — CAPTCHA, требуется ручная проверка"],
        "sources": ["ЕГРЮЛ (DaData) — 28.08.2026 — 01_Реестр/...ЕГРЮЛ.pdf"],
    }
    with tempfile.TemporaryDirectory() as td:
        out = str(Path(td) / "лист.docx")
        build_report(case, out)
        assert Path(out).exists()
        lines = extract_docx_text(out)
        joined = "\n".join(lines)
        for must in ("ЛИСТ ПРОВЕРКИ КОНТРАГЕНТА", "🟡 ДОПУСТИМО С УСЛОВИЯМИ",
                     "Правоспособность", "ручная проверка", "Источники"):
            assert must in joined, f"нет в отчёте: {must}"
        assert "⚪" in joined and "N/A" in joined
        # Регрессионная проверка: Normal-стиль не должен иметь дублей w:rFonts
        import zipfile as _zip
        import xml.etree.ElementTree as _ET
        with _zip.ZipFile(out) as _z:
            _styles = _ET.fromstring(_z.read("word/styles.xml"))
        _normal_rfonts = []
        for _style in _styles.iter(f"{{{_W}}}style"):
            if _style.get(f"{{{_W}}}styleId") == "Normal":
                _rpr = _style.find(f"{{{_W}}}rPr")
                if _rpr is not None:
                    _normal_rfonts = _rpr.findall(f"{{{_W}}}rFonts")
                break
        assert len(_normal_rfonts) == 1, f"ожидался ровно один w:rFonts в Normal, найдено {len(_normal_rfonts)}"
        assert _normal_rfonts[0].get(f"{{{_W}}}eastAsia") == "Times New Roman", "eastAsia в Normal != Times New Roman"
        ok += 1
        try:
            build_report({"verdict": "bad"}, out)
            raise AssertionError("неверный verdict должен падать")
        except ReportError:
            ok += 1
        try:
            bad = dict(case)
            bad["checks"] = [{"name": "x", "result": "y", "risk": "неверно"}]
            build_report(bad, out)
            raise AssertionError("неверный risk должен падать")
        except ReportError:
            ok += 1
    print(f"SELFTEST OK: {ok} проверок пройдено")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("build")
    p.add_argument("--in", dest="infile", required=True)
    p.add_argument("--out", required=True)
    sub.add_parser("selftest")
    return ap


def run(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "selftest":
        return selftest()
    with open(args.infile, encoding="utf-8") as fh:
        case_data = json.load(fh)
    path = build_report(case_data, args.out)
    print(path)
    return 0


def main() -> int:
    try:
        return run(sys.argv[1:])
    except ReportError as e:
        print(f"ОШИБКА: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
