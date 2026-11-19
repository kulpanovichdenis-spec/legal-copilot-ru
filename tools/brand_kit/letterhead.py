# -*- coding: utf-8 -*-
"""Письмо на фирменном бланке компании.

Бланк — .docx/.dotx из фирменного стиля пользователя (profile/knowledge/brand/).
Модуль не верстает бланк заново: открывает его как есть (колонтитулы, логотип,
реквизиты, шрифт остаются бланковыми) и заполняет «слоты» — места, которые
описаны в манифесте brand.yaml:

  field: "[Дата]"        поле MACROBUTTON или элемент управления содержимым
                         с такой подписью (тег, название, текст-заполнитель);
  text: "Уважаемый"      абзац, текст которого содержит подстроку.

Общие ключи слота: nth (1, 2 … — какое по счёту совпадение), in (body,
first_page_header, header, footer …), drop_next (сколько абзацев-подсказок
после найденного удалить), prefix (подпись строки, сохраняемая перед значением:
«Исполнитель: »), optional (не считать незаполненным).
Слот body: mode replace (абзац-заполнитель заменяется текстом письма) или
after (текст вставляется после найденного абзаца); align, first_line_cm,
size_pt, keep_empty (сколько пустых абзацев оставить после текста).

Правила использования — references/brand-letterhead.md.

    import sys; sys.path.insert(0, r"<корень legal-copilot>")
    from tools.brand_kit.letterhead import LetterheadDoc
    d = LetterheadDoc(purpose="counterparty_letter")
    d.fill("title", "О предоставлении документов")
    d.para("Текст письма …")
    report = d.save(r"...\\workflow\\...\\Письмо.docx")
"""

from __future__ import annotations

import copy
import os
import re
import tempfile
import zipfile
from pathlib import Path

import yaml
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt
from docx.text.paragraph import Paragraph

from tools.docx_style.profiles import MARKER_FILL, MARKER_RE

SCHEMA = "brand_kit.v1"
PARTS = ("first_page_header", "header", "even_page_header",
         "first_page_footer", "footer", "even_page_footer")
ALIGN = {"left": WD_ALIGN_PARAGRAPH.LEFT, "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
         "center": WD_ALIGN_PARAGRAPH.CENTER, "right": WD_ALIGN_PARAGRAPH.RIGHT}
_MACRO_RE = re.compile(r"^\s*MACROBUTTON\s+\S+\s*(.*?)\s*$", re.S)
# порядок дочерних элементов w:rPr по схеме OOXML
_RPR_ORDER = ["rStyle", "rFonts", "b", "bCs", "i", "iCs", "caps", "smallCaps", "strike", "dstrike",
              "outline", "shadow", "emboss", "imprint", "noProof", "snapToGrid", "vanish", "webHidden",
              "color", "spacing", "w", "kern", "position", "sz", "szCs", "highlight", "u", "effect",
              "bdr", "shd", "fitText", "vertAlign", "rtl", "cs", "em", "lang", "eastAsianLayout",
              "specVanish", "oMath"]


# ---------- где лежит фирменный стиль ----------

def brand_root() -> Path:
    from tools.profile.profile_lib import profile_subpath
    return profile_subpath("knowledge", "brand")


def load_manifest(path: str | os.PathLike | None = None) -> tuple[dict, Path]:
    p = Path(path) if path else brand_root() / "brand.yaml"
    if not p.exists():
        raise FileNotFoundError(
            f"Нет манифеста фирменного стиля: {p}. Положите папку фирменного стиля в "
            f"profile/knowledge/brand/_inbox/ и выполните: python -m tools.brand_kit scan")
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if data.get("schema") != SCHEMA:
        raise ValueError(f"{p}: schema должна быть {SCHEMA}")
    return data, p.parent


def pick_blank(manifest: dict, blank: str | None = None, purpose: str | None = None) -> dict:
    blanks = manifest.get("blanks") or []
    if not blanks:
        raise ValueError("в манифесте нет бланков")
    if blank:
        for b in blanks:
            if b.get("id") == blank:
                return b
        raise KeyError(f"бланк {blank!r} не найден; есть: {[b.get('id') for b in blanks]}")
    if purpose:
        for b in blanks:
            if purpose in (b.get("use_for") or []):
                return b
    default = manifest.get("default_blank")
    for b in blanks:
        if b.get("id") == default:
            return b
    letterheads = [b for b in blanks if b.get("kind", "letterhead") == "letterhead"]
    if not letterheads:
        raise ValueError("в манифесте нет бланков писем (kind: letterhead)")
    return letterheads[0]


# ---------- открытие .docx / .dotx ----------

def open_blank(path: str | os.PathLike) -> Document:
    """Открыть бланк. Шаблон .dotx открывается как документ (меняется тип содержимого)."""
    path = Path(path)
    if path.suffix.lower() not in (".dotx", ".dotm"):
        return Document(str(path))
    tmp = Path(tempfile.mkdtemp(prefix="brand_kit_")) / (path.stem + ".docx")
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "[Content_Types].xml":
                data = (data.decode("utf8")
                        .replace("wordprocessingml.template.main+xml", "wordprocessingml.document.main+xml")
                        .replace("ms-word.template.macroEnabledTemplate.main+xml",
                                 "officedocument.wordprocessingml.document.main+xml")
                        .encode("utf8"))
            zout.writestr(item, data)
    return Document(str(tmp))


# ---------- поиск мест для заполнения ----------

def doc_parts(doc) -> list[tuple[str, object]]:
    """Тело и собственные колонтитулы документа: [(имя части, корневой XML-элемент)]."""
    out, seen = [("body", doc.element.body)], set()
    for s in doc.sections:
        for name in PARTS:
            hf = getattr(s, name)
            if hf.is_linked_to_previous:
                continue
            key = str(hf.part.partname)
            if key in seen:
                continue
            seen.add(key)
            out.append((name, hf._element))
    return out


def _text(el) -> str:
    return "".join(t.text or "" for t in el.iter(qn("w:t"))).replace("\xa0", " ")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("\xa0", " ")).strip().lower()


def _bare(s: str) -> str:
    return _norm(s).strip("[]{}<> ")


def _sdt_label(sdt) -> str:
    pr = sdt.find(qn("w:sdtPr"))
    if pr is not None:
        for tag in ("w:alias", "w:tag"):
            el = pr.find(qn(tag))
            if el is not None and el.get(qn("w:val")):
                return el.get(qn("w:val"))
    content = sdt.find(qn("w:sdtContent"))
    return _text(content) if content is not None else ""


def _is_page_number_sdt(sdt) -> bool:
    pr = sdt.find(qn("w:sdtPr"))
    return pr is not None and pr.find(qn("w:docPartObj")) is not None


def _first_rpr(nodes) -> object | None:
    for n in nodes:
        for r in ([n] if n.tag == qn("w:r") else n.iter(qn("w:r"))):
            rpr = r.find(qn("w:rPr"))
            if rpr is not None:
                return rpr
    return None


def anchors(doc) -> list[dict]:
    """Все места для заполнения в порядке документа: поля MACROBUTTON, элементы
    управления содержимым и абзацы с текстом. Ключи: kind (field|sdt|text), label,
    part, p (абзац), nodes (что заменять), rpr (образец оформления текста)."""
    out = []
    for part, root in doc_parts(doc):
        for sdt in root.iter(qn("w:sdt")):
            if _is_page_number_sdt(sdt):
                continue
            parent = sdt.getparent()
            p = parent if parent.tag == qn("w:p") else None
            out.append(dict(kind="sdt", label=_sdt_label(sdt), part=part, p=p, nodes=[sdt],
                            block=p is None, rpr=_first_rpr([sdt])))
        for p in root.iter(qn("w:p")):
            fields, cur, instr, depth = [], None, "", 0
            for child in p:
                if child.tag == qn("w:fldSimple"):
                    m = _MACRO_RE.match(child.get(qn("w:instr")) or "")
                    if m:
                        fields.append(dict(label=m.group(1), nodes=[child]))
                    continue
                if child.tag != qn("w:r"):
                    continue
                fc = child.find(qn("w:fldChar"))
                kind = fc.get(qn("w:fldCharType")) if fc is not None else None
                if kind == "begin":
                    depth += 1
                    if depth == 1:
                        cur, instr = [], ""
                if cur is not None:
                    cur.append(child)
                    if depth == 1:
                        instr += "".join(i.text or "" for i in child.iter(qn("w:instrText")))
                if kind == "end":
                    depth -= 1
                    if depth == 0 and cur is not None:
                        m = _MACRO_RE.match(instr)
                        if m:
                            fields.append(dict(label=m.group(1), nodes=cur))
                        cur = None
            for f in fields:
                out.append(dict(kind="field", label=f["label"], part=part, p=p, nodes=f["nodes"],
                                block=False, rpr=_first_rpr(f["nodes"])))
            txt = _text(p)
            if txt.strip():
                out.append(dict(kind="text", label=txt, part=part, p=p, nodes=None, block=False,
                                rpr=_first_rpr([r for r in p.iter(qn("w:r")) if _text(r).strip()])))
    return out


def find_anchor(doc, spec: dict) -> dict | None:
    want_part = spec.get("in")
    nth = int(spec.get("nth", 1))
    hits = []
    for a in anchors(doc):
        if want_part and a["part"] != want_part:
            continue
        if "field" in spec:
            if a["kind"] in ("field", "sdt") and _bare(a["label"]) == _bare(spec["field"]):
                hits.append(a)
        elif "text" in spec:
            if a["kind"] == "text" and _norm(spec["text"]) in _norm(a["label"]):
                hits.append(a)
    return hits[nth - 1] if len(hits) >= nth else None


# ---------- сборка текста ----------

def _put(rpr, el):
    """Поставить элемент в w:rPr на место по схеме (с заменой одноимённого)."""
    name = el.tag.split("}")[1]
    old = rpr.find(el.tag)
    if old is not None:
        rpr.remove(old)
    idx = _RPR_ORDER.index(name) if name in _RPR_ORDER else len(_RPR_ORDER)
    for i, child in enumerate(list(rpr)):
        cname = child.tag.split("}")[1]
        if (_RPR_ORDER.index(cname) if cname in _RPR_ORDER else len(_RPR_ORDER)) > idx:
            rpr.insert(i, el)
            return
    rpr.append(el)


def _clean_rpr(tpl, *, size_pt: float | None = None):
    rpr = copy.deepcopy(tpl) if tpl is not None else OxmlElement("w:rPr")
    for tag in ("w:b", "w:bCs", "w:highlight", "w:shd", "w:vanish", "w:webHidden", "w:noProof"):
        for el in rpr.findall(qn(tag)):
            rpr.remove(el)
    st = rpr.find(qn("w:rStyle"))
    if st is not None and "placeholder" in (st.get(qn("w:val")) or "").lower():
        rpr.remove(st)
    if size_pt:
        for tag in ("w:sz", "w:szCs"):
            el = OxmlElement(tag)
            el.set(qn("w:val"), str(int(round(size_pt * 2))))
            _put(rpr, el)
    return rpr


def _runs(text: str, tpl, *, bold: bool = False) -> list:
    """Run'ы с образцовым оформлением бланка. Разметка: **полужирный**; маркеры неполноты
    ([ПРОВЕРИТЬ …]) — серой заливкой; перевод строки — разрыв строки внутри абзаца."""
    out = []
    for li, line in enumerate(text.split("\n")):
        if li:
            r = OxmlElement("w:r")
            r.append(_clean_rpr(tpl))
            r.append(OxmlElement("w:br"))
            out.append(r)
        for i, chunk in enumerate(re.split(r"\*\*", line)):
            b = bold or i % 2 == 1
            for sub in MARKER_RE.split(chunk):
                if not sub:
                    continue
                r = OxmlElement("w:r")
                rpr = _clean_rpr(tpl)
                if b:
                    _put(rpr, OxmlElement("w:b"))
                if MARKER_RE.fullmatch(sub):
                    shd = OxmlElement("w:shd")
                    shd.set(qn("w:val"), "clear")
                    shd.set(qn("w:color"), "auto")
                    shd.set(qn("w:fill"), MARKER_FILL)
                    _put(rpr, shd)
                r.append(rpr)
                t = OxmlElement("w:t")
                t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
                t.text = sub
                r.append(t)
                out.append(r)
    return out


def _is_empty_par(p) -> bool:
    if p.tag != qn("w:p") or _text(p).strip():
        return False
    for tag in ("w:drawing", "w:pict", "w:object", "w:fldChar", "w:fldSimple", "w:sdt", "w:sectPr"):
        if p.find(".//" + qn(tag)) is not None:
            return False
    return all(br.get(qn("w:type")) != "page" for br in p.iter(qn("w:br")))


def _tidy_after(run):
    """«Уважаемый [Имя] !» → «Уважаемый Иван Иванович!»: пробел перед знаком препинания
    сразу после заполненного поля убирается."""
    nxt = run.getnext()
    while nxt is not None and nxt.tag == qn("w:r") and not _text(nxt):
        nxt = nxt.getnext()
    if nxt is None or nxt.tag != qn("w:r"):
        return
    t = nxt.find(qn("w:t"))
    if t is not None and t.text and re.match(r"^\s+[!?.,;:]", t.text):
        t.text = t.text.lstrip()


def _value_text(value) -> str:
    if isinstance(value, (list, tuple)):
        return "\n".join(str(v) for v in value)
    return str(value)


# ---------- письмо на бланке ----------

class LetterheadDoc:
    """Письмо на фирменном бланке: слоты бланка заполняются через fill(),
    текст письма добавляется методами para / point / bullet / heading / table / signature."""

    def __init__(self, blank: str | None = None, *, purpose: str | None = None,
                 manifest: str | os.PathLike | None = None):
        self.manifest, self.root = load_manifest(manifest)
        self.blank = pick_blank(self.manifest, blank, purpose)
        self.path = self.root / self.blank["file"]
        if not self.path.exists():
            raise FileNotFoundError(f"файл бланка не найден: {self.path}")
        self.doc = open_blank(self.path)
        self.slots_spec: dict = self.blank.get("slots") or {}
        # места фиксируются до правок: после заполнения одного слота nth и текст-подсказки
        # других слотов уже не совпали бы с исходным бланком
        self._anchor = {name: find_anchor(self.doc, spec or {}) for name, spec in self.slots_spec.items()}
        self.filled: set[str] = set()
        self._body = None       # dict: anchor-абзац, режим, образцы оформления
        self._cursor = None     # после какого элемента вставлять следующий
        self._inserted: list = []

    # --- служебные слоты ---

    def slots(self) -> list[str]:
        return list(self.slots_spec)

    def fill(self, slot: str, value):
        """Заполнить слот бланка (дата, адресат, заголовок, обращение, подписант …).
        value: строка (переводы строк — разрывы строк) или список строк. None — оставить как в бланке."""
        if value is None:
            return
        spec = self.slots_spec.get(slot)
        if spec is None:
            raise KeyError(f"в бланке {self.blank['id']!r} нет слота {slot!r}; есть: {self.slots()}")
        if slot == "body":
            raise ValueError("текст письма добавляется методами para/point/…, не fill('body')")
        a = self._anchor.get(slot)
        if a is None:
            raise LookupError(f"слот {slot!r}: место в бланке не найдено по {spec}")
        text = spec.get("prefix", "") + _value_text(value)
        if a["kind"] == "text":
            self._replace_paragraph_text(a, text)
        elif a["block"]:
            a["p"] = self._unwrap_block_sdt(a["nodes"][0])
            a["kind"], a["block"] = "text", False
            self._replace_paragraph_text(a, text)
        else:
            new = _runs(text, a["rpr"])
            first = a["nodes"][0]
            for r in new:
                first.addprevious(r)
            for n in a["nodes"]:
                n.getparent().remove(n)
            a["nodes"] = new  # повторный fill заменит уже вставленный текст
            _tidy_after(new[-1])
        if not a.get("dropped"):
            for _ in range(int(spec.get("drop_next", 0))):
                nxt = a["p"].getnext() if a.get("p") is not None else None
                if nxt is not None and nxt.tag == qn("w:p"):
                    nxt.getparent().remove(nxt)
            a["dropped"] = True
        self.filled.add(slot)

    def _replace_paragraph_text(self, a, text):
        p = a["p"]
        for child in list(p):
            if child.tag != qn("w:pPr"):
                p.remove(child)
        for r in _runs(text, a["rpr"]):
            p.append(r)

    @staticmethod
    def _unwrap_block_sdt(sdt):
        content = sdt.find(qn("w:sdtContent"))
        first = None
        for child in list(content):
            sdt.addprevious(child)
            if first is None and child.tag == qn("w:p"):
                first = child
        sdt.getparent().remove(sdt)
        return first

    # --- текст письма ---

    def _ensure_body(self):
        if self._body is not None:
            return self._body
        spec = dict(self.slots_spec.get("body") or {})
        if not spec:
            raise ValueError(f"в бланке {self.blank['id']!r} не задан слот body (куда писать текст)")
        a = self._anchor.get("body")
        if a is None:
            raise LookupError(f"слот body: место в бланке не найдено по {spec}")
        p = a["p"]
        if a["block"]:
            p = self._unwrap_block_sdt(a["nodes"][0])
        mode = spec.get("mode", "replace")
        own_text = _text(p).strip()
        if mode == "replace" and a["kind"] != "text" and own_text and _bare(own_text) != _bare(a["label"]):
            mode = "after"  # в абзаце есть ещё текст кроме заполнителя — не уничтожать его
        ppr = p.find(qn("w:pPr"))
        self._body = dict(p=p, mode=mode, spec=spec, ppr=ppr,
                          rpr=_clean_rpr(a["rpr"], size_pt=spec.get("size_pt")))
        if mode == "replace":
            self._cursor = None  # вставка перед заполнителем, сам он удаляется при сохранении
        else:
            nxt = p.getnext()  # пустая строка бланка после обращения остаётся отбивкой
            self._cursor = nxt if nxt is not None and _is_empty_par(nxt) else p
        self.filled.add("body")
        return self._body

    def _place(self, el):
        b = self._ensure_body()
        if self._cursor is None:
            b["p"].addprevious(el)
        else:
            self._cursor.addnext(el)
        self._cursor = el
        self._inserted.append(el)
        return el

    def _new_par(self, *, align=None, first_cm=None, left_cm=None, after_pt=None, keep_next=False):
        b = self._ensure_body()
        p = OxmlElement("w:p")
        if b["ppr"] is not None:
            ppr = copy.deepcopy(b["ppr"])
            for tag in ("w:sectPr", "w:numPr", "w:pStyle"):
                for el in ppr.findall(qn(tag)):
                    ppr.remove(el)
            p.append(ppr)
        self._place(p)
        para = Paragraph(p, None)
        pf = para.paragraph_format
        spec = b["spec"]
        para.alignment = ALIGN[align or spec.get("align", "justify")]
        first = spec.get("first_line_cm", 0.0) if first_cm is None else first_cm
        pf.first_line_indent = Cm(first)
        if left_cm is not None:
            pf.left_indent = Cm(left_cm)
        if after_pt is not None:
            pf.space_after = Pt(after_pt)
        elif spec.get("after_pt") is not None:
            pf.space_after = Pt(spec["after_pt"])
        pf.keep_with_next = keep_next
        return p

    def para(self, text: str, *, align: str | None = None, first_line_cm: float | None = None,
             bold: bool = False, keep_next: bool = False):
        p = self._new_par(align=align, first_cm=first_line_cm, keep_next=keep_next)
        for r in _runs(text, self._body["rpr"], bold=bold):
            p.append(r)
        return p

    def heading(self, text: str):
        return self.para(text, align="left", first_line_cm=0.0, bold=True, keep_next=True)

    def point(self, number: str, text: str, *, level: int = 1, hang_cm: float = 0.8):
        """Пункт с висячим отступом: номер литералом + табуляция (без автонумерации Word)."""
        p = self._new_par(first_cm=-hang_cm, left_cm=hang_cm * level)
        Paragraph(p, None).paragraph_format.tab_stops.add_tab_stop(Cm(hang_cm * level))
        for r in _runs(f"{number}\t{text}", self._body["rpr"]):
            p.append(r)
        return p

    def bullet(self, text: str, *, hang_cm: float = 0.6):
        return self.point("–", text, hang_cm=hang_cm)

    def spacer(self):
        return self._new_par(first_cm=0.0)

    def signature(self, lines: list[str], *, gap: bool = True):
        """Подпись, когда в бланке нет своих слотов подписанта: строки слева, без отступа."""
        if gap:
            self.spacer()
        for i, line in enumerate(lines):
            p = self._new_par(align="left", first_cm=0.0, after_pt=0, keep_next=i < len(lines) - 1)
            for r in _runs(line, self._body["rpr"]):
                p.append(r)

    def table(self, header: list[str], rows: list[list[str]], widths_cm: list[float]):
        """Простая таблица в тексте письма: тонкая сетка, строка заголовка полужирная."""
        self._ensure_body()
        t = self.doc.add_table(rows=1 + len(rows), cols=len(header))
        tbl = t._tbl
        tbl.getparent().remove(tbl)
        self._place(tbl)
        tblpr = tbl.tblPr
        borders = OxmlElement("w:tblBorders")
        for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
            e = OxmlElement(f"w:{side}")
            e.set(qn("w:val"), "single")
            e.set(qn("w:sz"), "4")
            e.set(qn("w:color"), "A6A6A6")
            borders.append(e)
        tblpr.append(borders)
        layout = OxmlElement("w:tblLayout")
        layout.set(qn("w:type"), "fixed")
        tblpr.append(layout)
        for ri, values in enumerate([header] + rows):
            for ci, val in enumerate(values):
                cell = t.rows[ri].cells[ci]
                cell.width = Cm(widths_cm[ci])
                cp = cell.paragraphs[0]._p
                for r in _runs(str(val), self._body["rpr"], bold=ri == 0):
                    cp.append(r)
        return t

    # --- сохранение ---

    def unfilled(self) -> list[str]:
        return [name for name, spec in self.slots_spec.items()
                if name not in self.filled and not (spec or {}).get("optional")]

    def _trim_after_body(self):
        if not self._inserted:
            return
        keep = int(self._body["spec"].get("keep_empty", 1))
        nxt, empties = self._inserted[-1].getnext(), []
        if self._body["mode"] == "replace" and nxt is self._body["p"]:
            nxt = nxt.getnext()
        while nxt is not None and _is_empty_par(nxt):
            empties.append(nxt)
            nxt = nxt.getnext()
        for p in empties[keep:]:
            p.getparent().remove(p)
        # хвост пустых абзацев бланка в конце документа: при длинном тексте дал бы пустую страницу
        body = self.doc.element.body
        while True:
            kids = [el for el in body if el.tag != qn("w:sectPr")]
            if len(kids) < 2 or not _is_empty_par(kids[-1]) or kids[-2].tag != qn("w:p"):
                break  # после таблицы Word требует абзац — его не трогаем
            body.remove(kids[-1])

    def save(self, path: str | os.PathLike) -> dict:
        if self._body is not None:
            self._trim_after_body()
            if self._body["mode"] == "replace" and self._body["p"].getparent() is not None:
                self._body["p"].getparent().remove(self._body["p"])
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.doc.save(str(path))
        left = [a["label"] for a in anchors(self.doc) if a["kind"] in ("field", "sdt")]
        return dict(path=str(path), blank=self.blank["id"], manifest_status=self.manifest.get("status"),
                    unfilled_slots=self.unfilled(), placeholders_left=left,
                    slots_not_found=[n for n, a in self._anchor.items() if a is None])
