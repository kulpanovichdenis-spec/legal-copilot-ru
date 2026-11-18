"""Обезличенный фрагмент «чужой формы» договора для проверки apply_ops.ps1.

Содержит то, на чём ломался ручной редлайн: заголовки жирным, абзац с ведущим пробелом,
нумерованный список (ListString), ячейку таблицы и одно чужое исправление (автор «Контрагент»),
которое редлайн не должен принять. Реальных данных нет.

Запуск: python tools/docx_redline/example/make_sample.py <выход.docx>
"""
import sys

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn


def _foreign_insertion(paragraph, text, author="Контрагент"):
    ins = OxmlElement("w:ins")
    ins.set(qn("w:id"), "901")
    ins.set(qn("w:author"), author)
    ins.set(qn("w:date"), "2026-01-15T10:00:00Z")
    run = OxmlElement("w:r")
    t = OxmlElement("w:t")
    t.set(qn("xml:space"), "preserve")
    t.text = text
    run.append(t)
    ins.append(run)
    paragraph._p.append(ins)


def build(path):
    doc = Document()
    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.add_run("ДОГОВОР ПОСТАВКИ № [НОМЕР]").bold = True                                   # 1
    place = doc.add_paragraph("г. [ГОРОД], [ДАТА]")                                           # 2
    _foreign_insertion(place, " (редакция Поставщика)")
    doc.add_paragraph().add_run("1. ПРЕДМЕТ ДОГОВОРА").bold = True                           # 3
    doc.add_paragraph(                                                                         # 4
        "1.1. Поставщик обязуется передать в собственность Покупателя товар, а Покупатель "
        "обязуется принять и оплатить товар в порядке и сроки, предусмотренные Договором."
    )
    doc.add_paragraph(                                                                         # 5
        "1.2. Наименование, количество и цена товара указываются в спецификациях, "
        "являющихся неотъемлемой частью Договора."
    )
    doc.add_paragraph().add_run("2. ПОРЯДОК РАСЧЁТОВ").bold = True                           # 6
    doc.add_paragraph(                                                                         # 7
        " 2.1. Покупатель оплачивает товар в течение 90 (девяноста) календарных дней с даты поставки."
    )
    doc.add_paragraph(                                                                         # 8
        "2.2. Поставщик вправе в одностороннем порядке изменить цену товара, уведомив "
        "Покупателя не менее чем за 5 (пять) рабочих дней."
    )
    doc.add_paragraph(                                                                         # 9
        "2.3. Обязательство по оплате считается исполненным с даты зачисления денежных "
        "средств на счёт Поставщика."
    )
    doc.add_paragraph().add_run("3. ОТВЕТСТВЕННОСТЬ СТОРОН").bold = True                     # 10
    for text in (                                                                              # 11-13
        "За просрочку поставки Поставщик уплачивает неустойку в размере 0,1 % от стоимости "
        "непоставленного товара за каждый день просрочки.",
        "За просрочку оплаты Покупатель уплачивает неустойку в размере 0,5 % от неоплаченной "
        "суммы за каждый день просрочки.",
        "Уплата неустойки не освобождает Стороны от исполнения обязательств.",
    ):
        doc.add_paragraph(text, style="List Number")
    table = doc.add_table(rows=1, cols=2)                                                      # 14-15
    table.cell(0, 0).paragraphs[0].add_run("Поставщик: [НАИМЕНОВАНИЕ]")
    table.cell(0, 1).paragraphs[0].add_run("Покупатель:").bold = True
    doc.add_paragraph("Приложение: спецификация.")                                            # 16
    doc.save(path)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    build(sys.argv[1])
