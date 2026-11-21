# -*- coding: utf-8 -*-
"""База знаний отрасли: записи-ориентиры с источником, датой и статусом. Лежит в knowledge/, отдельно от проектов."""
import re
import urllib.parse
from pathlib import Path

from .common import (LAYER_RU, LAYER_HELP, check_layer, Fail, today, parse_date, period_start, period_end, parse_period, now_iso, sha256_bytes, write_text_atomic, write_json, read_json,
                     read_jsonl, write_jsonl, append_jsonl, read_text, normalize_copy, next_id, quote_in_text,
                     numbers_in, split_ids, short, is_inside, norm_match)
from .sources import _read_text_file, fetch_url, domain_allowed, domain_of

STRENGTHS = ["независимый-замер", "данные-компании", "мнение"]
STRENGTH_RANK = {"независимый-замер": 3, "данные-компании": 2, "мнение": 1}
KINDS = ["правило", "наблюдение", "урок"]
R_ACTIVE, R_RETIRED, R_REPLACED = "действует", "отозвана", "заменена"
DEFAULT_KB_FRESH = 1095


def kdir(root):
    return Path(root) / "knowledge"


def load_records(root):
    return read_jsonl(kdir(root) / "records.jsonl")


def save_records(root, rows):
    write_jsonl(kdir(root) / "records.jsonl", rows)


def get_record(root, bid):
    for r in load_records(root):
        if r["id"] == bid:
            return r
    raise Fail("Записи %s нет в базе знаний. Поиск: python3 tools/rychag.py kb search \"слова\"" % bid)


def active_count(root):
    return sum(1 for r in load_records(root) if r["status"] == R_ACTIVE)


def kb_fresh_days(cfg):
    return int(cfg["sources"].get("kb_freshness_days", DEFAULT_KB_FRESH))


# ---------------------------------------------------------------- источники базы

def list_kb_sources(root):
    d = kdir(root) / "sources"
    out = []
    if d.is_dir():
        for p in sorted(d.glob("KS*.meta.json")):
            m = read_json(p)
            if isinstance(m, dict) and m.get("id"):
                out.append(m)
    return out


def kb_source_text(root, ksid):
    p = kdir(root) / "sources" / (ksid + ".txt")
    if not p.exists():
        raise Fail("Нет копии knowledge/sources/%s.txt. Добавьте источник заново: kb source add." % ksid)
    return p.read_text(encoding="utf-8")


def store_source(root, text, url=None, path=None, published=None, title=None):
    """Сохраняет копию. Возвращает (meta, создан_ли_новый). Одинаковый текст второй раз не сохраняется."""
    text = normalize_copy(text)
    if not text.strip():
        raise Fail("В источнике нет текста: копия пустая.")
    if published:
        if period_start(published) > today():
            raise Fail("Дата публикации %s в будущем." % published)
    digest = sha256_bytes(text.encode("utf-8"))
    existing = list_kb_sources(root)
    for m in existing:
        if m.get("sha256") == digest or (url and m.get("url") == url):
            return m, False
    ksid = next_id("KS", [m["id"] for m in existing])
    write_text_atomic(kdir(root) / "sources" / (ksid + ".txt"), text)
    meta = {"id": ksid, "url": url, "path": path, "title": title or short(text.splitlines()[0], 80),
            "published": published or None, "accessed": today().isoformat(), "sha256": digest, "added": now_iso()}
    write_json(kdir(root) / "sources" / (ksid + ".meta.json"), meta)
    return meta, True


def _file_in_repo(root, raw):
    p = Path(raw)
    if not p.is_absolute():
        c = Path.cwd() / raw
        p = c if c.exists() else Path(root) / raw
    if not p.is_file():
        raise Fail("Файл %s не найден." % raw)
    if not is_inside(p, root):
        raise Fail("Файл %s лежит вне репозитория. Положите копию внутрь папки репозитория." % raw)
    return p.resolve()


def add_source(root, cfg, url, text_file=None, fetch=False, published=None, title=None):
    parsed = urllib.parse.urlparse(url or "")
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise Fail("Адрес «%s» не подходит: нужен полный адрес вида https://сайт/страница." % url)
    allow = cfg["sources"]["allowlist"]
    if not domain_allowed(url, allow):
        raise Fail("Сайт %s не в разрешённом списке (config/sources.json)." % domain_of(url))
    if bool(fetch) == bool(text_file):
        raise Fail("Нужно одно из двух: --text-file или --fetch.")
    if fetch:
        text, page_title = fetch_url(url)
    else:
        text, page_title = _read_text_file(_file_in_repo(root, text_file))
    meta, created = store_source(root, text, url=url, published=published, title=title or page_title or None)
    if not created:
        raise Fail("Такой источник уже сохранён как %s." % meta["id"])
    return meta


# ---------------------------------------------------------------- записи

def _clean_list(v):
    if isinstance(v, str):
        v = re.split(r"[,;]", v)
    return [x.strip() for x in (v or []) if str(x).strip()]


def create_record(root, f):
    """f: rule, applies_when, not_when, themes, tags, place, source, quote, number, strength, kind."""
    kind = f.get("kind") or "правило"
    if kind not in KINDS:
        raise Fail("Вид записи: %s." % ", ".join(KINDS))
    strength = f.get("strength") or ("мнение" if kind == "урок" else None)
    if strength not in STRENGTHS:
        raise Fail("Сила записи: %s." % ", ".join(STRENGTHS))
    layer = check_layer(f.get("layer"), 2, 5) if f.get("layer") not in (None, "") else None
    if layer is None:
        raise Fail("Не указан слой близости (--layer 2..5). Слои: %s. Слой 1 в общей базе знаний не хранится: он принадлежит проекту." % LAYER_HELP)
    rule = (f.get("rule") or "").strip()
    when = (f.get("applies_when") or "").strip()
    themes = _clean_list(f.get("themes"))
    if not rule or not when or not themes:
        raise Fail("Нужны правило (--rule), условие применимости (--applies-when) и хотя бы одна тема (--theme).")
    source = f.get("source")
    quote = f.get("quote")
    pub = None
    if kind != "урок":
        if not source or not quote:
            raise Fail("Запись без источника и дословной цитаты не принимается. Нужны --source KS001 и --quote. "
                       "Собственный урок агента записывается с --kind урок.")
        if not (f.get("place") or "").strip():
            raise Fail("Не указано место (--place \"страна, компания\").")
        meta = next((m for m in list_kb_sources(root) if m["id"] == source), None)
        if meta is None:
            raise Fail("Источника %s нет. Добавьте: kb source add --url ... --text-file ..." % source)
        if not quote_in_text(quote, kb_source_text(root, source)):
            raise Fail("Цитата не найдена в %s. Скопируйте фрагмент дословно из knowledge/sources/%s.txt "
                       "(регистр, пробелы и кавычки не важны). Начало цитаты: «%s»." % (source, source, short(quote, 50)))
        pub = meta.get("published")
    else:
        source, quote = None, None
        pub = today().isoformat()
    number = f.get("number")
    if number and quote and not (numbers_in(number) <= numbers_in(quote)):
        raise Fail("Число «%s» не встречается в цитате. Запись держит только то, что есть в цитате." % number)
    rows = load_records(root)
    key = norm_match(rule)
    for r in rows:
        if norm_match(r["rule"]) == key and r.get("source") == source and r.get("quote") == quote:
            raise Fail("Такая запись уже есть: %s." % r["id"])
    rec = {"id": next_id("B", [r["id"] for r in rows]), "rule": rule, "applies_when": when,
           "not_when": (f.get("not_when") or "").strip(), "themes": themes, "tags": _clean_list(f.get("tags")),
           "place": (f.get("place") or "").strip(), "kind": kind, "strength": strength, "layer": layer, "source": source,
           "quote": quote, "number": number, "date_published": pub, "status": R_ACTIVE, "status_date": None,
           "status_reason": None, "replaced_by": None, "links": [], "created": today().isoformat()}
    for extra in ("origin", "grounds", "human_words"):
        if f.get(extra):
            rec[extra] = f[extra]
    append_jsonl(kdir(root) / "records.jsonl", rec)
    return rec


REQUIRED_IMPORT = ("rule", "applies_when", "themes", "strength")


def import_records(root, jsonl_path, sources_dir, warnings=None):
    """Возвращает (принято, [(номер строки, причина)]). Предупреждения (пустая дата) дописываются в список warnings."""
    jp = Path(jsonl_path)
    sd = Path(sources_dir)
    if not jp.is_file():
        raise Fail("Файл импорта %s не найден." % jsonl_path)
    if not sd.is_dir():
        raise Fail("Папка с текстами %s не найдена." % sources_dir)
    accepted, rejected = 0, []
    rej_path = kdir(root) / "rejected.jsonl"
    for n, line in enumerate(jp.read_text(encoding="utf-8").split("\n"), 1):
        if not line.strip():
            continue
        try:
            rec = __import__("json").loads(line)
            if not isinstance(rec, dict):
                raise ValueError
        except ValueError:
            rejected.append((n, "строка не является объектом JSON"))
            append_jsonl(rej_path, {"line": n, "raw": line, "reason": rejected[-1][1], "ts": now_iso()})
            continue
        try:
            kind = rec.get("kind") or "правило"
            if rec.get("layer") in (None, ""):
                raise Fail("нет поля layer (слой близости 2..5)")
            for k in REQUIRED_IMPORT:
                if not rec.get(k) and not (k == "strength" and kind == "урок"):
                    raise Fail("нет поля %s" % k)
            f = {"rule": rec.get("rule"), "applies_when": rec.get("applies_when"), "not_when": rec.get("not_when"),
                 "themes": rec.get("themes"), "tags": rec.get("tags"), "place": rec.get("place"),
                 "quote": rec.get("quote"), "number": rec.get("number"), "strength": rec.get("strength"), "kind": kind,
                 "layer": rec.get("layer")}
            if kind != "урок":
                sf = rec.get("source_file")
                if not sf or not rec.get("quote"):
                    raise Fail("нет source_file или quote")
                fp = sd / sf
                if not fp.is_file() or not is_inside(fp, sd):
                    raise Fail("в папке %s нет файла %s" % (sources_dir, sf))
                text, _t = _read_text_file(fp)
                text = normalize_copy(text)
                if not quote_in_text(rec["quote"], text):
                    raise Fail("цитата не найдена в %s" % sf)
                if rec.get("date_published"):
                    parse_period(rec["date_published"])
                elif warnings is not None:
                    warnings.append((n, "нет даты публикации, свежесть не проверить"))
                meta, _c = store_source(root, text, url=rec.get("url"), path=sf,
                                        published=rec.get("date_published"), title=rec.get("title"))
                f["source"] = meta["id"]
            create_record(root, f)
            accepted += 1
        except Fail as e:
            rejected.append((n, str(e)))
            append_jsonl(rej_path, {"line": n, "record": rec, "reason": str(e), "ts": now_iso()})
    return accepted, rejected


# ---------------------------------------------------------------- статусы и связи

def _save_changed(root, rec):
    rows = load_records(root)
    for i, r in enumerate(rows):
        if r["id"] == rec["id"]:
            rows[i] = rec
    save_records(root, rows)


def retire(root, bid, reason):
    if not (reason or "").strip():
        raise Fail("Нужна причина: --reason \"почему отзываем\".")
    r = get_record(root, bid)
    r.update(status=R_RETIRED, status_date=today().isoformat(), status_reason=reason.strip())
    _save_changed(root, r)
    return r


def replace(root, bid, by, reason=None):
    r = get_record(root, bid)
    new = get_record(root, by)
    if bid == by:
        raise Fail("Запись нельзя заменить самой собой.")
    if new["status"] != R_ACTIVE:
        raise Fail("Замена %s не действует. Выберите действующую запись." % by)
    r.update(status=R_REPLACED, status_date=today().isoformat(), replaced_by=by,
             status_reason=(reason or "").strip() or "заменена записью %s" % by)
    _save_changed(root, r)
    return r


def link(root, a, b, note=None):
    if a == b:
        raise Fail("Запись нельзя связать с самой собой.")
    ra, rb = get_record(root, a), get_record(root, b)
    for x, y in ((ra, b), (rb, a)):
        if not any(l["id"] == y for l in x["links"]):
            x["links"].append({"id": y, "note": (note or "").strip()})
    _save_changed(root, ra)
    _save_changed(root, rb)


def stale_records(root, cfg):
    out = []
    limit = kb_fresh_days(cfg)
    metas = {m["id"]: m for m in list_kb_sources(root)}
    for r in load_records(root):
        if r["status"] != R_ACTIVE:
            continue
        if r.get("source") and (r["source"] not in metas or not (kdir(root) / "sources" / (r["source"] + ".txt")).exists()):
            out.append((r, "нет файла источника %s" % r["source"]))
            continue
        if r.get("date_published"):
            age = (today() - period_end(r["date_published"])).days
            if age > limit:
                out.append((r, "старше порога: %s, %d дн. при пороге %d" % (r["date_published"], age, limit)))
    return out


# ---------------------------------------------------------------- индекс

def line_of(r):
    return "%s | %s | %s | %s | %s | слой %s" % (r["id"], r["rule"], r.get("place") or "собственный урок",
                                              r.get("date_published") or "дата неизвестна", r["strength"], r.get("layer"))


def build_index(root):
    recs = [r for r in load_records(root) if r["status"] == R_ACTIVE]
    lines = ["# Индекс базы знаний", "",
             "Создаётся командой `kb index`, руками не правится. Записи это ориентиры: они подсказывают гипотезы и "
             "варианты и никогда не являются фактами о продукте.", "",
             "Формат строки: код | правило | место | дата | сила | слой близости.", ""]
    if not recs:
        lines.append("Записей пока нет.")
    groups = {}
    for r in recs:
        groups.setdefault(r["themes"][0], []).append(r)
    for t in sorted(groups):
        lines += ["## " + t, ""]
        lines += ["- " + line_of(r) for r in sorted(groups[t], key=lambda x: x["id"])]
        lines.append("")
    write_text_atomic(kdir(root) / "INDEX.md", "\n".join(lines).rstrip() + "\n")
    return len(recs)


# ---------------------------------------------------------------- поиск

def _words(text):
    return re.findall(r"[a-zа-я0-9]+", (text or "").lower().replace("ё", "е"))


STOP_WORDS = {"для", "при", "как", "что", "это", "или", "его", "они", "над", "под", "про", "без", "все", "так", "уже",
              "еще", "чем", "где", "когда", "если", "есть", "быть", "был", "была", "было", "были", "она", "оно", "нас",
              "вас", "них", "кто", "тот", "эти", "этот", "эта", "того", "свой", "своих", "также", "только", "может",
              "можно", "чтобы", "между", "после", "перед", "который", "которые", "которая", "которое", "надо", "нужно"}


def _stem(w):
    if len(w) <= 3:
        return w
    if len(w) == 4:
        return w[:3]
    return w[:max(5, len(w) - 2)]


def _same(a, b):
    """Слова до трёх букв совпадают только целиком. Четырёхбуквенные сравниваются по первым трём буквам, длинные по прежнему правилу."""
    if len(a) <= 3 or len(b) <= 3:
        return a == b
    return b.startswith(_stem(a)) or a.startswith(_stem(b))


def query_terms(query):
    """Значимые слова запроса без повторов: без слов из одной-двух букв и без служебных слов."""
    seen, out = set(), []
    for w in _words(query):
        if len(w) <= 2 or w in STOP_WORDS or w in seen:
            continue
        seen.add(w)
        out.append(w)
    return out


def need_terms(n):
    """Сколько слов запроса должна совпасть записи: все при одном-двух словах, иначе не меньше половины."""
    return n if n <= 2 else (n + 1) // 2


def load_synonyms(root):
    d = read_json(Path(root) / "config" / "synonyms.json", {}) or {}
    return [[_w for x in g for _w in _words(x)] for g in d.get("groups", []) if isinstance(g, list)]


def _expand(term, groups):
    alts = {term}
    for g in groups:
        if any(_same(term, w) for w in g):
            alts.update(g)
    return alts


def search_ranked(root, query, theme=None, tag=None, related=None, limit=10, include_inactive=False):
    """Возвращает (результаты [(запись, совпало слов)], число слов запроса, ближайшие три без допуска).
    Допуск: совпала хотя бы половина значимых слов (все, если их одно-два). Порядок: слой, совпавшие слова, сила, дата."""
    rows = load_records(root)
    if related:
        rel = get_record(root, related)
        ids = {l["id"] for l in rel["links"]}
        rows = [r for r in rows if r["id"] in ids]
    if theme:
        t = norm_match(theme)
        rows = [r for r in rows if any(norm_match(x) == t for x in r["themes"])]
    if tag:
        t = norm_match(tag)
        rows = [r for r in rows if any(norm_match(x) == t for x in r["tags"])]
    if not include_inactive:
        rows = [r for r in rows if r["status"] == R_ACTIVE]
    terms = query_terms(query)
    if not terms:
        rows = sorted(rows, key=lambda r: (r.get("date_published") or "", r["id"]), reverse=True)
        rows = sorted(rows, key=lambda r: (r.get("layer") or 5, -STRENGTH_RANK[r["strength"]]))
        return [(r, 0) for r in rows[:limit]], 0, []
    groups = load_synonyms(root)
    alts = [_expand(t, groups) for t in terms]
    need = need_terms(len(terms))
    hits = []
    for r in rows:
        toks = _words(" ".join([r["rule"], r["applies_when"], " ".join(r["tags"]), r.get("quote") or ""]))
        hit = sum(1 for al in alts if any(_same(a, tk) for a in al for tk in toks))
        if hit:
            hits.append((hit, r))

    def key(x):
        r = x[1]
        return (r.get("layer") or 5, -x[0], -STRENGTH_RANK[r["strength"]], _neg(r.get("date_published") or ""), r["id"])

    good = sorted([x for x in hits if x[0] >= need], key=key)
    if good:
        return [(r, h) for h, r in good[:limit]], len(terms), []
    near = sorted(hits, key=lambda x: (-x[0], x[1].get("layer") or 5, -STRENGTH_RANK[x[1]["strength"]], x[1]["id"]))[:3]
    return [], len(terms), [(r, h) for h, r in near]


def _neg(date):
    """Ключ для порядка «новее раньше» внутри сортировки по возрастанию."""
    return tuple(-ord(ch) for ch in date)


def search(root, query, theme=None, tag=None, related=None, limit=10, include_inactive=False):
    res, _n, _near = search_ranked(root, query, theme, tag, related, limit, include_inactive)
    return [r for r, _h in res]


def show_lines(r):
    out = ["%s [%s, %s]" % (r["id"], r["kind"], r["status"]),
           "Правило: " + r["rule"], "Применимо, когда: " + r["applies_when"]]
    if r["not_when"]:
        out.append("Не применимо, когда: " + r["not_when"])
    out.append("Темы: %s. Метки: %s." % (", ".join(r["themes"]), ", ".join(r["tags"]) or "нет"))
    out.append("Слой близости: %s (%s)." % (r.get("layer"), LAYER_RU.get(r.get("layer"), "не указан")))
    out.append("Место: %s. Дата: %s. Сила: %s." % (r.get("place") or "собственный урок", r.get("date_published") or "неизвестна", r["strength"]))
    if r.get("source"):
        out.append("Источник: %s (knowledge/sources/%s.txt). Цитата: «%s»" % (r["source"], r["source"], r["quote"]))
    if r.get("number"):
        out.append("Число: " + str(r["number"]))
    if r["status"] != R_ACTIVE:
        out.append("Статус с %s: %s%s" % (r["status_date"], r["status_reason"],
                                          ", заменена на %s" % r["replaced_by"] if r.get("replaced_by") else ""))
    if r["links"]:
        out.append("Связи: " + "; ".join("%s%s" % (l["id"], " (%s)" % l["note"] if l["note"] else "") for l in r["links"]))
    out.append("Это ориентир, а не факт о продукте.")
    return out


def short_line(r):
    return "%s: %s. Слой %s (%s), %s, %s, сила %s, статус %s" % (
        r["id"], r["rule"], r.get("layer"), LAYER_RU.get(r.get("layer"), "не указан"), r.get("place") or "собственный урок",
        r.get("date_published") or "дата неизвестна", r["strength"], r["status"])
