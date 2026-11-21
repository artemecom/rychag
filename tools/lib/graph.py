# -*- coding: utf-8 -*-
"""Что задето (impact) и уборка (sweep)."""
import re

from .common import (Fail, STATUS_OK, STATUS_DOUBT, STATUS_REPLACED, STATUS_REJECTED, today, parse_date, short,
                     journal, write_json)
from .sources import list_sources, is_stale, get_source
from .ledger import (load_claims, load_conclusions, save_conclusions, load_levers, load_decisions,
                     mark_decision_doubt, calc_grounds)
from . import kb as kbase
from .layers import claim_layers, conclusion_layer


def _nodes(proj):
    """Все узлы, у которых есть «на чём держится»: id -> (вид, объект, основания)."""
    nodes = {}
    for k in load_conclusions(proj):
        nodes[k["id"]] = ("вывод", k, k.get("rests_on", []))
    for lv in load_levers(proj):
        nodes[lv["id"]] = ("рычаг", lv, lv.get("rests_on", []))
    for d in load_decisions(proj):
        nodes[d["id"]] = ("решение", d, d.get("rests_on_list", []))
    grounds = calc_grounds(proj)
    for c in load_claims(proj):
        if c.get("kb"):
            nodes[c["id"]] = ("утверждение", c, c["kb"])
        elif c["id"] in grounds:
            nodes[c["id"]] = ("утверждение", c, grounds[c["id"]])  # расчёт зависит от записей, на которых стоят его параметры
    return nodes


def dependants_map(proj):
    nodes = _nodes(proj)
    dep = {}
    for nid, (_, _, rests) in nodes.items():
        for g in rests:
            dep.setdefault(g, []).append(nid)
    for g in dep:
        dep[g].sort()
    return dep, nodes


def common_ru(t):
    from .common import CLAIM_TYPE_RU
    return CLAIM_TYPE_RU.get(t, t)


def _label(kind, obj, lay=None):
    if kind == "вывод":
        extra = obj["kind"] + ", " + obj["status"]
        txt = obj["text"]
        if obj["kind"] == "promise":
            kind = "обещание"
    elif kind == "утверждение":
        extra, txt = "%s, %s" % (common_ru(obj["type"]), obj["status"]), obj["text"]
    elif kind == "рычаг":
        extra, txt = obj.get("status", STATUS_OK), obj["metric"]
    else:
        extra, txt = obj.get("status", ""), obj.get("title", "")
    if lay:
        extra += ", слой %d" % lay
    return "[%s, %s] %s" % (kind, extra, short(txt, 60))


def chain(proj, root_id):
    """Возвращает (строки дерева, список задетых id в порядке обхода)."""
    dep, nodes = dependants_map(proj)
    lm = claim_layers(proj)
    claims = {c["id"]: c for c in load_claims(proj)}
    concl = {k["id"]: k for k in load_conclusions(proj)}
    lines, order, seen = [], [], set()

    def walk(nid, depth):
        for d in dep.get(nid, []):
            kind, obj, _ = nodes[d]
            if d in seen:
                lines.append("%s%s (уже показано выше)" % ("  " * depth, d))
                continue
            seen.add(d)
            order.append(d)
            lay = lm.get(d) if kind == "утверждение" else (conclusion_layer(obj, claims, concl, lm) if kind == "вывод" else None)
            lines.append("%s%s %s" % ("  " * depth, d, _label(kind, obj, lay)))
            walk(d, depth + 1)

    walk(root_id, 1)
    return lines, order


def _root_title(proj, rid):
    for c in load_claims(proj):
        if c["id"] == rid:
            lay = claim_layers(proj).get(rid)
            return "утверждение %s%s: %s" % (c["type"] if c["type"] != "assumption" else common_ru(c["type"]),
                                             ", слой %d" % lay if lay else "", short(c["text"], 60))
    if rid.startswith("B") and rid[1:].isdigit():
        rec = kbase.get_record(proj.root, rid)
        return "запись базы знаний, слой %s, %s: %s" % (rec.get("layer"), rec["status"], short(rec["rule"], 60))
    nodes = _nodes(proj)
    if rid in nodes:
        return "%s: %s" % (nodes[rid][0], short(str(nodes[rid][1].get("text") or nodes[rid][1].get("metric") or nodes[rid][1].get("title")), 60))
    raise Fail("Объекта %s нет в реестре. Проверьте код (C... утверждение, K... вывод, L... рычаг)." % rid)


def mark_doubt(proj, ids):
    """Ставит «под-вопросом» выводам, рычагам и решениям из списка. Возвращает список реально изменённых."""
    changed = []
    ids = set(ids)
    concl = load_conclusions(proj)
    touched = False
    for k in concl:
        if k["id"] in ids and k["status"] == STATUS_OK:
            k["status"] = STATUS_DOUBT
            changed.append(k["id"])
            touched = True
    if touched:
        save_conclusions(proj, concl)
    levers = load_levers(proj)
    touched = False
    for lv in levers:
        if lv["id"] in ids and lv.get("status", STATUS_OK) == STATUS_OK:
            lv["status"] = STATUS_DOUBT
            changed.append(lv["id"])
            touched = True
    if touched:
        write_json(proj.path("levers.json"), {"levers": levers})
    for d in load_decisions(proj):
        if d["id"] in ids and d.get("doubt") != STATUS_DOUBT and d.get("status") != "заменено":
            mark_decision_doubt(proj, d["id"])
            changed.append(d["id"])
    return changed


def impact(proj, cfg, root_id=None, mark=False, stale=False):
    """Печатает цепочку. Возвращает список строк."""
    out = []
    if stale:
        stale_src = {m["id"] for m in list_sources(proj) if is_stale(m, cfg) or m.get("replaced_by")}
        roots = [c["id"] for c in load_claims(proj) if c.get("source") in stale_src]
        if not roots:
            return ["Устаревших и замещённых новой версией источников нет: ничего не задето."]
        out.append("Источники старше порога или замещённые новой версией: %s. Задеты утверждения: %s." % (", ".join(sorted(stale_src)), ", ".join(roots)))
    else:
        if not root_id:
            raise Fail("Укажите код (например C003) или --stale.")
        if re.match(r"^S\d{3,}$", root_id):
            get_source(proj, root_id)
            roots = [c["id"] for c in load_claims(proj) if c.get("source") == root_id]
            if not roots:
                return ["Источник %s: утверждений на нём нет, ничего не задето." % root_id]
            out.append("Источник %s: задеты утверждения %s." % (root_id, ", ".join(roots)))
        else:
            _root_title(proj, root_id)
            roots = [root_id]
    all_hit = []
    for rid in roots:
        lines, order = chain(proj, rid)
        out.append("От %s (%s):" % (rid, _root_title(proj, rid)))
        out.extend(lines or ["  на это ничего не опирается"])
        all_hit.extend(order)
    uniq = sorted(set(all_hit))
    nodes = _nodes(proj)
    n_promise = sum(1 for i in uniq if nodes[i][0] == "вывод" and nodes[i][1]["kind"] == "promise")
    out.append("Задето: %d (обещаний среди них %d)." % (len(uniq), n_promise))
    if mark:
        changed = mark_doubt(proj, uniq)
        journal(proj, "impact", {"roots": roots, "marked": changed, "status": STATUS_DOUBT})
        out.append("Поставлен статус «%s»: %s. Пересмотрите их и затем верните «действует» или замените." % (
            STATUS_DOUBT, ", ".join(changed) or "нечего менять"))
    elif uniq:
        out.append("Чтобы поставить статус «%s», повторите с --mark." % STATUS_DOUBT)
    return out


def sweep(proj, cfg):
    """Возвращает список (раздел, [строки])."""
    claims = {c["id"]: c for c in load_claims(proj)}
    concl = {k["id"]: k for k in load_conclusions(proj)}
    levers = load_levers(proj)
    res = []

    sec = []
    for k in concl.values():
        if k["status"] == STATUS_REPLACED:
            continue
        for g in k.get("rests_on", []):
            obj = claims.get(g) or concl.get(g)
            if obj is None:
                sec.append("%s: основания %s нет. Исправьте основание." % (k["id"], g))
            elif obj["status"] != STATUS_OK and k["status"] == STATUS_OK:
                sec.append("%s действует, но %s со статусом «%s». Пересмотрите вывод." % (k["id"], g, obj["status"]))
        if not k.get("rests_on"):
            sec.append("%s без оснований. Добавьте основание или замените вывод." % k["id"])
        if k["status"] == STATUS_DOUBT:
            sec.append("%s под вопросом. Верните «действует» или замените." % k["id"])
    for lv in levers:
        if lv.get("status", STATUS_OK) == STATUS_DOUBT:
            sec.append("рычаг %s под вопросом. Пересчитайте эффект." % lv["id"])
    res.append(("Выводы без оснований, с недействующими основаниями или под вопросом", sec))

    used = set()
    for k in concl.values():
        if k["status"] != STATUS_REPLACED:
            used.update(k.get("rests_on", []))
    for lv in levers:
        used.update(lv.get("rests_on", []))
    for cid, grounds in calc_grounds(proj).items():
        if claims[cid]["status"] == STATUS_OK:
            used.update(grounds)
    sec = ["%s (%s): не использовано и не отброшено. Используйте или claim reject %s --reason ..." % (c["id"], c["type"], c["id"])
           for c in claims.values() if c["type"] in ("fact", "calc") and c["status"] == STATUS_OK and c["id"] not in used]
    res.append(("Утверждения, которые никто не использует", sec))

    sec = []
    for d in load_decisions(proj):
        if d.get("status") == "заменено" or not d.get("review_date"):
            continue
        try:
            late = (today() - parse_date(d["review_date"])).days
        except Fail:
            sec.append("%s: дата пересмотра «%s» записана неверно." % (d["id"], d["review_date"]))
            continue
        if late > 0:
            sec.append("%s: пересмотр был назначен на %s, просрочено на %d дн. Пересмотрите: условие «%s»." % (
                d["id"], d["review_date"], late, d.get("review_if", "")))
        if d.get("doubt") == STATUS_DOUBT:
            sec.append("%s под вопросом: основания менялись. Пересмотрите решение." % d["id"])
    res.append(("Просроченные пересмотры решений", sec))

    sec = []
    for m in list_sources(proj):
        if is_stale(m, cfg):
            sec.append("%s: опубликован %s, старше порога %d дн. Найдите свежий источник и выполните impact --stale --mark." % (
                m["id"], m["published"], cfg["sources"]["freshness_days"]))
    for m in list_sources(proj):
        if m.get("replaced_by"):
            sec.append("%s замещён новой версией %s. Выполните impact %s --mark и перепроверьте цитаты." % (m["id"], m["replaced_by"], m["id"]))
    res.append(("Источники старше порога или замещённые новой версией", sec))

    sec = []
    seen = set()
    for k in concl.values():
        for o in k.get("contradicts", []):
            pair = tuple(sorted((k["id"], o)))
            if pair in seen or o not in concl:
                continue
            seen.add(pair)
            if k["status"] != STATUS_REPLACED and concl[o]["status"] != STATUS_REPLACED:
                sec.append("%s и %s противоречат друг другу. Оставьте один, второй пометьте «заменён»." % pair)
    res.append(("Противоречия между выводами", sec))

    sec = []
    lm = claim_layers(proj)
    seen_p = set()
    for c in claims.values():
        for o in c.get("contradicts", []):
            if o in claims and tuple(sorted((c["id"], o))) not in seen_p and c["status"] == STATUS_OK and claims[o]["status"] == STATUS_OK:
                seen_p.add(tuple(sorted((c["id"], o))))
                la, lb = lm.get(c["id"]), lm.get(o)
                tail = ""
                if la and lb and la != lb:
                    near, far = (c["id"], o) if la < lb else (o, c["id"])
                    tail = " Ближе %s (слой %d), дальше %s (слой %d): верьте ближнему." % (near, min(la, lb), far, max(la, lb))
                elif la and lb:
                    tail = " Слой один (%d): решите по источникам, какое надёжнее." % la
                sec.append("%s и %s противоречат друг другу.%s" % (c["id"], o, tail))
    res.append(("Противоречия между утверждениями", sec))

    sec = []
    recs = {x["id"]: x for x in kbase.load_records(proj.root)}
    for c in claims.values():
        if c.get("kb") and c["status"] == STATUS_OK:
            for b in c["kb"]:
                rec = recs.get(b)
                if rec is None or rec["status"] != kbase.R_ACTIVE:
                    sec.append("%s опирается на запись %s (%s). Выполните impact %s --mark и замените основание на действующую запись." % (
                        c["id"], b, rec["status"] if rec else "нет в базе", b))
    res.append(("Утверждения на отозванных или заменённых записях базы знаний", sec))
    return res
