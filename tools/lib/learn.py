# -*- coding: utf-8 -*-
"""Обучение волнами: отзывы руководителя и исходы решений собираются по всем задачам, из них рождаются предложения.
Правило без исключений: отзыв сам по себе не меняет статус утверждения, вывода или записи базы знаний и не создаёт факт.
Урок, который считается доказательством, рождается только из исхода. Применяется предложение только командой learn apply."""
import json
import re
from pathlib import Path

from .common import (Fail, today, now_iso, read_jsonl, write_jsonl, append_jsonl, read_json, write_json,
                     write_text_atomic, next_id, split_ids, short, find_projects, Project, journal,
                     DEFAULT_STYLE, LAYER_WORDS, explain_lever)
from .ledger import load_conclusions, load_levers, load_decisions, load_claims
from .sources import get_source, source_layer
from . import kb as kbase

VERDICTS = ["принято", "отклонено"]
VERDICT_RU = {"принято": "Принято", "отклонено": "Отклонено"}
# внутренний код, подпись для человека
REASONS = [
    ("не-верю-числу", "Число вызывает сомнение: не видно, откуда оно взято"),
    ("вода", "Много общих слов, мало конкретики"),
    ("нет-рычага", "Не сказано, что именно нужно сделать"),
    ("не-тот-вопрос", "Ответ не на тот вопрос"),
    ("вывод-не-следует", "Вывод не подтверждается приведёнными данными"),
    ("нельзя-выполнить", "Предложение невыполнимо в наших условиях"),
    ("слишком-длинно", "Слишком длинно"),
    ("устарело", "Данные устарели"),
    ("непонятно", "Написано непонятно"),
    ("другое", "Другое (нужно пояснение)"),
]
REASON_CODES = [c for c, _ in REASONS]
REASON_RU = dict(REASONS)
K_STYLE = "Как подавать результат"
K_CHECK = "Что проверять дополнительно"
K_LESSON = "Урок в базу знаний"
K_CALIB = "Насколько точны наши оценки эффекта"
ELEMENT_RU = {"страница": "итоговая страница", "вывод": "вывод", "рычаг": "рычаг", "решение": "решение", "утверждение": "утверждение"}


def parse_reason(value):
    """Принимает внутренний код, номер из списка или подпись. Возвращает код."""
    v = (value or "").strip()
    if v in REASON_CODES:
        return v
    if v.isdigit() and 1 <= int(v) <= len(REASONS):
        return REASONS[int(v) - 1][0]
    for c, t in REASONS:
        if v.lower() == t.lower():
            return c
    raise Fail("Такой причины нет. Допустимы номер от 1 до %d или подпись из списка: python3 tools/rychag.py feedback reasons" % len(REASONS))


def parse_verdict(value):
    v = (value or "").strip().lower()
    if v not in VERDICTS:
        raise Fail("Вердикт: Принято или Отклонено.")
    return v
MIN_SIGNALS = 2      # сколько однотипных отзывов нужно для предложения
MIN_OUTCOMES = 3     # сколько исходов со сравнением нужно для калибровки оценок
STYLE_REASONS = ("вода", "слишком-длинно", "непонятно")


def ldir(root):
    return Path(root) / "learn"


# ---------------------------------------------------------------- отзывы

def _kind_of_target(t):
    if t == "page":
        return "страница"
    if t.startswith("DR-"):
        return "решение"
    return {"K": "вывод", "L": "рычаг", "C": "утверждение"}.get(t[:1], "")


def load_feedback(proj):
    return read_jsonl(proj.path("feedback.jsonl"))


def load_outcomes(proj):
    return read_jsonl(proj.path("outcomes.jsonl"))


def add_feedback(proj, target, verdict, reason=None, note=None):
    target = (target or "").strip()
    verdict = parse_verdict(verdict)
    if not reason and verdict == "отклонено":
        raise Fail("Для отклонения нужна причина: --reason с номером из списка. Список: python3 tools/rychag.py feedback reasons")
    if reason:
        reason = parse_reason(reason)
    kind = _kind_of_target(target)
    if not kind:
        raise Fail("Объект отзыва: page (итоговая страница), K001 (вывод), L001 (рычаг), DR-001 (решение) или C001 (утверждение).")
    if target != "page":
        known = {k["id"] for k in load_conclusions(proj)} | {l["id"] for l in load_levers(proj)} | \
                {d["id"] for d in load_decisions(proj)} | {c["id"] for c in load_claims(proj)}
        if target not in known:
            raise Fail("Объекта %s нет в проекте. Проверьте код." % target)
    rows = load_feedback(proj)
    row = {"id": next_id("F", [r["id"] for r in rows]), "project": proj.name, "target": target, "element": kind,
           "verdict": verdict, "reason": reason or None, "note": (note or "").strip(), "date": today().isoformat(),
           "ts": now_iso()}
    append_jsonl(proj.path("feedback.jsonl"), row)
    return row


def reasons_lines():
    return ["Причины отклонения (в --reason можно указать номер):"] + ["  %d. %s" % (i, t) for i, (_c, t) in enumerate(REASONS, 1)] + [
        "Отзыв только записывается. Статус утверждений, выводов и записей базы знаний он не меняет, фактом не становится."]


# ---------------------------------------------------------------- исходы

def _num(v):
    try:
        f = float(str(v).replace(",", ".").replace(" ", ""))
    except ValueError:
        raise Fail("--actual должно быть числом, получено «%s»." % v)
    return int(f) if f == int(f) else f


def compare_effect(actual, eff):
    lo, ba, hi = eff["low"], eff["base"], eff["high"]
    if actual < lo:
        pos = "ниже низкой оценки"
    elif actual > hi:
        pos = "выше высокой оценки"
    elif actual < ba:
        pos = "между низкой и базовой оценкой"
    elif actual > ba:
        pos = "между базовой и высокой оценкой"
    else:
        pos = "точно на базовой оценке"
    return pos, lo <= actual <= hi


def add_outcome(proj, decision, metric, actual, period, source=None, note=None):
    decs = {d["id"]: d for d in load_decisions(proj)}
    if decision not in decs:
        raise Fail("Решения %s нет. Список: python3 tools/rychag.py decision list" % decision)
    for name, v in (("--metric", metric), ("--period", period)):
        if not (v or "").strip():
            raise Fail("Пустое поле %s." % name)
    val = _num(actual)
    layer, label = None, "со слов человека"
    if source:
        meta = get_source(proj, source)
        layer = source_layer(meta)
        if layer in (1, 2):
            label = "сильный исход, источник: %s" % LAYER_WORDS[layer]
        else:
            label = "слабый исход, источник вне компании: %s" % LAYER_WORDS.get(layer, "тип источника не указан")
    levers = {l["id"]: l for l in load_levers(proj)}
    comps = []
    for i in decs[decision].get("rests_on_list", []):
        if i in levers:
            pos, inside = compare_effect(val, levers[i]["effect"])
            comps.append({"lever": i, "effect": levers[i]["effect"], "position": pos, "in_range": inside,
                          "above_base": val > levers[i]["effect"]["base"], "below_base": val < levers[i]["effect"]["base"]})
    rows = load_outcomes(proj)
    row = {"id": next_id("O", [r["id"] for r in rows]), "project": proj.name, "decision": decision, "metric": metric.strip(),
           "actual": val, "period": period.strip(), "source": source, "source_layer": layer, "strength": label,
           "note": (note or "").strip(), "comparisons": comps,
           "in_range": (all(c["in_range"] for c in comps) if comps else None), "date": today().isoformat(), "ts": now_iso()}
    append_jsonl(proj.path("outcomes.jsonl"), row)
    return row


# ---------------------------------------------------------------- сбор по проектам

def _projects(root):
    return [Project(root, n) for n in find_projects(root) if not n.startswith("_")]


def all_feedback(root):
    out = []
    for p in _projects(root):
        out += load_feedback(p)
    return out


def all_outcomes(root):
    out = []
    for p in _projects(root):
        out += load_outcomes(p)
    return out


def _key(row):
    return "%s:%s" % (row["project"], row["id"])


# ---------------------------------------------------------------- история и предложения

def history(root):
    return read_jsonl(ldir(root) / "history.jsonl")


def _consumed(root):
    s = set()
    for h in history(root):
        if h.get("type") == "wave":
            s.update(h.get("consumed", []))
    return s


def all_proposals(root):
    out = {}
    d = ldir(root)
    if d.is_dir():
        for p in sorted(d.glob("proposals-*.json")):
            data = read_json(p, {}) or {}
            for pr in data.get("proposals", []):
                pr["_file"] = p.name
                out[pr["id"]] = pr
    return out


def _quoted(text):
    return [m.strip() for m in re.findall(r"«([^»]{3,80})»", text or "")]


def _ids_text(rows):
    return ", ".join(_key(r) for r in rows)


def build_proposals(root, since=None):
    """Возвращает (список предложений без номеров, подсказки). Данные: отзывы и исходы всех задач, ещё не учтённые прошлыми волнами."""
    used = _consumed(root)
    fb = [r for r in all_feedback(root) if (r["date"] >= since if since else _key(r) not in used)]
    oc = [r for r in all_outcomes(root) if (r["date"] >= since if since else _key(r) not in used)]
    props, hints = [], []
    rejected = [r for r in fb if r["verdict"] == "отклонено"]

    # как подавать результат
    style = read_json(Path(root) / "config" / "style.json", {}) or {}
    cur_lines = style.get("max_page_lines", DEFAULT_STYLE["max_page_lines"])
    banned = style.get("banned_phrases", DEFAULT_STYLE["banned_phrases"])
    longs = [r for r in rejected if r["reason"] == "слишком-длинно" and r["element"] == "страница"]
    if len(longs) >= MIN_SIGNALS:
        new = max(20, cur_lines - 5)
        if new < cur_lines:
            props.append({"kind": K_STYLE, "title": "Сделать итоговую страницу короче",
                          "what": "В настройках (config/style.json) уменьшить допустимое число строк на странице с %d до %d. "
                                  "Проверка стиля станет строже." % (cur_lines, new),
                          "change": {"type": "style", "set": {"max_page_lines": new}},
                          "grounds": {"feedback": [_key(r) for r in longs], "outcomes": []},
                          "counts": {REASON_RU["слишком-длинно"]: len(longs)}})
    wordy = [r for r in rejected if r["reason"] in ("вода", "непонятно") and r["element"] == "страница"]
    if len(wordy) >= MIN_SIGNALS:
        have = {p.lower().replace("ё", "е") for p in banned}
        phrases = []
        for r in wordy:
            for ph in _quoted(r["note"]):
                if ph.lower().replace("ё", "е") not in have and ph not in phrases:
                    phrases.append(ph)
        if phrases:
            props.append({"kind": K_STYLE, "title": "Запретить пустые обороты на итоговой странице",
                          "what": "В настройках (config/style.json) добавить в список запрещённых оборотов: %s. "
                                  "Проверка страницы начнёт их находить." % "; ".join("«%s»" % p for p in phrases),
                          "change": {"type": "style", "add_banned": phrases},
                          "grounds": {"feedback": [_key(r) for r in wordy], "outcomes": []},
                          "counts": {REASON_RU["вода"]: sum(1 for r in wordy if r["reason"] == "вода"),
                                     REASON_RU["непонятно"]: sum(1 for r in wordy if r["reason"] == "непонятно")}})
        else:
            hints.append("Страницу отклоняли с причинами «%s» и «%s» (%d раз), но в заметках нет оборотов в кавычках «». "
                         "Чтобы предложить запрет, укажите оборот в заметке к отзыву, например: --note \"оборот «в современном мире»\"." % (
                             REASON_RU["вода"], REASON_RU["непонятно"], len(wordy)))

    # что проверять дополнительно
    groups = {}
    for r in rejected:
        if r["reason"] in (None, "другое"):
            continue
        if r["element"] == "страница" and r["reason"] in STYLE_REASONS:
            continue
        groups.setdefault((r["reason"], r["element"]), []).append(r)
    for (reason, element), rows in sorted(groups.items()):
        if len(rows) >= MIN_SIGNALS:
            props.append({"kind": K_CHECK, "title": "Повторяющееся замечание: «%s» (%s)" % (REASON_RU[reason], ELEMENT_RU[element]),
                          "what": "Одно и то же замечание повторилось %d раза. Нужно решить, какую дополнительную проверку или заметку в методике "
                                  "добавить, чтобы оно не повторялось. Это текст для человека и агента, в программе ничего не меняется "
                                  "до вашего решения." % len(rows),
                          "change": {"type": "text"},
                          "grounds": {"feedback": [_key(r) for r in rows], "outcomes": []},
                          "counts": {REASON_RU[reason]: len(rows)}})

    # урок в базу знаний: из исходов
    for o in oc:
        if not o.get("comparisons"):
            pos_txt = "сравнить с оценкой было не с чем"
        else:
            c = o["comparisons"][0]
            pos_txt = "результат %s (оценка эффекта: низкая %s, базовая %s, высокая %s)" % (
                c["position"], c["effect"]["low"], c["effect"]["base"], c["effect"]["high"])
        human = not o.get("source")
        ext = bool(o.get("source")) and o.get("source_layer") not in (1, 2)
        layer = 2 if not ext else (o["source_layer"] if o.get("source_layer") in (3, 4, 5) else 5)
        rule = "По решению %s показатель «%s» за период %s составил %s: %s." % (o["decision"], o["metric"], o["period"],
                                                                              o["actual"], pos_txt)
        if human:
            rule = "Со слов человека: " + rule
        props.append({"kind": K_LESSON, "title": "Урок из фактического результата %s" % _key(o),
                      "what": "Добавить в базу знаний запись вида «урок»; источник записи: %s%s. Текст: %s" % (
                          LAYER_WORDS[layer], ", с пометкой «со слов человека»" if human else "", rule),
                      "change": {"type": "lesson", "rule": rule,
                                 "applies_when": "Оценка эффекта по показателю «%s» для решений такого вида" % o["metric"],
                                 "themes": ["исходы решений"], "tags": ["исход"] + (["со слов человека"] if human else []),
                                 "layer": layer, "origin": "исход", "human_words": human, "project": o["project"]},
                      "grounds": {"feedback": [], "outcomes": [_key(o)]}, "counts": {}})
    # урок в базу знаний: из отзывов, минимум два совпадающих с заметками
    for (reason, element), rows in sorted(groups.items()):
        with_notes = [r for r in rows if r["note"]]
        if len(with_notes) >= 2:
            rule = "Руководители отклоняли объект «%s» с замечанием «%s» (%d раза): %s" % (
                ELEMENT_RU[element], REASON_RU[reason], len(with_notes), "; ".join(short(r["note"], 80) for r in with_notes))
            props.append({"kind": K_LESSON, "title": "Урок из отзывов: «%s» (%s)" % (REASON_RU[reason], ELEMENT_RU[element]),
                          "what": "Добавить в базу знаний запись вида «урок». Она выведена из отзывов, а не из фактического результата, "
                                  "поэтому доказательством не считается и годится только для гипотезы. Текст: %s" % rule,
                          "change": {"type": "lesson", "rule": rule,
                                     "applies_when": "Подготовка объекта «%s» для руководителя" % ELEMENT_RU[element],
                                     "themes": ["отзывы руководителей"], "tags": ["отзывы"], "layer": 2,
                                     "origin": "отзывы", "human_words": False, "project": None},
                          "grounds": {"feedback": [_key(r) for r in with_notes], "outcomes": []}, "counts": {}})

    # насколько точны наши оценки эффекта
    comp = [o for o in oc if o.get("comparisons")]
    if len(comp) >= MIN_OUTCOMES:
        inside = sum(1 for o in comp if o["in_range"])
        ratios = []
        for o in comp:
            e = o["comparisons"][0]["effect"]
            if e["base"]:
                ratios.append(o["actual"] / e["base"])
        below = sum(1 for o in comp if o["comparisons"][0]["below_base"])
        above = sum(1 for o in comp if o["comparisons"][0]["above_base"])
        ratios.sort()
        if not ratios:
            med = None
        elif len(ratios) % 2:
            med = ratios[len(ratios) // 2]
        else:
            med = (ratios[len(ratios) // 2 - 1] + ratios[len(ratios) // 2]) / 2
        if below > above:
            direction = "оценки завышены: результат чаще ниже базовой оценки"
        elif above > below:
            direction = "оценки занижены: результат чаще выше базовой оценки"
        else:
            direction = "заметного перекоса в одну сторону нет"
        share = round(100.0 * inside / len(comp))
        what = ("Из %d фактических результатов в заявленный диапазон оценки (от низкой до высокой) попали %d (%d%%); "
                "ниже базовой оценки %d, выше %d. Вывод: %s." % (len(comp), inside, share, below, above, direction))
        if med is not None and abs(med - 1) > 0.1:
            what += " Предлагается умножать базовую оценку на %.2f (так соотносится типичный результат с базовой оценкой) и строить диапазон от нового значения." % med
        elif share < 70:
            what += " Предлагается заявлять диапазон шире: от более низкой до более высокой оценки."
        props.append({"kind": K_CALIB, "title": "Проверка точности оценок эффекта",
                      "what": what + " Это текст для человека, в программе ничего не меняется.",
                      "change": {"type": "text", "inside": inside, "total": len(comp), "below_base": below, "above_base": above,
                                 "median_ratio": med},
                      "grounds": {"feedback": [], "outcomes": [_key(o) for o in comp]},
                      "counts": {"результатов со сравнением": len(comp)}})
    elif comp:
        hints.append("Результатов со сравнением с оценкой пока %d, чтобы судить о точности оценок, нужно не меньше %d." % (len(comp), MIN_OUTCOMES))
    return props, hints


def wave(root, since=None):
    """Возвращает (предложения с номерами или [], hints, пути файлов)."""
    props, hints = build_proposals(root, since)
    if not props:
        return [], hints, None
    existing = all_proposals(root)
    ids = list(existing)
    for pr in props:
        pr["id"] = next_id("P", ids)
        pr["status"] = "предложено"
        ids.append(pr["id"])
    d = ldir(root)
    base = "proposals-%s" % today().isoformat()
    n = 1
    while (d / (base + ".json")).exists():
        n += 1
        base = "proposals-%s-%d" % (today().isoformat(), n)
    write_json(d / (base + ".json"), {"date": today().isoformat(), "since": since, "proposals": props})
    md = ["# Предложения по улучшению работы от %s" % today().isoformat(), "",
          "Ничего не применено. Применить одно предложение: `python3 tools/rychag.py learn apply P001 --approved-by \"имя\"`. "
          "Отказаться: `python3 tools/rychag.py learn reject P001 --reason \"...\"`.", ""]
    for pr in props:
        md += ["## %s. %s" % (pr["id"], pr["title"]), "", "Вид предложения: " + pr["kind"], "",
               "Что изменится: " + pr["what"],
               "Основания: отзывы %s; фактические результаты %s." % (", ".join(pr["grounds"]["feedback"]) or "нет",
                                                                    ", ".join(pr["grounds"]["outcomes"]) or "нет"), ""]
    write_text_atomic(d / (base + ".md"), "\n".join(explain_lever(md)))
    consumed = sorted({g for pr in props for g in pr["grounds"]["feedback"] + pr["grounds"]["outcomes"]})
    append_jsonl(d / "history.jsonl", {"type": "wave", "date": today().isoformat(), "file": base, "since": since,
                                       "proposals": [p["id"] for p in props], "consumed": consumed, "ts": now_iso()})
    return props, hints, base


def _decided(root, pid):
    for h in history(root):
        if h.get("type") in ("apply", "reject") and h.get("proposal") == pid:
            return h
    return None


def apply_proposal(root, pid, approved_by=None):
    pr = all_proposals(root).get(pid)
    if pr is None:
        raise Fail("Предложения %s нет. Список: python3 tools/rychag.py learn history, файлы в learn/." % pid)
    done = _decided(root, pid)
    if done:
        raise Fail("Предложение %s уже %s (%s)." % (pid, "применено" if done["type"] == "apply" else "отклонено", done["date"]))
    ch = pr["change"]
    result = ""
    if ch["type"] == "style":
        p = Path(root) / "config" / "style.json"
        st = read_json(p, None)
        if not isinstance(st, dict):
            st = {"max_page_lines": DEFAULT_STYLE["max_page_lines"], "banned_phrases": list(DEFAULT_STYLE["banned_phrases"])}
        st.setdefault("max_page_lines", DEFAULT_STYLE["max_page_lines"])
        st.setdefault("banned_phrases", list(DEFAULT_STYLE["banned_phrases"]))
        for k, v in ch.get("set", {}).items():
            st[k] = v
        for ph in ch.get("add_banned", []):
            if ph not in st["banned_phrases"]:
                st["banned_phrases"].append(ph)
        write_json(p, st)
        result = "изменён config/style.json"
    elif ch["type"] == "lesson":
        f = {"rule": ch["rule"], "applies_when": ch["applies_when"], "themes": ch["themes"], "tags": ch["tags"],
             "layer": ch["layer"], "kind": "урок", "strength": "мнение", "origin": ch["origin"],
             "human_words": ch.get("human_words"), "grounds": pr["grounds"]}
        rec = kbase.create_record(root, f)
        kbase.build_index(root)
        result = "в базу знаний добавлена запись %s (урок; источник: %s)" % (rec["id"], LAYER_WORDS[rec["layer"]])
    else:
        result = "принято к исполнению человеком, в программе ничего не менялось"
    append_jsonl(ldir(root) / "history.jsonl", {"type": "apply", "proposal": pid, "kind": pr["kind"], "date": today().isoformat(),
                                                "approved_by": (approved_by or "").strip() or None, "result": result, "ts": now_iso()})
    return pr, result


def reject_proposal(root, pid, reason):
    if not (reason or "").strip():
        raise Fail("Нужна причина: --reason \"почему не применяем\".")
    if pid not in all_proposals(root):
        raise Fail("Предложения %s нет." % pid)
    done = _decided(root, pid)
    if done:
        raise Fail("Предложение %s уже решено (%s)." % (pid, done["date"]))
    append_jsonl(ldir(root) / "history.jsonl", {"type": "reject", "proposal": pid, "date": today().isoformat(),
                                                "reason": reason.strip(), "ts": now_iso()})


def history_lines(root):
    rows = history(root)
    if not rows:
        return ["История пуста: волн и решений по предложениям ещё не было."]
    out = []
    for h in rows:
        if h["type"] == "wave":
            out.append("%s подготовлены предложения %s (файл learn/%s.md)" % (h["date"], ", ".join(h["proposals"]), h["file"]))
        elif h["type"] == "apply":
            out.append("%s применено %s (вид: %s): %s%s" % (h["date"], h["proposal"], h["kind"], h["result"],
                                                       ", утвердил %s" % h["approved_by"] if h.get("approved_by") else ""))
        else:
            out.append("%s отклонено %s: %s" % (h["date"], h["proposal"], h["reason"]))
    return out


# ---------------------------------------------------------------- статистика использования записей базы знаний

def _closure(proj, ids, claims, concl, levers, seen=None):
    """Все утверждения, на которых прямо или через выводы и рычаги держится набор оснований."""
    seen = seen if seen is not None else set()
    found = set()
    for g in ids:
        if g in seen:
            continue
        seen.add(g)
        if g in claims:
            found.add(g)
        elif g in concl:
            found |= _closure(proj, concl[g].get("rests_on", []), claims, concl, levers, seen)
        elif g in levers:
            found |= _closure(proj, levers[g].get("rests_on", []), claims, concl, levers, seen)
    return found


def kb_stats(root):
    """Возвращает {B-код: {used, concl_ok, concl_bad, out_yes, out_no, out_none}} для действующих записей."""
    stats = {r["id"]: {"used": 0, "concl_ok": 0, "concl_bad": 0, "reasons": {}, "out_yes": 0, "out_no": 0, "out_none": 0}
             for r in kbase.load_records(root) if r["status"] == kbase.R_ACTIVE}
    for p in _projects(root):
        claims = {c["id"]: c for c in load_claims(p)}
        concl = {k["id"]: k for k in load_conclusions(p)}
        levers = {l["id"]: l for l in load_levers(p)}
        bench = {cid for cid, c in claims.items() if c["type"] == "benchmark" and c.get("status") != "отброшено"}

        def kbs(cids):
            return {b for cid in cids if cid in bench for b in claims[cid].get("kb", [])}
        for cid in bench:
            for b in claims[cid].get("kb", []):
                if b in stats:
                    stats[b]["used"] += 1
        fb = {}
        fbr = {}
        for r in load_feedback(p):
            fb.setdefault(r["target"], []).append(r["verdict"])
            if r["verdict"] == "отклонено" and r.get("reason"):
                fbr.setdefault(r["target"], []).append(r["reason"])
        for kid, k in concl.items():
            for b in kbs(_closure(p, k.get("rests_on", []), claims, concl, levers)):
                if b in stats:
                    stats[b]["concl_ok"] += fb.get(kid, []).count("принято")
                    stats[b]["concl_bad"] += fb.get(kid, []).count("отклонено")
                    for rs in fbr.get(kid, []):
                        stats[b]["reasons"][rs] = stats[b]["reasons"].get(rs, 0) + 1
        decs = {d["id"]: d for d in load_decisions(p)}
        for o in load_outcomes(p):
            d = decs.get(o["decision"])
            if not d:
                continue
            for b in kbs(_closure(p, d.get("rests_on_list", []), claims, concl, levers)):
                if b in stats:
                    key = "out_none" if o.get("in_range") is None else ("out_yes" if o["in_range"] else "out_no")
                    stats[b][key] += 1
    return stats
