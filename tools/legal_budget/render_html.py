"""Self-contained management HTML. Numbers come only from the view model."""
from __future__ import annotations

from html import escape
from pathlib import Path


def render_html(view: dict, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    currency = escape(str(view.get("currency") or ""))
    total = escape(str(view.get("total") or ""))
    saving = view.get("scenario_saving")
    rows = []
    for name, amount in (view.get("categories") or {}).items():
        rows.append(f"<tr><td>{escape(str(name))}</td><td>{escape(str(amount))} {currency}</td></tr>")
    months = []
    for month, amount in (view.get("monthly") or {}).items():
        months.append(
            f"<tr><td>{escape(str(month))}</td><td>{escape(str(amount))} {currency}</td></tr>"
        )
    bridge_rows = []
    for row in view.get("bridge_rows") or []:
        bridge_rows.append(
            f"<tr><td>{escape(str(row.get('label')))}</td>"
            f"<td>{escape(str(row.get('amount')))} {currency}</td></tr>"
        )
    bridge_html = ""
    if view.get("bridge_total"):
        bridge_html = (
            "<h2>Мост к предложенному бюджету</h2>"
            f"<p data-bridge-total=\"{escape(str(view.get('bridge_total')))}\">"
            f"Итог моста: {escape(str(view.get('bridge_total')))} {currency}.</p>"
            "<table><tr><th>Шаг</th><th>Сумма</th></tr>"
            + "".join(bridge_rows)
            + "</table>"
            "<p>Что изменилось: от прошлого периода к предложению. Почему: каждое слагаемое передано отдельно. "
            "Что решить: подтвердить слагаемые, которых не хватает, если мост не собран.</p>"
        )
    reforecast = view.get("reforecast") or {}
    reforecast_html = ""
    if reforecast:
        reforecast_html = (
            "<h2>Рефорекаст</h2>"
            f"<p data-eac=\"{escape(str(reforecast.get('eac')))}\">"
            f"EAC {escape(str(reforecast.get('eac')))} {currency} против утверждённых "
            f"{escape(str(reforecast.get('approved')))} {currency}. "
            f"Отклонение EAC: {escape(str(reforecast.get('eac_vs_approved')))} {currency}. "
            f"Причина: {escape(str(reforecast.get('driver')))}.</p>"
            "<p>Что изменилось: прогноз остатка. Почему: факт, начисление и ETC сложены один раз. "
            "Что решить: подтвердить причину, если она ещё unknown.</p>"
        )
    def _list_block(title: str, rows: list[str]) -> str:
        if not rows:
            return ""
        return f"<h2>{title}</h2><ul>" + "".join(f"<li>{row}</li>" for row in rows) + "</ul>"

    finding_rows = [
        f"{escape(str(item.get('id')))} {escape(str(item.get('rule')))}: {escape(str(item.get('finding')))}"
        for item in (view.get("findings") or [])
    ]
    assumption_rows = [
        escape(str(item.get("statement") or item.get("id") or item))
        for item in (view.get("assumptions") or [])
    ]
    question_rows = [
        escape(str(item.get("question") if isinstance(item, dict) else item))
        for item in (view.get("open_issues") or [])
    ]
    incomplete = ""
    if view.get("total_complete") is False:
        incomplete = "<p data-total-complete=\"false\">Итог неполный: есть строки без суммы. Пустая сумма не входит как ноль.</p>"
    scenario = ""
    if saving is not None:
        scenario = (
            "<h2>Сценарий сокращения</h2>"
            f"<p data-scenario-saving=\"{escape(str(saving))}\">"
            f"Сумма рычагов: {escape(str(saving))} {currency}. "
            "Это не равномерный процент по всем строкам.</p>"
        )
    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>Бюджет Legal — черновик</title>
<style>
html {{ color-scheme: light; }}
body {{ font-family: "Segoe UI", sans-serif; margin: 32px auto; max-width: 880px; color: #1c1c1c; background: #fff; }}
h1 {{ font-size: 28px; margin-bottom: 8px; }}
.draft {{ color: #8a4b08; font-weight: 600; }}
table {{ border-collapse: collapse; margin-top: 12px; background: #fff; }}
td, th {{ border: 1px solid #ccc; padding: 6px 10px; text-align: left; }}
th {{ background: #f4f1ea; }}
@media print {{ body {{ margin: 12mm; }} }}
</style>
</head>
<body>
<p class="draft">ЧЕРНОВИК — требует проверки юристом</p>
<h1>Бюджет юридической функции</h1>
<p data-total-budget="{total}">Итого: {total} {currency}</p>
{incomplete}
<p>Что изменилось: итог собран из строк view model. Почему: каждая строка хранит свой расчёт. Что решить: подтвердить допущения до передачи в Finance.</p>
<h2>Состав</h2>
<table>
<tr><th>Категория</th><th>Сумма</th></tr>
{''.join(rows)}
</table>
<h2>Помесячно</h2>
<table>
<tr><th>Месяц</th><th>Сумма</th></tr>
{''.join(months)}
</table>
{bridge_html}
{scenario}
{reforecast_html}
{_list_block("Находки", finding_rows)}
{_list_block("Допущения", assumption_rows)}
{_list_block("Открытые вопросы", question_rows)}
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")
    return path
