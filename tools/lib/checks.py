# -*- coding: utf-8 -*-
"""Слои проверки 1-5, проверки этапов, печать отчёта и замок завершения."""
import hashlib
import json
import re
from pathlib import Path

from .common import (Fail, PLACEHOLDER, STATUS_OK, STATUS_DOUBT, STATUS_REPLACED, STATUS_REJECTED, STAGE_NAMES,
                     read_json, read_text, read_state, set_state_field, journal, sha256_file, sha256_bytes,
                     numbers_in, page_numbers, norm_match, quote_in_text, today, parse_date, period_start, short, is_inside,
                     UNMEASURED_FLAG)
from .sources import (source_layer, list_sources, source_text, is_stale, domain_allowed, domain_of, NON_GROUND_KINDS,
                      ready_recheck)
from . import kb as kbase
from . import strategy as strat
from . import diagnosis as diag
from . import reqs
from . import document as docs
from .layers import claim_layers, evidence_ids, support_counts, support_line, word
from .ledger import (load_claims, load_conclusions, load_levers, load_decisions, load_done, assumption_numbers,
                     unproven_calcs, calc_grounds)

LAYER_RU_SHORT = {1: "данные продукта", 2: "данные компании", 3: "отрасль в стране", 4: "отрасль в мире", 5: "смежные отрасли"}
LAYER_NAMES = {1: "Источник", 2: "Факт", 3: "Вывод", 4: "Вариант и стратегия", 5: "Итоговая страница",
               6: "Документ по частям заказчика"}
DOC_LAYER = 6
L4_ALL = ("options", "promises", "premortem", "strategy")


def _issue(where, what, fix, sev="fail"):
    return {"where": where, "what": what, "fix": fix, "severity": sev}


class LayerResult:
    def __init__(self, n):
        self.n = n
        self.issues = []
        self.warnings = []
        self.info = []

    def fail(self, where, what, fix):
        self.issues.append(_issue(where, what, fix))

    def warn(self, where, what, fix):
        self.warnings.append(_issue(where, what, fix, "warn"))

    @property
    def ok(self):
        return not self.issues

    def as_dict(self):
        return {"layer": self.n, "name": LAYER_NAMES[self.n], "ok": self.ok,
                "issues": self.issues, "warnings": self.warnings, "info": self.info}


# ---------------------------------------------------------------- слой 1

def layer1(proj, cfg):
    r = LayerResult(1)
    sc = cfg["sources"]
    metas = list_sources(proj)
    per_q = {}
    for m in metas:
        sid = m["id"]
        w = proj.where("sources", sid + ".txt")
        txt = proj.path("sources", sid + ".txt")
        if not txt.exists():
            r.fail(w, "нет сохранённой копии текста", "добавьте источник заново: source add ...")
            continue
        if sha256_file(txt) != m.get("sha256"):
            r.fail(w, "копия изменена после сохранения (не совпадает отпечаток)",
                   "не правьте копии руками; добавьте источник заново")
        if not m.get("accessed"):
            r.fail(w, "нет даты обращения", "добавьте источник заново")
        kind = m.get("kind")
        if kind == "расшифровка":
            mp = proj.path(m.get("path") or "")
            if not m.get("path") or not mp.is_file():
                r.fail(w, "нет исходного медиафайла %s" % m.get("path"), "верните файл в materials/")
            elif sha256_file(mp) != m.get("media_sha256"):
                r.fail(w, "медиафайл %s изменён после сохранения" % m.get("path"), "добавьте источник заново с новой расшифровкой")
            r.warn(w, "расшифровка: программа проверяет, что цитата есть в расшифровке, но не может проверить, "
                      "что расшифровка соответствует файлу %s" % m.get("path"), "сверьте расшифровку с файлом глазами")
        if kind == "расчёт" and m.get("ready"):
            for i in m.get("inputs", []):
                ip = proj.path(i["path"])
                if not ip.exists() or sha256_file(ip) != i["sha256"]:
                    r.fail(w, "файл параметров %s изменён или пропал после расчёта" % i["path"],
                           "запустите calc ready %s заново и обновите утверждения calc" % m["ready"])
                    break
            else:
                bad = ready_recheck(proj, m)
                if bad:
                    r.fail(w, "готовый расчёт «%s»: %s" % (m["ready"], bad), "запустите calc ready %s заново и обновите утверждения calc" % m["ready"])
            continue
        if kind == "расчёт":
            sp = proj.path(m.get("script", ""))
            if not m.get("script") or not sp.exists():
                r.fail(w, "нет скрипта расчёта %s" % m.get("script"), "верните скрипт в analysis/ и запустите calc run")
            elif sha256_file(sp) != m.get("script_sha256"):
                r.fail(w, "скрипт расчёта изменён после запуска", "запустите calc run заново и обновите утверждения calc")
            for i in m.get("inputs", []):
                ip = proj.path(i["path"])
                if not ip.exists() or sha256_file(ip) != i["sha256"]:
                    r.fail(w, "входной файл %s изменён или пропал" % i["path"], "запустите calc run заново и обновите утверждения calc")
            continue
        lay = source_layer(m)
        if lay is None or not isinstance(lay, int) or not 1 <= lay <= 5:
            r.fail(w, "не указан слой близости источника", "source set-layer %s --layer N (1 данные продукта, 2 данные компании, "
                   "3 отрасль в стране, 4 отрасль в мире, 5 смежные отрасли)" % sid)
        if not m.get("replaced_by"):
            per_q[m.get("question")] = per_q.get(m.get("question"), 0) + 1
        if kind == "страница" and not domain_allowed(m.get("url") or "", sc["allowlist"]):
            r.fail(w, "сайт %s не в разрешённом списке" % domain_of(m.get("url") or ""),
                   "замените источник или расширьте config/sources.json с согласия руководителя")
        if not m.get("published"):
            r.warn(w, "нет даты публикации, свежесть не проверить", "добавьте дату, если она известна")
        else:
            try:
                if period_start(m["published"]) > today():
                    r.fail(w, "дата публикации в будущем", "проверьте дату")
            except Fail:
                r.fail(w, "дата публикации «%s» не в формате ГГГГ, ГГГГ-ММ или ГГГГ-ММ-ДД" % m["published"], "исправьте meta.json")
            if is_stale(m, cfg):
                r.fail(w, "источник старше порога (%d дней): опубликован %s" % (sc["freshness_days"], m["published"]),
                       "найдите свежий источник, затем impact --stale --mark; или source accept-stale %s --reason \"...\"" % sid)
    for q, n in per_q.items():
        if n > sc["max_sources_per_question"]:
            r.fail("sources/", "по вопросу «%s» %d источников, потолок %d" % (q, n, sc["max_sources_per_question"]),
                   "оставьте самые сильные источники, лишние уберите из работы вручную")
    known = {m["id"] for m in metas}
    d = proj.path("sources")
    if d.is_dir():
        for p in d.glob("S*.txt"):
            if p.stem not in known:
                r.warn(proj.where("sources", p.name), "копия без файла .meta.json", "добавьте источник командой source add")
    r.info.append("источников: %d" % len(metas))
    return r


# ---------------------------------------------------------------- слой 2

def layer2(proj, cfg):
    r = LayerResult(2)
    metas = {m["id"]: m for m in list_sources(proj)}
    claims = load_claims(proj)
    for c in claims:
        cid = c["id"]
        w = proj.where("ledger", "claims.jsonl") + " " + cid
        t = c.get("type")
        if c.get("status") == STATUS_REJECTED and not c.get("reject_reason"):
            r.fail(w, "отброшено без причины", "claim reject %s --reason \"...\"" % cid)
        if t == "plan":
            continue
        if t == "assumption":
            rng = c.get("range") or {}
            if c.get("status") == STATUS_OK and not all(rng.get(k) for k in ("low", "high", "why", "how")):
                r.fail(w, "у допущения нет диапазона, обоснования границ или способа проверки",
                       "запишите заново: claim add --type assumption --low ... --high ... --why \"...\" --verify-by \"...\", прежнее отбросьте")
            elif c.get("status") == STATUS_OK and not rng.get("switch"):
                r.warn(w, "у допущения не задан порог смены решения", "запишите заново с --switch-if \"при каком значении выберем другой путь\", прежнее отбросьте")
            continue
        if t in ("synthetic", "agent"):
            r.warn(w, "%s: не основание факта и числа итоговой страницы" % t, "подтвердите настоящим источником и добавьте как fact")
            continue
        if t == "fact":
            sid = c.get("source")
            if not sid or not c.get("quote"):
                r.fail(w, "у факта нет источника или цитаты", "добавьте источник и дословную цитату или смените тип на hypothesis")
                continue
            m = metas.get(sid)
            if not m:
                r.fail(w, "источник %s не найден" % sid, "добавьте источник заново")
                continue
            if m["kind"] in NON_GROUND_KINDS:
                r.fail(w, "факт стоит на источнике вида «%s»" % m["kind"], "перезапишите как synthetic или найдите настоящий источник")
                continue
            if not proj.path("sources", sid + ".txt").exists():
                continue
            if not quote_in_text(c["quote"], source_text(proj, sid)):
                r.fail(w, "цитата не найдена в %s.txt" % sid, "скопируйте цитату дословно из копии или отбросьте факт")
        elif t == "calc":
            m = metas.get(c.get("source"))
            if not m or m["kind"] != "расчёт":
                r.fail(w, "calc без источника вида «расчёт»", "создайте расчёт командой calc run")
            elif c.get("quote") and proj.path("sources", m["id"] + ".txt").exists() \
                    and not quote_in_text(c["quote"], source_text(proj, m["id"])):
                r.fail(w, "цитата не найдена в выводе расчёта %s" % m["id"], "запустите calc run заново и обновите цитату")
            if m and c.get("status") == STATUS_OK:
                by_id = {x["id"]: x for x in claims}
                for g in m.get("rests_on") or []:
                    if g not in by_id or by_id[g]["status"] != STATUS_OK:
                        r.fail(w, "расчёт %s опирается на запись %s, которая не действует" % (m["id"], g),
                               "повторите расчёт на действующих записях (--rests-on) и обновите утверждение, прежнее отбросьте")
    n_fact = sum(1 for c in claims if c["type"] == "fact")
    r.info.append("утверждений: %d, из них фактов %d" % (len(claims), n_fact))
    return r


# ---------------------------------------------------------------- слой 3

def _ground_state(claims, concl, gid):
    if gid in claims:
        return claims[gid]["status"], claims[gid]
    if gid in concl:
        return concl[gid]["status"], concl[gid]
    return None, None


def layer3(proj, cfg):
    r = LayerResult(3)
    claims = {c["id"]: c for c in load_claims(proj)}
    concl = {k["id"]: k for k in load_conclusions(proj)}
    levers = load_levers(proj)
    lm = claim_layers(proj)
    shaky = unproven_calcs(proj)  # расчёты на допущениях: о продукте ничего не доказывают

    def layer_rules(item_id, where, rests, label, kind):
        ev = [c for c in evidence_ids(rests, claims, concl) if claims[c]["type"] in ("fact", "calc") and c not in shaky]
        have = sorted({lm[c] for c in ev if c in lm})
        have_txt = ", ".join("слой %d (%s)" % (n, LAYER_RU_SHORT[n]) for n in have) or "никаких фактов и расчётов"
        if kind in ("finding", "cause"):
            if 1 not in have:
                if 2 in have:
                    r.warn(where, "%s %s (%s) опирается на данные компании (слой 2), а не самого продукта" % (label, item_id, kind),
                           "добавьте факт или расчёт слоя 1: данные самого продукта")
                else:
                    r.fail(where, "%s %s (%s) о продукте не опирается на данные самого продукта; есть: %s" % (label, item_id, kind, have_txt),
                           "нужен факт или расчёт слоя 1: выгрузка продукта в materials/ и calc run либо факт из его документа; "
                           "слои 3-5 одни не годятся")
        elif kind in ("recommendation", "option"):
            if not (set(have) & {1, 2}):
                r.fail(where, "%s %s (%s) без факта слоя 1 или 2; есть: %s" % (label, item_id, kind, have_txt),
                       "добавьте основанием факт или расчёт о продукте (слой 1) или о компании (слой 2)")

    def check_item(item_id, where, rests, label, kind=None):
        if kind:
            layer_rules(item_id, where, rests, label, kind)
        if not rests:
            r.fail(where, "%s %s без записанных оснований" % (label, item_id), "укажите --rests-on или замените вывод")
            return
        if kind in ("finding", "cause") and all(g in claims and (claims[g]["type"] == "assumption" or g in shaky) for g in rests):
            r.fail(where, "%s %s (%s) держится только на допущениях и расчётах на них: это значения, принятые до проверки" % (label, item_id, kind),
                   "добавьте основание из fact или calc на фактах; вывод о допущении записывайте как option или recommendation")
        elif kind in ("finding", "cause") and all(g in claims and claims[g]["type"] in ("plan", "benchmark") for g in rests):
            if all(claims[g]["type"] == "plan" for g in rests):
                r.fail(where, "%s %s (%s) держится только на параметрах плана: это наш выбор, не доказательство" % (label, item_id, kind),
                       "добавьте основание из fact или calc; параметры плана годятся только вместе с фактами")
            else:
                r.fail(where, "%s %s (%s) держится только на ориентирах и параметрах плана: ориентир не факт о продукте" % (label, item_id, kind),
                       "добавьте основание из fact или calc о самом продукте")
        if kind == "recommendation" and any(g in claims and claims[g]["type"] == "benchmark" for g in rests) \
                and not any((g in claims and claims[g]["type"] in ("fact", "calc")) or g in concl for g in rests):
            r.fail(where, "рекомендация %s опирается на ориентир без единого факта" % item_id,
                   "добавьте основанием хотя бы один fact или calc о продукте")
        for g in rests:
            if g in claims and claims[g].get("kb_lesson") and claims[g]["type"] == "benchmark":
                r.fail(where, "%s %s опирается на собственный урок агента (%s): урок годится только для гипотезы" % (label, item_id, g),
                       "замените основание фактом или ориентиром из записи с источником")
        weak = 0
        for g in rests:
            st, obj = _ground_state(claims, concl, g)
            if st is None:
                r.fail(where, "%s %s опирается на %s, которого нет" % (label, item_id, g), "исправьте основание")
            elif st != STATUS_OK:
                r.fail(where, "%s %s опирается на %s со статусом «%s»" % (label, item_id, g, st),
                       "пересмотрите %s или замените основание на действующее" % item_id)
            elif g in claims and claims[g]["type"] in ("synthetic", "agent"):
                weak += 1
        if weak == len(rests):
            r.fail(where, "%s %s держится только на synthetic/agent" % (label, item_id),
                   "добавьте основание из настоящего источника (fact или calc)")

    for k in concl.values():
        w = proj.where("ledger", "conclusions.jsonl") + " " + k["id"]
        if k["status"] == STATUS_OK:
            check_item(k["id"], w, k.get("rests_on", []), "вывод", k["kind"])
        elif k["status"] == STATUS_DOUBT:
            r.warn(w, "вывод под вопросом", "пересмотрите: conclusion set-status %s --status заменён --replaced-by K... или верните действует" % k["id"])
    for lv in levers:
        w = proj.where("levers.json") + " " + lv["id"]
        if lv.get("status", STATUS_OK) == STATUS_OK:
            check_item(lv["id"], w, lv.get("rests_on", []), "рычаг")

    seen_pairs = set()
    for c in claims.values():
        if c["status"] != STATUS_OK:
            continue
        for o in c.get("contradicts", []):
            oc = claims.get(o)
            if not oc or oc["status"] != STATUS_OK or tuple(sorted((c["id"], o))) in seen_pairs:
                continue
            seen_pairs.add(tuple(sorted((c["id"], o))))
            la, lb = lm.get(c["id"]), lm.get(o)
            if la and lb and la != lb:
                far, near = (c["id"], o) if la > lb else (o, c["id"])
                for k in concl.values():
                    if k["status"] == STATUS_OK and far in k.get("rests_on", []) and near not in k.get("rests_on", []):
                        r.fail(proj.where("ledger", "conclusions.jsonl") + " " + k["id"],
                               "вывод опирается на %s (слой %d), которое противоречит более близкому %s (слой %d), и не опирается на него" % (
                                   far, max(la, lb), near, min(la, lb)),
                               "добавьте основанием ближнее утверждение %s или замените вывод" % near)
    recs = {x["id"]: x for x in kbase.load_records(proj.root)}
    for c in claims.values():
        if c.get("kb") and c["status"] == STATUS_OK:
            for b in c["kb"]:
                rec = recs.get(b)
                if rec is None:
                    r.fail(proj.where("ledger", "claims.jsonl") + " " + c["id"], "запись базы знаний %s не найдена" % b,
                           "верните запись или отбросьте утверждение: claim reject %s --reason ..." % c["id"])
                elif rec["status"] != kbase.R_ACTIVE:
                    r.fail(proj.where("ledger", "claims.jsonl") + " " + c["id"],
                           "опирается на запись %s со статусом «%s» (%s)" % (b, rec["status"], rec.get("status_reason")),
                           "impact %s --mark, затем замените основание на действующую запись или отбросьте утверждение" % b)
    used = set()
    for k in concl.values():
        if k["status"] != STATUS_REPLACED:
            used.update(k.get("rests_on", []))
    for lv in levers:
        if lv.get("status", STATUS_OK) != "снят":
            used.update(lv.get("rests_on", []))
    for cid, grounds in calc_grounds(proj).items():
        if claims[cid]["status"] == STATUS_OK:
            used.update(grounds)  # запись, вошедшая параметром в действующий расчёт, использована
    relevant = [c for c in claims.values() if c["type"] in ("fact", "calc")]
    used_n = sum(1 for c in relevant if c["id"] in used)
    rejected = sum(1 for c in relevant if c["status"] == STATUS_REJECTED)
    for c in relevant:
        if c["status"] == STATUS_OK and c["id"] not in used:
            r.fail(proj.where("ledger", "claims.jsonl") + " " + c["id"],
                   "%s не использовано ни одним выводом или рычагом и не отброшено" % c["type"],
                   "используйте в выводе или claim reject %s --reason \"...\"" % c["id"])
    r.info.append("использовано %d из %d, отброшено %d" % (used_n, len(relevant), rejected))
    if read_state(proj)["stage"] >= diag.FROM_STAGE:
        for where, what, fix in diag.diagnosis_issues(proj):
            r.fail(where, what, fix)
        for where, what, fix in diag.layers_issues(proj):
            r.fail(where, what, fix)
        for where, what, fix in diag.map_issues(proj):
            r.fail(where, what, fix)
    return r


# ---------------------------------------------------------------- слой 4

def _sections(text):
    """Разбор options.md: список (уровень, заголовок, строки)."""
    secs = []
    cur = None
    for line in text.split("\n"):
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            cur = [len(m.group(1)), m.group(2), []]
            secs.append(cur)
        elif cur is not None:
            cur[2].append(line)
    return secs


_OBJ_LINE = re.compile(r"^\s*(?:[-*]\s*)?(?:\*\*)?возражени[ея][^:]*:(?:\*\*)?\s*(\S.*)$", re.I)


def _has_objection(secs, kid):
    for i, (lvl, head, lines) in enumerate(secs):
        if not re.search(r"\b%s\b" % re.escape(kid), head):
            continue
        for ln in lines:
            if _OBJ_LINE.match(ln):
                return True
        for lvl2, head2, lines2 in secs[i + 1:]:
            if lvl2 <= lvl:
                break
            if "возражени" in head2.lower() and any(re.match(r"^\s*[-*]\s*\S", ln) or ln.strip() for ln in lines2):
                if any(ln.strip() for ln in lines2):
                    return True
    return False


def _premortem_ok(proj):
    texts = [read_text(proj.path("options.md")), read_text(proj.path(docs.DOC_FILE))]
    sd = proj.path("strategy")
    if sd.is_dir():
        texts += [p.read_text(encoding="utf-8") for p in sorted(sd.glob("*.md"))]
    for t in texts:
        for lvl, head, lines in _sections(t):
            if "почему провалится" in head.lower() and any(l.strip() and PLACEHOLDER not in l for l in lines):
                return True
    return False


def layer4(proj, cfg, parts=L4_ALL):
    r = LayerResult(4)
    concl = [k for k in load_conclusions(proj) if k["status"] != STATUS_REPLACED]
    claims = {c["id"]: c for c in load_claims(proj)}
    if "promises" in parts:
        for k in concl:
            if k["kind"] == "promise":
                if not any(g in claims and claims[g]["type"] == "fact" and claims[g]["status"] == STATUS_OK
                           for g in k.get("rests_on", [])):
                    r.fail(proj.where("ledger", "conclusions.jsonl") + " " + k["id"],
                           "обещание не опирается ни на один действующий факт о продукте",
                           "добавьте факт о продукте (claim add --type fact ...) и обновите основание или уберите обещание")
    if "options" in parts:
        opts = [k for k in concl if k["kind"] == "option"]
        where = proj.where("ledger", "conclusions.jsonl")
        if len(opts) < 3:
            r.fail(where, "вариантов %d, нужно не меньше трёх" % len(opts),
                   "добавьте варианты: conclusion add --kind option --text \"...\" --rests-on ...")
        if not any("оставить как есть" in norm_match(k["text"]) for k in opts):
            r.fail(where, "нет варианта «оставить как есть»", "добавьте вариант с этими словами в тексте")
        opt_text = read_text(proj.path("options.md"))
        dismiss = norm_match("Закрыть направление: не рассматриваем, потому что")
        has_close = any("закрыть направление" in norm_match(k["text"]) for k in opts)
        has_dismiss = any(norm_match(re.sub(r"^\s*[-*]\s*", "", l)).startswith(dismiss) for l in opt_text.split("\n"))
        if not (has_close or has_dismiss):
            r.fail(proj.where("options.md"), "нет варианта «закрыть направление» и нет явного отказа от него",
                   "добавьте вариант (conclusion add --kind option, в тексте «закрыть направление») или строку в options.md, "
                   "начинающуюся с «Закрыть направление: не рассматриваем, потому что ...»")
        secs = _sections(opt_text)
        for k in opts:
            if not _has_objection(secs, k["id"]):
                r.fail(proj.where("options.md"), "у варианта %s нет возражения" % k["id"],
                       "добавьте в options.md заголовок «## %s ...» и под ним строку «Возражение: ...»" % k["id"])
    if "strategy" in parts and not docs.exists(proj):  # при документе по частям заказчика три файла стратегий не обязательны
        for where, what, fix in strat.issues(proj):
            r.fail(where, what, fix)
    if "premortem" in parts and any(lv.get("status", STATUS_OK) != "снят" for lv in load_levers(proj)):
        if not _premortem_ok(proj):
            r.fail(proj.where("strategy"), "нет разбора «почему провалится» на выбранный рычаг",
                   "добавьте раздел «## Почему провалится» с причинами в strategy/test-plan.md, options.md или document.md "
                   "(его пишет критик с чистой памятью)")
    return r


# ---------------------------------------------------------------- слой 5

class Numbers:
    """Числа, которые можно писать в page.md и document.md, по видам: от вида зависит слово-пометка в строке."""

    def __init__(self):
        self.ok = set()       # действующие fact, calc и plan, условия пересмотра решений: пометка не нужна
        self.weak = {}        # число есть только в записи другого типа (гипотеза, прогноз, ответ агента)
        self.effect = set()   # эффект рычага: слово «оценка»
        self.bench = set()    # чужой опыт и данные слоёв 3-5: слово «ориентир»
        self.soft = set()     # счёт по словарю без измеренной точности: слово «оценка»
        self.assume = set()   # допущение: слово «допущение»
        self.derived = set()  # расчёт на допущениях: слово «допущение» или «оценка»

    def known(self, canon):
        return (canon in self.ok or canon in self.soft or canon in self.effect or canon in self.bench
                or canon in self.assume or canon in self.derived)


def _eligible_numbers(proj):
    """Собирает числа реестра, рычагов и решений по видам."""
    nb = Numbers()
    lm = claim_layers(proj)
    shaky = unproven_calcs(proj)
    for c in load_claims(proj):
        nums = numbers_in(c.get("number") or "") | numbers_in(c.get("text") or "")
        if c["type"] == "assumption" and c["status"] == STATUS_OK:
            nb.assume |= assumption_numbers(c)
        elif c["type"] in ("fact", "calc") and c["status"] == STATUS_OK and lm.get(c["id"], 1) >= 3:
            nb.bench |= nums  # данные слоёв 3-5 принимаются, но только в строке со словом «ориентир»
        elif c["type"] == "calc" and c["status"] == STATUS_OK and c["id"] in shaky:
            nb.derived |= nums
        elif c["type"] in ("fact", "calc", "plan") and c["status"] == STATUS_OK:
            if UNMEASURED_FLAG in (c.get("flags") or []):
                nb.soft |= nums
            else:
                nb.ok |= nums
        elif c["type"] == "benchmark" and c["status"] == STATUS_OK:
            nb.bench |= nums
        else:
            for n in nums:
                nb.weak.setdefault(n, c)
    for d in load_decisions(proj):
        if d.get("status") != "заменено" and d.get("doubt") != STATUS_DOUBT:
            nb.ok |= numbers_in((d.get("review_if") or "") + " " + (d.get("metric") or ""))
    for lv in load_levers(proj):
        if lv.get("status", STATUS_OK) == STATUS_OK:
            nb.effect |= numbers_in(" ".join(str(v) for v in lv.get("effect", {}).values()))
    return nb


CODE_RE = re.compile(r"(?<![\w/.\-])(?:KS|[CKLBSNP])\d{3,}(?!\w)|(?<![\w/.\-])DR-\d+(?!\w)|(?<!\w)R\d{2}(?!\d)|(?<!\w)D\d(?!\d)")
_PATH_TOKEN = re.compile(r"^[^\s:]*(?:/[^\s:]*|\.[A-Za-z][A-Za-z0-9]{0,4})$")
LONG_DASHES = (chr(0x2014), chr(0x2013))


def _path_of_line(line):
    """Если строка целиком путь к файлу (маркер списка и короткая подпись до двоеточия допустимы), вернёт путь."""
    s = line.strip()
    s = re.sub(r"^(?:[-*]|\d+[.)])\s+", "", s)
    m = re.match(r"^([^/`:]{1,40}):\s+(.+)$", s)
    if m:
        s = m.group(2).strip()
    s = s.strip("`").strip()
    if s and _PATH_TOKEN.match(s) and not re.match(r"^\d+(?:[.,]\d+)?$", s):
        return s
    return None


def _exists(proj, rel):
    return any(c.exists() and is_inside(c, proj.root) for c in (proj.dir / rel, proj.root / rel))


def _ids_line(all_lines):
    """Номер необязательной последней строки «Номера записей: ...» (в ней коды разрешены) или None."""
    nz = [k for k, l in enumerate(all_lines) if l.strip()]
    if nz and norm_match(all_lines[nz[-1]]).startswith("номера записей:"):
        return nz[-1]
    return None


def _marker_context(all_lines, n):
    """Где ищем слово-пометку («оценка», «ориентир», «допущение») для числа из строки n: сама строка,
    а для строки таблицы ещё шапка этой таблицы и подпись прямо над ней."""
    line = all_lines[n]
    if not line.lstrip().startswith("|"):
        return norm_match(line)
    top = n
    while top > 0 and all_lines[top - 1].lstrip().startswith("|"):
        top -= 1
    parts = [line, all_lines[top]]
    k = top - 1
    if k >= 0 and not all_lines[k].strip():
        k -= 1
    if k >= 0 and all_lines[k].strip():
        parts.append(all_lines[k])
    return norm_match(" ".join(parts))


def style_issues(r, label, checked, style, noun="страницы", dashes=False):
    """Внутренние номера записей, нераскрытые сокращения, пустые обороты и (по желанию) длинные тире. label(n) даёт место строки."""
    for n, l in checked:
        m = CODE_RE.search(l)
        if m:
            r.fail(label(n), "внутренний номер записи «%s» в тексте %s: руководитель его не поймёт" % (m.group(0).strip(), noun),
                   "назовите рычаг и вариант словами; номера записей уберите из текста: они допустимы только в блоке путей "
                   "или в одной последней строке «Номера записей: ...»")
    for ab in style.get("abbreviations", []):
        key = norm_match(ab.get("abbr", ""))
        if not key:
            continue
        rx = re.compile(r"(?<!\w)" + re.escape(key) + r"(?!\w)")
        for n, l in checked:
            if rx.search(norm_match(l)):
                r.fail(label(n), "сокращение «%s»" % ab["abbr"], "напишите словами: «%s»" % ab.get("write", ""))
    for ph in style["banned_phrases"]:
        key = norm_match(ph)
        if not key:
            continue
        for n, l in checked:
            if key in norm_match(l):
                r.fail(label(n), "пустой оборот «%s»" % ph, "замените конкретным фактом или уберите")
    if dashes:
        for n, l in checked:
            if any(d in l for d in LONG_DASHES):
                r.fail(label(n), "длинное тире в тексте %s" % noun, "перестройте фразу: двоеточие, запятая или два предложения")


def number_issues(r, proj, label, all_lines, checked):
    """Каждое число текста есть в реестре и стоит рядом с нужным словом-пометкой. Одна проверка для page.md и document.md."""
    nb = _eligible_numbers(proj)
    seen = set()
    for n, l in checked:
        for raw, canon in page_numbers(l):
            if nb.known(canon) or canon in seen:
                continue
            seen.add(canon)
            if canon in nb.weak:
                c = nb.weak[canon]
                r.fail(label(n), "число «%s» есть только в утверждении %s типа %s" % (raw, c["id"], c["type"]),
                       "число в тексте допустимо только из действующего fact или calc; подтвердите источником "
                       "или запишите как допущение с диапазоном (claim add --type assumption)")
            else:
                r.fail(label(n), "числа «%s» нет в реестре" % raw,
                       "добавьте утверждение с этим числом (fact с цитатой, calc с расчётом, plan для своего выбора, "
                       "assumption для значения до проверки) или уберите число")
    rules = (
        (nb.effect, lambda c: c not in nb.ok, ("оценка",),
         "число эффекта рычага (%s) без слова «оценка»",
         "перепишите строку так, чтобы в ней было слово «оценка»: эффект рычага это оценка, а не факт"),
        (nb.soft, lambda c: c not in nb.ok, ("оценка",),
         "число (%s) получено счётом по словарю слов, точность не измерена, а в строке нет слова «оценка»",
         "добавьте в строку слово «оценка» или измерьте точность на случайной выборке и запишите: claim add --type calc --method словарь --accuracy <процент> --sample <размер>"),
        (nb.bench, lambda c: c not in nb.ok and c not in nb.effect, ("ориентир",),
         "число из ориентира или данных слоёв 3-5 (%s) без слова «ориентир»",
         "перепишите строку со словом «ориентир»: число из чужих данных не факт о продукте"),
        (nb.assume, lambda c: c not in nb.ok and c not in nb.effect, ("допущени",),
         "число из допущения (%s) без слова «допущение»",
         "перепишите строку со словом «допущение» (в таблице слово ставится один раз, в строке-подписи прямо над ней, а не в названиях столбцов): значение принято до проверки"),
        (nb.derived, lambda c: c not in nb.ok and c not in nb.effect and c not in nb.assume, ("допущени", "оценк"),
         "число из расчёта на допущениях (%s) без слова «допущение» или «оценка»",
         "перепишите строку со словом «оценка» или «допущение» (в таблице слово ставится один раз, в строке-подписи прямо над ней, а не в названиях столбцов): итог расчёта не твёрже его входов"),
    )
    for pool, extra, words, what, fix in rules:
        if not pool:
            continue
        for n, l in checked:
            hit = [raw for raw, canon in page_numbers(l) if canon in pool and extra(canon)]
            if not hit:
                continue
            ctx = _marker_context(all_lines, n)
            if not any(w in ctx for w in words):
                r.fail(label(n), what % hit[0], fix)


def _done_issues(r, proj):
    done = load_done(proj)
    if not done["criteria"]:
        r.fail(proj.where("done.json"), "нет критериев «что значит готово»", "done add --text \"...\", затем done mark D1")
    for c in done["criteria"]:
        if not c.get("met"):
            r.fail(proj.where("done.json") + " " + c["id"], "критерий не выполнен: %s" % short(c["text"], 60),
                   "выполните и отметьте: done mark %s" % c["id"])


def layer5(proj, cfg):
    r = LayerResult(5)
    pw = proj.where("page.md")
    if docs.exists(proj):
        # Заказчик задал структуру результата: страница собирается из начала документа, текст проверяет слой документа.
        r.info.append("страница собирается из начала документа (doc page), её текст проверяется вместе с документом")
        _done_issues(r, proj)
        return r
    text = read_text(proj.path("page.md"))
    if not text.strip():
        r.fail(pw, "итоговой страницы нет или она пуста", "напишите page.md (одна страница, в конце пути к файлам)")
        return r
    if PLACEHOLDER in text:
        r.fail(pw, "в странице остался шаблонный текст %s" % PLACEHOLDER, "замените его настоящим текстом")
    all_lines = text.split("\n")
    nz = [k for k, l in enumerate(all_lines) if l.strip()]
    ids_line = _ids_line(all_lines)
    if ids_line is not None:
        nz = nz[:-1]
    last_start = nz[-1] if nz else 0
    while last_start > 0 and all_lines[last_start - 1].strip():
        last_start -= 1
    exempt = set()  # номера строк, которые целиком существующий путь
    for n, ln in enumerate(all_lines):
        pth = _path_of_line(ln)
        if pth is None:
            continue
        if _exists(proj, pth):
            exempt.add(n)
        elif n >= last_start:
            r.fail(pw + ", строка %d" % (n + 1), "в конце указан несуществующий файл %s" % pth,
                   "исправьте путь (от папки проекта) или создайте файл")
    if not any(n >= last_start for n in exempt):
        r.fail(pw, "в конце страницы нет блока с путями к файлам",
               "добавьте последним абзацем список существующих файлов, по одному пути в строке")
    style = cfg["style"]
    checked = [(n, l) for n, l in enumerate(all_lines) if n not in exempt and n != ids_line]

    def label(n):
        return pw + ", строка %d" % (n + 1)

    style_issues(r, label, checked, style)
    count = sum(1 for n, l in checked if l.strip())
    if count > style["max_page_lines"]:
        r.fail(pw, "страница длиннее порога: %d непустых строк (строки с путями не считаются), можно %d" % (
            count, style["max_page_lines"]),
            "сократите: оставьте вывод, рычаги, два пути и что просим решить; детали уберите в файлы")
    number_issues(r, proj, label, all_lines, checked)
    _done_issues(r, proj)
    return r


# ---------------------------------------------------------------- документ по частям заказчика

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[А-ЯЁA-Z«])")  # граница предложений внутри абзаца
_TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{2,}")  # строка-разделитель под шапкой таблицы
_HEAD_MARK = re.compile(r"\((?:[^()|]*?)(?:оценк|допущен|ориентир)[^()|]*\)")  # пометка в скобках в названии столбца
_HEAD_NUM = re.compile(r"^(\s*#{1,6}\s+)(\d+[.)](?:\d+[.)]?)*)(\s)")  # номер заголовка: «1.», «2.1», «3)»


def req_place_report(proj, doc, parsed):
    """Требования и их место в результате. Возвращает (замечания, предупреждения, счётчик по местам)."""
    fails, no_place, no_phrase, counts = [], [], [], {}
    for it in reqs.load(proj):
        if it["status"] != reqs.R_DONE:
            continue
        where = (it.get("where") or "").strip()
        if not where:
            no_place.append(it["id"])
            continue
        w = proj.where("requirements.json") + " " + it["id"]
        try:
            kind, val = docs.resolve_place(proj, where)
        except Fail:
            fails.append((w, "место выполнения требования «%s» не найдено" % short(where, 40),
                          "укажите место заново: req close %s --by %s --where \"часть N\"" % (it["id"], it.get("closed_by") or docs.DOC_FILE)))
            continue
        name = "часть %d" % (val + 1) if kind == "часть" else (docs.START_WORD if kind == docs.START_WORD else val)
        counts[name] = counts.get(name, 0) + 1
        if kind == "часть" and parsed.part_words(val) < docs.MIN_WORDS:
            fails.append((w, "требование закрыто частью %d, а она пуста или её нет" % (val + 1), "напишите эту часть документа или укажите другое место"))
            continue
        if kind in ("часть", docs.START_WORD):
            if not it.get("phrase"):
                no_phrase.append(it["id"])
            elif docs.phrase_found(proj, where, it["phrase"]) is False:
                fails.append((w, "требование было закрыто фразой «%s», а в месте «%s» её больше нет: при переписывании ответ мог пропасть"
                              % (short(it["phrase"], 60), name),
                              "верните ответ в документ или, если он теперь сказан иначе, закройте заново: req close %s --by %s --where \"%s\" --phrase \"<новая фраза>\""
                              % (it["id"], it.get("closed_by") or docs.DOC_FILE, name)))
    warns = []
    if no_phrase:
        warns.append((proj.where("requirements.json"),
                      "у закрытых требований нет фразы из документа (%d): %s" % (len(no_phrase), ", ".join(no_phrase[:15]) + (" и другие" if len(no_phrase) > 15 else "")),
                      "без фразы проверка не заметит, если ответ пропадёт в следующей версии. Закройте списком: req close --by %s --file <файл> "
                      "(строка «R01 || часть 2 || дословная фраза»)" % docs.DOC_FILE))
    if no_place:
        warns.append((proj.where("requirements.json"),
                      "у закрытых требований не указано место в результате (%d): %s" % (len(no_place), ", ".join(no_place[:15]) + (" и другие" if len(no_place) > 15 else "")),
                      "укажите, где выполнено каждое: req close %s --by %s --where \"часть N\" (несколько кодов через запятую)" % (no_place[0], docs.DOC_FILE)))
    return fails, warns, counts


_NOT_PARAGRAPH = re.compile(r"^(\||#|>|[-*+]\s|\d+[.)]\s)")


def _paragraphs(checked):
    """Абзацы текста: строки подряд без пустой строки между ними (так их покажет читателю любая программа).
    Таблицы, заголовки и пункты списков не считаются. Возвращает (номер первой строки, число знаков)."""
    out, start, size, prev = [], None, 0, None
    for n, l in checked:
        t = l.strip()
        plain = bool(t) and not _NOT_PARAGRAPH.match(t)
        if plain and start is not None and prev == n - 1:
            size += len(t) + 1
        else:
            if start is not None:
                out.append((start, size))
            start, size = (n, len(t)) if plain else (None, 0)
        prev = n
    if start is not None:
        out.append((start, size))
    return out


def layer_doc(proj, cfg):
    """Документ по частям заказчика: состав, начало, числа, стиль, место каждого требования, страница из начала."""
    r = LayerResult(DOC_LAYER)
    doc = docs.load(proj)
    parsed = docs.Parsed(proj, doc)
    dw = proj.where(doc.get("file") or docs.DOC_FILE)
    for where, what, fix in docs.structure_issues(proj, doc, parsed):
        r.fail(where, what, fix)
    if not parsed.text.strip():
        return r
    style = cfg["style"]
    for where, what, fix in docs.opening_issues(proj, doc, parsed, style["max_page_lines"]):
        r.fail(where, what, fix)
    for where, what, fix in docs.ending_issues(proj, doc, parsed):
        r.fail(where, what, fix)
    for where, what, fix in docs.own_elements_issues(proj, doc, parsed, style.get("document_elements")):
        r.fail(where, what, fix)
    retold = docs.retold_sentences(proj, doc, parsed)
    if retold:
        shown = "; ".join("строка %d «%s»" % (n + 1, short(t, 60)) for n, t in retold[:12])
        msg = "предложений, почти дословно взятых из текста заказчика: %d (%s)" % (len(retold), shown)
        fix = ("заказчик свой текст знает: вместо пересказа вопроса дайте свой ответ (решение, число, срок, ответственный). "
               "Допускается не больше %d таких предложений" % docs.RETOLD_ALLOWED)
        (r.fail if len(retold) > docs.RETOLD_ALLOWED else r.warn)(dw, msg, fix)
    all_lines = [_HEAD_NUM.sub(lambda m: m.group(1) + " " * len(m.group(2)) + m.group(3), l) for l in parsed.lines]
    ids_line = _ids_line(all_lines)

    def label(n):
        return "%s, строка %d (%s)" % (dw, n + 1, parsed.part_of_line(n))

    left = [n + 1 for n, l in enumerate(all_lines) if PLACEHOLDER in l or l.strip().startswith(strat.HINT_PREFIX)]
    if left:
        r.fail(dw, "остался шаблонный текст %s или строка-подсказка, строки: %s" % (PLACEHOLDER, ", ".join(str(x) for x in left[:20])),
               "замените пометки настоящим текстом, подсказки уберите: заказчик их читать не должен")
    exempt = {n for n, l in enumerate(all_lines) if _path_of_line(l) is not None and _exists(proj, _path_of_line(l))}
    checked = [(n, l) for n, l in enumerate(all_lines) if n not in exempt and n != ids_line and PLACEHOLDER not in l]
    style_issues(r, label, checked, style, noun="документа", dashes=True)
    limit = int(style.get("max_paragraph_chars") or 0)
    for n, size in _paragraphs(checked):
        if limit and size > limit:
            r.fail(label(n), "абзац на %d знаков при допустимых %d: такой текст руководитель не прочитает" % (size, limit),
                   "разбейте на два-три абзаца по одной мысли и отделите их пустой строкой (строки подряд без пустой строки "
                   "читаются как один абзац), перечисление оформите списком или таблицей")
    sent_limit = int(style.get("max_opening_sentence_chars") or 0)
    if sent_limit:
        for n, l in checked:
            if n >= parsed.first_part or l.lstrip().startswith("|"):
                continue
            for sent in _SENT_SPLIT.split(l.strip()):
                if len(sent) > sent_limit:
                    r.fail(label(n), "в начале документа предложение на %d знаков при допустимых %d: «%s...»" % (len(sent), sent_limit, short(sent, 50)),
                           "начало читают первым и часто только его. Разбейте на короткие предложения, оговорки из скобок перенесите в «Чего не знаем» или в нужную часть")
                    break
    for n, l in checked:
        nxt = all_lines[n + 1] if n + 1 < len(all_lines) else ""
        if l.lstrip().startswith("|") and _TABLE_RULE.match(nxt) and _HEAD_MARK.search(norm_match(l)):
            r.fail(label(n), "служебная пометка в названии столбца таблицы",
                   "уберите пометку из шапки и поставьте одну строку-подпись прямо над таблицей, например «Числа таблицы: оценка на допущениях.»")
    number_issues(r, proj, label, all_lines, checked)
    fails, warns, counts = req_place_report(proj, doc, parsed)
    for where, what, fix in fails:
        r.fail(where, what, fix)
    for where, what, fix in warns:
        r.warn(where, what, fix)
    sync = docs.page_sync_issue(proj, doc, parsed)
    if sync:
        r.fail(*sync)
    r.info.append("частей: %d, заполнено %d; непустых строк в начале: %d из %d допустимых" % (
        len(doc["parts"]), sum(1 for i in range(len(doc["parts"])) if parsed.part_words(i) >= docs.MIN_WORDS),
        sum(1 for l in parsed.opening_lines() if l.strip()), style["max_page_lines"]))
    if counts:
        order = sorted(counts, key=lambda k: (k != docs.START_WORD, not k.startswith("часть"), k))
        r.info.append("требований по местам: " + ", ".join("%s: %d" % (k, counts[k]) for k in order))
    return r


# ---------------------------------------------------------------- сборка

def run_layers(proj, cfg, layers=(1, 2, 3, 4, 5), l4=L4_ALL):
    out = []
    for n in layers:
        if n == 1:
            out.append(layer1(proj, cfg))
        elif n == 2:
            out.append(layer2(proj, cfg))
        elif n == 3:
            out.append(layer3(proj, cfg))
        elif n == 4:
            out.append(layer4(proj, cfg, l4))
        elif n == 5:
            out.append(layer5(proj, cfg))
    if 5 in layers and docs.exists(proj):
        out.append(layer_doc(proj, cfg))  # заказчик задал структуру результата: без документа работа не закончена
    return out


def _tpl_placeholder(path):
    return PLACEHOLDER in read_text(path)


def stage_artifact_issues(proj, stage):
    """Обязательные файлы этапа (кроме слоёв проверки). Возвращает список замечаний."""
    iss = []
    if stage == 1:
        if not reqs.load(proj):
            iss.append(_issue(proj.where("requirements.json"), "не выписано ни одного требования из запроса",
                              "выпишите каждое требование человека: req add --text \"...\" --quote \"дословный фрагмент запроса\""))
        if not read_text(proj.path("brief.md")).strip():
            iss.append(_issue(proj.where("brief.md"), "нет постановки", "заполните brief.md"))
        elif _tpl_placeholder(proj.path("brief.md")):
            iss.append(_issue(proj.where("brief.md"), "остались пометки %s" % PLACEHOLDER,
                              "ответьте на вопросы постановки, особенно что менялось в продукте, тарифах и рекламе на дату начала"))
    elif stage == 7:
        for it in reqs.open_items(proj):
            iss.append(_issue(proj.where("requirements.json") + " " + it["id"], "требование не закрыто: %s" % short(it["text"], 70),
                              "закройте: req close %s --by <критерий, вывод, рычаг, решение или файл> либо снимите: req drop %s --reason \"...\"" % (it["id"], it["id"])))
    elif stage == 2:
        d = load_done(proj)
        if not d["criteria"]:
            iss.append(_issue(proj.where("done.json"), "нет критериев «что значит готово»", "done add --text \"...\""))
        if not d["budget_usd"]:
            iss.append(_issue(proj.where("done.json"), "не задан бюджет", "done budget --usd 5"))
    elif stage == 3:
        if not list_sources(proj):
            iss.append(_issue(proj.where("sources"), "нет ни одного источника", "source add ..."))
        if not any(c["type"] == "fact" for c in load_claims(proj)):
            iss.append(_issue(proj.where("ledger", "claims.jsonl"), "нет ни одного факта", "claim add --type fact --source S001 --quote \"...\""))
    elif stage == 4:
        if not any(k["status"] == STATUS_OK for k in load_conclusions(proj)):
            iss.append(_issue(proj.where("ledger", "conclusions.jsonl"), "нет действующих выводов", "conclusion add --text ... --rests-on C001"))
    elif stage == 5:
        if not read_text(proj.path("options.md")).strip():
            iss.append(_issue(proj.where("options.md"), "нет файла вариантов", "опишите варианты и возражения в options.md"))
    elif stage == 6:
        if not load_levers(proj):
            iss.append(_issue(proj.where("levers.json"), "нет рычагов", "lever add ..."))
        if not load_decisions(proj):
            iss.append(_issue(proj.where("decisions"), "нет записи решения", "decision add ..."))
        if docs.exists(proj):
            # Результат задан заказчиком как один документ: три файла стратегий не обязательны, на этом этапе нужны все его части.
            for where, what, fix in docs.structure_issues(proj):
                iss.append(_issue(where, what, fix))
        else:
            for name in ("product.md", "communication.md", "test-plan.md"):
                t = read_text(proj.path("strategy", name))
                if not t.strip() or PLACEHOLDER in t:
                    iss.append(_issue(proj.where("strategy", name), "стратегия не написана", "заполните файл"))
    return iss


STAGE_LAYERS = {
    1: ((), ()), 2: ((), ()), 3: ((1, 2), ()), 4: ((1, 2, 3), ()),
    5: ((1, 2, 3, 4), ("options",)), 6: ((1, 2, 3, 4), L4_ALL), 7: ((1, 2, 3, 4, 5), L4_ALL),
    8: ((1, 2, 3, 4, 5), L4_ALL),
}

STAGE_REQUIREMENTS = {
    1: "brief.md без пометок %s; не больше трёх открытых вопросов; выписано хотя бы одно требование (req add)" % PLACEHOLDER,
    2: "done.json: критерии «что значит готово» и бюджет",
    3: "хотя бы один источник и один факт; слои 1 и 2",
    4: "хотя бы один действующий вывод; слои 1-3",
    5: "не меньше трёх вариантов, среди них «оставить как есть», возражения в options.md; слои 1-3 и часть слоя 4",
    6: "рычаги, запись решения, три файла strategy/ со всеми обязательными частями (strategy check), разбор «почему провалится»; слои 1-4. "
       "Если заказчик задал структуру результата (doc init): вместо трёх файлов все части document.md",
    7: "page.md без внутренних номеров записей, все критерии done.json выполнены, каждое требование из запроса закрыто или снято; слои 1-5. "
       "Если заказчик задал структуру результата: проходит doc check, а page.md собрана из начала документа (doc page)",
    8: "последний этап: пересмотр, уборка (sweep), сроки",
}


def stage_report(proj, cfg, stage):
    """Замечания для завершения этапа: файлы этапа и нужные слои."""
    layers, l4 = STAGE_LAYERS[stage]
    res = run_layers(proj, cfg, layers, l4)
    arts = stage_artifact_issues(proj, stage)
    return arts, res


# ---------------------------------------------------------------- печать

def format_layers(res, arts=None):
    lines = []
    total = 0
    if arts:
        lines.append("Файлы этапа: НЕ ГОТОВЫ (%d)" % len(arts))
        for i in arts:
            lines.append("  - [%s] %s. Как исправить: %s." % (i["where"], i["what"], i["fix"]))
        total += len(arts)
    for r in res:
        head = "Слой %d. %s: %s" % (r.n, LAYER_NAMES[r.n], "OK" if r.ok else "НЕ ПРОЙДЕН (%d)" % len(r.issues))
        lines.append(head)
        for i in r.issues:
            lines.append("  - [%s] %s. Как исправить: %s." % (i["where"], i["what"], i["fix"]))
        for i in r.warnings:
            lines.append("  - предупреждение [%s] %s. %s." % (i["where"], i["what"], i["fix"][:1].upper() + i["fix"][1:]))
        for t in r.info:
            lines.append("  " + t)
        total += len(r.issues)
    return lines, total


def result_json(proj, res, arts=None):
    ok = not arts and all(r.ok for r in res)
    return json.dumps({"project": proj.name, "ok": ok, "stage_files": arts or [],
                       "layers": {str(r.n): r.as_dict() for r in res}}, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------- замок

def fingerprint(proj):
    h = hashlib.sha256()
    skip = {"state.json", "journal.jsonl"}
    for p in sorted(proj.dir.rglob("*")):
        if p.is_file() and p.name not in skip and "__pycache__" not in p.parts and not p.name.endswith(".tmp"):
            h.update(p.relative_to(proj.dir).as_posix().encode("utf-8"))
            h.update(sha256_file(p).encode("ascii"))
    return h.hexdigest()


GUARD_LIMIT = 5


def guard_after_failure(proj):
    """Считает подряд идущие провалы без изменений файлов. Возвращает True, если пора выпустить."""
    st = read_state(proj)
    g = st.get("gate", {"fails": 0, "fp": ""})
    fp = fingerprint(proj)
    if g.get("fp") == fp:
        if g.get("fails", 0) >= GUARD_LIMIT:
            set_state_field(proj, "gate", {"fails": 0, "fp": fp})
            journal(proj, "gate", {"result": "выпущено защитой от зацикливания",
                                   "причина": "%d провалов подряд без изменений файлов" % GUARD_LIMIT})
            return True
        g = {"fails": g.get("fails", 0) + 1, "fp": fp}
    else:
        g = {"fails": 1, "fp": fp}
    set_state_field(proj, "gate", g)
    return False


def guard_reset(proj):
    st = read_state(proj)
    if st.get("gate", {}).get("fails"):
        set_state_field(proj, "gate", {"fails": 0, "fp": ""})
