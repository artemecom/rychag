# -*- coding: utf-8 -*-
"""Требования человека, выписанные из его запроса строка за строкой, и его более поздние сообщения."""
import re
from pathlib import Path

from .common import (Fail, Project, read_json, write_json, read_text, write_text_atomic, next_id, quote_in_text,
                     norm_match, journal, today, is_inside, short, read_state, split_ids)

VERBATIM_HEAD = "Запрос дословно"
R_OPEN, R_DONE, R_DROP = "открыто", "выполнено", "снято"


def verbatim_request(proj):
    """Дословный запрос из brief.md. У старых задач без раздела берётся вопрос из state.json."""
    text = read_text(proj.path("brief.md"))
    m = re.search(r"^##\s+%s\s*$(.*?)(?=^##\s|\Z)" % re.escape(VERBATIM_HEAD), text, re.S | re.M | re.I)
    if m and m.group(1).strip():
        return m.group(1).strip()
    try:
        return read_state(proj).get("question", "")
    except Fail:
        return ""


def requests_text(proj):
    return read_text(proj.path("requests.md"))


def load(proj):
    d = read_json(proj.path("requirements.json"), {"items": []})
    return d.get("items", []) if isinstance(d, dict) else []


def save(proj, items):
    write_json(proj.path("requirements.json"), {"items": items})


def add(proj, text, quote, source="brief"):
    if not (text or "").strip():
        raise Fail("Пустой текст требования. Запишите одной фразой, что именно нужно человеку.")
    if not (quote or "").strip():
        raise Fail("Нужна дословная цитата из запроса: --quote \"фрагмент\". Требование без цитаты легко потерять или исказить.")
    source = (source or "brief").strip()
    if source == "brief":
        pool = verbatim_request(proj) + "\n" + requests_text(proj)
        where = "дословном запросе в brief.md и в requests.md"
    elif re.match(r"^S\d{3,}$", source):
        from .sources import get_source, source_text
        get_source(proj, source)
        pool = source_text(proj, source)
        where = "копии источника %s" % source
    else:
        raise Fail("Источник требования: brief или код вида S001. Получено «%s»." % source)
    if not quote_in_text(quote, pool):
        raise Fail("Цитата не найдена в %s. Скопируйте фрагмент дословно (регистр, пробелы и тип кавычек не важны). "
                   "Новое сообщение человека сначала сохраните: req note \"сообщение дословно\". Начало цитаты: «%s»." % (
                       where, short(quote, 50)))
    items = load(proj)
    key = norm_match(text)
    for it in items:
        if norm_match(it["text"]) == key and it["status"] != R_DROP:
            raise Fail("Такое требование уже записано как %s (%s). Повтор не нужен." % (it["id"], it["status"]))
    it = {"id": next_id("R", [x["id"] for x in items], width=2), "text": text.strip(), "quote": quote.strip(),
          "source": source, "status": R_OPEN, "created": today().isoformat()}
    items.append(it)
    save(proj, items)
    journal(proj, "req add", {"id": it["id"], "source": source})
    return it


def import_file(proj, path, source="brief"):
    """Требования пачкой из файла со строками «что требуется || дословная цитата»."""
    import os
    full = path if os.path.isabs(path) else (proj.path(path) if os.path.exists(proj.path(path)) else path)
    if not os.path.exists(full):
        raise Fail("Файл %s не найден. Положите его в папку задачи и укажите путь." % path)
    ok, bad = [], []
    for n, raw in enumerate(read_text(full).splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "||" not in line:
            bad.append((n, short(line, 80), "нет разделителя ||: нужна строка вида «что требуется || дословная цитата»"))
            continue
        text, quote = [x.strip() for x in line.split("||", 1)]
        try:
            ok.append(add(proj, text, quote, source))
        except Fail as e:
            msg = str(e)
            if "уже записано" in msg:
                continue
            bad.append((n, short(line, 80), msg))
    return ok, bad


def _find(items, rid):
    for it in items:
        if it["id"] == rid:
            return it
    raise Fail("Требования %s нет. Список: python3 tools/rychag.py req list" % rid)


def check_closer(proj, by):
    """Проверяет, что закрывающий объект существует и действует. Возвращает его описание."""
    from . import ledger
    by = (by or "").strip()
    if not by:
        raise Fail("Укажите, чем закрыто требование: --by D1, K001, L001, DR-001 или путь к файлу проекта.")
    if re.match(r"^D\d+$", by):
        for c in ledger.load_done(proj)["criteria"]:
            if c["id"] == by:
                if not c.get("met"):
                    raise Fail("Критерий %s ещё не выполнен. Сначала done mark %s." % (by, by))
                return "критерий " + by
        raise Fail("Критерия %s нет. Список: done list." % by)
    if re.match(r"^K\d+$", by):
        for k in ledger.load_conclusions(proj):
            if k["id"] == by:
                if k["status"] != "действует":
                    raise Fail("Вывод %s имеет статус «%s», закрывать им нельзя." % (by, k["status"]))
                return "вывод " + by
        raise Fail("Вывода %s нет." % by)
    if re.match(r"^L\d+$", by):
        for lv in ledger.load_levers(proj):
            if lv["id"] == by:
                if lv.get("status", "действует") == "снят":
                    raise Fail("Рычаг %s снят, закрывать им нельзя." % by)
                return "рычаг " + by
        raise Fail("Рычага %s нет." % by)
    if re.match(r"^DR-\d+$", by):
        for d in ledger.load_decisions(proj):
            if d["id"] == by:
                if d.get("status") == "заменено":
                    raise Fail("Решение %s заменено, закрывать им нельзя." % by)
                return "решение " + by
        raise Fail("Решения %s нет." % by)
    cand = proj.dir / by
    if cand.is_file() and is_inside(cand, proj.dir):
        return "файл " + by
    raise Fail("«%s» не найдено. Допустимо: критерий готовности (D1), вывод (K001), рычаг (L001), решение (DR-001) "
               "или путь к существующему файлу внутри папки проекта." % by)


def close(proj, rid, by, where=None, phrase=None):
    """Закрывает требование. where: место в результате, где оно выполнено (часть документа или файл).
    phrase: дословная фраза из этого места, в которой требование выполнено. По ней проверка заметит,
    что при переписывании документа ответ пропал."""
    items = load(proj)
    it = _find(items, rid)
    if it["status"] == R_DROP:
        raise Fail("Требование %s снято: %s. Закрыть его нельзя." % (rid, it.get("drop_reason")))
    what = check_closer(proj, by)
    place = (where or "").strip() or None
    if place:
        from . import document
        document.resolve_place(proj, place)
    anchor = " ".join((phrase or "").split()) or None
    if anchor:
        from . import document
        if not place:
            raise Fail("Фраза без места не проверяется. Добавьте --where \"часть N\" или --where \"начало\".")
        if len(anchor.split()) < document.PHRASE_MIN_WORDS:
            raise Fail("Фраза слишком короткая: нужно не меньше %d слов, дословно из документа." % document.PHRASE_MIN_WORDS)
        found = document.phrase_found(proj, place, anchor)
        if found is None:
            raise Fail("Фразу можно указать только для места в документе («начало» или «часть N»).")
        if not found:
            raise Fail("Фразы «%s» нет в месте «%s». Скопируйте её из документа дословно: по ней проверка увидит, "
                       "если ответ на требование пропадёт при переписывании." % (short(anchor, 60), place))
    if (it["status"] == R_DONE and it.get("closed_by") == by.strip() and (place is None or it.get("where") == place)
            and (anchor is None or it.get("phrase") == anchor)):
        return it, False
    it["status"], it["closed_by"] = R_DONE, by.strip()
    if place:
        if it.get("where") != place and not anchor:
            it.pop("phrase", None)
        it["where"] = place
    if anchor:
        it["phrase"] = anchor
    save(proj, items)
    journal(proj, "req close", {"id": rid, "by": by.strip(), "where": place, "phrase": anchor})
    return it, True


def close_file(proj, path, by):
    """Закрывает требования списком из файла: строка «R01 || часть 2 || дословная фраза из документа».
    Возвращает (сколько закрыто, сколько уже было закрыто так же, список непринятых строк)."""
    p = Path(path)
    if not p.is_file():
        raise Fail("Файл %s не найден." % path)
    done = same = 0
    bad = []
    for n, raw in enumerate(read_text(p).split("\n"), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        cells = [c.strip() for c in line.split("||")]
        if len(cells) != 3 or not all(cells):
            bad.append((n, "нужно три поля через «||»: код, место, фраза"))
            continue
        try:
            _, changed = close(proj, cells[0], by, cells[1], cells[2])
        except Fail as e:
            bad.append((n, str(e)))
            continue
        done += 1 if changed else 0
        same += 0 if changed else 1
    return done, same, bad


def drop(proj, rid, reason):
    if not (reason or "").strip():
        raise Fail("Нужна причина: --reason \"почему требование снято\". Снять без причины нельзя.")
    items = load(proj)
    it = _find(items, rid)
    if it["status"] == R_DROP:
        return it, False
    it["status"], it["drop_reason"] = R_DROP, reason.strip()
    save(proj, items)
    journal(proj, "req drop", {"id": rid, "reason": reason.strip()})
    return it, True


def note(proj, message):
    """Дописывает дословное сообщение человека в requests.md. Тот же текст повторно не пишется."""
    msg = (message or "").strip()
    if not msg:
        raise Fail("Пустое сообщение. Вставьте текст сообщения человека дословно.")
    cur = requests_text(proj)
    if norm_match(msg) in norm_match(cur):
        return False
    head = cur if cur.strip() else "# Сообщения человека дословно\n"
    write_text_atomic(proj.path("requests.md"), head.rstrip("\n") + "\n\n## %s\n\n%s\n" % (today().isoformat(), msg))
    journal(proj, "req note", {"chars": len(msg)})
    return True


def counts(proj):
    items = load(proj)
    done = sum(1 for i in items if i["status"] == R_DONE)
    dropped = sum(1 for i in items if i["status"] == R_DROP)
    return done, len(items) - dropped, dropped


def line(proj):
    d, y, z = counts(proj)
    return "Требований из запроса: выполнено %d из %d, снято %d" % (d, y, z)


def open_items(proj):
    return [i for i in load(proj) if i["status"] == R_OPEN]
