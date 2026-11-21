# -*- coding: utf-8 -*-
"""Строка состояния: одна строка, которую агент вставляет в конец ответа. Её считает программа, руками она не пишется.
В строке есть контрольная сумма состояния проекта: по ней видно, что строка устарела или придумана."""
import hashlib
import json
import re

from .common import Fail, STAGE_NAMES, read_state, journal, read_jsonl
from .checks import stage_report, fingerprint
from .sources import list_sources
from .ledger import load_claims, cost_detail, cost_summary
from .common import STATUS_OK
from . import reqs
from . import incidents

PREFIX = "Состояние по программе: "
SUM_RX = re.compile(r"контрольная сумма ([0-9a-f]{6})\s*\.?\s*$")
CMD = "state receipt"


def _usd(x):
    return ("%.2f" % x).replace(".", ",")


def _body(proj, cfg):
    st = read_state(proj)
    cur = st["stage"]
    claims = load_claims(proj)
    facts = sum(1 for c in claims if c["type"] == "fact" and c["status"] == STATUS_OK)
    done, of, _dropped = reqs.counts(proj)
    det = cost_detail(proj)
    meas = sum(d["measured"] for d in det.values())
    if any(d["has_measured"] for d in det.values()):
        cost = "расход по замеру %s USD" % _usd(meas)
    else:
        cost = "замера расхода нет, оценка агента %s USD" % _usd(cost_summary(proj)[2])
    arts, res = stage_report(proj, cfg, cur)
    n_issues = len(arts) + sum(len(r.issues) for r in res)
    check = "проверка этапа пройдена" if not n_issues else "проверка этапа не пройдена (замечаний %d)" % n_issues
    return "этап %d из 8; источников %d; фактов %d; требований закрыто %d из %d; происшествий %d; %s; %s" % (
        cur, len(list_sources(proj)), facts, done, of, incidents.count(proj), cost, check), cur


def _sum(proj, body):
    h = hashlib.sha256(json.dumps([body, fingerprint(proj)], ensure_ascii=False).encode("utf-8")).hexdigest()
    return h[:6]


def current(proj, cfg):
    body, _cur = _body(proj, cfg)
    return "%s%s; контрольная сумма %s." % (PREFIX, body, _sum(proj, body))


def issue(proj, cfg):
    """Строка состояния; факт выдачи записывается в журнал (чтобы потом узнать более раннее состояние)."""
    line = current(proj, cfg)
    m = SUM_RX.search(line)
    rows = [r for r in read_jsonl(proj.path("journal.jsonl")) if r.get("cmd") == CMD]
    if not rows or (rows[-1].get("detail") or {}).get("line") != line:
        journal(proj, CMD, {"sum": m.group(1), "line": line})
    return line


def check(proj, cfg, line):
    """Возвращает (совпало с текущим, строки ответа)."""
    line = re.sub(r"\s+", " ", line or "").strip()
    if not line:
        raise Fail("Нужна строка состояния в кавычках.")
    if line.startswith("«") and line.endswith("»"):
        line = line[1:-1].strip()
    m = SUM_RX.search(line)
    if not line.startswith(PREFIX) or not m:
        return False, ["Это не строка состояния программы: нет начала «Состояние по программе:» или контрольной суммы. "
                       "Получить настоящую: python3 tools/rychag.py status --receipt"]
    cur = current(proj, cfg)
    if line == cur:
        return True, ["Строка совпадает с текущим состоянием задачи."]
    rows = [r for r in read_jsonl(proj.path("journal.jsonl")) if r.get("cmd") == CMD]
    for r in rows:
        d = r.get("detail") or {}
        if d.get("line") == line:
            when = (r.get("ts") or "")[:16].replace("T", " ")
            return False, ["Строка устарела: она совпадает с более ранним состоянием, записанным %s. С тех пор в задаче что-то изменилось." % when,
                           "Текущая строка: python3 tools/rychag.py status --receipt"]
    for r in rows:
        d = r.get("detail") or {}
        if d.get("sum") == m.group(1):
            when = (r.get("ts") or "")[:16].replace("T", " ")
            return False, ["Контрольная сумма известна (состояние от %s), но цифры в строке не совпадают с записанными: строку правили руками." % when]
    return False, ["Такого состояния программа не записывала: строка придумана или повреждена. Текущая строка: python3 tools/rychag.py status --receipt"]
