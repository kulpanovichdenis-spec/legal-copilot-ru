# -*- coding: utf-8 -*-
"""Расчёт по реестру группы (gov_group): группа лиц, аффилированные лица, журнал изменений,
связанные стороны, владение на дату. Чистые функции над словарём реестра, без LLM.

Признаки применяются механически:
- группа лиц — Федеральный закон от 26.07.2006 № 135-ФЗ, ст. 9 ч. 1: п. 1 (более 50 % голосов),
  п. 2 (единоличный исполнительный орган), п. 7 (родственники, только внесённые юристом),
  п. 8 (лица, связанные через общее лицо, цепочки замыкаются полностью), п. 9 (совместно более 50 %);
  пп. 3–6 не считаются: нужных сведений в реестре нет;
- аффилированные лица общества — Закон РСФСР от 22.03.1991 № 948-1, ст. 4: ЕИО и члены совета
  директоров, лица одной группы, лица с более чем 20 % голосов в обществе, юридические лица, где
  у общества более 20 % голосов;
- связанные стороны — ПБУ 11/2008, п. 4: аффилированные лица в любой момент периода плюс внесённые
  юристом участники совместной деятельности и НПФ (pbu11_other).
Голоса участника ООО считаются без доли, принадлежащей самому обществу (own_share компании).
Дата основания — начало непрерывного периода, в котором основание действует на дату списка.
"""
from __future__ import annotations

import datetime as dt
import sys
from collections import defaultdict, deque
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gov_group as gg  # noqa: E402

LAW_135 = "ч. 1 ст. 9 Закона № 135-ФЗ"
CODE_ORDER = ("eio", "board", "holds_20", "held_20", "group")
BASIS_TEXT = {
    "eio": "лицо осуществляет полномочия единоличного исполнительного органа общества",
    "board": "лицо является членом совета директоров общества",
    "holds_20": "лицо имеет право распоряжаться более чем 20 % общего количества голосов, приходящихся "
                "на доли, составляющие уставный капитал общества",
    "held_20": "общество имеет право распоряжаться более чем 20 % общего количества голосов, приходящихся "
               "на голосующие акции либо составляющие уставный или складочный капитал вклады, доли данного лица",
    "group": "лицо принадлежит к той группе лиц, к которой принадлежит общество",
}
_MIN = dt.date.min


# ---------- период действия записи ----------

def _period(record: dict, parties: tuple[str, ...], by_id: dict) -> tuple[dt.date, dt.date | None]:
    """[начало, окончание): закрытие любой из сторон тоже прекращает связь."""
    ends = [gg.as_date(record.get("until"), end=True)]
    ends += [gg.closure_end(by_id[p]) for p in parties if p in by_id]
    ends = [e for e in ends if e is not None]
    return gg.as_date(record.get("since")) or _MIN, min(ends) if ends else None


def _active(record: dict, parties: tuple[str, ...], by_id: dict, day: dt.date) -> bool:
    start, end = _period(record, parties, by_id)
    return start <= day and (end is None or day < end)


def holdings_at(data: dict, day: dt.date) -> list[dict]:
    """Действующие на дату доли: владелец, общество, доля в капитале и доля голосов."""
    by_id = gg.entities_by_id(data)
    out = []
    for link in data["links"]:
        if not _active(link, (link["owner"], link["target"]), by_id, day):
            continue
        share = gg.percent(link.get("percent"))
        own = gg.percent(by_id[link["target"]].get("own_share"))
        votes = share * 100 / (100 - own) if share is not None and own and own < 100 else share
        out.append({"owner": link["owner"], "target": link["target"], "percent": share, "votes": votes,
                    "link": link})
    return out


def _offices_at(data: dict, day: dt.date) -> list[dict]:
    by_id = gg.entities_by_id(data)
    return [o for o in data["offices"] if _active(o, (o["person"], o["company"]), by_id, day)]


def ultimate_owners(data: dict, day: dt.date) -> list[str]:
    """Владельцы долей, у которых самих владельцев в реестре на дату нет."""
    holdings = holdings_at(data, day)
    owned = {h["target"] for h in holdings}
    return sorted({h["owner"] for h in holdings} - owned)


# ---------- группа лиц ----------

def _votes_text(h: dict) -> str:
    text = gg.fmt_percent(h["percent"]) or "доля неизвестного размера"
    if h["votes"] is not None and h["votes"] != h["percent"]:
        text += f" ({gg.fmt_percent(round(h['votes'], 2))} голосов без доли, принадлежащей обществу)"
    return text


class Group:
    """Группы лиц на дату: объединение по признакам и рёбра с пояснением для цепочек."""

    def __init__(self, by_id: dict):
        self.by_id = by_id
        self.parent = {eid: eid for eid in by_id}
        self.adj: dict[str, list[tuple[str, str]]] = defaultdict(list)

    def find(self, x: str) -> str:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str, text: str) -> None:
        self.adj[a].append((b, text))
        self.adj[b].append((a, text))
        self.parent[self.find(a)] = self.find(b)

    def members(self, x: str) -> set[str]:
        root = self.find(x)
        return {y for y in self.parent if self.find(y) == root}

    def path(self, a: str, b: str) -> list[str]:
        """Пояснения рёбер кратчайшей цепочки от a до b."""
        prev: dict[str, tuple[str, str] | None] = {a: None}
        queue = deque([a])
        while queue:
            x = queue.popleft()
            if x == b:
                break
            for y, text in self.adj[x]:
                if y not in prev:
                    prev[y] = (x, text)
                    queue.append(y)
        steps, x = [], b
        while prev.get(x):
            x, text = prev[x]
            steps.append(text)
        return steps[::-1]

    def path_text(self, a: str, b: str) -> str:
        steps = self.path(a, b)
        if len(steps) == 1:
            return steps[0]
        return f"по цепочке (п. 8 {LAW_135}): " + "; ".join(steps)


def group_at(data: dict, day: dt.date) -> Group:
    by_id = gg.entities_by_id(data)
    name = lambda eid: gg.label(by_id[eid])  # noqa: E731
    g = Group(by_id)
    holdings = holdings_at(data, day)
    for h in holdings:
        if h["votes"] is not None and h["votes"] > 50:
            g.union(h["owner"], h["target"],
                    f"{name(h['owner'])} владеет долей {_votes_text(h)} в уставном капитале {name(h['target'])} "
                    f"(п. 1 {LAW_135})")
    for o in _offices_at(data, day):
        if o["role"] == "eio":
            g.union(o["person"], o["company"],
                    f"{name(o['person'])} осуществляет функции единоличного исполнительного органа "
                    f"{name(o['company'])} (п. 2 {LAW_135})")
    for r in data["relatives"]:
        if _active(r, (r["a"], r["b"]), by_id, day):
            g.union(r["a"], r["b"], f"{name(r['a'])} и {name(r['b'])}: {r['relation']} (п. 7 {LAW_135})")
    changed = True
    while changed:  # п. 9: лица одной группы совместно имеют более 50 % голосов
        changed = False
        for target in {h["target"] for h in holdings}:
            joint: dict[str, list[dict]] = defaultdict(list)
            for h in holdings:
                if h["target"] == target and h["votes"] is not None:
                    joint[g.find(h["owner"])].append(h)
            for root, items in joint.items():
                total = sum((h["votes"] for h in items), Decimal(0))
                if len(items) < 2 or root == g.find(target) or total <= 50:
                    continue
                lead = max(items, key=lambda h: h["votes"])["owner"]
                who = ", ".join(name(h["owner"]) for h in items)
                g.union(lead, target, f"{who} совместно имеют {gg.fmt_percent(round(total, 3))} голосов в "
                                      f"{name(target)} (п. 9 {LAW_135})")
                changed = True
    return g


# ---------- аффилированные лица ----------

def affiliates_at(data: dict, cid: str, day: dt.date) -> dict[str, dict]:
    """{id лица: {"codes", "holds" (доля лица в обществе), "held" (доля общества в лице), "detail"}}."""
    g = group_at(data, day)
    holdings = holdings_at(data, day)
    out: dict[str, dict] = {}

    def entry(eid: str) -> dict:
        return out.setdefault(eid, {"codes": set(), "holds": None, "held": None, "detail": ""})

    for o in _offices_at(data, day):
        if o["company"] == cid:
            entry(o["person"])["codes"].add(o["role"])
    for eid in g.members(cid) - {cid}:
        item = entry(eid)
        item["codes"].add("group")
        item["detail"] = g.path_text(cid, eid)
    for h in holdings:
        if h["votes"] is not None and h["votes"] > 20:
            if h["target"] == cid:
                entry(h["owner"])["codes"].add("holds_20")
            elif h["owner"] == cid:
                entry(h["target"])["codes"].add("held_20")
    for h in holdings:
        if h["target"] == cid and h["owner"] in out:
            out[h["owner"]]["holds"] = h["percent"]
        if h["owner"] == cid and h["target"] in out:
            out[h["target"]]["held"] = h["percent"]
    out.pop(cid, None)
    return out


def _snapshot(item: dict) -> tuple:
    return frozenset(item["codes"]), item["holds"], item["held"]


class History:
    """Состояние аффилированности общества на каждую дату события реестра (с кэшем)."""

    def __init__(self, data: dict, cid: str):
        self.data, self.cid = data, cid
        self.shown: dict[dt.date, str] = {}
        self._rank: dict[dt.date, int] = {}
        for record in (*data["links"], *data["offices"], *data["relatives"]):
            self._add(record.get("since"), end=False)
            self._add(record.get("until"), end=True, approx=record.get("until_note") == gg.APPROX)
        for entity in data["entities"]:
            if entity.get("closed"):
                self._put(gg.closure_end(entity), gg.fmt_date(entity["closed"]), 0 if gg.is_year(entity["closed"]) else 2)
        self.points = [_MIN, *sorted(self.shown)]
        self._cache: dict[dt.date, dict] = {}

    def _add(self, raw, *, end: bool, approx: bool = False) -> None:
        """Подпись даты события: точная дата важнее «не позднее …», та важнее года."""
        day = gg.as_date(raw, end=end)
        if day is None:
            return
        rank = 0 if gg.is_year(raw) else 1 if approx else 2
        self._put(day, (f"{gg.APPROX} " if rank == 1 else "") + gg.fmt_date(raw), rank)

    def _put(self, day: dt.date, text: str, rank: int) -> None:
        if rank >= self._rank.get(day, -1):
            self._rank[day] = rank
            self.shown[day] = text

    def text(self, day: dt.date | None) -> str:
        if day is None or day == _MIN:
            return ""
        return self.shown.get(day) or gg.fmt_date(day)

    def at(self, day: dt.date) -> dict:
        if day not in self._cache:
            self._cache[day] = affiliates_at(self.data, self.cid, day)
        return self._cache[day]

    def run_start(self, day: dt.date, holds) -> dt.date | None:
        """Начало непрерывного периода до day, в котором holds(состояние) истинно; None — неизвестно."""
        start = None
        for point in reversed([p for p in self.points if p <= day]):
            if not holds(self.at(point)):
                break
            start = point
        return None if start in (None, _MIN) else start

    def between(self, start: dt.date, end: dt.date) -> list[dt.date]:
        return [p for p in self.points if start < p <= end]


def _unknown_before(data: dict, cid: str, eid: str, day: dt.date | None) -> bool:
    """Накануне даты основания между обществом и лицом была доля неизвестного размера:
    основание могло действовать и раньше, дата недостоверна."""
    if day is None or day == _MIN:
        return False
    before = day - dt.timedelta(days=1)
    return any(h["percent"] is None and {h["owner"], h["target"]} == {cid, eid} for h in holdings_at(data, before))


def _since_text(history: "History", data: dict, cid: str, eid: str, since: dt.date | None) -> str:
    text = history.text(since)
    return f"{text} [ПРОВЕРИТЬ ФАКТ]" if text and _unknown_before(data, cid, eid, since) else text


def affiliate_rows(data: dict, cid: str, day: dt.date) -> list[dict]:
    """Строки списка аффилированных лиц на дату: лицо, основания с датами, цепочка, доли."""
    by_id = gg.entities_by_id(data)
    history = History(data, cid)
    rows = []
    for eid, item in affiliates_at(data, cid, day).items():
        bases = []
        for code in CODE_ORDER:
            if code in item["codes"]:
                since = history.run_start(day, lambda state, e=eid, c=code: c in state.get(e, {}).get("codes", ()))
                bases.append({"code": code, "text": BASIS_TEXT[code], "since": since,
                              "since_text": _since_text(history, data, cid, eid, since)})
        rows.append({"entity": by_id[eid], "bases": bases, "detail": item["detail"], "holds": item["holds"],
                     "held": item["held"]})
    rows.sort(key=lambda r: (CODE_ORDER.index(r["bases"][0]["code"]), gg.label(r["entity"])))
    return rows


def changes(data: dict, cid: str, start: dt.date, end: dt.date) -> list[dict]:
    """Включения, исключения и изменения (основания, доли) по датам событий в (start, end]."""
    by_id = gg.entities_by_id(data)
    history = History(data, cid)
    previous = history.at(start)
    out = []
    for point in history.between(start, end):
        current = history.at(point)
        for eid in sorted(set(previous) | set(current), key=lambda e: gg.label(by_id[e])):
            before, after = previous.get(eid), current.get(eid)
            if before and not after:
                kind = "exclude"
            elif after and not before:
                kind = "include"
            elif _snapshot(before) != _snapshot(after):
                kind = "change"
            else:
                continue
            out.append({"date": point, "date_text": history.text(point), "kind": kind, "entity": by_id[eid],
                        "before": before, "after": after})
        previous = current
    return out


# ---------- связанные стороны ----------

def related_parties(data: dict, cid: str, start: dt.date, end: dt.date) -> list[dict]:
    """Аффилированные лица в любой момент [start, end] (выбывшие — с датой выбытия) и pbu11_other."""
    by_id = gg.entities_by_id(data)
    history = History(data, cid)
    points = [start, *history.between(start, end)]
    codes: dict[str, set] = defaultdict(set)
    for point in points:
        for eid, item in history.at(point).items():
            codes[eid] |= item["codes"]
    out = []
    for eid, found in codes.items():
        present = [p for p in points if eid in history.at(p)]
        since = history.run_start(present[0], lambda state, e=eid: e in state)
        later = [p for p in points if p > present[-1] and eid not in history.at(p)]
        until = later[0] if later else None
        out.append({"entity": by_id[eid], "other": None, "codes": [c for c in CODE_ORDER if c in found],
                    "since": since, "since_text": _since_text(history, data, cid, eid, since), "until": until,
                    "until_text": history.text(until), "detail": history.at(present[-1])[eid]["detail"]})
    out.sort(key=lambda r: (CODE_ORDER.index(r["codes"][0]), gg.label(r["entity"])))
    for other in data["pbu11_other"]:
        if other.get("company") != cid:
            continue
        since, until = gg.as_date(other.get("since")), gg.as_date(other.get("until"), end=True)
        if (since or _MIN) <= end and (until is None or until > start):
            out.append({"entity": None, "other": other, "codes": [], "since": since,
                        "since_text": gg.fmt_date(other.get("since")), "until": until,
                        "until_text": gg.fmt_date(other.get("until")), "detail": ""})
    return out
