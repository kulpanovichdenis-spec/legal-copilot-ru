#!/usr/bin/env python3
"""CLI skill business-communication: проверка, чекпоинты и рендер пакета из content_model.yaml.

  python tools/business_comm/comm.py validate <model.yaml>
  python tools/business_comm/comm.py checkpoint {1,2,3} <model.yaml>
  python tools/business_comm/comm.py render <model.yaml> --out-dir <dir> [--formats pptx,docx,html] [--template <pptx>]
  python tools/business_comm/comm.py write-support <model.yaml> --out-dir <dir>
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import bc_model as M  # noqa: E402
import render_docx  # noqa: E402
import render_html  # noqa: E402
import render_pptx  # noqa: E402
import textfmt as T  # noqa: E402
import validate as V  # noqa: E402
from bc_model import Issue  # noqa: E402

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


def _pptx_slide_count(model: dict) -> int:
    appendix = M.appendix_storyline(model)
    return 1 + len(M.main_storyline(model)) + (1 + len(appendix) if appendix else 0) + (1 if model["sources"] else 0)


def checkpoint_text(model: dict, n: int) -> str:
    # F9: чекпоинт может быть показан на черновой модели, где ещё не заполнены
    # обязательные поля (S01-S17) — вместо KeyError возвращаем сам перечень ошибок,
    # чтобы юрист понял, чего не хватает, а не увидел трассировку.
    schema_issues = M.schema_errors(model)
    if schema_issues:
        return "Модель не прошла проверку схемы, чекпоинт недоступен:\n" + \
            "\n".join(str(i) for i in schema_issues)
    p, o, mi = model["project"], model["objective"], model["minto"]
    if n == 1:
        mode = T.MODE_LABELS[p["mode"]]
        if p.get("secondary_mode"):
            mode += f" (+ {T.MODE_LABELS[p['secondary_mode']]})"
        goal = o.get("required_decision") or o.get("desired_behavior") or o.get("desired_outcome") or "[НЕ ЗАПОЛНЕНО]"
        lines = [f"Режим: {mode}", f"Аудитория: {p['audience']}", f"Цель: {goal}",
                 f"Бизнес-вопрос: {o['business_question']}", f"Главный ответ: {mi['answer']}"]
        if o.get("learning_objectives"):
            lines.append("Learning objectives: " + "; ".join(o["learning_objectives"]))
        return "\n".join(lines)
    if n == 2:
        lines = [f"{k}. {s['message']}" for k, s in enumerate(M.main_storyline(model), 1)]
        lines += [f"Приложение: {s['message']}" for s in M.appendix_storyline(model)]
        return "\n".join(lines)
    if n == 3:
        outputs = p["output"]
        idx = M.index_items(model)
        lines = [f"Форматы: {', '.join(outputs)}"]
        if "pptx" in outputs:
            tpl = (model["render"].get("pptx") or {}).get("template")
            lines.append(f"PPTX: слайдов {_pptx_slide_count(model)}; шаблон: {tpl or 'нейтральный'}")
        if "docx" in outputs:
            lines.append(f"DOCX: {(model['render'].get('docx') or {}).get('variant') or 'memo'}")
        if "html" in outputs:
            lines.append("HTML: страница для самостоятельного чтения")
        lines.append(f"Приложение: {'есть' if M.appendix_storyline(model) else 'нет'}")
        visuals = sorted({s["visual_hint"] for s in M.main_storyline(model)})
        images = [i["image"] for i in idx.values() if i.get("image")]
        lines.append(f"Визуалы: {', '.join(visuals)}" + (f"; документы: {', '.join(images)}" if images else ""))
        open_items = list(model["quality"]["assumptions"]) + list(model["quality"]["open_questions"])
        lines.append("Открытые допущения и вопросы: " + ("; ".join(open_items) if open_items else "нет"))
        return "\n".join(lines)
    raise ValueError("checkpoint: 1, 2 или 3")


def storyline_md(model: dict) -> str:
    out = [f"# Storyline — {model['project']['title']}", "", f"Бизнес-вопрос: {model['objective']['business_question']}",
           f"Главный ответ: {model['minto']['answer']}", ""]
    for s in M.main_storyline(model):
        out.append(f"{s.get('order')}. {s['message']}  `{s['content_block']} / {s['visual_hint']}`")
    for s in M.appendix_storyline(model):
        out.append(f"- Приложение: {s['message']}")
    return "\n".join(out) + "\n"


def sources_md(model: dict) -> str:
    out = [f"# Источники — {model['project']['title']}", ""]
    out += [f"{n}. {T.source_line(s)}" for n, s in enumerate(model["sources"], 1)]
    return "\n".join(out) + "\n"


def render_all(model: dict, out_dir: str | Path, formats: list[str] | None = None,
               template: str | None = None) -> tuple[list[Path], list[Issue]]:
    issues = V.validate(model)
    if V.has_errors(issues):
        return [], issues
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    slug = T.slugify(model["project"]["title"])
    paths: list[Path] = []
    for fmt in formats or model["project"]["output"]:
        if fmt == "pptx":
            path = render_pptx.render(model, out / f"{slug}.pptx", template=template)
            file_issues = render_pptx.inspect_pptx(path)
        elif fmt == "docx":
            path = render_docx.render(model, out / f"{slug}_handout.docx")
            file_issues = render_docx.inspect_docx(path)
        elif fmt == "html":
            path = render_html.render(model, out / f"{slug}.html")
            file_issues = render_html.inspect_html(path)
        else:
            issues.append(Issue("error", "S05", "formats", f"неизвестный формат {fmt!r}"))
            continue
        issues += file_issues
        if V.has_errors(file_issues):
            # Файл с ошибкой инспекции (мусор шаблона, «финальный», нет метки
            # черновика и т.п.) не должен оставаться на диске и попадать в
            # «Создан: …» юристу — сама ошибка уже объясняет причину (fix-wave F5).
            path.unlink(missing_ok=True)
            continue
        paths.append(path)
    return paths, issues


def _print_issues(issues: list[Issue]) -> None:
    for i in issues:
        print(str(i))
    errors = sum(1 for i in issues if i.level == "error")
    print(f"Итог: ошибок {errors}, предупреждений {len(issues) - errors}.")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_val = sub.add_parser("validate")
    p_val.add_argument("model")
    p_cp = sub.add_parser("checkpoint")
    p_cp.add_argument("n", type=int, choices=(1, 2, 3))
    p_cp.add_argument("model")
    p_r = sub.add_parser("render")
    p_r.add_argument("model")
    p_r.add_argument("--out-dir", required=True)
    p_r.add_argument("--formats")
    p_r.add_argument("--template")
    p_ws = sub.add_parser("write-support")
    p_ws.add_argument("model")
    p_ws.add_argument("--out-dir", required=True)
    args = ap.parse_args(argv)

    m = M.load_model(args.model)
    if args.cmd == "validate":
        issues = V.validate(m)
        _print_issues(issues)
        return 1 if V.has_errors(issues) else 0
    if args.cmd == "checkpoint":
        print(checkpoint_text(m, args.n))
        return 0
    if args.cmd == "render":
        formats = args.formats.split(",") if args.formats else None
        paths, issues = render_all(m, args.out_dir, formats, args.template)
        _print_issues(issues)
        for path in paths:
            print(f"Создан: {path}")
        return 1 if V.has_errors(issues) else 0
    if args.cmd == "write-support":
        out = Path(args.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "storyline.md").write_text(storyline_md(m), encoding="utf-8")
        (out / "sources.md").write_text(sources_md(m), encoding="utf-8")
        print(f"Создан: {out / 'storyline.md'}\nСоздан: {out / 'sources.md'}")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
