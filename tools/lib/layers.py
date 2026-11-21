# -*- coding: utf-8 -*-
"""Слои близости доказательств: 1 данные продукта, 2 данные компании, 3 отрасль в стране, 4 отрасль в мире, 5 смежные отрасли."""
from .common import STATUS_OK, STATUS_REPLACED, LAYER_RU
from .sources import list_sources, source_layer
from .ledger import load_claims, load_conclusions, load_levers, unproven_calcs
from . import kb as kbase

EVIDENCE_TYPES = ("fact", "calc", "benchmark")


def claim_layers(proj):
    """Слой каждого утверждения. Факт и расчёт наследуют слой источника, ориентир берёт самый близкий слой записи.
    У гипотез, прогнозов, планов, допущений, synthetic и agent слоя нет. Нет его и у расчёта на допущениях:
    такой расчёт ничего не доказывает о продукте."""
    metas = {m["id"]: m for m in list_sources(proj)}
    recs = {r["id"]: r for r in kbase.load_records(proj.root)}
    shaky = unproven_calcs(proj)
    out = {}
    for c in load_claims(proj):
        if c["id"] in shaky:
            continue
        if c["type"] in ("fact", "calc"):
            m = metas.get(c.get("source"))
            lay = source_layer(m) if m else None
            if lay:
                out[c["id"]] = lay
        elif c["type"] == "benchmark":
            ls = [recs[b].get("layer") or 5 for b in c.get("kb", []) if b in recs]
            if ls:
                out[c["id"]] = min(ls)
    return out


def evidence_ids(ids, claims, concl, seen=None):
    """Утверждения-доказательства (факт, расчёт, ориентир), на которых прямо или через выводы держится набор оснований."""
    seen = seen if seen is not None else set()
    found = set()
    for g in ids:
        if g in seen:
            continue
        seen.add(g)
        if g in claims:
            if claims[g]["type"] in EVIDENCE_TYPES and claims[g]["status"] == STATUS_OK:
                found.add(g)
        elif g in concl:
            found |= evidence_ids(concl[g].get("rests_on", []), claims, concl, seen)
    return found


def word(n):
    return "слой %s (%s)" % (n, LAYER_RU[n]) if n else "без слоя"


def conclusion_layer(k, claims, concl, lm):
    """Слой самого близкого доказательства вывода или None."""
    ls = [lm[c] for c in evidence_ids(k.get("rests_on", []), claims, concl) if c in lm]
    return min(ls) if ls else None


def support_counts(proj):
    claims = {c["id"]: c for c in load_claims(proj)}
    lm = claim_layers(proj)
    used = set()
    for k in load_conclusions(proj):
        if k["status"] == STATUS_OK:
            used.update(k.get("rests_on", []))
    for lv in load_levers(proj):
        if lv.get("status", STATUS_OK) == STATUS_OK:
            used.update(lv.get("rests_on", []))
    counts = {n: 0 for n in range(1, 6)}
    for g in used:
        c = claims.get(g)
        if c and c["type"] in EVIDENCE_TYPES and c["status"] == STATUS_OK and g in lm:
            counts[lm[g]] += 1
    return counts


def support_line(counts):
    return "Опора: " + ", ".join("слой %d: %d" % (n, counts[n]) for n in range(1, 6))
