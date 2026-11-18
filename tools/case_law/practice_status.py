#!/usr/bin/env python3
"""Классификатор статуса судебной практики РФ — детерминированная часть case-law-search.

Реализует §13 (критерии сформированной/устоявшейся практики) и §14 (словарь статусов)
ТЗ по управлению поиском судебной практики. Единый источник истины по счёту округов и
порогам, чтобы правило не «плыло» в прозе (architecture-first: детерминированное — в код).

РАЗДЕЛЕНИЕ ТРУДА (важно):
- СУЖДЕНИЕ — работа агента по картам references/case-law-cards/: какой акт A1/A2/A3/A4,
  отсеять отказные определения (§10 X) из substantive set, ВАС survival check (CL-3),
  какие кассационные округа РЕАЛЬНО применяют тот же подход при сопоставимом
  регулировании (§13.2). Только после этого формируется структурированный вход.
- СЧЁТ И ПОРОГИ — этот модуль: считает ОКРУГА (не число решений, §13.2) и применяет
  пороги §13, возвращая статус §14 + признак established. Этот признак разрешает
  прекратить добор однотипных подтверждений, но не означает, что завершены проверки
  истории, режима права, adverse-линии и применимости к issue.

Классификатор НЕ открывает базы, НЕ квалифицирует акты, НЕ снимает маркеры. Его выход —
кандидат-статус для юриста, не окончательный вывод.

Вход PracticeInput (уже очищенный агентом):
  a1  — есть действующий Пленум ВС / сохраняющий силу Пленум ВАС по issue;
  a2  — есть позиция Президиума ВС / утверждённый Президиумом обзор ВС / сохраняющий
        силу Президиум ВАС;
  a4  — есть сохраняющее значение информ. письмо/обзор Президиума ВАС;
  skes — число СОГЛАСОВАННЫХ содержательных определений СКЭС ВС по существу (A3);
  circuits_support — число РАЗНЫХ кассационных округов, применяющих наш подход X;
  circuits_oppose  — число РАЗНЫХ округов, применяющих противоположный подход Y;
  decisions_support — всего решений за X (нужно лишь чтобы отличить SINGLE от LOCAL_STABLE
        при одном округе; на подсчёт округов не влияет).

Отказные определения ВС/ВАС (§10 X) в подсчёт не входят — их исключает агент до вызова.

Usage:
    python tools/case_law/practice_status.py classify --a1
    python tools/case_law/practice_status.py classify --skes 1 --circuits-support 3
    python tools/case_law/practice_status.py classify --circuits-support 4 --circuits-oppose 2
    python tools/case_law/practice_status.py selftest
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# --- статусы практики (§14) ---
SINGLE = "SINGLE"
REPEATED = "REPEATED"
LOCAL_STABLE = "LOCAL_STABLE"
CROSS_CIRCUIT_TREND = "CROSS_CIRCUIT_TREND"
HIGH_COURT_POSITION = "HIGH_COURT_POSITION"
ESTABLISHED_PRACTICE = "ESTABLISHED_PRACTICE"
ESTABLISHED_MAJORITY_PRACTICE = "ESTABLISHED_MAJORITY_PRACTICE"
SPLIT = "SPLIT"

# --- consistency (§13.1) ---
UNIFORM_CASSATION_PRACTICE = "UNIFORM_CASSATION_PRACTICE"
SPLIT_WITH_MAJORITY = "SPLIT_WITH_MAJORITY"
# SPLIT переиспользуется как значение consistency, когда преобладания нет.

STATUSES = {
    SINGLE, REPEATED, LOCAL_STABLE, CROSS_CIRCUIT_TREND, HIGH_COURT_POSITION,
    ESTABLISHED_PRACTICE, ESTABLISHED_MAJORITY_PRACTICE, SPLIT,
}

# established: кандидат-статус сформированной практики; не общий research STOP.
_ESTABLISHED_SET = {ESTABLISHED_PRACTICE, ESTABLISHED_MAJORITY_PRACTICE}

# Порог широты для «устоявшейся преобладающей кассационной практики» (§13.1 вариант 4):
# большинства среди 2–3 округов мало, чтобы называть практику общероссийской → нужен
# явный кросс-окружной охват. Значение — дефолт; итог подтверждает юрист.
_MAJORITY_MIN_CIRCUITS = 3


@dataclass
class PracticeInput:
    a1: bool = False
    a2: bool = False
    a4: bool = False
    skes: int = 0
    circuits_support: int = 0
    circuits_oppose: int = 0
    decisions_support: int = 0


@dataclass
class PracticeResult:
    status: str
    consistency: str | None
    established: bool
    reason: str
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "consistency": self.consistency,
            "established": self.established,
            "reason": self.reason,
            "notes": list(self.notes),
        }


def _consistency(support: int, oppose: int) -> str | None:
    if support >= 1 and oppose == 0:
        return UNIFORM_CASSATION_PRACTICE
    if oppose > 0 and support > oppose:
        return SPLIT_WITH_MAJORITY
    if oppose > 0 and support <= oppose:
        return SPLIT
    return None


def classify(inp: PracticeInput) -> PracticeResult:
    """Пороговая логика §13 → статус §14. Порядок проверок значим."""
    s, o = int(inp.circuits_support), int(inp.circuits_oppose)
    cons = _consistency(s, o)
    notes: list[str] = []
    if o > 0:
        notes.append("есть противоположные округа — межокружной split скрывать нельзя (§12.2)")

    # Вариант 1 — высшая инстанция сама по себе (§13.1). Возраст/прекращение ВАС не в счёт:
    # это уже учтено агентом при простановке a1/a2/a4 (CL-3, ВАС survival).
    if inp.a1 or inp.a2 or inp.a4:
        return PracticeResult(
            ESTABLISHED_PRACTICE, cons, True,
            "есть действующая позиция высшей инстанции (A1/A2/A4) по issue (§13.1, вариант 1)",
            notes)

    # Вариант 2 — ≥2 согласованных содержательных определения СКЭС (§13.1).
    if inp.skes >= 2:
        return PracticeResult(
            ESTABLISHED_PRACTICE, cons, True,
            "≥2 согласованных содержательных определения СКЭС по одному issue (§13.1, вариант 2)",
            notes)

    # Вариант 3 — 1 СКЭС + ≥3 согласованных кассационных округа (§13.1).
    if inp.skes >= 1 and s >= 3:
        return PracticeResult(
            ESTABLISHED_PRACTICE, cons, True,
            "1 определение СКЭС + ≥3 согласованных кассационных округа (§13.1, вариант 3)",
            notes)

    # Одно определение СКЭС без достаточного подтверждения — не сформированная практика.
    if inp.skes >= 1:
        return PracticeResult(
            HIGH_COURT_POSITION, cons, False,
            "одно содержательное определение СКЭС; для сформированной практики недостаточно (§14)",
            notes)

    # Дальше — только кассация/ниже, без A1–A4 (§13.1 вариант 4 + §14 словарь).
    if s == 0:
        if inp.decisions_support >= 1:
            return PracticeResult(SINGLE, cons, False,
                                  "нет кассационных округов за подход при наличии отдельных решений", notes)
        return PracticeResult(SINGLE, cons, False, "подтверждающей практики не обнаружено", notes)

    if s == 1:
        if inp.decisions_support >= 2:
            return PracticeResult(
                LOCAL_STABLE, cons, False,
                "устойчивая позиция ОДНОГО округа; много решений внутри округа не дают доп. голосов "
                "(§13.2) — не общероссийская практика", notes)
        return PracticeResult(SINGLE, cons, False, "единичное решение одного округа", notes)

    # s >= 2
    majority = s > o
    if majority and s >= _MAJORITY_MIN_CIRCUITS:
        return PracticeResult(
            ESTABLISHED_MAJORITY_PRACTICE, cons, True,
            f"подход поддерживают {s} округов против {o} — преобладающая кассационная практика "
            "(§13.1, вариант 4); единообразной называть нельзя при наличии меньшинства (§13.1)",
            notes)
    if majority:
        return PracticeResult(
            CROSS_CIRCUIT_TREND, cons, False,
            f"перевес есть ({s} против {o}), но кросс-окружного охвата для «преобладающей "
            f"практики» недостаточно (порог ≥{_MAJORITY_MIN_CIRCUITS} округов) — тренд (§14)",
            notes)
    # s <= o: наш подход в меньшинстве/паритете
    return PracticeResult(
        SPLIT, SPLIT, False,
        f"межокружной раскол: {s} за, {o} против; наш подход не преобладает (§14)",
        notes)


def classify_kwargs(**kw) -> PracticeResult:
    return classify(PracticeInput(**kw))


# ---------- CLI ----------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Классификатор статуса судебной практики (§13–14)")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("classify", help="классифицировать по структурированному входу")
    c.add_argument("--a1", action="store_true", help="действующий Пленум ВС/ВАС по issue")
    c.add_argument("--a2", action="store_true", help="Президиум ВС / обзор ВС / Президиум ВАС")
    c.add_argument("--a4", action="store_true", help="информ. письмо/обзор Президиума ВАС")
    c.add_argument("--skes", type=int, default=0, help="число согласованных определений СКЭС (A3)")
    c.add_argument("--circuits-support", type=int, default=0, help="округов за подход X")
    c.add_argument("--circuits-oppose", type=int, default=0, help="округов за подход Y")
    c.add_argument("--decisions-support", type=int, default=0, help="всего решений за X")
    sub.add_parser("selftest", help="прогнать встроенные тесты")
    return p


def run(argv: list[str]) -> int:
    args = _build_parser().parse_args(argv)
    if args.cmd == "selftest":
        import test_practice_status as t  # co-located
        t._run_all()
        return 0
    r = classify(PracticeInput(
        a1=args.a1, a2=args.a2, a4=args.a4, skes=args.skes,
        circuits_support=args.circuits_support, circuits_oppose=args.circuits_oppose,
        decisions_support=args.decisions_support))
    print(f"status:      {r.status}")
    print(f"consistency: {r.consistency}")
    saturation = "можно остановить добор однотипных подтверждений" if r.established else "нужно профессиональное суждение"
    print(f"established: {r.established}  ({saturation})")
    print("completion:  отдельно проверить coverage/history/regime/adverse; см. research_check.py")
    print(f"reason:      {r.reason}")
    for n in r.notes:
        print(f"note:        {n}")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent))
    raise SystemExit(run(sys.argv[1:]))
