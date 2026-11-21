# -*- coding: utf-8 -*-
"""Выбор модели и методики по таблице config/routing.json и исправление ошибочного выбора после повторной неудачи."""
import hashlib
import re

from .common import (Fail, MODEL_CLASSES, STAGE_NAMES, read_state, set_state_field, read_jsonl, journal, norm_match)

CORRECTION = "исправление выбора"


def table(cfg):
    rows = (cfg.get("routing") or {}).get("table") or []
    if not rows:
        raise Fail("В config/routing.json нет таблицы table. Восстановите файл из поставки.")
    return rows


def stronger(cls):
    """Следующий по силе класс модели или None, если класс уже самый сильный."""
    if cls not in MODEL_CLASSES:
        return None
    i = MODEL_CLASSES.index(cls)
    return MODEL_CLASSES[i + 1] if i + 1 < len(MODEL_CLASSES) else None


def row_for_stage(cfg, stage):
    for r in table(cfg):
        if stage in (r.get("stages") or []):
            return r
    return None


def _stems(text):
    return set(w[:5] for w in re.findall(r"\w+", norm_match(text)) if len(w) > 2)


def row_for_step(cfg, step):
    q = _stems(step)
    if not q:
        raise Fail("Опишите вид шага словами: --step \"диагностика причины\".")
    best, best_n = None, 0
    for r in table(cfg):
        n = len(q & _stems(r.get("step", "")))
        if n > best_n:
            best, best_n = r, n
    if best is None:
        raise Fail("Не нашёл такого вида шага в config/routing.json. Виды шагов: " + "; ".join(r["step"] for r in table(cfg)))
    return best


def suggest_lines(row):
    lines = ["Вид шага: %s." % row["step"], "Класс модели: %s." % row["model_class"],
             "Методика: %s." % (row.get("method") or "не указана в config/routing.json"),
             "Почему: %s." % row.get("why", "не указано")]
    return lines


def correction_count(proj):
    return sum(1 for r in read_jsonl(proj.path("journal.jsonl")) if r.get("cmd") == CORRECTION)


def _advice(cfg, stage):
    row = row_for_stage(cfg, stage)
    if row is None:
        return None, ["Смените подход: перечитайте методику этапа в methods/INDEX.md и сузьте задачу."], "методика этапа"
    nxt = stronger(row["model_class"])
    method = row.get("method") or "methods/INDEX.md"
    lines = []
    if nxt:
        lines.append("Для шага «%s» нужна модель классом выше: %s (сейчас %s)." % (row["step"], nxt, row["model_class"]))
    else:
        lines.append("Для шага «%s» класс модели уже самый сильный (%s): менять нужно подход, а не модель." % (row["step"], row["model_class"]))
    lines.append("Перечитайте методику: %s. Если и после этого не выходит, покажите руководителю, что именно не получается." % method)
    return nxt, lines, method


def record_result(proj, cfg, stage, issues):
    """Учитывает итог проверки (gate или verify). Возвращает строки для печати (пусто, если повтора нет)."""
    st = read_state(proj)
    if not issues:
        if st.get("fail_track"):
            set_state_field(proj, "fail_track", None)
        return []
    fp = hashlib.sha256("\n".join(sorted("%s|%s" % (i["where"], i["what"]) for i in issues)).encode("utf-8")).hexdigest()[:16]
    tr = st.get("fail_track") or {}
    if tr.get("stage") == stage and tr.get("fp") == fp:
        tr = {"stage": stage, "fp": fp, "count": tr.get("count", 1) + 1}
    else:
        tr = {"stage": stage, "fp": fp, "count": 1}
    set_state_field(proj, "fail_track", tr)
    if tr["count"] < 2:
        return []
    nxt, lines, method = _advice(cfg, stage)
    journal(proj, CORRECTION, {"stage": stage, "how": "автоматически: та же проверка не пройдена %d раза подряд" % tr["count"],
                               "класс": nxt, "методика": method})
    return ["Повторная неудача той же проверки. Смените подход: " + lines[0]] + lines[1:]


def escalate(proj, cfg, stage, reason):
    if not 1 <= stage <= 8:
        raise Fail("Этап от 1 до 8.")
    if not (reason or "").strip():
        raise Fail("Нужна причина: --reason \"что не получается и почему\".")
    nxt, lines, method = _advice(cfg, stage)
    journal(proj, CORRECTION, {"stage": stage, "how": "вручную: " + reason.strip(), "класс": nxt, "методика": method})
    return ["Записано исправление выбора для этапа %d (%s): %s." % (stage, STAGE_NAMES[stage], reason.strip())] + lines
