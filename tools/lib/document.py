# -*- coding: utf-8 -*-
"""Документ по частям заказчика: когда заказчик сам задал структуру результата (например, «один документ из пяти частей»).

Структура хранится в document.json задачи: название, обязательные элементы начала и части в порядке заказчика.
Она берётся из запроса, в программе не зашита. Сам текст лежит в document.md. Начало документа (до первой части)
и есть страница для руководителя: page.md собирает из него команда doc page.
"""
import re

from .common import (Fail, PLACEHOLDER, norm_match, read_json, write_json, read_text, write_text_atomic, today, journal,
                     quote_in_text, is_inside, short)
from . import strategy as strat

DOC_JSON = "document.json"
DOC_FILE = "document.md"
START_WORD = "начало"
FILES_HEAD = "Подробности и расчёты:"
MIN_WORDS = 3
_HEAD_RX = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_LEAD_RX = re.compile(r"^[\s#>*_`|\-\d.)]+")


def exists(proj):
    return proj.path(DOC_JSON).exists()


def load(proj):
    """Описание документа или None, если заказчик структуру не задавал."""
    d = read_json(proj.path(DOC_JSON))
    if d is None:
        return None
    if not isinstance(d, dict) or not isinstance(d.get("parts"), list) or not d["parts"]:
        raise Fail("Файл %s испорчен: в нём должен быть список частей parts. Пересоздайте: doc init ... --replace" % proj.where(DOC_JSON))
    d.setdefault("opening", [])
    d.setdefault("title", "")
    return d


def _key(text):
    return strat._head_key(text or "")


def skeleton(doc):
    out = ["# " + doc["title"], ""]
    for el in doc["opening"]:
        out += ["**%s:** %s" % (el, PLACEHOLDER), ""]
    for n, part in enumerate(doc["parts"], 1):
        out += ["## %d. %s" % (n, part), "", PLACEHOLDER, ""]
    return "\n".join(out)


def init(proj, title, opening, parts, quote=None, source="brief", replace=False, ending=None):
    """Записывает document.json и каркас document.md. Возвращает (описание, создан ли каркас)."""
    title = (title or "").strip()
    opening = [x.strip() for x in (opening or []) if (x or "").strip()]
    parts = [re.sub(r"^\s*\d+[.)]\s*", "", x).strip() for x in (parts or []) if (x or "").strip()]
    if not title:
        raise Fail("Нужно название документа: --title \"...\".")
    if not parts:
        raise Fail("Нужна хотя бы одна часть: --part \"название части\" (по одной на каждую часть, в порядке заказчика).")
    for group, what in ((parts, "Часть"), (opening, "Элемент начала")):
        keys = [_key(x) for x in group]
        for a in keys:
            if keys.count(a) > 1 or not a:
                raise Fail("%s указана дважды или пуста. Названия должны различаться." % what)
    if quote:
        from . import reqs
        if source == "brief":
            pool = reqs.verbatim_request(proj) + "\n" + reqs.requests_text(proj)
        elif re.match(r"^S\d{3,}$", source or ""):
            from .sources import get_source, source_text
            get_source(proj, source)
            pool = source_text(proj, source)
        else:
            raise Fail("Откуда цитата о структуре: --source brief или код источника вида S001.")
        if not quote_in_text(quote, pool):
            raise Fail("Цитата о структуре документа не найдена. Скопируйте дословно слова заказчика о том, из чего состоит результат. "
                       "Начало вашей цитаты: «%s»." % short(quote, 50))
    ending = (ending or "").strip() or None
    doc = {"title": title, "opening": opening, "parts": parts, "ending": ending, "file": DOC_FILE,
           "quote": (quote or "").strip() or None, "source": source if quote else None, "created": today().isoformat()}
    old = load(proj)
    if old is not None:
        same = all(old.get(k) == doc[k] for k in ("title", "opening", "parts", "ending"))
        if same:
            return old, False
        if not replace:
            raise Fail("Структура документа уже задана (%s) и отличается от новой. Чтобы заменить описание, добавьте --replace: "
                       "текст %s при этом не трогается, перенесите части сами." % (proj.where(DOC_JSON), DOC_FILE))
    write_json(proj.path(DOC_JSON), doc)
    made = False
    if not read_text(proj.path(DOC_FILE)).strip():
        write_text_atomic(proj.path(DOC_FILE), skeleton(doc))
        made = True
    journal(proj, "doc init", {"parts": len(parts), "opening": len(opening), "replace": bool(old is not None)})
    return doc, made


# ---------------------------------------------------------------- разбор текста

class Parsed:
    """Разобранный document.md: строки, заголовки, место каждой части, границы начала."""

    def __init__(self, proj, doc):
        self.doc = doc
        self.text = read_text(proj.path(doc.get("file") or DOC_FILE))
        self.lines = self.text.split("\n")
        self.heads = []  # (номер строки, уровень, ключ)
        fence = False
        for n, ln in enumerate(self.lines):
            if ln.strip().startswith("```"):
                fence = not fence
                continue
            if fence:
                continue
            m = _HEAD_RX.match(ln)
            if m:
                self.heads.append((n, len(m.group(1)), _key(m.group(2))))
        self.title_line = self.heads[0][0] if self.heads and self.heads[0][1] == 1 else None
        self.part_line = []  # для каждой части номер строки заголовка или None
        for part in doc["parts"]:
            k = _key(part)
            hit = next((n for n, lvl, key in self.heads if n != self.title_line and lvl <= 3 and key.startswith(k)), None)
            self.part_line.append(hit)
        found = sorted(x for x in self.part_line if x is not None)
        self.first_part = found[0] if found else len(self.lines)

    def opening_lines(self):
        return self.lines[:self.first_part]

    def part_body(self, i):
        """Строки части i (с нуля) до заголовка следующей найденной части. None, если части нет."""
        start = self.part_line[i]
        if start is None:
            return None
        later = [x for x in self.part_line if x is not None and x > start]
        return self.lines[start + 1:(min(later) if later else len(self.lines))]

    def part_words(self, i):
        body = self.part_body(i)
        return 0 if body is None else len(re.findall(r"\w+", strat._body_text(body)))

    def part_of_line(self, n):
        """Название места для строки: «начало» или «часть N»."""
        best = None
        for i, start in enumerate(self.part_line):
            if start is not None and start <= n and (best is None or start > self.part_line[best]):
                best = i
        return START_WORD if best is None else "часть %d" % (best + 1)


def _label_rest(line, key):
    """Если строка начинается с названия элемента (разметка впереди не важна), возвращает текст после названия."""
    stripped = _LEAD_RX.sub("", line)
    norm = norm_match(stripped.replace("*", "").replace("_", ""))
    if not norm.startswith(key):
        return None
    return norm[len(key):]


def opening_states(parsed):
    """[(элемент, состояние)]: «есть», «пусто» или «нет»."""
    lines = parsed.opening_lines()
    keys = [norm_match(x) for x in parsed.doc["opening"]]
    marks = {}  # номер строки -> номер элемента
    for n, ln in enumerate(lines):
        for i, k in enumerate(keys):
            if i not in marks.values() and _label_rest(ln, k) is not None:
                marks[n] = i
                break
    out = []
    for i, el in enumerate(parsed.doc["opening"]):
        at = next((n for n, j in marks.items() if j == i), None)
        if at is None:
            out.append((el, "нет"))
            continue
        chunk = [_label_rest(lines[at], keys[i])]
        for n in range(at + 1, len(lines)):
            if n in marks or _HEAD_RX.match(lines[n]):
                break
            chunk.append(lines[n])
        text = strat._body_text(chunk)
        out.append((el, "есть" if len(re.findall(r"\w+", text)) >= MIN_WORDS else "пусто"))
    return out


def structure_issues(proj, doc=None, parsed=None):
    """Замечания к составу документа: файл, название, части на месте, в порядке заказчика и не пустые."""
    doc = doc or load(proj)
    where = proj.where(doc.get("file") or DOC_FILE)
    parsed = parsed or Parsed(proj, doc)
    out = []
    if not parsed.text.strip():
        return [(where, "документа по частям заказчика нет или он пуст", "заполните %s: каркас создаёт команда doc init" % DOC_FILE)]
    if parsed.title_line is None:
        out.append((where, "у документа нет названия", "первой строкой поставьте заголовок «# %s»" % doc["title"]))
    prev = -1
    for i, part in enumerate(doc["parts"]):
        at = parsed.part_line[i]
        if at is None:
            out.append((where, "нет части %d «%s»" % (i + 1, part), "добавьте заголовок «## %d. %s» и текст под ним" % (i + 1, part)))
            continue
        if at < prev:
            out.append((where, "часть %d «%s» стоит раньше предыдущей: порядок частей задал заказчик" % (i + 1, part),
                        "расставьте части в порядке: %s" % "; ".join(doc["parts"])))
        prev = max(prev, at)
        if parsed.part_words(i) < MIN_WORDS:
            out.append((where, "часть %d «%s» пуста" % (i + 1, part), "напишите текст под заголовком части"))
    return out


def ending_issues(proj, doc, parsed):
    """Заказчик велел чем-то закончить документ (например, просьбой руководителю): этот элемент стоит последним."""
    label = doc.get("ending")
    if not label:
        return []
    where = proj.where(doc.get("file") or DOC_FILE)
    key = norm_match(label)
    at = None
    for n, ln in enumerate(parsed.lines):
        if _label_rest(ln, key) is not None:
            at = n
    if at is None:
        return [(where, "документ должен заканчиваться элементом «%s», а его нет" % label,
                 "последним абзацем документа поставьте строку, которая начинается со слов «%s:»" % label)]
    for ln in parsed.lines[at + 1:]:
        t = ln.strip()
        if _HEAD_RX.match(ln) or t.startswith("**") or t.startswith("|"):
            return [(where, "после элемента «%s» в документе есть ещё разделы: заказчик просил закончить именно им" % label,
                     "перенесите всё, что стоит после «%s», выше (риски и разбор слабых мест идут до него)" % label)]
    return []


RETOLD_SHARE = 0.6   # доля четвёрок слов предложения, найденных в тексте заказчика
RETOLD_MIN_WORDS = 8
RETOLD_ALLOWED = 3   # столько почти дословных повторов допускается (определения, условия заказчика)


def _plain_words(text):
    return re.findall(r"[a-zа-я0-9]+", (text or "").lower().replace("ё", "е"))


def _four_grams(words):
    return {tuple(words[i:i + 4]) for i in range(len(words) - 3)}


def retold_sentences(proj, doc, parsed):
    """[(номер строки, предложение)]: предложения документа, почти дословно взятые из текста заказчика.
    Заказчик свой текст знает: ему нужен ответ (решение, число, срок), а не пересказ вопроса."""
    sid = doc.get("source") or ""
    if not re.match(r"^S\d{3,}$", sid):
        return []
    try:
        from .sources import source_text
        pool = _four_grams(_plain_words(source_text(proj, sid)))
    except Fail:
        return []
    out = []
    for n, line in enumerate(parsed.lines):
        if _HEAD_RX.match(line):
            continue
        cells = line.split("|") if line.strip().startswith("|") else [line]
        for cell in cells:
            for sent in re.split(r"(?<=[.?!:;])\s+", cell):
                words = _plain_words(sent)
                if len(words) < RETOLD_MIN_WORDS:
                    continue
                grams = _four_grams(words)
                if grams and len(grams & pool) / float(len(grams)) >= RETOLD_SHARE:
                    out.append((n, sent.strip()))
    return out


def own_elements_issues(proj, doc, parsed, elements):
    """Наши обязательные элементы документа сверх частей заказчика (config/style.json, document_elements):
    вклад действий в цели и коммуникационная часть. Каждый элемент это строка, которая начинается с его названия."""
    where = proj.where(doc.get("file") or DOC_FILE)
    out = []
    for el in elements or []:
        name, hint = el.get("name", ""), el.get("hint", "")
        key = norm_match(name)
        if not key:
            continue
        if not any(_label_rest(ln, key) is not None for ln in parsed.lines):
            out.append((where, "в документе нет обязательного элемента «%s»" % name,
                        "добавьте в подходящую часть абзац или таблицу, перед которой стоит строка «**%s.**» %s" % (name, hint)))
    return out


def opening_issues(proj, doc, parsed, max_lines):
    where = proj.where(doc.get("file") or DOC_FILE)
    out = []
    for el, st in opening_states(parsed):
        if st == "нет":
            out.append((where, "в начале документа нет обязательного элемента «%s»" % el,
                        "до первой части добавьте строку, которая начинается со слов «%s:», и ответ в ней" % el))
        elif st == "пусто":
            out.append((where, "элемент начала «%s» не заполнен" % el, "после слов «%s:» напишите ответ хотя бы одним предложением" % el))
    count = sum(1 for l in parsed.opening_lines() if l.strip())
    if count > max_lines:
        out.append((where, "начало документа (до первой части) длиннее страницы: %d непустых строк, можно %d" % (count, max_lines),
                    "сократите начало: оно читается как отдельная страница для руководителя; подробности перенесите в части"))
    return out


# ---------------------------------------------------------------- страница из начала документа

def page_text(proj, doc=None, parsed=None):
    """Текст page.md: начало документа и список файлов с подробностями."""
    doc = doc or load(proj)
    parsed = parsed or Parsed(proj, doc)
    body = "\n".join(parsed.opening_lines()).strip("\n")
    files = [doc.get("file") or DOC_FILE]
    for rel in ("options.md", "levers.json", "requirements.json"):
        if proj.path(rel).exists():
            files.append(rel)
    dec = proj.path("decisions")
    if dec.is_dir():
        files += ["decisions/" + p.name for p in sorted(dec.glob("DR-*.md"))]
    return body + "\n\n" + FILES_HEAD + "\n" + "\n".join("- " + f for f in files) + "\n"


def write_page(proj):
    doc = load(proj)
    if doc is None:
        raise Fail("Структура документа не задана (%s нет): page.md в такой задаче пишется вручную." % DOC_JSON)
    parsed = Parsed(proj, doc)
    if not "\n".join(parsed.opening_lines()).strip():
        raise Fail("В %s нет начала: сначала заполните документ." % proj.where(DOC_FILE))
    text = page_text(proj, doc, parsed)
    changed = read_text(proj.path("page.md")) != text
    if changed:
        write_text_atomic(proj.path("page.md"), text)
        journal(proj, "doc page", {"lines": sum(1 for l in parsed.opening_lines() if l.strip())})
    return changed


def page_sync_issue(proj, doc, parsed):
    if read_text(proj.path("page.md")) == page_text(proj, doc, parsed):
        return None
    return (proj.where("page.md"), "страница для руководителя не совпадает с началом документа",
            "page.md руками не пишите: соберите её из начала документа командой doc page")


# ---------------------------------------------------------------- место требования в результате

def resolve_place(proj, where):
    """Проверяет место выполнения требования. Возвращает («начало», None), («часть», номер с нуля) или («файл», путь)."""
    text = (where or "").strip()
    if not text:
        raise Fail("Пустое место. Примеры: --where \"начало\", --where \"часть 2\", --where \"strategy/test-plan.md\".")
    low = norm_match(text)
    doc = load(proj)
    if doc is not None:
        if low.startswith(START_WORD):
            return START_WORD, None
        m = re.match(r"^часть\s*№?\s*(\d+)", low)
        if m:
            n = int(m.group(1))
            if not 1 <= n <= len(doc["parts"]):
                raise Fail("В документе частей %d, а указана часть %d." % (len(doc["parts"]), n))
            return "часть", n - 1
        for i, part in enumerate(doc["parts"]):
            if _key(text).startswith(_key(part)):
                return "часть", i
    token = re.split(r"[\s,;:]", text.strip("`"), 1)[0]
    cand = proj.dir / token
    if token and cand.is_file() and is_inside(cand, proj.dir):
        return "файл", token
    forms = "путь к существующему файлу задачи"
    if doc is not None:
        forms = "«начало», «часть N» (N от 1 до %d), название части или " % len(doc["parts"]) + forms
    raise Fail("Место «%s» не найдено. Допустимо: %s. После места можно дописать уточнение через запятую." % (text, forms))


def place_label(proj, where):
    """Короткое название места для сводки или None, если место не распознано."""
    try:
        kind, val = resolve_place(proj, where)
    except Fail:
        return None
    if kind == "часть":
        return "часть %d" % (val + 1)
    return START_WORD if kind == START_WORD else val


PHRASE_MIN_WORDS = 4


def place_text(proj, where):
    """Текст места документа («начало» или часть) одной строкой для поиска фразы. None, если место это файл или его нет."""
    doc = load(proj)
    if doc is None:
        return None
    kind, val = resolve_place(proj, where)
    parsed = Parsed(proj, doc)
    if kind == START_WORD:
        lines = parsed.opening_lines()
    elif kind == "часть":
        lines = parsed.part_body(val)
    else:
        return None
    if lines is None:
        return None
    return _flat(" ".join(lines))


def _flat(text):
    """Для сверки фразы: без разметки таблиц и выделения, регистр и пробелы как в сверке цитат."""
    t = re.sub(r"[|*_`#>]", " ", text or "")
    return re.sub(r"\s+", " ", norm_match(t)).strip()


def phrase_found(proj, where, phrase):
    """True, если фраза дословно стоит в названном месте документа. None, если проверить негде."""
    body = place_text(proj, where)
    if body is None:
        return None
    return _flat(phrase) in body
