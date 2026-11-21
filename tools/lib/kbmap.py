# -*- coding: utf-8 -*-
"""Карта причин внутри базы знаний: узлы (показатели, факторы, действия) и связи «усиливает» или «ослабляет».
Каждая связь держится на записях базы знаний. Связь без действующих записей это гипотеза, знанием она не показывается."""
import difflib
import json
from collections import deque
from pathlib import Path

from .common import (Fail, LAYER_WORDS, today, now_iso, read_jsonl, write_jsonl, append_jsonl, write_text_atomic,
                     next_id, norm_match, split_ids, short)
from . import kb as kbase

KINDS = ["показатель", "фактор", "действие"]
SIGNS = ["усиливает", "ослабляет"]
L_ACTIVE, L_HYPOTHESIS, L_RETIRED = "действует", "гипотеза", "отозвана"
LINK_STATUSES = [L_ACTIVE, L_HYPOTHESIS, L_RETIRED]
DEFAULT_DEPTH = 3


class NoNode(Fail):
    """На карте нет узла под запрос (агент посмотрел и ничего не нашёл): это тоже след в журнале."""


def lw(layer):
    """Слой близости словами."""
    return LAYER_WORDS.get(layer, "не определено")


def mdir(root):
    return Path(root) / "knowledge" / "map"


def load_nodes(root):
    return read_jsonl(mdir(root) / "nodes.jsonl")


def load_links(root):
    return read_jsonl(mdir(root) / "links.jsonl")


def save_links(root, rows):
    write_jsonl(mdir(root) / "links.jsonl", rows)


def counts(root):
    """(узлов, связей, из них действует, гипотез)."""
    links = [l for l in load_links(root) if l["status"] != L_RETIRED]
    return (len(load_nodes(root)), len(links), sum(1 for l in links if l["status"] == L_ACTIVE),
            sum(1 for l in links if l["status"] == L_HYPOTHESIS))


# ---------------------------------------------------------------- узлы

def add_node(root, name, kind, aliases=None):
    name = (name or "").strip()
    if not name:
        raise Fail("Пустое название узла: --name \"Отток абонентов\".")
    if kind not in KINDS:
        raise Fail("Вид узла: %s." % ", ".join(KINDS))
    al = [a.strip() for a in (aliases.split(",") if isinstance(aliases, str) else (aliases or [])) if str(a).strip()]
    nodes = load_nodes(root)
    keys = {norm_match(name)} | {norm_match(a) for a in al}
    for n in nodes:
        have = {norm_match(n["name"])} | {norm_match(a) for a in n.get("aliases", [])}
        if keys & have:
            raise Fail("Узел с таким названием или псевдонимом уже есть: %s «%s»." % (n["id"], n["name"]))
    node = {"id": next_id("N", [n["id"] for n in nodes]), "name": name, "kind": kind, "aliases": al,
            "created": today().isoformat()}
    append_jsonl(mdir(root) / "nodes.jsonl", node)
    return node


def _exact_node(nodes, ref):
    ref = (ref or "").strip()
    for n in nodes:
        if n["id"] == ref:
            return n
    key = norm_match(ref)
    for n in nodes:
        if key and (norm_match(n["name"]) == key or key in [norm_match(a) for a in n.get("aliases", [])]):
            return n
    return None


def find_node(root, ref, nodes=None):
    """Строгий поиск: код, точное название или псевдоним."""
    nodes = nodes if nodes is not None else load_nodes(root)
    n = _exact_node(nodes, ref)
    if n:
        return n
    key = norm_match(ref)
    close = [n for n in nodes if key and (key in norm_match(n["name"]) or norm_match(n["name"]) in key)][:3]
    hint = " Похожие: %s." % "; ".join("%s «%s»" % (n["id"], n["name"]) for n in close) if close else ""
    raise Fail("Узла «%s» нет на карте. Список: python3 tools/rychag.py map node list. Добавить: map node add.%s" % (ref, hint))


def _node_score(n, alts):
    """Сколько слов запроса найдено в названии или в одном из псевдонимов (по отдельности, не вперемешку)."""
    best = 0
    for text in [n["name"]] + list(n.get("aliases", [])):
        toks = kbase._words(text)
        hit = sum(1 for al in alts if any(kbase._same(a, tk) for a in al for tk in toks))
        best = max(best, hit)
    return best


def resolve_node(root, ref, nodes=None):
    """Узел по словам руководителя: код, точное название, псевдоним, потом все значимые слова запроса
    (с теми же окончаниями и синонимами, что в kb search). Несколько узлов: список с номерами. Ни одного: пять ближайших."""
    nodes = nodes if nodes is not None else load_nodes(root)
    n = _exact_node(nodes, ref)
    if n:
        return n
    terms = kbase.query_terms(ref)
    groups = kbase.load_synonyms(root)
    alts = [kbase._expand(t, groups) for t in terms]
    scored = [(_node_score(n, alts) if terms else 0, n) for n in nodes]
    full = [n for sc, n in scored if terms and sc == len(terms)]
    if len(full) == 1:
        return full[0]
    if len(full) > 1:
        lines = ["  %d. %s" % (i, node_label(n)) for i, n in enumerate(full, 1)]
        raise Fail("Под запрос «%s» подходит несколько узлов, выберите один и повторите команду с его кодом (например %s):\n%s" % (
            ref, full[0]["id"], "\n".join(lines)))
    key = norm_match(ref)
    ranked = sorted(scored, key=lambda x: (-x[0], -difflib.SequenceMatcher(None, key, norm_match(x[1]["name"])).ratio(), x[1]["id"]))[:5]
    if not ranked:
        raise NoNode("На карте нет ни одного узла. Добавить: python3 tools/rychag.py map node add.")
    lines = ["  %d. %s" % (i, node_label(n)) for i, (_sc, n) in enumerate(ranked, 1)]
    raise NoNode("Узла «%s» на карте нет. Пять ближайших, повторите команду с кодом нужного:\n%s\nВесь список: python3 tools/rychag.py map node list" % (
        ref, "\n".join(lines)))


def node_label(n):
    return "%s «%s»" % (n["id"], n["name"])


# ---------------------------------------------------------------- связи

def _evidence_state(root, ids):
    recs = {r["id"]: r for r in kbase.load_records(root)}
    active = [recs[i] for i in ids if i in recs and recs[i]["status"] == kbase.R_ACTIVE]
    return recs, active


def _recompute(root, link, recs=None):
    """Пересчитывает слой, силу и статус связи по действующим записям. Возвращает True, если статус изменился."""
    if recs is None:
        recs = {r["id"]: r for r in kbase.load_records(root)}
    active = [recs[i] for i in link.get("evidence", []) if i in recs and recs[i]["status"] == kbase.R_ACTIVE]
    link["layer"] = min(r.get("layer") or 5 for r in active) if active else None
    link["strength"] = max((r["strength"] for r in active), key=lambda s: kbase.STRENGTH_RANK[s]) if active else None
    old = link.get("status")
    if old != L_RETIRED:
        link["status"] = L_ACTIVE if active else L_HYPOTHESIS
    return old != link["status"]


def _check_evidence(root, ids):
    recs = {r["id"]: r for r in kbase.load_records(root)}
    for i in ids:
        if i not in recs:
            raise Fail("Записи %s нет в базе знаний. Поиск: python3 tools/rychag.py kb search \"слова\"" % i)
        if recs[i]["status"] != kbase.R_ACTIVE:
            raise Fail("Запись %s не действует (статус «%s»). Основанием связи может быть только действующая запись." % (
                i, recs[i]["status"]))
    return recs


def add_link(root, frm, to, sign, conditions=None, evidence=None, note=None, contradicted_by=None):
    """Возвращает (связь, объединена_ли_с_существующей)."""
    if sign not in SIGNS:
        raise Fail("Знак связи: %s." % ", ".join(SIGNS))
    nodes = load_nodes(root)
    a, b = find_node(root, frm, nodes), find_node(root, to, nodes)
    if a["id"] == b["id"]:
        raise Fail("Связь узла с самим собой не нужна: %s." % node_label(a))
    ids = split_ids(evidence) if isinstance(evidence, str) else list(evidence or [])
    ids = list(dict.fromkeys(ids))
    recs = _check_evidence(root, ids)
    against = split_ids(contradicted_by) if isinstance(contradicted_by, str) else list(contradicted_by or [])
    against = list(dict.fromkeys(against))
    if against:
        _check_evidence(root, against)
    both = [i for i in ids if i in against]
    if both:
        raise Fail("Запись %s указана и как основание связи, и как довод против неё. Оставьте её в одном списке." % ", ".join(both))
    links = load_links(root)
    cond = (conditions or "").strip()
    nt = (note or "").strip()
    for l in links:
        if l["from"] == a["id"] and l["to"] == b["id"] and l["sign"] == sign and l["status"] != L_RETIRED:
            for i in ids:
                if i not in l["evidence"]:
                    l["evidence"].append(i)
            for i in against:
                if i not in l.setdefault("contradicted_by", []):
                    l["contradicted_by"].append(i)
            clash = [i for i in l["evidence"] if i in l.get("contradicted_by", [])]
            if clash:
                raise Fail("Запись %s окажется и основанием, и доводом против связи %s." % (", ".join(clash), l["id"]))
            if cond and cond not in l.get("conditions", ""):
                l["conditions"] = (l.get("conditions", "") + "; " + cond).strip("; ")
            if nt and nt not in l.get("note", ""):
                l["note"] = (l.get("note", "") + "; " + nt).strip("; ")
            _recompute(root, l, recs)
            save_links(root, links)
            return l, True
    l = {"id": next_id("R", [x["id"] for x in links]), "from": a["id"], "to": b["id"], "sign": sign,
         "conditions": cond, "evidence": ids, "layer": None, "strength": None, "status": L_HYPOTHESIS,
         "note": nt, "contradicted_by": against, "created": today().isoformat()}
    _recompute(root, l, recs)
    links.append(l)
    save_links(root, links)
    return l, False


def get_link(root, rid):
    for l in load_links(root):
        if l["id"] == rid:
            return l
    raise Fail("Связи %s нет на карте. Список: python3 tools/rychag.py map link list" % rid)


def retire_link(root, rid, reason):
    if not (reason or "").strip():
        raise Fail("Нужна причина: --reason \"почему отзываем\".")
    links = load_links(root)
    for l in links:
        if l["id"] == rid:
            l["status"] = L_RETIRED
            l["note"] = (l.get("note", "") + "; отозвана: " + reason.strip()).strip("; ")
            save_links(root, links)
            return l
    raise Fail("Связи %s нет на карте." % rid)


def refresh_links(root):
    """После отзыва или замены записи: пересчитывает связи. Возвращает [(код связи, было, стало)] для изменивших статус."""
    links = load_links(root)
    if not links:
        return []
    recs = {r["id"]: r for r in kbase.load_records(root)}
    changed = []
    for l in links:
        old = l["status"]
        if _recompute(root, l, recs):
            changed.append((l["id"], old, l["status"]))
    save_links(root, links)
    return changed


def links_using(root, bid):
    return [l for l in load_links(root) if bid in l.get("evidence", [])]


def link_line(root, l, nodes_by_id, recs=None):
    a, b = nodes_by_id.get(l["from"]), nodes_by_id.get(l["to"])
    s = "%s: %s «%s» %s %s «%s»" % (l["id"], l["from"], a["name"] if a else "?", l["sign"], l["to"], b["name"] if b else "?")
    return s + _tail(l, recs)


def _tail(l, recs=None):
    parts = []
    if l.get("conditions"):
        parts.append("условия: " + l["conditions"])
    if l["status"] == L_HYPOTHESIS:
        parts.append("записей-оснований нет, это гипотеза, не доказана")
    else:
        parts.append("ближайшие данные: %s" % lw(l.get("layer")))
        parts.append("сила доказательства: %s" % (l.get("strength") or "не определена"))
    parts.append("записи: %s" % (", ".join(l["evidence"]) or "нет"))
    if l.get("note"):
        parts.append(("чего не хватает: " if l["status"] == L_HYPOTHESIS else "примечание: ") + l["note"])
    if l.get("contradicted_by"):
        shown = []
        for i in l["contradicted_by"]:
            r = (recs or {}).get(i)
            shown.append("%s (%s)" % (i, short(r["rule"], 80)) if r else i)
        parts.append("записи против связи: " + "; ".join(shown))
    parts.append("статус %s" % l["status"])
    return ". " + "; ".join(parts) + "."


# ---------------------------------------------------------------- импорт

def _import_node(root, rec, stats):
    name = (rec.get("name") or "").strip()
    nodes = load_nodes(root)
    have = _exact_node(nodes, name) if name else None
    if have is not None:
        if have["kind"] == rec.get("kind") and norm_match(have["name"]) == norm_match(name):
            stats["nodes_same"] += 1
            return
        raise Fail("узел «%s» уже есть как %s «%s» (вид %s), а в файле другой: вид %s. Приведите файл в порядок или переименуйте узел" % (
            name, have["id"], have["name"], have["kind"], rec.get("kind")))
    add_node(root, rec.get("name"), rec.get("kind"), rec.get("aliases"))
    stats["nodes_ok"] += 1


def _import_link(root, rec, stats):
    for k in ("from", "to", "sign"):
        if not rec.get(k):
            raise Fail("нет поля %s" % k)
    if rec.get("status") not in (None, "", L_ACTIVE, L_HYPOTHESIS, L_RETIRED):
        raise Fail("статус связи: %s" % ", ".join(LINK_STATUSES))
    nodes = load_nodes(root)
    a, b = find_node(root, rec["from"], nodes), find_node(root, rec["to"], nodes)
    ev = split_ids(rec["evidence"]) if isinstance(rec.get("evidence"), str) else list(rec.get("evidence") or [])
    ag = split_ids(rec["contradicted_by"]) if isinstance(rec.get("contradicted_by"), str) else list(rec.get("contradicted_by") or [])
    twins = [l for l in load_links(root) if l["from"] == a["id"] and l["to"] == b["id"] and l["sign"] == rec["sign"]]
    live = [l for l in twins if l["status"] != L_RETIRED]
    if rec.get("status") == L_RETIRED:
        if live:
            raise Fail("в файле связь отозвана, а на карте %s действует: отзовите её командой map link retire" % live[0]["id"])
        if twins:
            stats["links_same"] += 1
            return
    if live:
        l = live[0]
        cond, nt = (rec.get("conditions") or "").strip(), (rec.get("note") or "").strip()
        new_ev = [i for i in dict.fromkeys(ev) if i not in l["evidence"]]
        new_ag = [i for i in dict.fromkeys(ag) if i not in l.get("contradicted_by", [])]
        same = not new_ev and not new_ag and (not cond or cond in l.get("conditions", "")) and (not nt or nt in l.get("note", ""))
        if same:
            stats["links_same"] += 1
            return
        add_link(root, rec["from"], rec["to"], rec["sign"], cond, ev, nt, ag)
        stats["links_merged"] += 1
        return
    l, _merged = add_link(root, rec["from"], rec["to"], rec["sign"], rec.get("conditions"), ev, rec.get("note"), ag)
    if rec.get("status") == L_RETIRED:
        retire_link(root, l["id"], "отозвана при импорте")
    stats["links_ok"] += 1


def import_map(root, path):
    """Повторный импорт безопасен: одинаковые узлы и связи пропускаются, новые записи вливаются в существующие связи,
    отклоняются только настоящие конфликты. Возвращает (счётчики, [(номер строки, причина)])."""
    p = Path(path)
    if not p.is_file():
        raise Fail("Файл импорта %s не найден." % path)
    rej_path = mdir(root) / "rejected.jsonl"
    stats = {"nodes_ok": 0, "links_ok": 0, "nodes_same": 0, "links_same": 0, "links_merged": 0}
    bad = []
    for n, line in enumerate(p.read_text(encoding="utf-8").split("\n"), 1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
            if not isinstance(rec, dict):
                raise ValueError
        except ValueError:
            bad.append((n, "строка не является объектом JSON"))
            append_jsonl(rej_path, {"line": n, "raw": line, "reason": bad[-1][1], "ts": now_iso()})
            continue
        try:
            t = rec.get("type")
            if t == "node":
                _import_node(root, rec, stats)
            elif t == "link":
                _import_link(root, rec, stats)
            else:
                raise Fail("поле type должно быть node или link")
        except Fail as e:
            bad.append((n, str(e)))
            append_jsonl(rej_path, {"line": n, "record": rec, "reason": str(e), "ts": now_iso()})
    return stats, bad


# ---------------------------------------------------------------- обход

def _rank(l):
    return (l["layer"] or 9, -kbase.STRENGTH_RANK.get(l["strength"], 0), l["id"])


def traverse(root, start, direction, depth, layer_max=None, proven_only=False):
    """direction: 'up' (что влияет на узел) или 'down' (на что влияет). Возвращает [(глубина, связь, идёт_через_гипотезу)].
    На каждом уровне сначала доказанные связи по близости данных, потом гипотезы. Гипотезы раскручиваются дальше,
    если не задано proven_only: тогда обход на них останавливается."""
    links = [l for l in load_links(root) if l["status"] != L_RETIRED]
    end_key, next_key = ("to", "from") if direction == "up" else ("from", "to")
    tree = []

    def walk(node_id, d, path, via_hyp):
        if d > depth:
            return
        here = [l for l in links if l[end_key] == node_id]
        proven = sorted([l for l in here if l["status"] == L_ACTIVE and (layer_max is None or (l["layer"] or 9) <= layer_max)], key=_rank)
        hyps = sorted([l for l in here if l["status"] == L_HYPOTHESIS], key=lambda l: l["id"])
        for l in proven + hyps:
            hyp = l["status"] == L_HYPOTHESIS
            tree.append((d, l, via_hyp or hyp))
            nxt = l[next_key]
            if nxt not in path and not (hyp and proven_only):
                walk(nxt, d + 1, path | {nxt}, via_hyp or hyp)

    walk(start, 1, {start}, False)
    return tree


def chain_lines(root, node, direction, depth, layer_max=None, proven_only=False):
    nodes = {n["id"]: n for n in load_nodes(root)}
    recs = {r["id"]: r for r in kbase.load_records(root)}
    tree = traverse(root, node["id"], direction, depth, layer_max, proven_only)
    out = []
    head = ("Причины для %s (глубина до %d" if direction == "up" else "Следствия от %s (глубина до %d") % (node_label(node), depth)
    out.append(head + (", данные не дальше: %s" % lw(layer_max) if layer_max else "")
               + (", обход останавливается на гипотезах" if proven_only else "") + "):")
    if not tree:
        out.append("  Связей нет.")
    for d, l, via in tree:
        other = nodes.get(l["from"] if direction == "up" else l["to"])
        if direction == "up":
            txt = "%s «%s» %s %s" % (other["id"], other["name"], l["sign"], l["to"])
        else:
            txt = "%s %s %s «%s»" % (l["from"], l["sign"], other["id"], other["name"])
        mark = "[ГИПОТЕЗА, не доказана] " if l["status"] == L_HYPOTHESIS else ("[цепочка идёт через гипотезу] " if via else "")
        out.append("  " * d + "%s%s %s%s" % (mark, l["id"], txt, _tail(l, recs)))
    out.append("")
    seen = {}
    for _d, l, _v in tree:
        seen[l["id"]] = l
    proven_n = sum(1 for l in seen.values() if l["status"] == L_ACTIVE)
    hyp_n = len(seen) - proven_n
    out.append("Показано связей: %d, из них доказано %d, гипотез %d." % (len(seen), proven_n, hyp_n))
    if hyp_n:
        out.append("Гипотезы знанием не считать: проверьте их на данных продукта, а чего не хватает для доказательства, сказано в строке связи.")
    return out


def find_paths(root, a, b, limit=5):
    """Кратчайшие цепочки от a к b по направлению связей. Возвращает [[связи]]."""
    links = [l for l in load_links(root) if l["status"] != L_RETIRED]
    out_by = {}
    for l in links:
        out_by.setdefault(l["from"], []).append(l)
    dist = {a: 0}
    q = deque([a])
    while q:
        x = q.popleft()
        for l in out_by.get(x, []):
            if l["to"] not in dist:
                dist[l["to"]] = dist[x] + 1
                q.append(l["to"])
    if b not in dist:
        return []
    paths = []

    def dfs(x, acc):
        if len(paths) >= limit:
            return
        if x == b:
            paths.append(list(acc))
            return
        for l in sorted(out_by.get(x, []), key=_rank):
            if dist.get(l["to"]) == dist[x] + 1 and dist[l["to"]] <= dist[b]:
                acc.append(l)
                dfs(l["to"], acc)
                acc.pop()

    dfs(a, [])
    return paths


def path_lines(root, a_ref, b_ref):
    nodes_list = load_nodes(root)
    a, b = resolve_node(root, a_ref, nodes_list), resolve_node(root, b_ref, nodes_list)
    nodes = {n["id"]: n for n in nodes_list}
    paths = find_paths(root, a["id"], b["id"])
    if not paths:
        return ["Цепочки от %s к %s на карте нет." % (node_label(a), node_label(b))]
    out = ["Кратчайшие цепочки от %s к %s: %d." % (node_label(a), node_label(b), len(paths))]
    for i, p in enumerate(paths, 1):
        flips = sum(1 for l in p if l["sign"] == "ослабляет")
        total = "ослабляет" if flips % 2 else "усиливает"
        unproven = [l["id"] for l in p if l["status"] != L_ACTIVE]
        out.append("Цепочка %d, длина %d, в итоге %s%s:" % (
            i, len(p), total, ", есть звенья без доказательств: %s" % ", ".join(unproven) if unproven else ""))
        for l in p:
            out.append("  " + link_line(root, l, nodes))
    return out


# ---------------------------------------------------------------- проверка

def find_cycles(links):
    out_by = {}
    for l in links:
        out_by.setdefault(l["from"], []).append(l["to"])
    cycles, seen_keys = [], set()

    def dfs(x, stack):
        for y in sorted(out_by.get(x, [])):
            if y in stack:
                cyc = stack[stack.index(y):]
                key = tuple(sorted(cyc))
                if key not in seen_keys:
                    seen_keys.add(key)
                    cycles.append(cyc + [y])
            elif len(stack) < 12:
                dfs(y, stack + [y])

    for s in sorted(out_by):
        dfs(s, [s])
    return cycles


def check(root):
    """Возвращает [(раздел, [строки], это_проблема)]."""
    nodes = {n["id"]: n for n in load_nodes(root)}
    links = [l for l in load_links(root) if l["status"] != L_RETIRED]
    recs = {r["id"]: r for r in kbase.load_records(root)}
    res = []
    sec = []
    for l in links:
        for i in l.get("evidence", []):
            r = recs.get(i)
            if r is None:
                sec.append("%s: записи %s нет в базе знаний. Уберите её или найдите замену: map link add с другой записью." % (l["id"], i))
            elif r["status"] != kbase.R_ACTIVE:
                sec.append("%s: запись %s %s. %s" % (l["id"], i, r["status"],
                           "Связь стала гипотезой: найдите действующую запись и добавьте её (map link add ... --evidence)."
                           if l["status"] == L_HYPOTHESIS else "У связи есть другие действующие записи."))
    res.append(("Связи с отозванными или отсутствующими записями", sec, True))
    used = {l["from"] for l in links} | {l["to"] for l in links}
    res.append(("Узлы без связей", ["%s. Свяжите или уберите из работы." % node_label(n) for n in nodes.values()
                                    if n["id"] not in used], True))
    sec = []
    seen = set()
    for l in links:
        for m in links:
            if l["from"] == m["from"] and l["to"] == m["to"] and l["sign"] != m["sign"] and l["id"] < m["id"] \
                    and (l["id"], m["id"]) not in seen:
                seen.add((l["id"], m["id"]))
                la, lb = l.get("layer"), m.get("layer")
                tail = ""
                if la and lb and la != lb:
                    near = l if la < lb else m
                    tail = " Ближе к продукту связь %s (%s): ей можно верить больше, вторую проверьте по условиям." % (near["id"], lw(min(la, lb)))
                elif la and lb:
                    tail = " Данные одинаково близки: сравните условия и источники."
                sec.append("%s (%s; данные: %s) и %s (%s; данные: %s): между %s и %s утверждается противоположное.%s" % (
                    l["id"], l["sign"], lw(la), m["id"], m["sign"], lw(lb), l["from"], l["to"], tail))
    res.append(("Противоречащие друг другу связи", sec, True))
    sec = []
    for l in links:
        against = [i for i in l.get("contradicted_by", []) if i in recs and recs[i]["status"] == kbase.R_ACTIVE]
        pro = [i for i in l.get("evidence", []) if i in recs and recs[i]["status"] == kbase.R_ACTIVE]
        if against and pro:
            sec.append("%s (%s -> %s): подтверждают записи %s, а возражают записи %s. Сравните условия и источники, при необходимости "
                       "сузьте условия связи или отзовите её." % (l["id"], l["from"], l["to"], ", ".join(pro), ", ".join(against)))
    res.append(("Связи, у которых есть и подтверждающие, и возражающие записи", sec, True))
    cyc = find_cycles(links)
    res.append(("Циклы (справочно, не ошибка: обратные связи бывают)",
                [" -> ".join(c) for c in cyc], False))
    return res


# ---------------------------------------------------------------- экспорт

def export_mermaid(root, around=None, depth=2):
    nodes_list = load_nodes(root)
    nodes = {n["id"]: n for n in nodes_list}
    links = [l for l in load_links(root) if l["status"] != L_RETIRED]
    keep = set(nodes)
    if around:
        c = resolve_node(root, around, nodes_list)
        keep = {c["id"]}
        frontier = {c["id"]}
        for _ in range(max(depth, 0)):
            nxt = set()
            for l in links:
                if l["from"] in frontier or l["to"] in frontier:
                    nxt |= {l["from"], l["to"]}
            frontier = nxt - keep
            keep |= nxt
    lines = ["flowchart LR"]

    def q(t):
        return t.replace('"', "'")

    shapes = {"показатель": ("([", "])"), "фактор": ("[", "]"), "действие": ("{{", "}}")}
    for nid in sorted(keep):
        n = nodes[nid]
        o, c = shapes[n["kind"]]
        lines.append('  %s%s"%s"%s' % (nid, o, q(n["name"]), c))
    for l in links:
        if l["from"] in keep and l["to"] in keep:
            if l["status"] == L_ACTIVE:
                lines.append('  %s -->|"%s, %s"| %s' % (l["from"], l["sign"], lw(l["layer"]), l["to"]))
            else:
                lines.append('  %s -.->|"%s, гипотеза, не доказана"| %s' % (l["from"], l["sign"], l["to"]))
    path = mdir(root) / "map.mmd"
    write_text_atomic(path, "\n".join(lines) + "\n")
    return path
