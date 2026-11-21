# -*- coding: utf-8 -*-
"""След запросов в журнале проекта: что искали в базе знаний и на карте причин и сколько нашли.
По этим записям проверки узнают, смотрел ли агент в базу и на карту, прежде чем писать «пусто»."""
import re

from .common import resolve_project, find_projects, journal, read_state, read_jsonl
from . import kb as kbase

SEARCH_CMD = "kb search"
SHOW_CMD = "kb show"
MAP_CMDS = ("map causes", "map effects", "map path")
MAP_DIAG_CMDS = ("map causes", "map effects")
QUERY_CMDS = (SEARCH_CMD, SHOW_CMD) + MAP_CMDS


def trace_project(root, name=None):
    """Проект, в журнал которого пишется след запроса: названный явно или единственный действующий. Иначе None."""
    if name:
        return resolve_project(root, name)
    cand = [p for p in find_projects(root) if not p.startswith("_")]
    if len(cand) == 1:
        return resolve_project(root, cand[0])
    if not cand and len(find_projects(root)) == 1:
        return resolve_project(root, find_projects(root)[0])
    return None


def no_project_hint(root, name=None):
    """Строка-подсказка, если проектов несколько и след записать некуда."""
    if name:
        return None
    cand = [p for p in find_projects(root) if not p.startswith("_")]
    if len(cand) > 1:
        return "След запроса в журнал не записан: задач несколько. Добавьте --project ID, чтобы запрос был виден в журнале и в проверках."
    return None


def record_query(proj, cmd, detail):
    if proj is not None:
        journal(proj, cmd, detail)


def _rows_after_start(proj):
    st = read_state(proj)
    start = str(st.get("created") or "")
    out = []
    for r in read_jsonl(proj.path("journal.jsonl")):
        if (r.get("ts") or "")[:10] >= start:
            out.append(r)
    return out


def searched_layer(proj, n):
    """Был ли после создания проекта поиск по базе знаний, который честно показывает, что в слое n пусто:
    поиск, ограниченный этим слоем, либо поиск по словам, где результатов в слое n было ноль."""
    for r in _rows_after_start(proj):
        if r.get("cmd") != SEARCH_CMD:
            continue
        d = r.get("detail") or {}
        if d.get("layer") == n:
            return True
        pl = d.get("per_layer") or {}
        if (d.get("query") or "").strip() and pl.get(str(n)) == 0:
            return True
    return False


def map_consulted(proj):
    return any(r.get("cmd") in MAP_DIAG_CMDS for r in _rows_after_start(proj))


_SKIP = {"почему", "зачем", "какой", "какая", "какие", "каком", "делать", "чтобы", "этого", "этом", "когда", "сколько", "нужно", "можно"}


def question_words(proj, limit=6):
    """Значимые слова вопроса задачи в исходном написании: для готовой команды в подсказке."""
    q = read_state(proj).get("question") or ""
    seen, out = set(), []
    for w in re.findall(r"[\w]+", q):
        if w.lower() in _SKIP or w.isdigit() or not kbase.query_terms(w):
            continue
        key = w.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(w)
        if len(out) >= limit:
            break
    return " ".join(out) or "показатель"
