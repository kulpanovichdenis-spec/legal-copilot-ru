# -*- coding: utf-8 -*-
"""Профили оформления .docx: процессуальный, договорные (три варианта) и аналитическая заметка.

Единый источник параметров — references/document-formatting.md (разделы 1-2, 6-7);
техника сборки — references/docx-generation.md. Варианты утверждены юристом
2026-09-15 по присланным образцам; шрифт везде Times New Roman.

  ContractDoc    — «Стандарт»: договоры, ДС, спецификации, NDA. Номера в левой колонке,
                   текст по левому краю одной вертикалью, колонтитул с названием документа.
  IndividualDoc  — «Для физлиц»: договоры с физическими лицами (трудовые, ГПХ, потребительские).
                   Шапка-сетка, ключевые условия карточками, сноски, далее — разметка стандарта.
  RubricDoc      — «Рубрикатор»: оферты и term sheet. Рубрика слева, сквозная нумерация справа,
                   тонкие линии между разделами.
  BilingualDoc   — двуязычные документы (EN | RU) в разметке «Стандарта»: две колонки,
                   строка = смысловая единица, выравнивание по номерам пунктов.
  ProceduralDoc  — процессуальные документы, претензии, ответы госорганам: шапка справа,
                   разделы римскими цифрами, пункты с висячим отступом.
  NoteDoc        — аналитическая заметка юристу.

Модуль отвечает только за форму. Содержание (текст пунктов, реквизиты, маркеры)
передаёт вызывающий скрипт; модуль ничего не дописывает.

Разметка текста: **полужирный**; ^1 — надстрочный номер сноски; маркеры неполноты
в квадратных скобках прописными ([ПРОВЕРИТЬ СРОК], [НАИМЕНОВАНИЕ]) подсвечиваются серой заливкой.

Использование из рабочего скрипта в %TEMP%:

    import sys; sys.path.insert(0, r"<корень legal-copilot>")
    from tools.docx_style.profiles import ContractDoc
    d = ContractDoc()
    d.header("Договор поставки № [ПРОВЕРИТЬ РЕКВИЗИТЫ] от [ПРОВЕРИТЬ ДАТУ]")
    d.title("Договор поставки № [ПРОВЕРИТЬ РЕКВИЗИТЫ]")
    ...
    d.save(r"...\\workflow\\...\\Договор.docx")

CLI:
    python tools/docx_style/profiles.py selftest
    python tools/docx_style/profiles.py demo <папка>   # демо-макеты без фактуры
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
import zipfile

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

FONT = "Times New Roman"
BLACK = RGBColor(0, 0, 0)
GREY = RGBColor(0x59, 0x59, 0x59)  # номера на поле, подписи полей, колонтитул
BORDER = "D9D9D9"        # тонкая светло-серая сетка и разделители
HEADER_FILL = "D9D9D9"   # строка заголовка таблицы данных
ZEBRA_FILL = "F2F2F2"    # чередование строк
MARKER_FILL = "E7E6E6"   # подсветка маркеров неполноты
# маркер неполноты — квадратные скобки без строчных букв: [ПРОВЕРИТЬ СРОК], [ФИО]
MARKER_RE = re.compile(r"(\[[^\]a-zа-яё]*\])")
# порядок дочерних элементов w:tcPr по схеме OOXML
_TCPR_ORDER = ["tcW", "gridSpan", "hMerge", "vMerge", "tcBorders", "shd", "noWrap", "tcMar",
               "textDirection", "tcFitText", "vAlign", "hideMark"]

# Параметры профилей — зеркало references/document-formatting.md, разделы 6-7.
CONTRACT = dict(
    margins_cm=(2.0, 2.0, 1.8, 1.8),  # левое, правое, верхнее, нижнее
    body_pt=11, line=1.15, after_pt=6,
    title_pt=15, subtitle_pt=11, h1_pt=13, h2_pt=11,
    number_pt=8.5, table_pt=10, footer_pt=9, header_pt=8.5,
    number_col_cm=1.3,
)
# Компактные поля — чтобы короткое ДС/соглашение уместилось на 1 страницу
# (поля сужает юрист намеренно).
CONTRACT_COMPACT_MARGINS = (2.25, 1.5, 1.0, 0.5)

# Процессуальный профиль (document-formatting.md, разд. 1-2): иски, отзывы, заявления в суд,
# в т. ч. в деле о банкротстве, ходатайства, жалобы, объяснения, претензии, ответы госорганам.
# Снят с реального иска, который юрист утвердил как стиль копайлота (2026-10-13).
PROCEDURAL = dict(
    margins_cm=(3.0, 1.5, 2.0, 2.0),
    body_pt=12, line=1.3, after_pt=6,
    title_pt=14, subtitle_pt=12, h1_pt=12, h2_pt=12,
    number_pt=12, table_pt=10, footer_pt=10, header_pt=10,
    number_col_cm=0.0,
    head_indent_cm=8.8, head_line=1.1, head_after_pt=2,  # шапка: правый блок, кегль = тексту
    hang_cm=0.8,                                          # висячий отступ нумерованных пунктов
)

NOTE = dict(
    margins_cm=(2.2, 1.8, 1.4, 1.2),
    body_pt=10.5, line=1.05, after_pt=3,
    title_pt=14, subtitle_pt=11, h1_pt=12, h2_pt=11,
    number_pt=8.5, table_pt=9, footer_pt=9, header_pt=8.5,
    number_col_cm=0.0,
)


# ---------- низкоуровневые помощники ----------

def _fonts(rpr):
    rf = rpr.find(qn("w:rFonts"))
    if rf is None:
        rf = OxmlElement("w:rFonts")
        rpr.insert(0, rf)
    for a in ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme", "w:cstheme"):
        if rf.get(qn(a)) is not None:
            del rf.attrib[qn(a)]
    for a in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rf.set(qn(a), FONT)


def _run(p, text, *, size, bold=False, italic=False, grey=False, shade=False, superscript=False):
    r = p.add_run(text)
    r.font.name = FONT
    r.font.size = Pt(size)
    r.font.color.rgb = GREY if grey else BLACK
    r.bold = bold
    r.italic = italic
    if superscript:
        r.font.superscript = True
    rpr = r._element.get_or_add_rPr()
    _fonts(rpr)
    if shade:
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:color"), "auto")
        shd.set(qn("w:fill"), MARKER_FILL)
        rpr.append(shd)
    return r


def _rich(p, text, *, size, bold=False, grey=False):
    """Разметка: **полужирный**, ^1 — надстрочная ссылка на сноску; маркеры неполноты — с заливкой."""
    for i, chunk in enumerate(re.split(r"\*\*", text)):
        b = bold or i % 2 == 1
        for part in re.split(r"(\^\d+)", chunk):
            if not part:
                continue
            if re.fullmatch(r"\^\d+", part):
                _run(p, part[1:], size=max(size - 3, 7), superscript=True, grey=grey)
                continue
            for sub in MARKER_RE.split(part):
                if sub:
                    _run(p, sub, size=size, bold=b, grey=grey, shade=bool(MARKER_RE.fullmatch(sub)))


def _fmt(p, *, after, line, before=0, left=None, right=None, first=None,
         align=WD_ALIGN_PARAGRAPH.LEFT, keep_next=False, keep_lines=False):
    pf = p.paragraph_format
    pf.space_before = Pt(before)
    pf.space_after = Pt(after)
    pf.line_spacing = line
    pf.widow_control = True
    if left is not None:
        pf.left_indent = Cm(left)
    if right is not None:
        pf.right_indent = Cm(right)
    if first is not None:
        pf.first_line_indent = Cm(first)
    pf.keep_with_next = keep_next
    pf.keep_together = keep_lines
    p.alignment = align
    return p


def _style(doc, name, *, size, bold=False, after=0, before=0, line=1.0, keep_next=False):
    st = doc.styles[name]
    st.font.name = FONT
    st.font.size = Pt(size)
    st.font.bold = bold
    st.font.italic = False
    st.font.color.rgb = BLACK
    _fonts(st.element.get_or_add_rPr())
    ppr = st.element.get_or_add_pPr()
    el = ppr.find(qn("w:pBdr"))  # у Title в шаблоне python-docx синяя линия снизу
    if el is not None:
        ppr.remove(el)
    pf = st.paragraph_format
    pf.space_before = Pt(before)
    pf.space_after = Pt(after)
    pf.line_spacing = line
    pf.keep_with_next = keep_next
    return st


def _borders(cell, sides=("top", "left", "bottom", "right"), color=BORDER, sz=4):
    tcpr = cell._tc.get_or_add_tcPr()
    b = OxmlElement("w:tcBorders")
    for side in ("top", "left", "bottom", "right"):
        e = OxmlElement(f"w:{side}")
        if side in sides:
            e.set(qn("w:val"), "single")
            e.set(qn("w:sz"), str(sz))
            e.set(qn("w:color"), color)
        else:
            e.set(qn("w:val"), "nil")
        b.append(e)
    tcpr.append(b)


def _margins(cell, top=90, side=110, bottom=90):
    tcpr = cell._tc.get_or_add_tcPr()
    old = tcpr.find(qn("w:tcMar"))
    if old is not None:
        tcpr.remove(old)
    mar = OxmlElement("w:tcMar")
    for s, w in (("top", top), ("start", side), ("bottom", bottom), ("end", side)):
        e = OxmlElement(f"w:{s}")
        e.set(qn("w:w"), str(w))
        e.set(qn("w:type"), "dxa")
        mar.append(e)
    tcpr.append(mar)


def _cell_borders(cell):
    """Совместимость: полная светло-серая сетка + стандартные поля ячейки."""
    _borders(cell)
    _margins(cell)


def _shade(cell, fill):
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    cell._tc.get_or_add_tcPr().append(shd)


def _row_flag(row, tag):
    trpr = row._tr.get_or_add_trPr()
    e = OxmlElement(tag)
    if tag == "w:tblHeader":
        e.set(qn("w:val"), "true")
    trpr.append(e)


def _fix_widths(table, widths_cm: list[float]):
    """Фиксированная раскладка: ширина таблицы, колонок сетки (tblGrid) и каждой ячейки.
    Без tblLayout=fixed и gridCol Word может растянуть таблицу за правое поле."""
    table.autofit = False
    tblpr = table._tbl.tblPr
    lay = tblpr.find(qn("w:tblLayout"))
    if lay is None:
        lay = OxmlElement("w:tblLayout")
        tblpr.append(lay)
    lay.set(qn("w:type"), "fixed")
    tw = tblpr.find(qn("w:tblW"))
    if tw is None:
        tw = OxmlElement("w:tblW")
        tblpr.append(tw)
    tw.set(qn("w:w"), str(int(round(sum(widths_cm) * 567))))
    tw.set(qn("w:type"), "dxa")
    for col, w in zip(table.columns, widths_cm):
        col.width = Cm(w)
    for row in table.rows:
        for c, w in zip(row.cells, widths_cm):
            c.width = Cm(w)


def _tbl_indent(table, cm_value: float):
    ind = OxmlElement("w:tblInd")
    ind.set(qn("w:w"), str(int(round(cm_value * 567))))
    ind.set(qn("w:type"), "dxa")
    table._tbl.tblPr.append(ind)


def _field(p, instr, *, size, grey=False):
    """Поле Word (PAGE / NUMPAGES): пересчитывается при открытии и печати."""
    r = _run(p, "", size=size, grey=grey)
    for kind, text in (("begin", None), (None, instr), ("separate", None), (None, "1"), ("end", None)):
        if kind:
            fc = OxmlElement("w:fldChar")
            fc.set(qn("w:fldCharType"), kind)
            r._element.append(fc)
        elif text == instr:
            it = OxmlElement("w:instrText")
            it.set(qn("xml:space"), "preserve")
            it.text = f" {instr} "
            r._element.append(it)
        else:
            t = OxmlElement("w:t")
            t.text = text
            r._element.append(t)


# ---------- базовый документ ----------

class _BaseDoc:
    P: dict = CONTRACT

    def __init__(self, *, body_pt: float | None = None, margins_cm: tuple | None = None):
        self.p = dict(self.P)
        if body_pt:
            self.p["body_pt"] = body_pt
        if margins_cm:
            self.p["margins_cm"] = tuple(margins_cm)
        self.doc = Document()
        s = self.doc.sections[0]
        s.page_width, s.page_height = Cm(21.0), Cm(29.7)
        s.left_margin, s.right_margin, s.top_margin, s.bottom_margin = (Cm(x) for x in self.p["margins_cm"])
        self.text_width_cm = 21.0 - self.p["margins_cm"][0] - self.p["margins_cm"][1]
        self.col = self.p["number_col_cm"]
        p = self.p
        _style(self.doc, "Normal", size=p["body_pt"], after=p["after_pt"], line=p["line"])
        _style(self.doc, "Title", size=p["title_pt"], bold=True, after=4, keep_next=True)
        _style(self.doc, "Heading 1", size=p["h1_pt"], bold=True, before=14, after=6, keep_next=True)
        _style(self.doc, "Heading 2", size=p["h2_pt"], bold=True, before=6, after=3, keep_next=True)

    @property
    def body_width_cm(self) -> float:
        return self.text_width_cm - self.col

    def title(self, text: str, *subtitle: str):
        t = self.doc.add_paragraph(style="Title")
        _fmt(t, after=4 if subtitle else 12, line=1.0, align=WD_ALIGN_PARAGRAPH.CENTER, keep_next=True)
        _rich(t, text, size=self.p["title_pt"], bold=True)
        for i, line in enumerate(subtitle):
            s = self.doc.add_paragraph()
            _fmt(s, after=10 if i == len(subtitle) - 1 else 0, line=1.0,
                 align=WD_ALIGN_PARAGRAPH.CENTER, keep_next=True)
            _rich(s, line, size=self.p["subtitle_pt"], bold=True)

    def heading(self, text: str, level: int = 1):
        h = self.doc.add_paragraph(style=f"Heading {level}")
        _fmt(h, before=12 if level == 1 else 6, after=6 if level == 1 else 3, line=1.0,
             align=WD_ALIGN_PARAGRAPH.LEFT, keep_next=True, keep_lines=True)
        _rich(h, text, size=self.p["h1_pt"] if level == 1 else self.p["h2_pt"], bold=True)
        return h

    def para(self, text: str, *, first_line: float = 0.0, after: float | None = None,
             align=WD_ALIGN_PARAGRAPH.JUSTIFY, keep_next=False):
        p = self.doc.add_paragraph()
        _fmt(p, after=self.p["after_pt"] if after is None else after, line=self.p["line"],
             first=first_line, align=align, keep_next=keep_next)
        _rich(p, text, size=self.p["body_pt"])
        return p

    def table(self, header: list[str], rows: list[list[str]], widths_cm: list[float], *,
              zebra: bool = True, center_cols: tuple[int, ...] = (), bold_cols: tuple[int, ...] = ()):
        """Таблица данных в колонке текста: серая строка заголовка повторяется на каждой странице,
        строки не рвутся между страницами. Сумма ширин = ширине колонки текста."""
        if abs(sum(widths_cm) - self.body_width_cm) > 0.3:
            raise ValueError(f"сумма ширин {sum(widths_cm)} см ≠ ширине колонки текста {self.body_width_cm:.2f} см")
        size = self.p["table_pt"]
        t = self.doc.add_table(rows=1 + len(rows), cols=len(header))
        _fix_widths(t, widths_cm)
        if self.col:
            _tbl_indent(t, self.col)
        else:
            t.alignment = WD_TABLE_ALIGNMENT.CENTER
        for ri, values in enumerate([header] + rows):
            row = t.rows[ri]
            _row_flag(row, "w:tblHeader" if ri == 0 else "w:cantSplit")
            for ci, val in enumerate(values):
                c = row.cells[ci]
                c.width = Cm(widths_cm[ci])
                c.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
                _cell_borders(c)
                if ri == 0:
                    _shade(c, HEADER_FILL)
                elif zebra and ri % 2 == 0:
                    _shade(c, ZEBRA_FILL)
                cp = c.paragraphs[0]
                centered = ri == 0 or ci in center_cols
                _fmt(cp, after=0, line=1.0, align=WD_ALIGN_PARAGRAPH.CENTER if centered else WD_ALIGN_PARAGRAPH.LEFT)
                _rich(cp, val, size=size, bold=ri == 0 or ci in bold_cols)
        self.doc.add_paragraph().paragraph_format.space_after = Pt(2)
        return t

    def header(self, text: str):
        """Верхний колонтитул на каждой странице: название и дата документа, мелко серым."""
        h = self.doc.sections[0].header.paragraphs[0]
        _fmt(h, after=0, line=1.0, align=WD_ALIGN_PARAGRAPH.LEFT)
        _rich(h, text, size=self.p["header_pt"], bold=True, grey=True)

    def save(self, path: str):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        order = {name: i for i, name in enumerate(_TCPR_ORDER)}
        for tcpr in self.doc.element.body.iter(qn("w:tcPr")):
            kids = list(tcpr)
            kids.sort(key=lambda el: order.get(el.tag.split("}")[1], len(order)))
            for el in kids:
                tcpr.remove(el)
                tcpr.append(el)
        self.doc.save(path)
        return path


# ---------- «Стандарт» ----------

class ContractDoc(_BaseDoc):
    """Вариант «Стандарт»: договор, ДС, спецификация, приложение, соглашение о расторжении, NDA."""
    P = CONTRACT
    # текст пунктов по ширине, название — на вертикали текста (правки юриста к ДС, 2026-09-24)
    ALIGN = WD_ALIGN_PARAGRAPH.JUSTIFY
    TITLE_IN_COLUMN = True

    def __init__(self, *, compact: bool = False, **kw):
        """compact=True — узкие поля, чтобы короткий документ уместился на одну страницу."""
        if compact:
            kw.setdefault("margins_cm", CONTRACT_COMPACT_MARGINS)
        super().__init__(**kw)
        self.compact = compact

    def title(self, text: str, *subtitle: str):
        t = self.doc.add_paragraph(style="Title")
        left = self.col if self.TITLE_IN_COLUMN else None
        _fmt(t, after=2 if subtitle else 10, line=1.0, left=left, align=WD_ALIGN_PARAGRAPH.LEFT, keep_next=True)
        _rich(t, text, size=self.p["title_pt"], bold=True)
        for i, line in enumerate(subtitle):
            s = self.doc.add_paragraph()
            _fmt(s, after=10 if i == len(subtitle) - 1 else 0, line=1.0, left=left,
                 align=WD_ALIGN_PARAGRAPH.LEFT, keep_next=True)
            _rich(s, line, size=self.p["subtitle_pt"], bold=True)

    def place_date(self, place: str, date: str):
        p = self.doc.add_paragraph()
        _fmt(p, after=12, line=1.0)
        p.paragraph_format.tab_stops.add_tab_stop(Cm(self.text_width_cm), WD_TAB_ALIGNMENT.RIGHT)
        _rich(p, f"{place}\t{date}", size=self.p["body_pt"])

    def preamble(self, text: str):
        """Преамбула в колонке текста; определяемые термины при первом введении — **«Поставщик»**."""
        p = self.doc.add_paragraph()
        _fmt(p, after=10, line=self.p["line"], left=self.col, align=self.ALIGN)
        _rich(p, text, size=self.p["body_pt"])
        return p

    def section(self, number: str, title: str):
        """Раздел: номер мелко серым в левой колонке, заголовок жирным (стиль Heading 1 — навигация).
        number="" — раздел без номера (при сквозной нумерации пунктов)."""
        h = self.doc.add_paragraph(style="Heading 1")
        _fmt(h, before=14, after=6, line=1.0, left=self.col, first=-self.col if number else 0,
             keep_next=True, keep_lines=True)
        if number:
            h.paragraph_format.tab_stops.add_tab_stop(Cm(self.col))
            _run(h, f"{number}\t", size=self.p["number_pt"] + 0.5, grey=True)
        _rich(h, title, size=self.p["h1_pt"], bold=True)
        return h

    def heading(self, text: str, level: int = 1):
        """Совместимость: «1. Предмет» → section("1.", "Предмет"); level=2 — подзаголовок в колонке."""
        if level == 1:
            m = re.match(r"^\s*(\d+(?:\.\d+)*\.?)\s+(.*)$", text)
            return self.section(m.group(1), m.group(2)) if m else self.section("", text)
        h = self.doc.add_paragraph(style="Heading 2")
        _fmt(h, before=6, after=3, line=1.0, left=self.col, keep_next=True, keep_lines=True)
        _rich(h, text, size=self.p["h2_pt"], bold=True)
        return h

    def clause(self, number: str, text: str, *, keep_next: bool = False):
        """Пункт: номер («1.1.», «1.1.1.» или «7.») мелко серым в колонке, текст — на общей вертикали."""
        p = self.doc.add_paragraph()
        _fmt(p, after=self.p["after_pt"], line=self.p["line"], left=self.col, first=-self.col, keep_next=keep_next,
             align=self.ALIGN)
        p.paragraph_format.tab_stops.add_tab_stop(Cm(self.col))
        _run(p, f"{number}\t", size=self.p["number_pt"], grey=True)
        _rich(p, text, size=self.p["body_pt"])
        return p

    def text(self, body: str, *, keep_next: bool = False):
        """Абзац без номера в колонке текста."""
        p = self.doc.add_paragraph()
        _fmt(p, after=self.p["after_pt"], line=self.p["line"], left=self.col, keep_next=keep_next, align=self.ALIGN)
        _rich(p, body, size=self.p["body_pt"])
        return p

    def bullet(self, body: str):
        """Подпункт-маркер с дополнительным отступом внутри колонки текста."""
        p = self.doc.add_paragraph()
        left = self.col + 1.0
        _fmt(p, after=4, line=self.p["line"], left=left, first=-0.6, align=self.ALIGN)
        p.paragraph_format.tab_stops.add_tab_stop(Cm(left))
        _run(p, "▪\t", size=9, grey=True)
        _rich(p, body, size=self.p["body_pt"])
        return p

    def quoted(self, paragraphs: list[str]):
        """Новая редакция пункта в ДС: блок с дополнительным отступом, строки блока не разрываются."""
        for i, body in enumerate(paragraphs):
            last = i == len(paragraphs) - 1
            p = self.doc.add_paragraph()
            _fmt(p, after=7 if last else 4, line=self.p["line"], left=self.col + 0.5, right=0.4,
                 first=0.7 if i == 0 else 0.0, align=self.ALIGN, keep_lines=True)
            _rich(p, body, size=self.p["body_pt"])

    def signatures(self, parties: list[dict], heading: str = "Реквизиты и подписи сторон"):
        """parties: [{role, name, details: [..], signatory, stamp=True}] — сетка D9D9D9 в колонке текста,
        блок не разрывается. stamp=False — без «М. П.» (физическое лицо). Незаполненное — маркерами."""
        h = self.doc.add_paragraph()
        _fmt(h, before=16, after=6, line=1.0, left=self.col, keep_next=True)
        _run(h, heading, size=self.p["h1_pt"], bold=True)
        n = len(parties)
        t = self.doc.add_table(rows=1, cols=n)
        _fix_widths(t, [self.body_width_cm / n] * n)
        if self.col:
            _tbl_indent(t, self.col)
        _row_flag(t.rows[0], "w:cantSplit")
        size = self.p["table_pt"]
        for ci, party in enumerate(parties):
            c = t.rows[0].cells[ci]
            c.width = Cm(self.body_width_cm / n)
            _cell_borders(c)
            lines = [(party["role"], True), (party.get("name", ""), True)]
            lines += [(d, False) for d in party.get("details", [])]
            lines += [("", False), (party.get("signatory", ""), False), ("", False),
                      ("_______________ / _________________", False)]
            if party.get("stamp", True):
                lines.append(("М. П.", False))
            for li, (body, bold) in enumerate(lines):
                cp = c.paragraphs[0] if li == 0 else c.add_paragraph()
                _fmt(cp, after=0, line=1.0, keep_next=True)
                _rich(cp, body, size=size, bold=bold)
        return t

    def footer(self, roles: list[str] | None = None, *, page_numbers: bool = True):
        """Нижний колонтитул: строка визирования сторонами (roles) и номер страницы «X | Y» справа."""
        ft = self.doc.sections[0].footer
        p = ft.paragraphs[0]
        size = self.p["footer_pt"]
        if roles:
            _fmt(p, after=0, before=3, line=1.0, align=WD_ALIGN_PARAGRAPH.CENTER)
            _run(p, "     ".join(f"{r} ____________________" for r in roles), size=size)
            p = ft.add_paragraph()
        if page_numbers:
            _fmt(p, after=0, line=1.0, align=WD_ALIGN_PARAGRAPH.RIGHT)
            _field(p, "PAGE", size=size)
            _run(p, "  |  ", size=size, grey=True)
            _field(p, "NUMPAGES", size=size)


# ---------- «Для физлиц» ----------

class IndividualDoc(ContractDoc):
    """Вариант «Для физлиц»: трудовые, ГПХ, потребительские договоры с физическими лицами.
    Шапка-сетка и ключевые условия карточками (без иконок), пояснения сносками;
    остальной текст — в разметке «Стандарта»."""
    ALIGN = WD_ALIGN_PARAGRAPH.LEFT      # вариант утверждён с выравниванием по левому краю
    TITLE_IN_COLUMN = False

    def _grid(self, rows: int, widths: list[float]):
        t = self.doc.add_table(rows=rows, cols=len(widths))
        _fix_widths(t, widths)
        for r in t.rows:
            _row_flag(r, "w:cantSplit")
            for c in r.cells:
                _borders(c)
                _margins(c, top=100, side=140, bottom=100)
                c.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.TOP
        return t

    def _gap(self, pt: float = 8):
        p = self.doc.add_paragraph()
        _fmt(p, after=pt, line=1.0)
        _run(p, "", size=4)

    def _fill(self, cell, lines: list[tuple[str, str]]):
        """lines: ("caption", подпись поля) / ("key", главное значение) / ("value", значение) /
        ("bullet", пункт перечня) / ("title", название документа)."""
        for li, (kind, body) in enumerate(lines):
            p = cell.paragraphs[0] if li == 0 else cell.add_paragraph()
            if kind == "caption":
                _fmt(p, after=2, line=1.0, keep_next=True)
                _rich(p, body, size=9, grey=True)
            elif kind in ("value", "key"):
                _fmt(p, after=0, line=1.1, keep_next=True)
                _rich(p, body, size=13 if kind == "key" else 11.5, bold=kind == "key")
            elif kind == "bullet":
                _fmt(p, after=0, line=1.1, left=0.5, first=-0.4, keep_next=True)
                p.paragraph_format.tab_stops.add_tab_stop(Cm(0.5))
                _run(p, "•\t", size=10)
                _rich(p, body, size=11)
            elif kind == "title":
                _fmt(p, after=4, line=1.0, keep_next=True)
                _rich(p, body, size=16, bold=True)
            else:
                raise ValueError(f"неизвестный тип строки карточки: {kind}")

    def head(self, title: str, place: str, date: str,
             left_party: list[tuple[str, str]], right_party: list[tuple[str, str]]):
        """Шапка-сетка: название | город и дата; сторона 1 | сторона 2."""
        w = self.text_width_cm / 2
        t = self._grid(2, [w, w])
        self._fill(t.rows[0].cells[0], [("title", title)])
        self._fill(t.rows[0].cells[1], [("value", place), ("value", date)])
        self._fill(t.rows[1].cells[0], left_party)
        self._fill(t.rows[1].cells[1], right_party)
        self._gap()
        return t

    def cards(self, pairs: list[tuple[list, list]]):
        """Блок карточек ключевых условий в две колонки: [(левая, правая), ...]."""
        w = self.text_width_cm / 2
        t = self._grid(len(pairs), [w, w])
        for r, (lft, rgt) in zip(t.rows, pairs):
            self._fill(r.cells[0], lft)
            self._fill(r.cells[1], rgt)
        self._gap()
        return t

    def box(self, lines: list[tuple[str, str]]):
        """Рамка на всю ширину (например, перечень приложений)."""
        t = self._grid(1, [self.text_width_cm])
        self._fill(t.rows[0].cells[0], lines)
        self._gap()
        return t

    def notes(self, items: list[tuple[int, str]]):
        """Сноски-пояснения под чертой; ссылки в тексте — разметкой ^1."""
        p = self.doc.add_paragraph()
        _fmt(p, after=2, line=1.0)
        _run(p, "_" * 28, size=8, grey=True)
        for n, body in items:
            q = self.doc.add_paragraph()
            _fmt(q, after=0, line=1.0)
            _run(q, str(n), size=7, superscript=True)
            _rich(q, " " + body, size=9)
        self._gap(10)


# ---------- «Рубрикатор» ----------

class RubricDoc(ContractDoc):
    """Вариант «Рубрикатор»: оферты и term sheet. Рубрика слева, сквозная нумерация
    пунктов справа, тонкая линия над каждым разделом; разделы могут переходить на следующую страницу."""
    ALIGN = WD_ALIGN_PARAGRAPH.LEFT      # вариант утверждён с выравниванием по левому краю
    TITLE_IN_COLUMN = False

    RUBRIC_CM = 4.0

    def __init__(self, **kw):
        super().__init__(**kw)
        self.counter = 0

    def title(self, text: str, *subtitle: str):
        t = self.doc.add_paragraph(style="Title")
        _fmt(t, after=2, line=1.0, keep_next=True)
        _rich(t, text, size=18, bold=True)
        for line in subtitle:
            s = self.doc.add_paragraph()
            _fmt(s, after=8, line=1.0, keep_next=True)
            _rich(s, line, size=9, grey=True)

    def lead(self, body: str):
        """Вводный абзац на всю ширину (например, «Дата публикации: …» или суть оферты)."""
        p = self.doc.add_paragraph()
        _fmt(p, after=8, line=self.p["line"])
        _rich(p, body, size=self.p["body_pt"])
        return p

    def rubric(self, name: str, items: list, *, numbered: bool = True):
        """Раздел-строка: name — рубрика слева; items — str (пункт) или ("bullet", текст) / ("text", текст).
        numbered=False — без номеров (term sheet: «параметр — значение»)."""
        t = self.doc.add_table(rows=1, cols=2)
        _fix_widths(t, [self.RUBRIC_CM, self.text_width_cm - self.RUBRIC_CM])
        left, right = t.rows[0].cells
        for c in (left, right):
            _borders(c, sides=("top",))
            _margins(c, top=120, side=0, bottom=60)
        lp = left.paragraphs[0]
        _fmt(lp, after=0, line=1.1, right=0.3, keep_next=True)
        _rich(lp, name, size=self.p["body_pt"], bold=True)
        hang = 0.8
        for ii, item in enumerate(items):
            kind, body = ("clause", item) if isinstance(item, str) else item
            p = right.paragraphs[0] if ii == 0 else right.add_paragraph()
            if kind == "clause" and numbered:
                self.counter += 1
                _fmt(p, after=6, line=self.p["line"], left=hang, first=-hang)
                p.paragraph_format.tab_stops.add_tab_stop(Cm(hang))
                _run(p, f"{self.counter}.\t", size=self.p["body_pt"])
            elif kind == "bullet":
                _fmt(p, after=3, line=self.p["line"], left=hang + 0.6, first=-0.5)
                p.paragraph_format.tab_stops.add_tab_stop(Cm(hang + 0.6))
                _run(p, "•\t", size=10)
            else:
                _fmt(p, after=6, line=self.p["line"], left=hang if numbered else 0)
            _rich(p, body, size=self.p["body_pt"])
        return t

    def signatures(self, parties: list[dict], heading: str = "Реквизиты и подписи сторон"):
        self.col = 0.0
        try:
            return super().signatures(parties, heading)
        finally:
            self.col = self.p["number_col_cm"]


# ---------- двуязычные документы (EN | RU) ----------

_CLAUSE_NUM_RE = re.compile(r"^(\d+\.\d+(?:\.\d+)*\.)\s*(.*)$", re.S)
_SECTION_NUM_RE = re.compile(r"^(\d+\.)\s+(.*)$", re.S)


def _clause_units(paragraphs: list) -> list[list]:
    """Группы абзацев по номерам пунктов («3.1.»): абзацы без номера примыкают к текущему пункту."""
    groups, cur = [], []
    for item in paragraphs:
        text = item[0] if isinstance(item, tuple) else item
        if _CLAUSE_NUM_RE.match(text) and cur:
            groups.append(cur)
            cur = []
        cur.append(item)
    if cur:
        groups.append(cur)
    return groups


class BilingualDoc(ContractDoc):
    """Двуязычный документ в разметке «Стандарта» (document-formatting.md 6.5): две колонки
    (по умолчанию EN слева, RU справа), строка = смысловая единица; номера пунктов мелко серым
    с висячим отступом внутри каждой колонки. Текст пунктов передаётся как есть: модуль
    только раскладывает его по колонкам и не меняет формулировок."""
    ALIGN = WD_ALIGN_PARAGRAPH.LEFT      # вариант утверждён с выравниванием по левому краю
    TITLE_IN_COLUMN = False

    P = dict(CONTRACT, body_pt=10, line=1.1, after_pt=4, number_pt=8, number_col_cm=0.0)
    GAP_CM = 0.6
    HANG_CM = 0.9
    SPLIT_CHARS = 900  # строку длиннее (EN+RU) разрешено разрывать между страницами

    @property
    def col_width_cm(self) -> float:
        return (self.text_width_cm - self.GAP_CM) / 2

    def _pair_row(self, *, can_split: bool):
        t = self.doc.add_table(rows=1, cols=3)
        _fix_widths(t, [self.col_width_cm, self.GAP_CM, self.col_width_cm])
        row = t.rows[0]
        if not can_split:
            _row_flag(row, "w:cantSplit")
        for c in row.cells:
            _margins(c, top=0, side=0, bottom=0)
        return row.cells[0], row.cells[2]

    def _write(self, cell, paragraphs: list):
        """paragraphs: str или (текст, is_list)."""
        size, hang = self.p["body_pt"], self.HANG_CM
        for i, item in enumerate(paragraphs):
            text, is_list = (item, False) if isinstance(item, str) else item
            p = cell.paragraphs[0] if i == 0 else cell.add_paragraph()
            m = _CLAUSE_NUM_RE.match(text)
            if is_list:
                _fmt(p, after=2, line=self.p["line"], left=hang + 0.5, first=-0.45)
                p.paragraph_format.tab_stops.add_tab_stop(Cm(hang + 0.5))
                _run(p, "▪\t", size=8, grey=True)
                _rich(p, text, size=size)
            elif m:
                _fmt(p, after=self.p["after_pt"], line=self.p["line"], left=hang, first=-hang)
                p.paragraph_format.tab_stops.add_tab_stop(Cm(hang))
                _run(p, m.group(1) + "\t", size=self.p["number_pt"], grey=True)
                _rich(p, m.group(2), size=size)
            else:
                _fmt(p, after=self.p["after_pt"], line=self.p["line"], left=hang)
                _rich(p, text, size=size)

    def title(self, text: str, *subtitle: str):
        super().title(text, *subtitle)

    def parties(self, left_lines: list[str], right_lines: list[str]):
        """Стороны и реквизиты: сетка D9D9D9 в две колонки, первая строка каждой — полужирным."""
        t = self.doc.add_table(rows=1, cols=2)
        _fix_widths(t, [self.text_width_cm / 2] * 2)
        _row_flag(t.rows[0], "w:cantSplit")
        for c, lines in zip(t.rows[0].cells, (left_lines, right_lines)):
            _borders(c)
            _margins(c, top=90, side=120, bottom=90)
            for i, text in enumerate(lines):
                p = c.paragraphs[0] if i == 0 else c.add_paragraph()
                _fmt(p, after=1, line=1.05, keep_next=True)
                _rich(p, text, size=self.p["body_pt"], bold=i == 0)
        gap = self.doc.add_paragraph()
        _fmt(gap, after=4, line=1.0)
        return t

    def section(self, left: str, right: str):
        """Заголовок раздела на двух языках: «1. Goods and Price» | «1. Товар и Цена»."""
        lc, rc = self._pair_row(can_split=False)
        for cell, text in ((lc, left), (rc, right)):
            p = cell.paragraphs[0]
            m = _SECTION_NUM_RE.match(text)
            _fmt(p, before=12, after=4, line=1.0, left=self.HANG_CM, first=-self.HANG_CM if m else 0,
                 keep_next=True, keep_lines=True)
            if m:
                p.paragraph_format.tab_stops.add_tab_stop(Cm(self.HANG_CM))
                _run(p, m.group(1) + "\t", size=self.p["number_pt"] + 0.5, grey=True)
            _rich(p, m.group(2) if m else text, size=12, bold=True)
        # стиль Heading 1 на левой колонке — навигация по разделам
        lp = lc.paragraphs[0]
        pf = lp.paragraph_format
        saved = (pf.left_indent, pf.first_line_indent, pf.space_before, pf.space_after)
        lp.style = self.doc.styles["Heading 1"]
        pf.left_indent, pf.first_line_indent, pf.space_before, pf.space_after = saved
        return lc, rc

    def pair(self, left: str, right: str):
        """Одна строка: абзац слева — абзац справа."""
        lc, rc = self._pair_row(can_split=len(left) + len(right) > self.SPLIT_CHARS)
        self._write(lc, [left])
        self._write(rc, [right])

    def block(self, left_paragraphs: list, right_paragraphs: list):
        """Текст раздела на двух языках с выравниванием: по номерам пунктов, а внутри пункта —
        абзац напротив абзаца, если их число совпадает; иначе пункт — одной строкой."""
        ul, ur = _clause_units(left_paragraphs), _clause_units(right_paragraphs)
        if len(ul) != len(ur):
            lc, rc = self._pair_row(can_split=True)
            self._write(lc, left_paragraphs)
            self._write(rc, right_paragraphs)
            return
        for gl, gr in zip(ul, ur):
            if len(gl) == len(gr):
                for pl, pr in zip(gl, gr):
                    tl = pl if isinstance(pl, str) else pl[0]
                    tr = pr if isinstance(pr, str) else pr[0]
                    lc, rc = self._pair_row(can_split=len(tl) + len(tr) > self.SPLIT_CHARS)
                    self._write(lc, [pl])
                    self._write(rc, [pr])
            else:
                lc, rc = self._pair_row(can_split=True)
                self._write(lc, gl)
                self._write(rc, gr)

    def data_table(self, header: list[str], rows: list[list[str]], widths_cm: list[float],
                   *, center_cols: tuple[int, ...] = (0,)):
        """Таблица данных на всю ширину с двуязычными заголовками (заголовок повторяется при переносе)."""
        return self.table(header, rows, widths_cm, zebra=False, center_cols=center_cols)

    def signatures(self, left_lines: list[str], right_lines: list[str]):
        """Подписи: сетка D9D9D9 в две колонки, строки — как в документе (роль, подписант, «Печать» и т. п.)."""
        h = self.doc.add_paragraph()
        _fmt(h, before=14, after=4, line=1.0, keep_next=True)
        return self.parties(left_lines, right_lines)


# ---------- профиль аналитической заметки ----------

def _nb(text: str) -> str:
    """Неразрывные пробелы, чтобы суммы и номера не рвались по строкам:
    разряды чисел («1 339 560,00»), «№ 874», «5 464 851,27 руб.»."""
    text = re.sub(r"(?<=\d) (?=\d{3}(?:\D|$))", " ", text)
    text = re.sub(r"(?<=\d) (?=\d{3}(?:\D|$))", " ", text)
    text = text.replace("№ ", "№ ")
    text = re.sub(r"(?<=\d) (?=(?:руб|коп)\.)", " ", text)
    return text


class ProceduralDoc(_BaseDoc):
    """Процессуальный документ, претензия, ответ госоргану.

    Шапка — блок справа кеглем основного текста; заголовок по центру; разделы римскими
    цифрами («I. ОБСТОЯТЕЛЬСТВА ДЕЛА»), подразделы «2.1.»; факты, просительная часть и
    приложения — пункты с висячим отступом (номер литералом + табуляция, без автонумерации).
    Суммы и номера автоматически получают неразрывные пробелы.
    """
    P = PROCEDURAL

    def para(self, text: str, **kw):
        return super().para(_nb(text), **kw)

    def table(self, header: list[str], rows: list[list[str]], widths_cm: list[float], *,
              right_cols: tuple[int, ...] = (), **kw):
        """Таблица расчёта; right_cols — колонки сумм, выравниваются по правому краю."""
        t = super().table(header, [[_nb(v) for v in r] for r in rows], widths_cm, **kw)
        for cell in t.rows[0].cells:  # заголовок таблицы не остаётся один внизу страницы
            cell.paragraphs[0].paragraph_format.keep_with_next = True
        for row in t.rows[1:]:
            for ci in right_cols:
                row.cells[ci].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT
        return t

    def head(self, *blocks: list[str]):
        """Шапка: блоки строк (суд, стороны, цена/размер требования), между блоками пустая строка.
        Ярлык строки выделяется разметкой: «**Истец:** ООО …»."""
        p = self.p
        for bi, lines in enumerate(blocks):
            if bi:
                gap = self.doc.add_paragraph()
                _fmt(gap, after=0, line=p["head_line"], left=p["head_indent_cm"])
            for line in lines:
                para = self.doc.add_paragraph()
                _fmt(para, after=p["head_after_pt"], line=p["head_line"], left=p["head_indent_cm"],
                     align=WD_ALIGN_PARAGRAPH.LEFT)
                _rich(para, _nb(line), size=p["body_pt"])
        tail = self.doc.add_paragraph()
        _fmt(tail, after=4, line=1.0)

    def title(self, text: str, *subtitle: str):
        t = self.doc.add_paragraph()
        _fmt(t, before=6, after=2 if subtitle else 8, line=1.15, align=WD_ALIGN_PARAGRAPH.CENTER, keep_next=True)
        _rich(t, text, size=self.p["title_pt"], bold=True)
        for i, line in enumerate(subtitle):
            s = self.doc.add_paragraph()
            _fmt(s, after=8 if i == len(subtitle) - 1 else 0, line=1.15,
                 align=WD_ALIGN_PARAGRAPH.CENTER, keep_next=True)
            _rich(s, line, size=self.p["subtitle_pt"], bold=True)

    def section(self, text: str):
        """Раздел («I. ОБСТОЯТЕЛЬСТВА ДЕЛА») или подраздел («2.1. …»), а также «Приложения:»."""
        h = self.doc.add_paragraph()
        _fmt(h, before=10, after=4, line=1.15, align=WD_ALIGN_PARAGRAPH.LEFT, keep_next=True, keep_lines=True)
        _rich(h, _nb(text), size=self.p["h1_pt"], bold=True)
        return h

    heading = section

    def point(self, number: str, text: str, *, level: int = 1):
        """Пункт с висячим отступом: факты, просительная часть, приложения."""
        hang = self.p["hang_cm"]
        p = self.doc.add_paragraph()
        _fmt(p, after=self.p["after_pt"], line=self.p["line"], left=hang * level, first=-hang,
             align=WD_ALIGN_PARAGRAPH.JUSTIFY)
        p.paragraph_format.tab_stops.add_tab_stop(Cm(hang * level))
        _run(p, f"{number}\t", size=self.p["body_pt"])
        _rich(p, _nb(text), size=self.p["body_pt"])
        return p

    def prayer(self, text: str = "ПРОШУ:"):
        p = self.doc.add_paragraph()
        _fmt(p, before=6, after=4, line=1.15, align=WD_ALIGN_PARAGRAPH.CENTER, keep_next=True)
        _rich(p, text, size=self.p["body_pt"], bold=True)
        return p

    def signature(self, lines: list[str], date: str = "«___» ____________ 20__ г.", *,
                  image: str | None = None, image_height_cm: float = 1.3):
        """Подпись: строки должности/представителя, последняя — «______ / И. О. Фамилия».
        image — изображение собственной подписи подписанта, переданное им самим: ставится в последнюю
        строку перед расшифровкой вместо линии."""
        gap = self.doc.add_paragraph()
        _fmt(gap, after=8, line=1.0)
        for i, line in enumerate(lines):
            last = i == len(lines) - 1
            p = self.doc.add_paragraph()
            _fmt(p, before=10 if last and i else 0, after=0, line=1.0 if (last and image) else 1.15,
                 keep_next=not last)
            if last and image:
                p.add_run().add_picture(image, height=Cm(image_height_cm))
                line = " " + re.sub(r"^[_\s]*/?\s*", "", line)
            _rich(p, _nb(line), size=self.p["body_pt"])
        d = self.doc.add_paragraph()
        _fmt(d, before=10, after=0, line=1.15)
        _rich(d, date, size=self.p["body_pt"])

    def footer(self, *, page_numbers: bool = True):
        if page_numbers:
            p = self.doc.sections[0].footer.paragraphs[0]
            _fmt(p, after=0, line=1.0, align=WD_ALIGN_PARAGRAPH.CENTER)
            _field(p, "PAGE", size=self.p["footer_pt"])


class NoteDoc(_BaseDoc):
    """Заметка юристу, анализ, заключение-памятка, лист проверки."""
    P = NOTE

    def bullet(self, text: str):
        p = self.doc.add_paragraph()
        _fmt(p, after=3, line=self.p["line"], left=0.8, first=-0.45, align=WD_ALIGN_PARAGRAPH.JUSTIFY)
        p.paragraph_format.tab_stops.add_tab_stop(Cm(0.8))
        _run(p, "•\t", size=self.p["body_pt"])
        _rich(p, text, size=self.p["body_pt"])
        return p

    def footer(self, *, page_numbers: bool = True):
        if page_numbers:
            p = self.doc.sections[0].footer.paragraphs[0]
            _fmt(p, after=0, line=1.0, align=WD_ALIGN_PARAGRAPH.CENTER)
            _field(p, "PAGE", size=self.p["footer_pt"])


# ---------- демо и самопроверка ----------

def demo(folder: str) -> list[str]:
    """Макеты без фактуры сделки: только форма, всё содержательное — маркерами."""
    out = []

    c = ContractDoc()
    c.header("Договор поставки № [ПРОВЕРИТЬ РЕКВИЗИТЫ] от [ПРОВЕРИТЬ ДАТУ]")
    c.title("Договор поставки № [ПРОВЕРИТЬ РЕКВИЗИТЫ]")
    c.place_date("г. [ПРОВЕРИТЬ ФАКТ]", "«__» ________ 20__ г.")
    c.preamble("[НАИМЕНОВАНИЕ], именуемое в дальнейшем **«Поставщик»**, в лице [ПРОВЕРИТЬ РЕКВИЗИТЫ], "
               "и [НАИМЕНОВАНИЕ], именуемое в дальнейшем **«Покупатель»**, в лице [ПРОВЕРИТЬ РЕКВИЗИТЫ], "
               "заключили настоящий договор (далее — **«Договор»**) о нижеследующем:")
    c.section("1.", "Предмет и модель работы")
    c.clause("1.1.", "Поставщик поставляет товар партиями по заявкам Покупателя, а Покупатель принимает и оплачивает его.")
    c.clause("1.2.", "Наименование, количество и цена товара согласуются в спецификации (Приложение № 1).")
    c.section("2.", "Заказы и поставка")
    c.clause("2.1.", "Покупатель направляет заявку, в которой указывает:", keep_next=True)
    c.bullet("наименование и количество товара;")
    c.bullet("адрес и желаемую дату поставки [ПРОВЕРИТЬ СРОК].")
    c.clause("2.2.", "Поставщик передаёт вместе с товаром следующие документы:", keep_next=True)
    c.table(["Документ", "Кто передаёт", "Срок"],
            [["[ПРОВЕРИТЬ ФАКТ]", "Поставщик", "[ПРОВЕРИТЬ СРОК]"],
             ["[ПРОВЕРИТЬ ФАКТ]", "Поставщик", "[ПРОВЕРИТЬ СРОК]"]],
            [7.0, 4.0, 4.7])
    c.signatures([
        {"role": "Поставщик", "name": "[НАИМЕНОВАНИЕ]",
         "details": ["ИНН [ПРОВЕРИТЬ РЕКВИЗИТЫ] / КПП [ПРОВЕРИТЬ РЕКВИЗИТЫ]", "ОГРН [ПРОВЕРИТЬ РЕКВИЗИТЫ]"],
         "signatory": "[ДОЛЖНОСТЬ]"},
        {"role": "Покупатель", "name": "[НАИМЕНОВАНИЕ]",
         "details": ["ИНН [ПРОВЕРИТЬ РЕКВИЗИТЫ] / КПП [ПРОВЕРИТЬ РЕКВИЗИТЫ]", "ОГРН [ПРОВЕРИТЬ РЕКВИЗИТЫ]"],
         "signatory": "[ДОЛЖНОСТЬ]"},
    ])
    c.footer(["Поставщик", "Покупатель"])
    out.append(c.save(os.path.join(folder, "demo_contract_standard.docx")))

    ds = ContractDoc(compact=True)
    ds.title("Дополнительное соглашение № [N]", "к Договору [ВИД] № [ПРОВЕРИТЬ РЕКВИЗИТЫ] от [ПРОВЕРИТЬ ДАТУ]")
    ds.place_date("г. [ПРОВЕРИТЬ ФАКТ]", "«__» ________ 20__ г.")
    ds.preamble("[НАИМЕНОВАНИЕ], именуемое в дальнейшем **«Поставщик»**, и [НАИМЕНОВАНИЕ], именуемое "
                "в дальнейшем **«Покупатель»**, заключили настоящее соглашение о нижеследующем:")
    ds.clause("1.", "Изложить пункт [X.X] Договора в следующей редакции:", keep_next=True)
    ds.quoted(["«[X.X]. [Новая редакция — абзац 1.]", "[Новая редакция — абзац 2.]»"])
    ds.clause("2.", "Настоящее Соглашение вступает в силу с момента его подписания обеими Сторонами.")
    out.append(ds.save(os.path.join(folder, "demo_amendment_compact.docx")))

    iv = IndividualDoc()
    iv.header("Трудовой договор № [ПРОВЕРИТЬ РЕКВИЗИТЫ] от [ПРОВЕРИТЬ ДАТУ]")
    iv.head("Трудовой договор № [ПРОВЕРИТЬ РЕКВИЗИТЫ]", "г. [ПРОВЕРИТЬ ФАКТ]", "[ПРОВЕРИТЬ ДАТУ]",
            [("caption", "Работодатель"), ("value", "[НАИМЕНОВАНИЕ]"), ("value", "в лице [ПРОВЕРИТЬ РЕКВИЗИТЫ]")],
            [("caption", "Работник"), ("value", "[ФИО]")])
    iv.cards([
        ([("caption", "Должность^1"), ("key", "[ПРОВЕРИТЬ ФАКТ]")],
         [("caption", "Заработная плата"), ("key", "[ПРОВЕРИТЬ РАЗМЕР] руб.")]),
        ([("caption", "Дата начала работы"), ("value", "[ПРОВЕРИТЬ ДАТУ]")],
         [("caption", "Выплата заработной платы"), ("value", "до [ПРОВЕРИТЬ СРОК] числа^2")]),
    ])
    iv.notes([(1, "Трудовая функция определяется в Приложении № 1."), (2, "За первую половину месяца.")])
    iv.section("", "Начало работы и оплата труда")
    iv.clause("1.", "Работник приступает к работе с даты, указанной в карточке «Дата начала работы».")
    iv.signatures([
        {"role": "Работодатель", "name": "[НАИМЕНОВАНИЕ]", "details": ["ИНН [ПРОВЕРИТЬ РЕКВИЗИТЫ]"], "signatory": "[ДОЛЖНОСТЬ]"},
        {"role": "Работник", "name": "[ФИО]", "details": ["паспорт [ПРОВЕРИТЬ РЕКВИЗИТЫ]"], "stamp": False},
    ])
    iv.footer()
    out.append(iv.save(os.path.join(folder, "demo_individual.docx")))

    rb = RubricDoc()
    rb.header("Оферта на заключение договора оказания услуг от [ПРОВЕРИТЬ ДАТУ]")
    rb.title("Оферта на заключение договора оказания услуг", "далее — Оферта")
    rb.lead("Дата публикации: [ПРОВЕРИТЬ ДАТУ]")
    rb.lead("Оферта является предложением [НАИМЕНОВАНИЕ] (далее — **«Исполнитель»**) заключить договор оказания услуг "
            "с дееспособным физическим лицом (далее — **«Заказчик»**).")
    rb.rubric("Предмет", ["Исполнитель обязуется оказать услуги (далее — **«Услуги»**), а Заказчик — оплатить их.",
                          "Вид, стоимость и срок Услуги определяются Заказчиком при выборе Услуги на сайте [ПРОВЕРИТЬ ФАКТ]."])
    rb.rubric("Акцепт", ["Акцепт считается совершённым в момент оплаты Услуги.",
                         "Договор вступает в силу с момента акцепта."])
    rb.rubric("Оплата", ["После оплаты Исполнитель направляет Заказчику:",
                         ("bullet", "информацию о деталях оказания Услуг;"),
                         ("bullet", "чек об оплате.")])
    rb.rubric("Ключевые параметры", [("text", "Стоимость: [ПРОВЕРИТЬ РАЗМЕР]"),
                                     ("text", "Срок оказания: [ПРОВЕРИТЬ СРОК]")], numbered=False)
    rb.footer()
    out.append(rb.save(os.path.join(folder, "demo_rubric.docx")))

    bi = BilingualDoc()
    bi.header("Supply Contract No. [ПРОВЕРИТЬ РЕКВИЗИТЫ] / Контракт на поставку № [ПРОВЕРИТЬ РЕКВИЗИТЫ]")
    bi.title("Supply Contract No. [ПРОВЕРИТЬ РЕКВИЗИТЫ] / Контракт на поставку № [ПРОВЕРИТЬ РЕКВИЗИТЫ]",
             "Date / Дата: [ПРОВЕРИТЬ ДАТУ]")
    bi.parties(["Buyer / Покупатель: [НАИМЕНОВАНИЕ]", "Address / Адрес: [ПРОВЕРИТЬ РЕКВИЗИТЫ]"],
               ["Supplier / Поставщик: [НАИМЕНОВАНИЕ]", "Address / Адрес: [ПРОВЕРИТЬ РЕКВИЗИТЫ]"])
    bi.section("1. Goods and Price", "1. Товар и цена")
    bi.block(["The Supplier delivers the Goods specified in the table below, and the Buyer pays for them."],
             ["Поставщик поставляет Товар, указанный в таблице ниже, а Покупатель оплачивает его."])
    bi.data_table(["No.", "Description / Описание", "Quantity / Количество", "Amount / Сумма"],
                  [["1", "[ПРОВЕРИТЬ ФАКТ]", "[ПРОВЕРИТЬ ФАКТ]", "[ПРОВЕРИТЬ РАЗМЕР]"]],
                  [1.2, 7.8, 4.0, 4.0])
    bi.section("2. Documents", "2. Документы")
    bi.block(["No later than the Delivery Date, the Supplier provides:", ("packing list;", True), ("invoice.", True)],
             ["Не позднее Даты поставки Поставщик передаёт:", ("упаковочный лист;", True), ("инвойс.", True)])
    bi.section("3. Delivery", "3. Поставка")
    bi.block(["3.1. Delivery terms: [ПРОВЕРИТЬ ФАКТ].", "Additional paragraph of clause 3.1.",
              "3.2. Delivery period: [ПРОВЕРИТЬ СРОК]."],
             ["3.1. Условия поставки: [ПРОВЕРИТЬ ФАКТ].", "Дополнительный абзац пункта 3.1.",
              "3.2. Срок поставки: [ПРОВЕРИТЬ СРОК]."])
    bi.signatures(["On behalf of the Buyer / От имени Покупателя", "[ДОЛЖНОСТЬ]", "_______________"],
                  ["On behalf of the Supplier / От имени Поставщика", "[ДОЛЖНОСТЬ]", "_______________"])
    bi.footer()
    out.append(bi.save(os.path.join(folder, "demo_bilingual.docx")))

    n = NoteDoc()
    n.title("ЗАМЕТКА ДЛЯ ЮРИСТА", "к проекту [ДОКУМЕНТ]")
    n.heading("1. Результат")
    n.para("[Что подготовлено и что изменено.]")
    n.heading("2. Что проверено")
    n.bullet("[Пункт проверки.]")
    n.heading("3. Юридические риски")
    n.table(["Уровень", "Риск", "Как учтено"],
            [["Высокий", "[Риск.]", "[Как учтено.]"], ["Средний", "[Риск.]", "[Как учтено.]"]],
            [2.4, 8.5, 6.1], center_cols=(0,), bold_cols=(0,))
    n.footer()
    out.append(n.save(os.path.join(folder, "demo_note.docx")))

    pr = ProceduralDoc()
    pr.head(["**В Арбитражный суд [ПРОВЕРИТЬ РЕКВИЗИТЫ]**", "[АДРЕС СУДА]"],
            ["**Истец:** [НАИМЕНОВАНИЕ]", "ИНН [ПРОВЕРИТЬ РЕКВИЗИТЫ], ОГРН [ПРОВЕРИТЬ РЕКВИЗИТЫ]"],
            ["**Ответчик:** [НАИМЕНОВАНИЕ]", "ИНН [ПРОВЕРИТЬ РЕКВИЗИТЫ], ОГРН [ПРОВЕРИТЬ РЕКВИЗИТЫ]"],
            ["**Цена иска:** [ПРОВЕРИТЬ РАСЧЁТ]", "**Государственная пошлина:** [ПРОВЕРИТЬ РАСЧЁТ]"])
    pr.title("ИСКОВОЕ ЗАЯВЛЕНИЕ", "о [ПРЕДМЕТ ТРЕБОВАНИЯ]")
    pr.section("I. ОБСТОЯТЕЛЬСТВА ДЕЛА")
    pr.point("1.", "[Факт с привязкой к доказательству.]")
    pr.point("2.", "Оплачено 1 339 560,00 руб. платёжным поручением № 7234 [ПРОВЕРИТЬ ФАКТ].")
    pr.section("II. ПРАВОВОЕ ОБОСНОВАНИЕ")
    pr.section("2.1. [Правовой вопрос]")
    pr.para("[Норма и её применение к фактам.]")
    pr.section("III. РАСЧЁТ ТРЕБОВАНИЙ")
    pr.table(["Показатель", "Сумма, руб."], [["[Основной долг]", "[ПРОВЕРИТЬ РАСЧЁТ]"]], [11.5, 5.0])
    pr.prayer()
    pr.point("1.", "[Требование.]")
    pr.section("Приложения:")
    pr.point("1.", "[Документ], на [N] л.")
    pr.signature(["[Должность]", "________________ / [ФИО]"])
    pr.footer()
    out.append(pr.save(os.path.join(folder, "demo_procedural.docx")))
    return out


def selftest() -> int:
    tmp = tempfile.mkdtemp(prefix="docx_style_")
    files = demo(tmp)
    by_name = {os.path.basename(f): f for f in files}
    problems = []
    for name, f in by_name.items():
        z = zipfile.ZipFile(f)
        xml = z.read("word/document.xml").decode("utf8")
        styles = z.read("word/styles.xml").decode("utf8")
        header = "".join(z.read(n).decode("utf8") for n in z.namelist() if "header" in n)
        footer = "".join(z.read(n).decode("utf8") for n in z.namelist() if "footer" in n)
        if "<w:numPr>" in xml:
            problems.append(f"{name}: автонумерация Word (numPr) — запрещена")
        runs = re.findall(r"<w:rPr>(.*?)</w:rPr>", xml, re.S)
        if any('w:eastAsia="Times New Roman"' not in r for r in runs if "w:rFonts" in r):
            problems.append(f"{name}: run без eastAsia")
        for sid in ("Title", "Heading1", "Heading2"):
            block = re.search(r'<w:style [^>]*w:styleId="%s".*?</w:style>' % sid, styles, re.S).group(0)
            if "Theme" in block or "theme" in block:
                problems.append(f"{name}: тематический шрифт/цвет в стиле {sid}")
            if "pBdr" in block:
                problems.append(f"{name}: линия-граница в стиле {sid}")
        if "[ПРОВЕРИТЬ" in xml and MARKER_FILL not in xml:
            problems.append(f"{name}: маркеры не подсвечены")
        if name != "demo_amendment_compact.docx" and "PAGE" not in footer:
            problems.append(f"{name}: нет номера страницы в колонтитуле")
        if name in ("demo_contract_standard.docx", "demo_individual.docx", "demo_rubric.docx") and "ПРОВЕРИТЬ" not in header:
            problems.append(f"{name}: нет верхнего колонтитула с названием документа")
    std = zipfile.ZipFile(by_name["demo_contract_standard.docx"]).read("word/document.xml").decode("utf8")
    ind = ind_xml = zipfile.ZipFile(by_name["demo_individual.docx"]).read("word/document.xml").decode("utf8")
    if "tblHeader" not in std:
        problems.append("demo_contract_standard: нет повтора строки заголовка таблицы")
    if 'w:val="both"' not in std:
        problems.append("demo_contract_standard: текст пунктов не по ширине (решение юриста 2026-09-24)")
    title_p = Document(by_name["demo_contract_standard.docx"]).paragraphs[0]
    if title_p.paragraph_format.left_indent is None or abs(title_p.paragraph_format.left_indent.cm - CONTRACT["number_col_cm"]) > 0.05:
        problems.append("demo_contract_standard: название не на вертикали текста (отступ = колонке номеров)")
    if 'w:val="both"' in ind_xml:
        problems.append("demo_individual: «Для физлиц» — по левому краю, выравнивание по ширине не утверждалось")

    if "М. П." in ind.split("Работник")[-1]:
        problems.append("demo_individual: «М. П.» у физического лица")
    for name, expected in (("demo_contract_standard.docx", CONTRACT["margins_cm"]),
                           ("demo_amendment_compact.docx", CONTRACT_COMPACT_MARGINS)):
        s = Document(by_name[name]).sections[0]
        got = tuple(round(x.cm, 2) for x in (s.left_margin, s.right_margin, s.top_margin, s.bottom_margin))
        if got != tuple(expected):
            problems.append(f"{name}: поля {got} ≠ профилю {expected}")
    rub = Document(by_name["demo_rubric.docx"])
    nums = [p.text.split("\t")[0] for t in rub.tables for p in t.rows[0].cells[1].paragraphs
            if "\t" in p.text and p.text[0].isdigit()]
    if not nums or nums != [f"{i}." for i in range(1, len(nums) + 1)]:
        problems.append(f"demo_rubric: нумерация не сквозная: {nums}")
    for name, f in by_name.items():
        xml = zipfile.ZipFile(f).read("word/document.xml").decode("utf8")
        n_tbl, n_fixed = xml.count("<w:tbl>"), xml.count('w:tblLayout w:type="fixed"')
        if n_tbl != n_fixed:
            problems.append(f"{name}: таблиц {n_tbl}, с фиксированной раскладкой {n_fixed} — таблица может уйти за поле")
    bi = Document(by_name["demo_bilingual.docx"])
    text_w = 21.0 - CONTRACT["margins_cm"][0] - CONTRACT["margins_cm"][1]
    for tbl in bi.tables:
        w = sum(c.width.cm for c in tbl.rows[0].cells if c.width is not None)
        if w > text_w + 0.05:
            problems.append(f"demo_bilingual: таблица шириной {w:.2f} см > ширины текста {text_w} см")
    pairs = [(r.cells[0].text, r.cells[2].text) for tbl in bi.tables if len(tbl.columns) == 3 for r in tbl.rows]
    if ("3.2.	Delivery period: [ПРОВЕРИТЬ СРОК].", "3.2.	Срок поставки: [ПРОВЕРИТЬ СРОК].") not in pairs:
        problems.append(f"demo_bilingual: пункты EN/RU не выровнены по номерам: {pairs}")
    proc = Document(by_name["demo_procedural.docx"])
    s = proc.sections[0]
    got = tuple(round(x.cm, 2) for x in (s.left_margin, s.right_margin, s.top_margin, s.bottom_margin))
    if got != tuple(PROCEDURAL["margins_cm"]):
        problems.append(f"demo_procedural: поля {got} ≠ профилю {PROCEDURAL['margins_cm']}")
    sizes = {r.font.size.pt for p in proc.paragraphs[:4] for r in p.runs if r.text.strip()}
    if sizes != {PROCEDURAL["body_pt"]}:
        problems.append(f"demo_procedural: кегль шапки {sizes} ≠ кеглю текста {PROCEDURAL['body_pt']}")
    pts = [p for p in proc.paragraphs if re.match(r"^\d+\.\t", p.text)]
    if not pts or any(abs(p.paragraph_format.first_line_indent.cm + PROCEDURAL["hang_cm"]) > 0.05 for p in pts):
        problems.append("demo_procedural: пункты без висячего отступа")
    if "1 339 560,00 руб." not in "".join(p.text for p in proc.paragraphs):
        problems.append("demo_procedural: суммы без неразрывных пробелов — рвутся по строкам")
    if any(p.paragraph_format.first_line_indent is not None and p.paragraph_format.first_line_indent.cm > 0.05
           for p in proc.paragraphs):
        problems.append("demo_procedural: красная строка — в процессуальном профиле не применяется")
    try:
        ContractDoc().table(["a"], [["b"]], [1.0])
        problems.append("table: не отклонена неверная сумма ширин")
    except ValueError:
        pass
    for pr in problems:
        print("FAIL", pr)
    print(f"selftest: {len(files)} файлов, проблем {len(problems)} ({tmp})")
    return 1 if problems else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    cmd = sys.argv[1] if len(sys.argv) > 1 else "selftest"
    if cmd == "demo":
        for f in demo(sys.argv[2] if len(sys.argv) > 2 else "."):
            print(f)
        sys.exit(0)
    sys.exit(selftest())
