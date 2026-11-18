# -*- coding: utf-8 -*-
"""Команда report: матрицы-проекции, профиль и .docx-отчёт юристу."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gov_store as store  # noqa: E402
import gov_views as views  # noqa: E402

VIEW_CHOICES = tuple(views.VIEWS) + ("profile", "inconsistencies", "all")


def render_markdown(entity: store.Entity, view: str) -> str:
    profile = entity.load_profile()
    sources = entity.load_sources()["sources"]
    rules = entity.load_rules()["rules"]
    by_id = {s["source_id"]: s for s in sources}
    banner = views.charter_banner(sources)
    prefix = (banner + "\n\n") if banner else ""
    if view == "all":
        return views.render_full(profile, rules, sources)
    if view == "profile":
        return prefix + views.render_profile(profile)
    if view == "inconsistencies":
        return prefix + views.render_inconsistencies(views.find_inconsistencies(rules))
    return prefix + views.render_view(view, rules, by_id)


def _refuse_out_inside_entities_dir(entity: store.Entity, out: str) -> None:
    """T8.1 (+ ревью): --out внутрь entities/ — своей или ЧУЖОЙ компании — перезаписал бы её
    sources/rules/profile.yaml или audit.jsonl без единого предупреждения (аудит при этом пишется
    в СВОЮ компанию, так что порча чужого хранилища оставалась незамеченной). Резолвим оба пути
    и отказываем на всём каталоге entities/, а не только на папке текущей компании."""
    resolved = Path(out).resolve()
    entities_root = entity.dir.parent.resolve()
    if resolved == entities_root or entities_root in resolved.parents:
        raise store.GovError(
            f"--out указывает внутрь каталога компаний ({entities_root}): так можно затереть "
            "sources.yaml/rules.yaml/profile.yaml/audit.jsonl своей или чужой компании без "
            "предупреждения — сохраните отчёт в другое место (например, workflow/<дело>/)")


def cmd_report(args) -> int:
    entity = store.entity_from_args(args)
    if args.out:
        _refuse_out_inside_entities_dir(entity, args.out)
    if args.format == "docx":
        if args.view != "all":
            raise store.GovError("--view не применяется к --format docx: отчёт собирается целиком")
        if not args.out:
            raise store.GovError("для --format docx нужен --out путь к .docx")
        import gov_docx  # noqa: PLC0415

        path = gov_docx.build_report(entity, args.out)
        entity.audit("report-docx", entity.slug, actor=args.actor, new={"path": str(path)})
        print(f"OK: {path}")
        return 0
    text = render_markdown(entity, args.view)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
        entity.audit("report-md", entity.slug, actor=args.actor, new={"path": str(Path(args.out))})
        print(f"OK: {args.out}")
    else:
        print(text)
    return 0


def register(sub) -> None:
    p = sub.add_parser("report", parents=[store.common_parser()],
                       help="матрицы-проекции, профиль и .docx-отчёт")
    p.add_argument("--view", default="all", choices=VIEW_CHOICES)
    p.add_argument("--format", default="md", choices=("md", "docx"))
    p.add_argument("--out", help="файл результата (для docx обязателен)")
    p.set_defaults(func=cmd_report)
