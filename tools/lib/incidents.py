# -*- coding: utf-8 -*-
"""Происшествия: всё, о чём агент сообщает как о случившемся и исправленном, записывает программа.
Запись добавляется командой incident add в errors.md (фиксированный формат) и в журнал.
Старые файлы errors.md со свободным текстом работают: пункты списка считаются записями «записано вручную»."""
import re

from .common import Fail, today, write_text_atomic, read_text, journal, short
from .sources import list_sources

FILE = "errors.md"
KINDS = ["ошибка-агента", "команда-в-источнике", "недоступный-инструмент", "расхождение-данных", "другое"]
TOP_NOTE = ("Записи в этот файл добавляет команда python3 tools/rychag.py incident add, вручную их не пишут. "
            "Посмотреть: python3 tools/rychag.py incident list.")
TEMPLATE = "# Ошибки агента\n\n" + TOP_NOTE + "\n\nФормат записи: номер, дата, вид, что произошло, кто заметил, что исправлено.\n"
HEAD_RX = re.compile(r"^##\s+(I\d{3,})\.\s+(\d{4}-\d{2}-\d{2})\.\s+(.+?)\s*$")
ITEM_RX = re.compile(r"^(?:[-*]|\d+[.)])\s+(\S.*)$")
FIELDS = [("Что произошло", "what"), ("Кто заметил", "caught_by"), ("Что исправлено", "fix"), ("Источник", "source")]


def parse(proj):
    """Возвращает (записи программы, записи вручную). Запись программы: dict id, date, kind, what, caught_by, fix, source."""
    text = read_text(proj.path(FILE))
    prog, legacy, cur = [], [], None
    for line in text.splitlines():
        m = HEAD_RX.match(line)
        if m:
            cur = {"id": m.group(1), "date": m.group(2), "kind": m.group(3), "what": "", "caught_by": "", "fix": "", "source": ""}
            prog.append(cur)
            continue
        if line.startswith("#"):
            cur = None
            continue
        if cur is not None:
            for label, key in FIELDS:
                pre = "- %s: " % label
                if line.startswith(pre):
                    cur[key] = line[len(pre):].strip()
            continue
        m = ITEM_RX.match(line)
        if m:
            legacy.append(m.group(1).strip())
    return prog, legacy


def count(proj):
    prog, legacy = parse(proj)
    return len(prog) + len(legacy)


def last_line(proj):
    prog, legacy = parse(proj)
    if prog:
        r = prog[-1]
        return "%s от %s, %s: %s" % (r["id"], r["date"], r["kind"], short(r["what"], 80))
    if legacy:
        return "записано вручную: %s" % short(legacy[-1], 80)
    return ""


def status_line(proj):
    n = count(proj)
    if not n:
        return "Происшествий записано: 0."
    _p, legacy = parse(proj)
    extra = ", из них записано вручную: %d" % len(legacy) if legacy else ""
    return "Происшествий записано: %d (последнее: %s)%s." % (n, last_line(proj), extra)


def add(proj, kind, what, caught_by=None, fix=None, source=None):
    if kind not in KINDS:
        raise Fail("Вид происшествия «%s» не подходит. Допустимо: %s." % (kind, ", ".join(KINDS)))
    what = re.sub(r"\s+", " ", what or "").strip()
    if not what:
        raise Fail("Нужно описание: --what \"что произошло\".")
    caught_by = re.sub(r"\s+", " ", caught_by or "").strip()
    fix = re.sub(r"\s+", " ", fix or "").strip()
    source = (source or "").strip()
    if source and source not in {m["id"] for m in list_sources(proj)}:
        raise Fail("Источника %s в этой задаче нет. Список: python3 tools/rychag.py source list" % source)
    path = proj.path(FILE)
    text = read_text(path)
    if not text.strip():
        text = TEMPLATE
    elif TOP_NOTE.split(",")[0] not in text:
        # старый файл со свободным текстом: пометка сверху, остальное не трогаем
        lines = text.split("\n")
        i = 1 if lines and lines[0].startswith("#") else 0
        lines[i:i] = ["", TOP_NOTE]
        text = "\n".join(lines)
    prog, _legacy = parse(proj)
    n = max([int(r["id"][1:]) for r in prog] + [0]) + 1
    iid = "I%03d" % n
    block = ["", "## %s. %s. %s" % (iid, today().isoformat(), kind), "",
             "- Что произошло: " + what,
             "- Кто заметил: " + (caught_by or "не указано"),
             "- Что исправлено: " + (fix or "не указано")]
    if source:
        block.append("- Источник: " + source)
    if not text.endswith("\n"):
        text += "\n"
    write_text_atomic(path, text + "\n".join(block) + "\n")
    journal(proj, "incident add", {"id": iid, "kind": kind, "what": short(what, 120), "source": source or None})
    return {"id": iid, "date": today().isoformat(), "kind": kind, "what": what, "caught_by": caught_by, "fix": fix, "source": source}


def list_lines(proj):
    prog, legacy = parse(proj)
    if not prog and not legacy:
        return ["Происшествий нет. Записать: python3 tools/rychag.py incident add --kind ошибка-агента --what \"что произошло\""]
    out = ["Происшествий записано: %d." % (len(prog) + len(legacy))]
    for r in prog:
        s = "%s. %s, %s. Что произошло: %s. Кто заметил: %s. Что исправлено: %s." % (
            r["id"], r["date"], r["kind"], r["what"], r["caught_by"] or "не указано", r["fix"] or "не указано")
        if r["source"]:
            s += " Источник: %s." % r["source"]
        out.append(s)
    for i, t in enumerate(legacy, 1):
        out.append("Р%02d (записано вручную). %s" % (i, t))
    if legacy:
        out.append("Записи вручную программа не проверяет. Новые происшествия записывайте командой incident add.")
    return out
