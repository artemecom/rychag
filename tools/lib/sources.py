# -*- coding: utf-8 -*-
"""Источники: сохранение копии текста с датами, разрешённый список, потолок, свежесть, расчёты."""
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

from .common import (LAYER_HELP, check_layer, Fail, Project, STATUS_OK, today, parse_date, period_start, period_end, now_iso, sha256_bytes, sha256_file,
                     write_text_atomic, write_json, read_json, normalize_copy, next_id, is_inside,
                     journal, short, CALC_METHODS, read_jsonl, split_ids, numbers_in, canon_number, UNPROVEN_TYPES)

SOURCE_KINDS = ["страница", "файл", "собеседник", "агент", "расчёт", "расшифровка"]
MEDIA_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".heic", ".svg", ".pdf",
             ".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac", ".opus",
             ".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
NON_GROUND_KINDS = ("собеседник", "агент")  # не могут быть основанием факта
DEFAULT_QUESTION = "общий"


# ---------------------------------------------------------------- HTML

class _Stripper(HTMLParser):
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "ul", "ol", "table"}
    SKIP = {"script", "style", "noscript", "head", "template"}

    def __init__(self):
        HTMLParser.__init__(self, convert_charrefs=True)
        self.parts = []
        self.skip = 0
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
        if tag in self.SKIP:
            self.skip += 1
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if not self.skip:
            self.parts.append(data)


def strip_html(html):
    """Возвращает (текст, заголовок страницы)."""
    p = _Stripper()
    p.feed(html)
    p.close()
    text = "".join(p.parts)
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    return text, p.title.strip()


class _Redirect308(urllib.request.HTTPRedirectHandler):
    """Python 3.9 сам не идёт по перенаправлению 308: добавляем."""

    def http_error_308(self, req, fp, code, msg, headers):
        return self.http_error_302(req, fp, 307, msg, headers)


def _unpack(data, encoding):
    """Распаковывает сжатый ответ сервера (gzip, deflate)."""
    import gzip
    import zlib
    enc = (encoding or "").lower()
    if enc == "gzip" or data[:2] == b"\x1f\x8b":
        return gzip.decompress(data)
    if enc == "deflate":
        try:
            return zlib.decompress(data)
        except zlib.error:
            return zlib.decompress(data, -zlib.MAX_WBITS)
    return data


def _looks_like_text(body):
    """Грубая защита от мусора: в тексте почти не должно быть нечитаемых знаков."""
    if not body.strip():
        return False
    sample = body[:20000]
    bad = sum(1 for ch in sample if ch == "\ufffd" or (ord(ch) < 32 and ch not in "\n\r\t"))
    return bad / max(len(sample), 1) < 0.02


def fetch_url(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; rychag/1.0)",
        "Accept-Encoding": "gzip, identity",
        "Accept-Language": "ru,en;q=0.8",
    })
    opener = urllib.request.build_opener(_Redirect308())
    try:
        with opener.open(req, timeout=25) as r:
            data = r.read(5000001)
            charset = r.headers.get_content_charset() or "utf-8"
            ctype = r.headers.get_content_type()
            encoding = r.headers.get("Content-Encoding", "")
        if len(data) > 5000000:
            raise Fail("Страница больше 5 МБ. Сохраните нужный фрагмент в файл и используйте --text-file.")
        data = _unpack(data, encoding)
    except Fail:
        raise
    except Exception as e:  # сеть, таймаут, 404 и т.п.
        raise Fail("Не удалось скачать %s (%s). Сохраните текст страницы в файл и добавьте так: "
                   "source add --url %s --text-file файл.txt" % (url, e, url))
    try:
        body = data.decode(charset, errors="replace")
    except LookupError:
        body = data.decode("utf-8", errors="replace")
    if not _looks_like_text(body):
        raise Fail("Страница %s скачалась в нечитаемом виде. Сохраните текст страницы в файл и добавьте так: "
                   "source add --url %s --text-file файл.txt" % (url, url))
    if "html" in ctype:
        text, title = strip_html(body)
        if len(text.strip()) < 200:
            raise Fail("На странице %s почти нет текста: похоже, содержимое подгружается программой в браузере. "
                       "Сохраните текст страницы в файл и добавьте так: source add --url %s --text-file файл.txt" % (url, url))
        return text, title
    return body, ""


# ---------------------------------------------------------------- чтение

def list_sources(proj):
    out = []
    d = proj.path("sources")
    if not d.is_dir():
        return out
    for p in sorted(d.glob("S*.meta.json")):
        m = read_json(p)
        if isinstance(m, dict) and m.get("id"):
            out.append(m)
    return out


def get_source(proj, sid):
    for m in list_sources(proj):
        if m["id"] == sid:
            return m
    raise Fail("Источника %s нет. Список: python3 tools/rychag.py source list" % sid)


def source_text(proj, sid):
    p = proj.path("sources", sid + ".txt")
    if not p.exists():
        raise Fail("Нет копии %s. Добавьте источник заново командой source add." % proj.where("sources", sid + ".txt"))
    return p.read_text(encoding="utf-8")


def source_layer(meta):
    """Слой близости источника. У старых файлов без поля слой 1, у страниц без поля слоя нет."""
    if meta.get("layer"):
        return int(meta["layer"])
    return None if meta.get("kind") == "страница" else 1


def domain_of(url):
    return (urllib.parse.urlparse(url).hostname or "").lower()


def domain_allowed(url, allowlist):
    if not allowlist:
        return True
    host = domain_of(url)
    for d in allowlist:
        d = d.lower().strip().lstrip(".")
        if host == d or host.endswith("." + d):
            return True
    return False


def age_days(meta):
    if not meta.get("published"):
        return None
    return (today() - period_end(meta["published"])).days


def is_stale(meta, cfg):
    if meta.get("kind") == "расчёт" or meta.get("stale_accepted"):
        return False
    a = age_days(meta)
    return a is not None and a > cfg["sources"]["freshness_days"]


# ---------------------------------------------------------------- добавление

def _resolve_inside(proj, raw, folder, what):
    p = Path(raw)
    if not p.is_absolute():
        cand = proj.dir / raw
        if not cand.exists() and folder is not None:
            cand = folder / raw
        if not cand.exists():
            cand = Path.cwd() / raw
        p = cand
    base = folder if folder is not None else proj.dir
    if not p.exists() or not p.is_file():
        raise Fail("Файл %s не найден. Положите его в %s и повторите." % (raw, proj.where("materials")))
    if not is_inside(p, base):
        raise Fail("%s должен лежать внутри %s, а %s снаружи. Скопируйте файл туда вручную. "
                   "Команда сама ничего не копирует из чужих папок." % (what, proj.where(*([] if folder is None else ["materials"])), raw))
    return p.resolve()


def _read_text_file(path):
    try:
        raw = path.read_bytes()
        txt = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise Fail("Файл %s не в UTF-8 или не текстовый. Сохраните его как txt, md, csv или html в UTF-8." % path.name)
    if path.suffix.lower() in (".html", ".htm"):
        t, title = strip_html(txt)
        return t, title
    return txt, ""


def add_source(proj, cfg, url=None, text_file=None, file=None, kind=None, published=None,
               title=None, question=None, allow_stale=False, fetch=False, layer=None,
               period_from=None, period_to=None):
    """Сохраняет источник. Возвращает (meta, предупреждения)."""
    warnings = []
    media_sha = None
    if layer is not None:
        layer = check_layer(layer)
    if (url is None) == (file is None):
        raise Fail("Нужно одно из двух: --url (с --text-file или --fetch) либо --file.")
    scfg = cfg["sources"]
    if url is not None:
        if kind not in (None, "страница"):
            raise Fail("С --url вид источника всегда «страница». Для ответов ИИ используйте --file и --kind собеседник.")
        kind = "страница"
        if layer is None:
            raise Fail("Для страницы из сети нужен слой близости: --layer N. Слои: %s." % LAYER_HELP)
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise Fail("Адрес «%s» не подходит: нужен полный адрес вида https://сайт/страница." % url)
        if not domain_allowed(url, scfg["allowlist"]):
            raise Fail("Сайт %s не в разрешённом списке (config/sources.json, allowlist: %s). "
                       "Выберите источник из списка или попросите руководителя расширить список." % (
                           domain_of(url), ", ".join(scfg["allowlist"])))
        if fetch and text_file:
            raise Fail("Укажите что-то одно: --fetch или --text-file.")
        if not fetch and not text_file:
            raise Fail("Для --url нужен --text-file (сохранённый текст страницы) или --fetch (скачать самому).")
        if fetch:
            text, page_title = fetch_url(url)
            origin = url
        else:
            p = _resolve_inside(proj, text_file, None, "Файл с текстом")
            text, page_title = _read_text_file(p)
            origin = url
    elif Path(file).suffix.lower() in MEDIA_EXT:
        if kind not in (None, "расшифровка"):
            raise Fail("Для изображения, аудио и видео вид источника всегда «расшифровка».")
        if fetch:
            raise Fail("С --file не используется --fetch.")
        if not text_file:
            raise Fail("Файл %s это изображение, аудио, видео или PDF: программа не читает их. Добавьте --text-file с "
                       "расшифровкой или описанием (файл внутри папки проекта). Цитаты будут сверяться с ним." % file)
        kind = "расшифровка"
        mp = _resolve_inside(proj, file, proj.path("materials"), "Медиафайл")
        tp = _resolve_inside(proj, text_file, None, "Файл с расшифровкой")
        text, page_title = _read_text_file(tp)
        origin = mp.relative_to(proj.dir.resolve()).as_posix()
        media_sha = sha256_file(mp)
    else:
        kind = kind or "файл"
        if kind not in ("файл", "собеседник", "агент"):
            raise Fail("--kind для файла: файл, собеседник или агент.")
        if fetch or text_file:
            raise Fail("С --file не используются --fetch и --text-file (кроме изображений, аудио и видео).")
        p = _resolve_inside(proj, file, proj.path("materials"), "Файл-источник")
        text, page_title = _read_text_file(p)
        origin = p.relative_to(proj.dir.resolve()).as_posix()

    if layer is None:
        layer = 1  # файлы из materials/ это данные самого продукта, пока не указано иное
    pf = pt = None
    if period_from or period_to:
        if not (period_from and period_to):
            raise Fail("Период данных задаётся двумя датами: --period-from и --period-to.")
        pf, pt = period_start(period_from), period_end(period_to)
        if pf > pt:
            raise Fail("Начало периода данных %s позже конца %s." % (period_from, period_to))
        pf, pt = pf.isoformat(), pt.isoformat()
    text = normalize_copy(text)
    if not text.strip():
        raise Fail("В источнике нет текста. Проверьте файл: копия пустая.")
    if published:
        if period_start(published) > today():
            raise Fail("Дата публикации %s в будущем. Проверьте дату." % published)
        if (today() - period_end(published)).days > scfg["freshness_days"] and not allow_stale:
            raise Fail("Источник старше порога: опубликован %s, порог %d дней. Найдите свежий источник "
                       "или добавьте --allow-stale, если старые данные допустимы (это попадёт в журнал)." % (
                           published, scfg["freshness_days"]))
    else:
        warnings.append("Нет даты публикации: проверить свежесть нельзя. Добавьте --published ГГГГ-ММ-ДД, если дата известна.")

    q = question or DEFAULT_QUESTION
    existing = list_sources(proj)
    digest = sha256_bytes(text.encode("utf-8"))
    for m in existing:
        if m.get("sha256") == digest:
            raise Fail("Такой источник (тот же текст) уже сохранён как %s. Повторно не добавляю: используйте %s." % (m["id"], m["id"]))
    replaces = None
    if url:
        for m in existing:
            if m.get("url") == url and not m.get("replaced_by"):
                replaces = m["id"]
    same_q = [m for m in existing if m.get("question") == q and m.get("kind") != "расчёт" and not m.get("replaced_by")]
    if len(same_q) >= scfg["max_sources_per_question"] and not replaces:
        raise Fail("Потолок источников на вопрос «%s»: %d, уже сохранено %d. Выберите самые сильные "
                   "или поднимите max_sources_per_question в config/sources.json с согласия руководителя." % (
                       q, scfg["max_sources_per_question"], len(same_q)))

    sid = next_id("S", [m["id"] for m in existing])
    write_text_atomic(proj.path("sources", sid + ".txt"), text)
    meta = {
        "id": sid, "kind": kind,
        "url": url if url else None,
        "path": None if url else origin,
        "title": title or page_title or short(text.splitlines()[0], 80),
        "published": published or None,
        "accessed": today().isoformat(),
        "sha256": digest,
        "question": q,
        "layer": layer,
        "stale_accepted": bool(allow_stale and published),
        "added": now_iso(),
    }
    if pf:
        meta["period_from"], meta["period_to"] = pf, pt
    if replaces:
        meta["replaces"] = replaces
        old = get_source(proj, replaces)
        old["replaced_by"] = sid
        write_json(proj.path("sources", replaces + ".meta.json"), old)
        warnings.append("Страница по этому адресу изменилась: сохранена как новая версия %s, она заменяет %s. "
                        "Всё, что опирается на %s, задето: python3 tools/rychag.py impact %s --mark" % (sid, replaces, replaces, replaces))
    if kind == "расшифровка":
        meta["media_sha256"] = media_sha
        meta["transcript"] = tp.relative_to(proj.dir.resolve()).as_posix()
    write_json(proj.path("sources", sid + ".meta.json"), meta)
    journal(proj, "source add", {"id": sid, "kind": kind, "question": q, "replaces": replaces})
    return meta, warnings


def set_layer(proj, sid, layer):
    meta = get_source(proj, sid)
    old = meta.get("layer")
    meta["layer"] = check_layer(layer)
    write_json(proj.path("sources", sid + ".meta.json"), meta)
    journal(proj, "source set-layer", {"id": sid, "from": old, "to": meta["layer"]})
    return meta


def accept_stale(proj, sid, reason):
    meta = get_source(proj, sid)
    meta["stale_accepted"] = True
    meta["stale_reason"] = reason
    write_json(proj.path("sources", sid + ".meta.json"), meta)
    journal(proj, "source accept-stale", {"id": sid, "reason": reason})
    return meta


# ---------------------------------------------------------------- расчёты

def _find_in_project(proj, raw, folders):
    p = Path(raw)
    cands = [p] if p.is_absolute() else [proj.dir / raw] + [proj.dir / f / raw for f in folders]
    for c in cands:
        if c.exists() and c.is_file():
            if not is_inside(c, proj.dir):
                raise Fail("Файл %s лежит вне папки проекта. Расчёт читает только файлы проекта." % raw)
            return c.resolve()
    raise Fail("Файл %s не найден в проекте (искали в %s)." % (raw, ", ".join(folders) or "корне проекта"))


def check_rests_on(proj, rests_on):
    """Записи реестра, на которые опирается расчёт: должны существовать и действовать. Возвращает (коды, записи)."""
    ids = split_ids(rests_on) if isinstance(rests_on, str) else list(rests_on or [])
    claims = {c["id"]: c for c in read_jsonl(proj.path("ledger", "claims.jsonl"))}
    for i in ids:
        if i not in claims:
            raise Fail("В --rests-on указано %s, но такого утверждения нет. Список: python3 tools/rychag.py claim list" % i)
        if claims[i]["status"] != STATUS_OK:
            raise Fail("Запись %s не действует (статус «%s»): расчёт на ней строить нельзя." % (i, claims[i]["status"]))
    return ids, [claims[i] for i in ids]


def _claim_numbers(c):
    rng = c.get("range") or {}
    return numbers_in(" ; ".join(str(rng.get(k) or "") for k in ("low", "base", "high"))) | numbers_in(c.get("number") or "") \
        | numbers_in(c.get("text") or "") | numbers_in(c.get("quote") or "")


def run_ready(proj, kind, params_file, rests_on, question=None):
    """Готовый расчёт: формулы в программе, параметры в файле JSON задачи. Возвращает (meta, вывод, предупреждения)."""
    from . import calcs
    if kind not in calcs.KINDS:
        raise Fail("Готового расчёта «%s» нет. Есть: %s. Подробнее: python3 tools/rychag.py calc list" % (kind, ", ".join(calcs.KINDS)))
    ids, grounds = check_rests_on(proj, rests_on)
    if not ids:
        raise Fail("Укажите, на какие записи реестра опираются параметры: --rests-on C001,C002. Число из брифа это fact, "
                   "ваш выбор это plan, значение до проверки это assumption. Параметров «из головы» в расчёте быть не должно.")
    pp = _find_in_project(proj, params_file, ["analysis", "materials"])
    if pp.suffix.lower() != ".json":
        raise Fail("Файл параметров должен быть файлом .json. Образец: python3 tools/rychag.py calc template %s" % kind)
    params = read_json(pp)
    out = normalize_copy("\n".join(calcs.compute(kind, params)))
    warns = []
    known = set()
    for c in grounds:
        known |= _claim_numbers(c)
    stray = sorted(calcs.param_numbers(params) - known - {"0"}, key=lambda x: float(x))
    if stray:
        warns.append("Чисел параметров нет в записях из --rests-on: %s. Откуда они? Число из материалов запишите как fact, свой выбор как plan, "
                     "значение до проверки как assumption и повторите расчёт с этими записями." % ", ".join(stray[:12]))
    weak = [c["id"] for c in grounds if c["type"] in UNPROVEN_TYPES]
    existing = list_sources(proj)
    digest = sha256_bytes(out.encode("utf-8"))
    rel = pp.relative_to(proj.dir.resolve()).as_posix()
    for m in existing:
        if m.get("ready") == kind and m.get("sha256") == digest and (m.get("inputs") or [{}])[0].get("path") == rel \
                and m.get("rests_on") == ids:
            return m, out, ["Такой расчёт с теми же параметрами уже сохранён как %s. Повторно не записываю." % m["id"]]
    sid = next_id("S", [m["id"] for m in existing])
    write_text_atomic(proj.path("sources", sid + ".txt"), out)
    meta = {
        "id": sid, "kind": "расчёт", "url": None, "path": None, "layer": 1,
        "title": "Готовый расчёт «%s» (%s)" % (kind, pp.name),
        "published": today().isoformat(), "accessed": today().isoformat(),
        "sha256": digest, "question": question or DEFAULT_QUESTION,
        "stale_accepted": False, "added": now_iso(), "method": "расчёт",
        "ready": kind, "script": None, "script_sha256": None,
        "inputs": [{"path": rel, "sha256": sha256_file(pp)}],
        "rests_on": ids,
    }
    write_json(proj.path("sources", sid + ".meta.json"), meta)
    journal(proj, "calc ready", {"id": sid, "kind": kind, "params": rel, "rests_on": ids})
    if weak:
        warns.append("Расчёт стоит на допущениях (%s): его числа в page.md и document.md идут только в строке со словом «допущение» или «оценка»." % ", ".join(weak))
    return meta, out, warns


def ready_recheck(proj, meta):
    """Повторяет готовый расчёт по сохранённым параметрам. Возвращает None, если вывод совпал, иначе текст замечания."""
    from . import calcs
    inp = (meta.get("inputs") or [{}])[0].get("path")
    if not inp or not proj.path(inp).exists():
        return "нет файла параметров %s" % inp
    try:
        out = normalize_copy("\n".join(calcs.compute(meta.get("ready"), read_json(proj.path(inp)))))
    except Fail as e:
        return "готовый расчёт не повторяется: %s" % e
    if sha256_bytes(out.encode("utf-8")) != meta.get("sha256"):
        return "повторный расчёт дал другой вывод, чем сохранён"
    return None


def write_template(proj, kind, out=None):
    """Кладёт образец файла параметров готового расчёта в analysis/. Существующий файл не перезаписывает."""
    from . import calcs
    if kind not in calcs.KINDS:
        raise Fail("Готового расчёта «%s» нет. Есть: %s." % (kind, ", ".join(calcs.KINDS)))
    rel = out or "analysis/%s.json" % calcs.KINDS[kind]["file"]
    path = proj.dir / rel
    if not is_inside(path, proj.path("analysis")) or path.suffix.lower() != ".json":
        raise Fail("Файл параметров кладётся в %s и имеет расширение .json. Получено «%s»." % (proj.where("analysis"), rel))
    if path.exists():
        raise Fail("Файл %s уже есть. Чтобы не затереть ваши числа, образец туда не пишу: укажите другое имя через --out." % proj.where(rel))
    write_json(path, calcs.KINDS[kind]["template"])
    return rel


def run_calc(proj, script, inputs, question=None, timeout=120, method=None, rests_on=None):
    """Запускает скрипт из analysis/, сохраняет вывод как источник вида «расчёт»."""
    method = method or "расчёт"
    if method not in CALC_METHODS:
        raise Fail("Способ счёта: %s." % ", ".join(CALC_METHODS))
    grounds_ids, _grounds = check_rests_on(proj, rests_on)
    sp = _find_in_project(proj, script, ["analysis"])
    if not is_inside(sp, proj.path("analysis")):
        raise Fail("Скрипт должен лежать в %s. Положите его туда." % proj.where("analysis"))
    if sp.suffix != ".py":
        raise Fail("Скрипт расчёта должен быть файлом .py.")
    in_paths = [_find_in_project(proj, i, ["materials", "analysis"]) for i in inputs]
    # Чистая среда: никакие переменные окружения (в том числе секреты) в расчёт не передаются.
    env = {"PATH": "/usr/bin:/bin", "PYTHONIOENCODING": "utf-8", "PYTHONHASHSEED": "0", "LC_ALL": "C.UTF-8"}
    try:
        r = subprocess.run([sys.executable, "-I", str(sp)] + [str(p) for p in in_paths], cwd=str(proj.dir),
                           env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise Fail("Расчёт идёт дольше %d секунд и остановлен. Упростите скрипт." % timeout)
    out = r.stdout.decode("utf-8", errors="replace")
    if r.returncode != 0:
        err = r.stderr.decode("utf-8", errors="replace").strip().splitlines()[-5:]
        raise Fail("Скрипт %s завершился с ошибкой (код %d):\n  %s\nИсправьте скрипт и запустите снова." % (
            sp.name, r.returncode, "\n  ".join(err)))
    out = normalize_copy(out)
    if not out.strip():
        raise Fail("Скрипт %s ничего не напечатал. Расчёт должен печатать результат (print) - он станет источником." % sp.name)
    existing = list_sources(proj)
    sid = next_id("S", [m["id"] for m in existing])
    write_text_atomic(proj.path("sources", sid + ".txt"), out)
    rels = [p.relative_to(proj.dir.resolve()).as_posix() for p in in_paths]
    in_layers = [next((source_layer(m) or 1 for m in existing if m.get("path") == rel), 1) for rel in rels]
    meta = {
        "id": sid, "kind": "расчёт", "url": None, "path": None, "layer": min(in_layers or [1]),
        "title": "Расчёт %s" % sp.name,
        "published": today().isoformat(), "accessed": today().isoformat(),
        "sha256": sha256_bytes(out.encode("utf-8")),
        "question": question or DEFAULT_QUESTION,
        "stale_accepted": False, "added": now_iso(),
        "method": method,
        "script": sp.relative_to(proj.dir.resolve()).as_posix(),
        "script_sha256": sha256_file(sp),
        "inputs": [{"path": p.relative_to(proj.dir.resolve()).as_posix(), "sha256": sha256_file(p)} for p in in_paths],
    }
    if grounds_ids:
        meta["rests_on"] = grounds_ids
    write_json(proj.path("sources", sid + ".meta.json"), meta)
    journal(proj, "calc run", {"id": sid, "script": meta["script"], "inputs": [i["path"] for i in meta["inputs"]]})
    return meta, out
