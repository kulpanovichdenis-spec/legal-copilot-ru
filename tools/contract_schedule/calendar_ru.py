#!/usr/bin/env python3
"""Календарная арифметика для сроков по ГК РФ (ст. 190-193).

Safety contract:
- Год, выверенный юристом по официальному постановлению (загружен в
  `holidays_ru.yaml`), считается ПОДТВЕРЖДЁННЫМ (`year_source == "confirmed"`)
  и работает ВСЕГДА, для любого года, без всяких границ — данные подтверждены
  человеком, генератор для них не нужен.
- Год, НЕ подтверждённый юристом, обслуживается ГЕНЕРАТОРОМ только в границах
  GENERATOR_MIN_YEAR-GENERATOR_MAX_YEAR (сейчас 2015-2100). Генератор считает
  по фиксированному перечню праздников ст. 112 ТК РФ с автопереносом по ч. 2
  ст. 112 (`year_source == "generated"`). Он НЕ восстанавливает дискреционные
  переносы Правительства (последний абзац ст. 112, окно 1-8 января) — это
  недетерминированная часть, из закона не выводится. Вызывающий код обязан
  явно предупреждать о расчётных годах через `spans_generated_year` — модуль
  сам не отказывает молча, но и не скрывает условность расчёта.
- Неподтверждённый год за пределами GENERATOR_MIN_YEAR-GENERATOR_MAX_YEAR
  отклоняется CalendarError: за этими границами перечень праздников заведомо
  другой (менялся до 2015 — 4 ноября появилось не сразу, 7 ноября и
  12 декабря перестали быть праздниками), генератору приближать нельзя.
  Сообщение об ошибке — это просьба к юристу, а не тупик: оно называет
  причину и просит загрузить выверенный производственный календарь на этот
  год в `holidays_ru.yaml` (после чего год становится подтверждённым и
  граница генератора на него уже не действует).
- Модуль ничего не знает про договоры и обязательства — только про даты.

Правила, которые реализованы (сверено по ГК РФ — legal-kb / pravo.gov.ru):
- ст. 191 ГК — течение срока, определённого периодом времени, начинается на
  следующий день после календарной даты или наступления события;
- ст. 192 ГК — срок в месяцах истекает в соответствующее число последнего
  месяца; если такого числа нет — в последний день месяца; неделями — в
  соответствующий день последней недели; годами — в соответствующие месяц и число;
- ст. 193 ГК — если последний день срока приходится на нерабочий день, днём
  окончания считается ближайший следующий рабочий день.

Usage:
    python -m tools.contract_schedule.calendar_ru selftest
"""
from __future__ import annotations

import calendar as _calendar
import datetime as dt
import sys
from pathlib import Path

import yaml

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_CALENDAR_PATH = Path(__file__).with_name("holidays_ru.yaml")
UNITS = ("calendar_days", "business_days", "banking_days", "weeks", "months", "years")
BUSINESS_UNITS = ("business_days", "banking_days")


class CalendarError(Exception):
    pass


# ст. 112 ТК РФ, действующая редакция (сверено по производственному
# календарю КонсультантПлюс на 2026 год — см. task-4b-brief.md).
# Блок новогодних каникул (1-8 января): переносы совпавших выходных
# распределяет Правительство по своему усмотрению — из закона не выводятся,
# генератор их НЕ строит.
JAN_BLOCK_MD: tuple[tuple[int, int], ...] = (
    (1, 1), (1, 2), (1, 3), (1, 4), (1, 5), (1, 6), (1, 7), (1, 8),
)
# Остальные праздники ст. 112: попадание на сб/вс переносится по ч. 2 ст. 112
# на ближайший следующий рабочий день — это правило детерминировано.
TRANSFERABLE_HOLIDAYS_MD: tuple[tuple[int, int], ...] = (
    (2, 23), (3, 8), (5, 1), (5, 9), (6, 12), (11, 4),
)


def _generate_holidays(year: int) -> set[dt.date]:
    """Нерабочие праздничные дни ст. 112 ТК РФ на произвольный год.

    Строит фиксированный перечень + автоперенос по ч. 2 ст. 112 для
    праздников вне новогоднего блока. НЕ включает дискреционные переносы
    Правительства (блок 1-8 января) — они не выводятся из закона.
    """
    holidays = {dt.date(year, m, d) for m, d in JAN_BLOCK_MD}
    transferable = [dt.date(year, m, d) for m, d in TRANSFERABLE_HOLIDAYS_MD]
    holidays.update(transferable)
    for holiday in transferable:
        if holiday.weekday() < 5:
            continue
        transfer = holiday + dt.timedelta(days=1)
        while transfer.weekday() >= 5 or transfer in holidays:
            transfer += dt.timedelta(days=1)
        holidays.add(transfer)
    return holidays


class WorkCalendar:
    """Производственный календарь. Подтверждённые годы (из YAML или переданные
    напрямую) работают ВСЕГДА, для любого года — без границ генератора. Любой
    другой год ГЕНЕРИРУЕТСЯ по ст. 112 ТК РФ, но только в границах
    GENERATOR_MIN_YEAR-GENERATOR_MAX_YEAR."""

    # Граница относится ТОЛЬКО К ГЕНЕРАТОРУ, не к модулю в целом:
    # подтверждённый год из holidays_ru.yaml работает и за пределами этой
    # границы (см. _check_bounds — он вызывается, только когда год не найден
    # среди подтверждённых).
    #
    # 2015 выбран с запасом позже последнего изменения перечня нерабочих
    # праздничных дней ст. 112 ТК РФ (7 ноября и 12 декабря были праздниками
    # раньше и перестали ими быть; 4 ноября стало праздником не сразу).
    # Точные годы этих изменений достоверно не установить: полной истории
    # редакций ст. 112 ГК под рукой нет. Поэтому решение юриста — не пытаться
    # поддерживать генератором более
    # ранние годы. Для года вне этой границы юрист загружает выверенный
    # производственный календарь в holidays_ru.yaml — это работает без
    # изменения константы (год становится подтверждённым).
    GENERATOR_MIN_YEAR = 2015
    GENERATOR_MAX_YEAR = 2100

    def __init__(self, years: dict) -> None:
        self._holidays: dict[int, set[dt.date]] = {}
        self._extra_workdays: dict[int, set[dt.date]] = {}
        self._generated_cache: dict[int, set[dt.date]] = {}
        for year, block in (years or {}).items():
            y = int(year)
            self._holidays[y] = {_as_date(x) for x in (block.get("holidays") or [])}
            self._extra_workdays[y] = {_as_date(x) for x in (block.get("extra_workdays") or [])}

    @classmethod
    def load(cls, path: Path | None = None) -> "WorkCalendar":
        p = Path(path) if path else DEFAULT_CALENDAR_PATH
        if not p.exists():
            raise CalendarError(f"файл производственного календаря не найден: {p}")
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        if "years" not in data:
            raise CalendarError(f"файл не похож на производственный календарь: {p}")
        return cls(data["years"])

    def year_source(self, year: int) -> str:
        """'confirmed' — год выверен юристом (загружен в holidays_ru.yaml),
        работает для любого года без границ генератора; 'generated' —
        рассчитан генератором по ст. 112 ТК, только в границах
        GENERATOR_MIN_YEAR-GENERATOR_MAX_YEAR (иначе CalendarError)."""
        if year in self._holidays:
            return "confirmed"
        self._check_bounds(year)
        return "generated"

    def _check_bounds(self, year: int) -> None:
        """Граница ГЕНЕРАТОРА, а не модуля: зовётся только для года, которого
        нет среди подтверждённых (см. вызовы в year_source/require_year/
        _holidays_for). Сообщение — не отказ, а просьба к юристу: называет
        причину и конкретное действие (загрузить календарь в holidays_ru.yaml)."""
        if year < self.GENERATOR_MIN_YEAR:
            raise CalendarError(
                f"производственный календарь на {year} год не загружен, а "
                f"сгенерировать его нельзя: перечень нерабочих праздничных "
                f"дней ст. 112 ТК РФ в {year} году отличался от действующего "
                f"(генератор поддерживает {self.GENERATOR_MIN_YEAR} год и "
                f"позже) — загрузите выверенный производственный календарь "
                f"на {year} год в holidays_ru.yaml."
            )
        if year > self.GENERATOR_MAX_YEAR:
            raise CalendarError(
                f"производственный календарь на {year} год не загружен, а "
                f"генератор его не строит: год вне поддерживаемого диапазона "
                f"генератора ({self.GENERATOR_MIN_YEAR}-{self.GENERATOR_MAX_YEAR}) "
                f"— загрузите выверенный производственный календарь на "
                f"{year} год в holidays_ru.yaml."
            )

    def require_year(self, d: dt.date) -> None:
        """Публичная: год обслуживается (подтверждён ИЛИ в границах
        генератора)? Иначе CalendarError. Зовут и resolver, и end_of_term.
        Подтверждённый год работает всегда, без границ генератора."""
        if d.year in self._holidays:
            return
        self._check_bounds(d.year)

    def _holidays_for(self, year: int) -> set[dt.date]:
        if year in self._holidays:
            return self._holidays[year]
        if year not in self._generated_cache:
            self._check_bounds(year)
            self._generated_cache[year] = _generate_holidays(year)
        return self._generated_cache[year]

    def is_working_day(self, d: dt.date) -> bool:
        self.require_year(d)
        if d in self._extra_workdays.get(d.year, ()):
            return True
        if d in self._holidays_for(d.year):
            return False
        return d.weekday() < 5

    def roll_forward(self, d: dt.date) -> dt.date:
        """ст. 193 ГК: последний день на нерабочий -> ближайший следующий рабочий."""
        cur = d
        for _ in range(400):
            if self.is_working_day(cur):
                return cur
            cur += dt.timedelta(days=1)
        raise CalendarError(f"не удалось найти рабочий день после {d.isoformat()}")

    def add_business_days(self, start: dt.date, n: int) -> dt.date:
        """Отсчёт n рабочих дней; течение начинается со следующего дня (ст. 191 ГК)."""
        if n < 0:
            raise CalendarError("add_business_days: отрицательное количество дней")
        cur = start
        left = n
        for _ in range(n * 10 + 400):
            if left == 0:
                return cur
            cur += dt.timedelta(days=1)
            if self.is_working_day(cur):
                left -= 1
        raise CalendarError(f"не удалось отсчитать {n} рабочих дней от {start.isoformat()}")


def _as_date(value) -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(str(value))


def _add_months(d: dt.date, n: int) -> dt.date:
    """ст. 192 ГК: соответствующее число последнего месяца; нет такого — последний день."""
    year = d.year + (d.month - 1 + n) // 12
    month = (d.month - 1 + n) % 12 + 1
    last_day = _calendar.monthrange(year, month)[1]
    return dt.date(year, month, min(d.day, last_day))


def end_of_term(anchor: dt.date, offset: int, unit: str,
                cal: WorkCalendar, direction: str = "after") -> dt.date:
    """Дата окончания срока, отложенного от anchor.

    direction="after"  — срок течёт после события (типовой случай), применяется ст. 193;
    direction="before" — отсчёт назад от события («за 30 дней до…»); ст. 193 НЕ
    применяется, потому что перенос установлен для окончания срока, а не для его начала.
    """
    if unit not in UNITS:
        raise CalendarError(f"неизвестная единица срока: {unit!r} (допустимо: {', '.join(UNITS)})")
    if direction not in ("after", "before"):
        raise CalendarError(f"неизвестное направление: {direction!r}")

    sign = 1 if direction == "after" else -1

    if unit in BUSINESS_UNITS:
        if direction == "before":
            raise CalendarError(
                "отсчёт рабочих дней назад (direction=before) в MVP не поддержан — "
                "укажите срок в календарных днях или задайте дату явно"
            )
        cal.require_year(anchor)
        return cal.add_business_days(anchor, offset)

    if unit == "calendar_days":
        raw = anchor + dt.timedelta(days=sign * offset)
    elif unit == "weeks":
        raw = anchor + dt.timedelta(days=sign * offset * 7)
    elif unit == "months":
        raw = _add_months(anchor, sign * offset)
    else:  # years
        raw = _add_months(anchor, sign * offset * 12)

    cal.require_year(raw)
    if direction == "before":
        return raw
    return cal.roll_forward(raw)


def spans_generated_year(start: dt.date, end: dt.date, cal: WorkCalendar) -> list[int]:
    """Список годов в диапазоне [start, end], рассчитанных генератором ст. 112 ТК,
    а не подтверждённых юристом по постановлению. Публичная — зовёт resolver.py
    после успешного вычисления даты обязательства, чтобы предупредить юриста."""
    if end < start:
        start, end = end, start
    return [y for y in range(start.year, end.year + 1) if cal.year_source(y) == "generated"]


def selftest() -> int:
    cal = WorkCalendar.load()

    # Сходимость календаря 2026: 247 рабочих / 118 нерабочих.
    work = nonwork = 0
    d = dt.date(2026, 1, 1)
    while d.year == 2026:
        if cal.is_working_day(d):
            work += 1
        else:
            nonwork += 1
        d += dt.timedelta(days=1)
    assert (work, nonwork) == (247, 118), f"календарь 2026 не сходится: {work}/{nonwork}"

    # ст. 191 + рабочие дни: 10 рабочих дней от чт 15.01.2026 -> чт 29.01.2026.
    assert end_of_term(dt.date(2026, 1, 15), 10, "business_days", cal) == dt.date(2026, 1, 29)

    # ст. 193: 3 календарных дня от пт 20.02.2026 -> 23.02 (праздник) -> 24.02.
    assert end_of_term(dt.date(2026, 2, 20), 3, "calendar_days", cal) == dt.date(2026, 2, 24)

    # ст. 192: 1 месяц от 31.01.2026 -> 28.02 (нет 31-го) -> сб -> ст. 193 -> пн 02.03.
    assert end_of_term(dt.date(2026, 1, 31), 1, "months", cal) == dt.date(2026, 3, 2)

    # ст. 192 п.4: 2 недели от 01.04.2026 (ср) -> 15.04.2026 (ср, рабочий).
    assert end_of_term(dt.date(2026, 4, 1), 2, "weeks", cal) == dt.date(2026, 4, 15)

    # banking_days считаются как business_days (решение MVP).
    assert (end_of_term(dt.date(2026, 1, 15), 10, "banking_days", cal)
            == end_of_term(dt.date(2026, 1, 15), 10, "business_days", cal))

    # direction=before: перенос по ст. 193 НЕ применяется (это начало, не окончание).
    # 30 календарных дней до 12.06.2026 -> 13.05.2026.
    assert end_of_term(dt.date(2026, 6, 12), 30, "calendar_days", cal,
                       direction="before") == dt.date(2026, 5, 13)

    # Год вне календаря (2027, не подтверждён юристом) больше НЕ отказ:
    # генератор по ст. 112 ТК считает его сам. 5 рабочих дней от 29.12.2026
    # уходят в январь 2027 (генерируемый) -> 14.01.2027.
    assert end_of_term(dt.date(2026, 12, 29), 5, "business_days", cal) == dt.date(2027, 1, 14)

    # offset=0 c business/banking_days на генерируемый год (в пределах 2015-2100)
    # больше не отказ — считается тем же годом.
    assert end_of_term(dt.date(2020, 1, 15), 0, "business_days", cal) == dt.date(2020, 1, 15)
    assert end_of_term(dt.date(2020, 1, 15), 0, "banking_days", cal) == dt.date(2020, 1, 15)

    # Неизвестная единица измерения.
    try:
        end_of_term(dt.date(2026, 1, 15), 5, "fortnights", cal)
        raise AssertionError("неизвестная единица должна падать")
    except CalendarError:
        pass

    # --- Task 4b: генерация календаря на произвольный год --------------------

    # Главный тест: генератор воспроизводит подтверждённый 2026 год ВЕЗДЕ,
    # кроме двух дискреционных январских переносов (не выводятся из закона).
    generated_2026 = _generate_holidays(2026)
    confirmed_2026 = cal._holidays[2026]
    diff_confirmed_only = confirmed_2026 - generated_2026
    diff_generated_only = generated_2026 - confirmed_2026
    assert diff_confirmed_only == {dt.date(2026, 1, 9), dt.date(2026, 12, 31)}, diff_confirmed_only
    assert diff_generated_only == set(), diff_generated_only

    # year_source: 2026 подтверждён юристом, 2027 — расчётный.
    assert cal.year_source(2026) == "confirmed"
    assert cal.year_source(2027) == "generated"

    # ст. 192: 12 месяцев от 10.03.2026 -> 10.03.2027, обычный будний день,
    # считается без отказа (производственный календарь для самой даты не нужен).
    assert end_of_term(dt.date(2026, 3, 10), 12, "months", cal) == dt.date(2027, 3, 10)

    # 2027: 8 марта — понедельник, обычный праздник БЕЗ автопереноса
    # (следующий день, 9 марта, рабочий).
    assert cal.is_working_day(dt.date(2027, 3, 8)) is False
    assert cal.is_working_day(dt.date(2027, 3, 9)) is True

    # 2027: 9 мая — воскресенье -> автоперенос по ч. 2 ст. 112 ТК на 10 мая.
    assert cal.is_working_day(dt.date(2027, 5, 9)) is False
    assert cal.is_working_day(dt.date(2027, 5, 10)) is False

    # Год за пределами генератора (не подтверждённый) -> CalendarError.
    try:
        cal.year_source(1900)
        raise AssertionError("год 1900 вне диапазона должен падать")
    except CalendarError:
        pass
    try:
        end_of_term(dt.date(2200, 1, 15), 1, "calendar_days", cal)
        raise AssertionError("год 2200 вне диапазона должен падать")
    except CalendarError:
        pass

    # spans_generated_year: диапазон целиком в подтверждённом 2026 -> [].
    assert spans_generated_year(dt.date(2026, 1, 15), dt.date(2026, 12, 1), cal) == []

    # spans_generated_year: диапазон уходит в расчётный 2027 -> [2027].
    assert spans_generated_year(dt.date(2026, 12, 1), dt.date(2027, 3, 10), cal) == [2027]

    # --- Task 4b (правка): граница относится только к ГЕНЕРАТОРУ ------------

    # ГЛАВНЫЙ ТЕСТ: подтверждённый год ВНЕ зоны генератора (2003 < 2015)
    # обязан работать всегда — граница ограничивает только генератор, не
    # подтверждённые данные. Собираем WorkCalendar напрямую из словаря
    # (holidays_ru.yaml не трогаем), кладём в него 2003 год с парой
    # праздников (4 ноября в 2003 году праздником НЕ было — это сознательно
    # не совпадает с действующим перечнем, чтобы показать, что подтверждённые
    # данные не подгоняются под генератор).
    confirmed_2003 = WorkCalendar({
        2003: {
            "holidays": ["2003-01-01", "2003-01-02", "2003-05-01", "2003-05-09"],
            "extra_workdays": [],
        }
    })
    assert confirmed_2003.year_source(2003) == "confirmed"
    assert confirmed_2003.is_working_day(dt.date(2003, 1, 1)) is False
    assert confirmed_2003.is_working_day(dt.date(2003, 11, 4)) is True  # обычный будний день
    assert confirmed_2003.is_working_day(dt.date(2003, 1, 3)) is True  # пятница, будний
    # Расчёт по подтверждённому 2003 году отрабатывает без CalendarError,
    # хотя год далеко за пределами генератора.
    assert end_of_term(dt.date(2003, 1, 3), 3, "business_days", confirmed_2003) == dt.date(2003, 1, 8)

    # Год ниже границы генератора (2014), НЕ подтверждённый в этом календаре
    # -> CalendarError с сообщением-действием: причина (перечень праздников
    # отличался) + конкретное действие (загрузить календарь в holidays_ru.yaml).
    try:
        cal.year_source(2014)
        raise AssertionError("год 2014 ниже GENERATOR_MIN_YEAR должен падать")
    except CalendarError as exc:
        msg = str(exc)
        assert "перечень" in msg and "праздни" in msg, msg
        assert "holidays_ru.yaml" in msg, msg

    # Граница генератора включительна: 2015 генерируется нормально.
    assert cal.year_source(2015) == "generated"

    # Регрессия: 2003 год раньше молча считался (4 ноября ошибочно нерабочий).
    # В календаре, где 2003 НЕ подтверждён (обычный `cal` из файла), год ниже
    # границы генератора -> CalendarError, а не молчаливый неверный расчёт.
    try:
        cal.year_source(2003)
        raise AssertionError("год 2003 ниже GENERATOR_MIN_YEAR должен падать")
    except CalendarError:
        pass

    # Год выше верхней границы генератора, не подтверждённый -> CalendarError
    # с сообщением-действием (тоже загрузить календарь, а не просто "вне диапазона").
    try:
        cal.year_source(2200)
        raise AssertionError("год 2200 выше GENERATOR_MAX_YEAR должен падать")
    except CalendarError as exc:
        msg = str(exc)
        assert "holidays_ru.yaml" in msg, msg

    print("calendar_ru selftest: OK")
    return 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        return selftest()
    print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
