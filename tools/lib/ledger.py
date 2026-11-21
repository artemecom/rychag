# -*- coding: utf-8 -*-
"""Реестр: утверждения, выводы, рычаги, решения, расход, договор «что значит готово», вопросы."""
import re

from .common import (Fail, CLAIM_TYPES, CONCLUSION_KINDS, STATUS_OK, STATUS_DOUBT, STATUS_REPLACED,
                     STATUS_REJECTED, read_jsonl, write_jsonl, append_jsonl, read_json, write_json,
                     read_text, write_text_atomic, next_id, quote_in_text, numbers_in, canon_number,
                     today, now_iso, journal, read_state, set_state_field, parse_date, split_ids, short, norm_match,
                     CALC_METHODS, UNMEASURED_FLAG, UNPROVEN_TYPES, ON_ASSUMPTIONS_FLAG)
from .sources import get_source, source_text, list_sources, NON_GROUND_KINDS
from . import kb as kbase

# ---------------------------------------------------------------- утверждения


def load_claims(proj):
    return read_jsonl(proj.path("ledger", "claims.jsonl"))


def save_claims(proj, rows):
    write_jsonl(proj.path("ledger", "claims.jsonl"), rows)


def claim_by_id(proj, cid):
    for c in load_claims(proj):
        if c["id"] == cid:
            return c
    raise Fail("Утверждения %s нет. Список: python3 tools/rychag.py claim list" % cid)


ASSUME_FIELDS = (("low", "--low"), ("base", "--base"), ("high", "--high"), ("why", "--why"), ("how", "--verify-by"),
                 ("switch", "--switch-if"), ("unit", "--unit"))


def _plain_number(value, name):
    """Число параметра допущения: принимает запятую и пробелы в разрядах, возвращает (как записано, значение)."""
    raw = str(value).strip()
    try:
        return raw, float(canon_number(raw))
    except ValueError:
        raise Fail("%s должно быть числом, получено «%s». Единицу измерения укажите отдельно: --unit \"%%\"." % (name, value))


def _check_assumption(assume):
    """Проверяет поля допущения. Возвращает (поля для записи, предупреждения)."""
    a = {k: (v.strip() if isinstance(v, str) else v) for k, v in (assume or {}).items() if v is not None and str(v).strip()}
    for key, flag, what in (("low", "--low", "нижняя граница диапазона"), ("high", "--high", "верхняя граница диапазона"),
                            ("why", "--why", "почему границы именно такие"), ("how", "--verify-by", "как и когда проверим значение")):
        if key not in a:
            raise Fail("Допущению не хватает поля %s (%s). Допущение записывается диапазоном с обоснованными границами "
                       "и способом проверки: --low, --high, --why, --verify-by, по возможности --base и --switch-if." % (flag, what))
    low_raw, low = _plain_number(a["low"], "--low")
    high_raw, high = _plain_number(a["high"], "--high")
    if low > high:
        raise Fail("Границы допущения перепутаны: нижняя %s больше верхней %s." % (low_raw, high_raw))
    out = {"low": low_raw, "high": high_raw, "why": a["why"], "how": a["how"]}
    if "base" in a:
        base_raw, base = _plain_number(a["base"], "--base")
        if not low <= base <= high:
            raise Fail("Основное значение %s должно лежать между границами %s и %s." % (base_raw, low_raw, high_raw))
        out["base"] = base_raw
    notes = ["Записано как допущение: значение принято для расчёта до проверки. В page.md и document.md его числа идут только "
             "в строке со словом «допущение», а итог расчёта на нём со словом «допущение» или «оценка»."]
    if "switch" in a:
        out["switch"] = a["switch"]
    else:
        notes.append("Предупреждение: не задан порог смены решения. Добавьте --switch-if \"при каком значении выберем другой путь и какой\": "
                     "без него неясно, зачем проверять это допущение.")
    if "unit" in a:
        out["unit"] = a["unit"]
    return out, notes


def assumption_numbers(c):
    """Все числа допущения: границы, основное значение, порог смены решения и числа текста."""
    rng = c.get("range") or {}
    parts = [str(rng.get(k) or "") for k in ("low", "base", "high", "switch")]
    return numbers_in(" ; ".join(parts)) | numbers_in(c.get("number") or "") | numbers_in(c.get("text") or "")


def assumptions(proj):
    return [c for c in load_claims(proj) if c["type"] == "assumption" and c["status"] == STATUS_OK]


def calc_grounds(proj):
    """Код расчётного утверждения -> записи, на которые опирается его расчёт (параметр --rests-on у calc run и calc ready)."""
    metas = {m["id"]: m for m in list_sources(proj)}
    out = {}
    for c in load_claims(proj):
        if c["type"] == "calc":
            m = metas.get(c.get("source"))
            if m and m.get("rests_on"):
                out[c["id"]] = list(m["rests_on"])
    return out


def unproven_calcs(proj):
    """Расчётные утверждения, которые прямо или через другие расчёты стоят на допущении, гипотезе или прогнозе.
    Возвращает {код расчёта: [коды недоказанных записей]}."""
    claims = {c["id"]: c for c in load_claims(proj)}
    grounds = calc_grounds(proj)
    memo = {}

    def weak(cid, trail):
        if cid in memo:
            return memo[cid]
        found = []
        for g in grounds.get(cid, []):
            c = claims.get(g)
            if c is None or g in trail:
                continue
            if c["type"] in UNPROVEN_TYPES:
                found.append(g)
            elif c["type"] == "calc":
                found += weak(g, trail | {cid})
        memo[cid] = sorted(set(found))
        return memo[cid]

    return {cid: w for cid in grounds for w in [weak(cid, frozenset())] if w}


def assumption_lines(proj):
    """Сводка допущений задачи: список с кодами для работы и таблица для документа без кодов."""
    rows = assumptions(proj)
    if not rows:
        return ["Допущений нет. Записать: python3 tools/rychag.py claim add --type assumption --text \"...\" --low ... --high ... "
                "--why \"...\" --verify-by \"...\" --switch-if \"...\""]
    users = {}
    for cid, weak in unproven_calcs(proj).items():
        for g in weak:
            users.setdefault(g, []).append(cid)
    out = ["Допущений: %d. Сначала список с номерами записей (для --rests-on), ниже таблица для документа без номеров." % len(rows)]
    no_switch = []
    for c in rows:
        r = c["range"]
        unit = (" " + r["unit"]) if r.get("unit") else ""
        mid = ", основное %s%s" % (r["base"], unit) if r.get("base") else ""
        out.append("%s: %s. Диапазон: от %s до %s%s%s. Расчёты на нём: %s." % (
            c["id"], c["text"].rstrip("."), r["low"], r["high"], unit, mid, ", ".join(sorted(users.get(c["id"], []))) or "нет"))
        if not r.get("switch"):
            no_switch.append(c["id"])
    out.append("")
    out.append("Таблица допущений (значения приняты для расчёта до проверки):")
    out.append("")
    out.append("| Допущение | Низкое | Основное | Высокое | Почему такие границы | Как проверим | Когда выберем другой путь |")
    out.append("|---|---|---|---|---|---|---|")

    def cell(t):
        return re.sub(r"\s+", " ", str(t or "")).replace("|", "/").strip()

    for c in rows:
        r = c["range"]
        unit = (" " + r["unit"]) if r.get("unit") else ""
        out.append("| %s | %s%s | %s | %s%s | %s | %s | %s |" % (
            cell(c["text"]), r["low"], unit, (r["base"] + unit) if r.get("base") else "не задано", r["high"], unit,
            cell(r["why"]), cell(r["how"]), cell(r.get("switch")) or "не задано"))
    if no_switch:
        out.append("")
        out.append("Предупреждение: у допущений %s не задан порог смены решения. Запишите допущение заново с --switch-if, "
                   "а прежнее отбросьте: claim reject <код> --reason \"заменено\"." % ", ".join(no_switch))
    return out


def add_claim(proj, ctype, text, source=None, quote=None, number=None, kb=None, contradicts=None, from_map=None,
              method=None, accuracy=None, sample=None, assume=None):
    """Добавляет утверждение. Возвращает (claim, предупреждения)."""
    if ctype not in CLAIM_TYPES:
        raise Fail("Тип утверждения: %s." % ", ".join(CLAIM_TYPES))
    if not (text or "").strip():
        raise Fail("Пустой текст утверждения. Запишите, что именно утверждается, одной фразой.")
    notes = []
    flags = []
    rng = None
    given = [flag for key, flag in ASSUME_FIELDS if (assume or {}).get(key) is not None]
    if ctype != "assumption" and given:
        raise Fail("%s допустимы только для типа assumption (допущение)." % ", ".join(given))
    if ctype != "calc" and (method or accuracy is not None or sample is not None):
        raise Fail("--method, --accuracy и --sample допустимы только для типа calc.")
    if method is not None and method not in CALC_METHODS:
        raise Fail("Способ счёта: %s." % ", ".join(CALC_METHODS))
    if accuracy is not None and not (0 <= accuracy <= 100):
        raise Fail("Точность задаётся в процентах от 0 до 100, получено %s." % accuracy)
    if sample is not None and sample < 1:
        raise Fail("Размер выборки для проверки должен быть не меньше 1, получено %s." % sample)
    kb_ids = split_ids(kb) if kb else []
    if from_map:
        if ctype != "hypothesis":
            raise Fail("--from-map допустим только для типа hypothesis: связь карты причин это гипотеза, а не факт.")
        from . import kbmap
        kbmap.get_link(proj.root, from_map)
    cont = split_ids(contradicts) if contradicts else []
    if cont:
        known = {x["id"] for x in load_claims(proj)}
        for o in cont:
            if o not in known:
                raise Fail("Противоречие указано с %s, но такого утверждения нет." % o)
    lesson = False
    if kb_ids and ctype not in ("benchmark", "hypothesis"):
        raise Fail("--kb допустим только для типов benchmark (ориентир) и hypothesis.")
    if source is not None and not re.match(r"^S\d{3,}$", source):
        raise Fail("Источник указывается кодом вида S001 (список: source list). Получено «%s»." % source)
    meta = get_source(proj, source) if source else None
    if ctype == "fact":
        if not source or not quote:
            raise Fail("Факт без источника и дословной цитаты не принимается. Добавьте --source S001 "
                       "--quote \"фрагмент из копии\". Если источника нет, запишите как hypothesis.")
        if meta["kind"] in NON_GROUND_KINDS:
            raise Fail("Источник %s (вид «%s») не может быть основанием факта: это ответ ИИ или прежний вывод агента. "
                       "Запишите как --type synthetic (или agent) либо найдите настоящий источник." % (source, meta["kind"]))
        if meta["kind"] == "расчёт":
            raise Fail("Источник %s это расчёт. Числа из расчёта записываются как --type calc." % source)
        if not quote_in_text(quote, source_text(proj, source)):
            raise Fail("Цитата не найдена в %s. Скопируйте фрагмент дословно из sources/%s.txt "
                       "(регистр, пробелы и тип кавычек не важны). Начало вашей цитаты: «%s»." % (
                           source, source, short(quote, 50)))
        if number and not (numbers_in(number) <= numbers_in(quote)):
            raise Fail("Число «%s» не встречается в цитате. Факт держит только то, что есть в цитате. "
                       "Если число получено вычислением, запишите отдельное утверждение --type calc." % number)
    elif ctype == "calc":
        if not source or meta["kind"] != "расчёт":
            raise Fail("Для calc нужен --source с источником вида «расчёт» (его создаёт calc run).")
        if not number and not numbers_in(text):
            raise Fail("Расчёт без числа не нужен. Добавьте --number \"...\" или число в текст.")
        method = method or meta.get("method") or "расчёт"
        if method == "словарь" and (accuracy is None or sample is None):
            flags.append(UNMEASURED_FLAG)
            notes.append("Счёт по словарю слов без измеренной точности: помечено «%s». Проверьте случайную выборку и добавьте --accuracy <процент> "
                         "и --sample <размер>; пока этого нет, число на итоговой странице идёт только в строке со словом «оценка»." % UNMEASURED_FLAG)
        if method == "словарь" and accuracy is not None and sample is not None:
            flags.append("точность %s%% на выборке %d" % (("%g" % accuracy), sample))
        if quote and not quote_in_text(quote, source_text(proj, source)):
            raise Fail("Цитата не найдена в выводе расчёта %s. Скопируйте строку из sources/%s.txt." % (source, source))
    elif ctype in ("benchmark", "hypothesis") and kb_ids:
        if ctype == "benchmark" and (source or quote):
            raise Fail("Ориентиру источник и цитата не нужны: они уже в записи базы знаний. Уберите --source и --quote.")
        recs = [kbase.get_record(proj.root, i) for i in kb_ids]
        for r in recs:
            if r["status"] != kbase.R_ACTIVE:
                raise Fail("Запись %s не действует (статус «%s»). Найдите действующую: kb search." % (r["id"], r["status"]))
        lesson = any(r["kind"] == "урок" for r in recs)
        if ctype == "benchmark" and any(r.get("origin") == "отзывы" for r in recs):
            raise Fail("Запись выведена из отзывов, а не из исхода решения: это не доказательство. Её можно взять только в гипотезу (--type hypothesis --kb ...).")
        if number:
            pool = set()
            for r in recs:
                pool |= numbers_in(r["rule"] + " " + (r.get("quote") or "") + " " + str(r.get("number") or ""))
            if not numbers_in(number) <= pool:
                raise Fail("Число «%s» не встречается в записи базы знаний. Ориентир берёт числа только из записи." % number)
        if ctype == "benchmark":
            flags = ["ориентир: не факт о продукте"] + (["урок: основание только для гипотезы"] if lesson else [])
            notes.append("Записано как ориентир: он подсказывает гипотезы, варианты и рекомендации, но не факт о продукте. "
                         "Находка и причина на нём одном не держатся. Число с него на странице идёт только в строке со словом «ориентир».")
    elif ctype == "benchmark":
        raise Fail("Для ориентира нужна запись базы знаний: --kb B012 (поиск: kb search).")
    elif ctype == "plan":
        if source or quote:
            raise Fail("Параметру плана источник и цитата не нужны: это наш выбор, не доказательство. Уберите --source и --quote.")
        flags = ["наш выбор, не доказательство"]
        notes.append("Записано как параметр плана: наш выбор, не доказательство. На нём нельзя строить находку или причину, "
                     "рекомендация, проверка рычага и решение могут опираться на него вместе с фактами.")
    elif ctype == "assumption":
        if source or quote or kb_ids:
            raise Fail("Допущению источник, цитата и запись базы знаний не нужны: это значение, принятое до проверки. "
                       "Откуда взяты границы, напишите в --why. Число из источника записывайте как fact.")
        rng, more = _check_assumption(assume)
        flags = ["допущение: принято до проверки"]
        notes += more
    elif ctype in ("synthetic", "agent"):
        flags = ["не основание факта", "не основание числа на странице"]
        notes.append("Записано, но помечено: %s не может быть основанием факта или числа итоговой страницы. "
                     "Подтвердите настоящим источником и добавьте как fact." % ctype)
    claims = load_claims(proj)
    for x in claims:
        if x["status"] == STATUS_OK and norm_match(x["text"]) == norm_match(text) and (x.get("source") or None) == (source or None):
            raise Fail("Такое утверждение с тем же источником уже записано как %s. Повтор не нужен: используйте %s." % (x["id"], x["id"]))
    c = {"id": next_id("C", [x["id"] for x in claims]), "type": ctype, "text": text.strip(),
         "source": source, "quote": quote, "number": number, "status": STATUS_OK,
         "flags": flags, "created": today().isoformat()}
    if cont:
        c["contradicts"] = cont
    if kb_ids:
        c["kb"] = kb_ids
        c["kb_lesson"] = lesson
    if from_map:
        c["from_map"] = from_map
    if rng:
        c["range"] = rng
    if ctype == "calc":
        if unproven_grounds_of_source(proj, meta):
            notes.append("Расчёт стоит на допущениях (%s): его числа в page.md и document.md идут только в строке со словом «допущение» или «оценка»." % (
                ", ".join(unproven_grounds_of_source(proj, meta))))
        c["method"] = method
        if accuracy is not None:
            c["accuracy"] = accuracy
        if sample is not None:
            c["sample"] = sample
    append_jsonl(proj.path("ledger", "claims.jsonl"), c)
    journal(proj, "claim add", {"id": c["id"], "type": ctype, "source": source})
    return c, notes


def unproven_grounds_of_source(proj, meta):
    """Недоказанные записи (допущение, гипотеза, прогноз), на которых прямо или через другие расчёты стоит источник-расчёт."""
    claims = {c["id"]: c for c in load_claims(proj)}
    deeper = unproven_calcs(proj)
    found = []
    for g in (meta or {}).get("rests_on") or []:
        c = claims.get(g)
        if c is None:
            continue
        if c["type"] in UNPROVEN_TYPES:
            found.append(g)
        elif c["type"] == "calc":
            found += deeper.get(g, [])
    return sorted(set(found))


def reject_claim(proj, cid, reason):
    if not (reason or "").strip():
        raise Fail("Нужна причина: --reason \"почему не используем\".")
    claims = load_claims(proj)
    for c in claims:
        if c["id"] == cid:
            c["status"] = STATUS_REJECTED
            c["reject_reason"] = reason.strip()
            save_claims(proj, claims)
            journal(proj, "claim reject", {"id": cid, "reason": reason})
            users = [k["id"] for k in load_conclusions(proj) if cid in k.get("rests_on", []) and k["status"] != STATUS_REPLACED]
            return c, users
    raise Fail("Утверждения %s нет." % cid)


# ---------------------------------------------------------------- выводы

def load_conclusions(proj):
    return read_jsonl(proj.path("ledger", "conclusions.jsonl"))


def save_conclusions(proj, rows):
    write_jsonl(proj.path("ledger", "conclusions.jsonl"), rows)


def _check_grounds(proj, ids, allow_levers=False):
    claims = {c["id"]: c for c in load_claims(proj)}
    concl = {k["id"]: k for k in load_conclusions(proj)}
    if not ids:
        raise Fail("Не указаны основания: --rests-on C001,C002. Вывод без оснований не принимается.")
    for i in ids:
        if i in claims:
            if claims[i]["status"] != STATUS_OK:
                raise Fail("Основание %s не действует (статус «%s»). Выберите действующее." % (i, claims[i]["status"]))
        elif i in concl:
            if concl[i]["status"] != STATUS_OK:
                raise Fail("Основание %s не действует (статус «%s»)." % (i, concl[i]["status"]))
        else:
            raise Fail("Основания %s нет ни среди утверждений, ни среди выводов. Проверьте код." % i)
    return claims, concl


def add_conclusion(proj, text, rests_on, kind="finding", contradicts=None):
    if kind not in CONCLUSION_KINDS:
        raise Fail("Вид вывода: %s." % ", ".join(CONCLUSION_KINDS))
    if not (text or "").strip():
        raise Fail("Пустой текст вывода.")
    ids = split_ids(rests_on) if isinstance(rests_on, str) else list(rests_on or [])
    claims, concl = _check_grounds(proj, ids)
    cont = split_ids(contradicts) if isinstance(contradicts, str) else list(contradicts or [])
    for k in cont:
        if k not in concl:
            raise Fail("Противоречие указано с %s, но такого вывода нет." % k)
    notes = []
    for i in ids:
        if i in claims and claims[i].get("kb_lesson") and claims[i]["type"] == "benchmark":
            raise Fail("Основание %s опирается на собственный урок агента: урок может поддерживать только гипотезу (claim add --type hypothesis --kb ...)." % i)
    if kind == "recommendation" and any(i in claims and claims[i]["type"] == "benchmark" for i in ids) \
            and not any((i in claims and claims[i]["type"] in ("fact", "calc")) or i in concl for i in ids):
        notes.append("Внимание: рекомендация на ориентире требует хотя бы одного факта среди оснований. Проверка слоя 3 это не пропустит.")
    if kind in ("finding", "cause") and all(i in claims and claims[i]["type"] in ("plan", "benchmark") for i in ids):
        notes.append("Внимание: %s не может держаться только на параметрах плана (наш выбор, не доказательство). "
                     "Проверка слоя 3 это не пропустит." % kind)
    if kind == "promise" and not any(i in claims and claims[i]["type"] == "fact" for i in ids):
        notes.append("Внимание: обещание должно опираться хотя бы на один факт (--type fact). Проверка слоя 4 это не пропустит.")
    rows = load_conclusions(proj)
    for x in rows:
        if x["status"] != STATUS_REPLACED and norm_match(x["text"]) == norm_match(text):
            raise Fail("Такой вывод уже записан как %s. Повтор не нужен: используйте %s." % (x["id"], x["id"]))
    k = {"id": next_id("K", [x["id"] for x in rows]), "text": text.strip(), "kind": kind,
         "rests_on": ids, "status": STATUS_OK, "replaced_by": None, "contradicts": cont,
         "created": today().isoformat()}
    append_jsonl(proj.path("ledger", "conclusions.jsonl"), k)
    journal(proj, "conclusion add", {"id": k["id"], "kind": kind, "rests_on": ids})
    return k, notes


def set_conclusion_status(proj, kid, status, replaced_by=None):
    if status not in (STATUS_OK, STATUS_DOUBT, STATUS_REPLACED):
        raise Fail("Статус вывода: %s, %s или %s." % (STATUS_OK, STATUS_DOUBT, STATUS_REPLACED))
    rows = load_conclusions(proj)
    ids = [r["id"] for r in rows]
    if replaced_by and replaced_by not in ids:
        raise Fail("Замена %s не найдена среди выводов." % replaced_by)
    for r in rows:
        if r["id"] == kid:
            r["status"] = status
            r["replaced_by"] = replaced_by if status == STATUS_REPLACED else None
            save_conclusions(proj, rows)
            journal(proj, "conclusion set-status", {"id": kid, "status": status, "replaced_by": replaced_by})
            return r
    raise Fail("Вывода %s нет." % kid)


# ---------------------------------------------------------------- рычаги

def load_levers(proj):
    d = read_json(proj.path("levers.json"), {"levers": []})
    return d.get("levers", []) if isinstance(d, dict) else []


def _num(v, name):
    try:
        f = float(str(v).replace(",", "."))
    except ValueError:
        raise Fail("%s должно быть числом, получено «%s»." % (name, v))
    return int(f) if f == int(f) else f


def add_lever(proj, metric, where, cause, action, low, base, high, check, rests_on):
    for name, v in (("--metric", metric), ("--where", where), ("--cause", cause), ("--action", action), ("--check", check)):
        if not (v or "").strip():
            raise Fail("Пустое поле %s. Рычаг описывается полностью: показатель, где просадка, причина, точка нажима, эффект, проверка." % name)
    lo, ba, hi = _num(low, "--effect-low"), _num(base, "--effect-base"), _num(high, "--effect-high")
    if not (lo <= ba <= hi):
        raise Fail("Эффект должен идти по возрастанию: низкий <= базовый <= высокий (получено %s, %s, %s)." % (lo, ba, hi))
    ids = split_ids(rests_on)
    _check_grounds(proj, ids)
    levers = load_levers(proj)
    sig = norm_match(" ".join((metric, where, action)))
    for x in levers:
        if x.get("status", STATUS_OK) != "снят" and norm_match(" ".join((x["metric"], x["where"], x["action"]))) == sig:
            raise Fail("Такой рычаг уже записан как %s. Повтор не нужен: используйте %s." % (x["id"], x["id"]))
    lv = {"id": next_id("L", [x["id"] for x in levers]), "metric": metric.strip(), "where": where.strip(),
          "cause": cause.strip(), "action": action.strip(),
          "effect": {"low": lo, "base": ba, "high": hi}, "check": check.strip(),
          "rests_on": ids, "status": STATUS_OK, "created": today().isoformat()}
    levers.append(lv)
    write_json(proj.path("levers.json"), {"levers": levers})
    journal(proj, "lever add", {"id": lv["id"], "rests_on": ids})
    return lv


LEVER_RETIRED = "снят"
LEVER_STATUSES = [STATUS_OK, STATUS_DOUBT, LEVER_RETIRED]


def set_lever_status(proj, lid, status, reason=None):
    if status not in LEVER_STATUSES:
        raise Fail("Статус рычага: %s." % ", ".join(LEVER_STATUSES))
    levers = load_levers(proj)
    for lv in levers:
        if lv["id"] == lid:
            old = lv.get("status", STATUS_OK)
            lv["status"] = status
            if reason:
                lv["status_reason"] = reason.strip()
            write_json(proj.path("levers.json"), {"levers": levers})
            journal(proj, "lever set-status", {"id": lid, "from": old, "to": status, "reason": reason})
            return lv
    raise Fail("Рычага %s нет. Список: python3 tools/rychag.py lever list" % lid)


# ---------------------------------------------------------------- решения

def parse_front(text):
    m = re.match(r"^---\n(.*?)\n---\n?", text, re.S)
    if not m:
        return {}
    d = {}
    for line in m.group(1).split("\n"):
        if ":" in line:
            k, v = line.split(":", 1)
            d[k.strip()] = v.strip()
    return d


def load_decisions(proj):
    out = []
    d = proj.path("decisions")
    if not d.is_dir():
        return out
    for p in sorted(d.glob("DR-*.md")):
        f = parse_front(p.read_text(encoding="utf-8"))
        if f.get("id"):
            f["rests_on_list"] = split_ids(f.get("rests_on", ""))
            f["file"] = "decisions/" + p.name
            out.append(f)
    return out


DECISION_STATUSES = ["принято", "предложено", "заменено"]


def add_decision(proj, title, owner, metric, review_date, review_if, rests_on, status="предложено"):
    if status not in DECISION_STATUSES:
        raise Fail("Статус решения: %s." % ", ".join(DECISION_STATUSES))
    for name, v in (("--title", title), ("--owner", owner), ("--metric", metric), ("--review-if", review_if)):
        if not (v or "").strip():
            raise Fail("Пустое поле %s. У решения есть название, владелец, показатель и условие пересмотра." % name)
    parse_date(review_date)
    ids = split_ids(rests_on)
    claims = {c["id"] for c in load_claims(proj)}
    known = claims | {k["id"] for k in load_conclusions(proj)} | {l["id"] for l in load_levers(proj)}
    if not ids:
        raise Fail("Не указаны основания: --rests-on K001,L001.")
    for i in ids:
        if i not in known:
            raise Fail("Основания %s нет в реестре. Проверьте код." % i)
    for d in load_decisions(proj):
        if d.get("status") != "заменено" and norm_match(d.get("title", "")) == norm_match(title):
            raise Fail("Такое решение уже записано как %s. Повтор не нужен: используйте %s." % (d["id"], d["id"]))
    did = next_id("DR-", [d["id"] for d in load_decisions(proj)])
    body = ("---\nid: %s\ntitle: %s\nowner: %s\nmetric: %s\nreview_date: %s\nreview_if: %s\nrests_on: %s\n"
            "status: %s\ncreated: %s\n---\n\n# %s: %s\n\nПоказатель: %s\nВладелец: %s\n"
            "Пересмотреть до %s или раньше, если: %s\nОснования: %s\n") % (
        did, title.strip(), owner.strip(), metric.strip(), review_date, review_if.strip(), ", ".join(ids),
        status, today().isoformat(), did, title.strip(), metric.strip(), owner.strip(), review_date,
        review_if.strip(), ", ".join(ids))
    write_text_atomic(proj.path("decisions", did + ".md"), body)
    journal(proj, "decision add", {"id": did, "rests_on": ids})
    return did


def _edit_front(proj, did, key, value):
    p = proj.path("decisions", did + ".md")
    if not p.exists():
        raise Fail("Решения %s нет." % did)
    text = p.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        raise Fail("У %s нет блока --- в начале. Исправьте файл вручную." % p.name)
    lines = [l for l in m.group(1).split("\n")]
    for i, l in enumerate(lines):
        if l.startswith(key + ":"):
            if value is None:
                del lines[i]
            else:
                lines[i] = "%s: %s" % (key, value)
            break
    else:
        if value is not None:
            lines.append("%s: %s" % (key, value))
    write_text_atomic(p, "---\n" + "\n".join(lines) + "\n---\n" + text[m.end():])


def set_decision_status(proj, did, status, note=None):
    if status not in DECISION_STATUSES:
        raise Fail("Статус решения: %s." % ", ".join(DECISION_STATUSES))
    dec = next((d for d in load_decisions(proj) if d["id"] == did), None)
    if dec is None:
        raise Fail("Решения %s нет." % did)
    doubt = dec.get("doubt") == STATUS_DOUBT
    if doubt and status != "заменено" and not (note or "").strip():
        raise Fail("Решение %s помечено «под вопросом». Чтобы вернуть статус «%s», добавьте --note \"что перепроверили\"." % (did, status))
    _edit_front(proj, did, "status", status)
    if doubt:
        _edit_front(proj, did, "doubt", None)
    if (note or "").strip():
        _edit_front(proj, did, "recheck_note", note.strip())
    journal(proj, "decision set-status", {"id": did, "status": status, "note": note, "cleared_doubt": doubt})


def mark_decision_doubt(proj, did):
    _edit_front(proj, did, "doubt", STATUS_DOUBT)


# ---------------------------------------------------------------- расход

KIND_MEASURED = "замер"
KIND_ESTIMATE = "оценка агента"


def log_cost(proj, stage, usd, tokens=None, note=None, measured=False):
    if not 1 <= stage <= 8:
        raise Fail("Этап от 1 до 8.")
    if usd < 0:
        raise Fail("Расход не может быть отрицательным.")
    row = {"ts": now_iso(), "stage": stage, "usd": round(usd, 4), "tokens": tokens, "note": note or "",
           "kind": KIND_MEASURED if measured else KIND_ESTIMATE}
    append_jsonl(proj.path("cost.jsonl"), row)
    journal(proj, "cost log", {"stage": stage, "usd": row["usd"], "kind": row["kind"]})
    return row


def cost_rows(proj):
    rows = read_jsonl(proj.path("cost.jsonl"))
    for r in rows:
        r.setdefault("kind", KIND_ESTIMATE)
    return rows


def cost_detail(proj):
    """По этапам: {этап: {"measured": USD, "estimate": USD, "ms": мс, "turns": ходы, "tokens": токены}}."""
    out = {}
    for r in cost_rows(proj):
        d = out.setdefault(r["stage"], {"measured": 0.0, "estimate": 0.0, "ms": 0, "turns": 0, "tokens": 0, "has_measured": False})
        if r["kind"] == KIND_MEASURED:
            d["measured"] += float(r.get("usd") or 0)
            d["has_measured"] = True
            d["ms"] += int(r.get("duration_ms") or 0)
            d["turns"] += int(r.get("turns") or 0)
        else:
            d["estimate"] += float(r.get("usd") or 0)
        d["tokens"] += int(r.get("tokens") or 0)
    return out


def cost_summary(proj):
    """Расход по этапам для бюджета: где есть замер, берётся он, иначе оценка агента."""
    per, tokens = {}, {}
    for st, d in cost_detail(proj).items():
        per[st] = d["measured"] if d["has_measured"] else d["estimate"]
        tokens[st] = d["tokens"]
    return per, tokens, sum(per.values())


def import_session(proj, path, stages, split=None):
    """Читает отчёт сессии Claude Code и записывает прирост расхода как замер. Возвращает (строки, добавлено USD)."""
    import json
    from pathlib import Path
    p = Path(path)
    if not p.is_file():
        raise Fail("Файл отчёта %s не найден." % path)
    try:
        rep = json.loads(p.read_text(encoding="utf-8"))
    except ValueError as e:
        raise Fail("Файл %s не читается как JSON (%s)." % (path, e))
    for k in ("session_id", "total_cost_usd", "duration_api_ms", "num_turns"):
        if not isinstance(rep, dict) or k not in rep:
            raise Fail("В отчёте нет поля %s. Нужен отчёт сессии с полями session_id, total_cost_usd, duration_api_ms, num_turns." % k)
    try:
        total, dur, turns = float(rep["total_cost_usd"]), int(rep["duration_api_ms"]), int(rep["num_turns"])
    except (TypeError, ValueError):
        raise Fail("Поля total_cost_usd, duration_api_ms и num_turns в отчёте должны быть числами.")
    sid = str(rep["session_id"])
    stg = []
    for x in split_ids(stages):
        if not x.isdigit() or not 1 <= int(x) <= 8:
            raise Fail("Этапы указываются номерами от 1 до 8 через запятую, получено «%s»." % x)
        stg.append(int(x))
    if not stg or len(set(stg)) != len(stg):
        raise Fail("Укажите один или несколько разных этапов: --stage 3,4.")
    if split:
        try:
            shares = [float(x.replace(",", ".")) for x in split.split(",")]
        except ValueError:
            raise Fail("--split это доли через запятую, например 0.6,0.4.")
        if len(shares) != len(stg) or abs(sum(shares) - 1) > 0.001 or any(x < 0 for x in shares):
            raise Fail("--split: нужно столько долей, сколько этапов (%d), и в сумме они дают 1." % len(stg))
    else:
        shares = [1.0 / len(stg)] * len(stg)
    prev_cost, prev_ms = 0.0, 0
    for r in cost_rows(proj):
        if r.get("session") == sid:
            prev_cost = max(prev_cost, float(r.get("session_total_usd") or 0))
            prev_ms = max(prev_ms, int(r.get("session_duration_ms") or 0))
    if total < prev_cost - 1e-9:
        raise Fail("Накопленная стоимость сессии в отчёте (%.4f USD) меньше уже учтённой (%.4f USD). Это не тот отчёт или он старый." % (total, prev_cost))
    delta = total - prev_cost
    if delta <= 1e-9:
        return ["Сессия %s: прироста с прошлого импорта нет (накопленно %.4f USD). Ничего не записано." % (sid, total)], 0.0
    d_ms = max(dur - prev_ms, 0)
    left_turns = turns
    for n, (st, sh) in enumerate(zip(stg, shares)):
        t = left_turns if n == len(stg) - 1 else int(round(turns * sh))
        left_turns -= t
        row = {"ts": now_iso(), "stage": st, "usd": round(delta * sh, 4), "tokens": None,
               "note": "замер по отчёту сессии %s" % sid, "kind": KIND_MEASURED, "session": sid,
               "duration_ms": int(round(d_ms * sh)), "turns": t,
               "session_total_usd": round(total, 6), "session_duration_ms": dur}
        append_jsonl(proj.path("cost.jsonl"), row)
    journal(proj, "cost import-session", {"session": sid, "added_usd": round(delta, 4), "stages": stg})
    return ["Сессия %s: добавлен замер %.2f USD (было учтено %.2f, стало %.2f) по этапам %s, время %.1f с, ходов %d." % (
        sid, delta, prev_cost, total, ", ".join(map(str, stg)), d_ms / 1000.0, turns)], delta


# ---------------------------------------------------------------- договор «готово»

def load_done(proj):
    d = read_json(proj.path("done.json"), {"criteria": [], "budget_usd": 0})
    d.setdefault("criteria", [])
    d.setdefault("budget_usd", 0)
    return d


def add_criterion(proj, text):
    if not (text or "").strip():
        raise Fail("Пустой критерий.")
    d = load_done(proj)
    cid = next_id("D", [c["id"] for c in d["criteria"]], width=1)
    d["criteria"].append({"id": cid, "text": text.strip(), "met": False})
    write_json(proj.path("done.json"), d)
    journal(proj, "done add", {"id": cid})
    return cid


def mark_criterion(proj, cid, met=True):
    d = load_done(proj)
    for c in d["criteria"]:
        if c["id"] == cid:
            if bool(c.get("met")) == bool(met):
                c["unchanged"] = True  # уже в этом состоянии: ничего не пишем и в журнал не заносим
                return c
            c["met"] = met
            write_json(proj.path("done.json"), d)
            journal(proj, "done mark", {"id": cid, "met": met})
            return c
    raise Fail("Критерия %s нет. Список: done list." % cid)


def set_budget(proj, usd):
    if usd <= 0:
        raise Fail("Бюджет должен быть больше нуля.")
    d = load_done(proj)
    d["budget_usd"] = usd
    write_json(proj.path("done.json"), d)
    journal(proj, "done budget", {"usd": usd})


# ---------------------------------------------------------------- вопросы руководителю

def add_question(proj, text, if_yes, if_no):
    for name, v in (("--text", text), ("--if-yes", if_yes), ("--if-no", if_no)):
        if not (v or "").strip():
            raise Fail("Пустое поле %s. Вопрос задаётся с пометкой «если да, делаю так, если нет, так»." % name)
    st = read_state(proj)
    qs = st.get("open_questions", [])
    if len(qs) >= 3:
        raise Fail("Открытых вопросов уже три. Больше трёх не задаём: закройте один (question close N) или объедините.")
    n = max([q["n"] for q in qs] + [0]) + 1
    qs.append({"n": n, "text": text.strip(), "if_yes": if_yes.strip(), "if_no": if_no.strip()})
    set_state_field(proj, "open_questions", qs)
    journal(proj, "question add", {"n": n})
    return n


def close_question(proj, n, answer=None):
    st = read_state(proj)
    qs = st.get("open_questions", [])
    if not any(q["n"] == n for q in qs):
        raise Fail("Открытого вопроса №%d нет." % n)
    set_state_field(proj, "open_questions", [q for q in qs if q["n"] != n])
    journal(proj, "question close", {"n": n, "answer": answer})
