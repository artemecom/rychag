# -*- coding: utf-8 -*-
"""Общие помощники: пути, чтение и запись файлов, даты, нормализация текста, настройки."""
import datetime
import hashlib
import json
import os
import re
import unicodedata
from decimal import Decimal, InvalidOperation
from pathlib import Path


class Fail(Exception):
    """Ошибка использования. Текст показывается человеку, код возврата 1."""


STAGE_NAMES = {
    1: "Постановка",
    2: "Договор «что значит готово» и план",
    3: "Сбор материалов",
    4: "Диагностика и выводы",
    5: "Варианты",
    6: "Стратегии",
    7: "Итоговая страница и полная проверка",
    8: "После решения",
}
LAYER_RU = {1: "данные самого продукта", 2: "данные компании и её других сервисов", 3: "отрасль в той же стране",
            4: "отрасль в мире", 5: "смежные отрасли"}
LAYER_WORDS = {1: "данные самого продукта", 2: "данные компании", 3: "другие компании в России", 4: "компании в мире",
               5: "смежные отрасли"}
LEVER_NOTE = "Рычаг: то, что можно изменить, чтобы показатель вырос."


def explain_lever(lines):
    """Если в выводе впервые упомянут рычаг, добавляет короткое пояснение после этой строки (один раз)."""
    out, done = [], False
    for l in lines:
        out.append(l)
        if not done and "рычаг" in l.lower() and l.strip() != LEVER_NOTE:
            out.append(LEVER_NOTE)
            done = True
    return out


CALC_METHODS = ["словарь", "разметка", "расчёт"]
UNMEASURED_FLAG = "точность не измерена"

LAYER_HELP = "; ".join("%d = %s" % (k, v) for k, v in LAYER_RU.items())


def check_layer(value, low=1, high=5):
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = None
    if n is None or not low <= n <= high:
        raise Fail("Слой близости должен быть числом от %d до %d. Слои: %s." % (low, high, LAYER_HELP))
    return n


HUMAN_STOPS = {1: 1, 2: 2, 5: 3, 7: 4}  # этап -> номер остановки для человека
# Что показать руководителю на остановке этапа.
STOP_SHOW = {
    1: "как поняли задачу (5-8 строк), что будет результатом, и не больше трёх вопросов",
    2: "критерии «что значит готово» и бюджет",
    5: "варианты с возражениями: выбирает руководитель, а не вы",
    7: "итог: страницу или начало документа",
}
# stops_need_answer: перейти с этапа-остановки дальше можно только со словами руководителя (stage next --answer).
DEFAULT_PROCESS = {"stops_need_answer": False}


def stops_need_answer(cfg):
    return bool((cfg or {}).get("process", {}).get("stops_need_answer"))


def stop_answered(proj, stage):
    return str(stage) in (read_state(proj).get("stop_answers") or {})


def stop_hint(stage):
    return ("Остановка для человека №%d. Покажите руководителю: %s. Закончите ответ и ждите. Дальше не работайте. "
            "Он отвечает обычными словами в чате, команду ему не показывайте. Получив ответ, выполните сами: python3 tools/rychag.py stage next --answer \"<его слова>\"" % (HUMAN_STOPS[stage], STOP_SHOW[stage]))


def early_work_guard(proj, cfg, what):
    """До ответов руководителя на остановках 1 и 2 расчёты, допущения и закрытие требований не начинаются."""
    if not stops_need_answer(cfg):
        return
    cur = read_state(proj)["stage"]
    if cur < 3:
        raise Fail("Рано: %s начинается с этапа 3, а сейчас этап %d (%s). %s" % (what, cur, STAGE_NAMES[cur], stop_hint(cur)))

CLAIM_TYPES = ["fact", "hypothesis", "forecast", "agent", "synthetic", "calc", "plan", "benchmark", "assumption"]
CLAIM_TYPE_RU = {"fact": "факт", "hypothesis": "гипотеза", "forecast": "прогноз", "agent": "ответ агента",
                 "synthetic": "синтетическое", "calc": "расчёт", "plan": "параметр плана", "benchmark": "ориентир",
                 "assumption": "допущение"}
UNPROVEN_TYPES = ("assumption", "hypothesis", "forecast")  # расчёт на таких записях наследует пометку «на допущениях»
ON_ASSUMPTIONS_FLAG = "на допущениях"
CONCLUSION_KINDS = ["finding", "cause", "option", "recommendation", "promise"]
STATUS_OK = "действует"
STATUS_DOUBT = "под-вопросом"
STATUS_REPLACED = "заменён"
STATUS_REJECTED = "отброшено"
PLACEHOLDER = "<<заполнить>>"
MODEL_CLASSES = ["дешёвая", "средняя", "сильная"]

DEFAULT_SOURCES = {"allowlist": [], "max_sources_per_question": 10, "freshness_days": 730,
                   "kb_freshness_days": 1095}
DEFAULT_STYLE = {
    "max_page_lines": 45,
    "banned_phrases": [
        "в современном мире", "на сегодняшний день", "в рамках данного", "играет важную роль",
        "не секрет, что", "комплексный подход", "синергия", "уникальное решение",
        "инновационный подход", "максимально эффективно", "высокое качество", "широкий спектр",
        "индивидуальный подход", "является ключевым", "ни для кого не секрет", "мы стремимся",
        "лидер рынка", "передовые технологии", "оптимальное решение", "всесторонний анализ",
        "динамично развивающийся", "в условиях неопределённости", "принимая во внимание",
        "необходимо отметить", "как известно", "в современных реалиях", "важно отметить",
        "ключевые драйверы",
    ],
    "abbreviations": [
        {"abbr": "п.п.", "write": "процентных пункта"},
        {"abbr": "п. п.", "write": "процентных пункта"},
        {"abbr": "т.е.", "write": "то есть"},
        {"abbr": "т. е.", "write": "то есть"},
        {"abbr": "т.д.", "write": "так далее"},
        {"abbr": "т. д.", "write": "так далее"},
        {"abbr": "т.п.", "write": "тому подобное"},
        {"abbr": "т. п.", "write": "тому подобное"},
        {"abbr": "руб.", "write": "рублей"},
        {"abbr": "тыс.", "write": "тысяч"},
        {"abbr": "млн", "write": "миллионов"},
        {"abbr": "млрд", "write": "миллиардов"},
    ],
}

# ---------------------------------------------------------------- даты

_TODAY = [None]


def parse_date(value):
    s = str(value).strip()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        raise Fail("Дата «%s» должна быть в формате ГГГГ-ММ-ДД, например 2026-11-18." % value)
    try:
        return datetime.datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        raise Fail("Даты «%s» не существует. Формат: ГГГГ-ММ-ДД." % value)


def parse_period(value):
    """Дата публикации в виде ГГГГ, ГГГГ-ММ или ГГГГ-ММ-ДД. Возвращает (первый день, последний день) названного периода."""
    s = str(value).strip()
    m = re.match(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?$", s)
    if not m:
        raise Fail("Дата «%s» должна быть в формате ГГГГ, ГГГГ-ММ или ГГГГ-ММ-ДД, например 2026, 2026-11 или 2026-11-18." % value)
    y = int(m.group(1))
    mo = int(m.group(2)) if m.group(2) else None
    d = int(m.group(3)) if m.group(3) else None
    try:
        if d:
            day = datetime.date(y, mo, d)
            return day, day
        if mo:
            first = datetime.date(y, mo, 1)
            nxt = datetime.date(y + (mo == 12), mo % 12 + 1, 1)
            return first, nxt - datetime.timedelta(days=1)
        return datetime.date(y, 1, 1), datetime.date(y, 12, 31)
    except ValueError:
        raise Fail("Даты «%s» не существует. Форматы: ГГГГ, ГГГГ-ММ, ГГГГ-ММ-ДД." % value)


def period_end(value):
    """Последний день названного периода: для свежести считаем от него."""
    return parse_period(value)[1]


def period_start(value):
    return parse_period(value)[0]


def set_today(value):
    """Подмена «сегодня» (для проверок и тестов). None возвращает настоящую дату."""
    _TODAY[0] = parse_date(value) if value else None


def today():
    return _TODAY[0] or datetime.date.today()


def now_iso():
    return datetime.datetime.now().replace(microsecond=0).isoformat()


# ---------------------------------------------------------------- файлы

def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def write_text_atomic(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(str(tmp), str(path))


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False, indent=2) + "\n"


def read_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except ValueError as e:
        raise Fail("Файл %s не читается как JSON (%s). Исправьте его вручную или верните прежнюю версию." % (path, e))


def write_json(path, obj):
    write_text_atomic(path, dumps(obj))


def read_jsonl(path):
    path = Path(path)
    out = []
    if not path.exists():
        return out
    with open(path, "r", encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                raise Fail("Файл %s, строка %d: это не JSON. Исправьте строку или удалите её вручную." % (path, n))
    return out


def write_jsonl(path, rows):
    write_text_atomic(path, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


def append_jsonl(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def read_text(path, default=""):
    path = Path(path)
    if not path.exists():
        return default
    return path.read_text(encoding="utf-8")


def is_inside(path, folder):
    try:
        Path(path).resolve().relative_to(Path(folder).resolve())
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------- проекты

def default_root():
    return Path(__file__).resolve().parents[2]


class Project:
    def __init__(self, root, name):
        self.root = Path(root)
        self.name = name
        self.dir = self.root / "projects" / name

    def path(self, *parts):
        return self.dir.joinpath(*parts)

    def where(self, *parts):
        return "projects/%s/%s" % (self.name, "/".join(parts)) if parts else "projects/%s" % self.name


def find_projects(root):
    base = Path(root) / "projects"
    if not base.is_dir():
        return []
    return sorted(p.name for p in base.iterdir() if p.is_dir() and (p / "state.json").exists())


def work_projects(root):
    """Рабочие задачи: всё, кроме служебных папок с подчёркиванием в начале имени."""
    projs = find_projects(root)
    return [p for p in projs if not p.startswith("_")] or projs


def latest_project(root):
    """Задача, которая менялась последней (по журналу и состоянию). None, если задач нет."""
    best, stamp = None, ("", -1.0)
    for name in work_projects(root):
        base = Path(root) / "projects" / name
        # Время берём из последней записи журнала: время изменения файла после копирования или клонирования у всех одинаково.
        t = (_last_journal_time(base / "journal.jsonl"),
             max((f.stat().st_mtime for f in (base / "journal.jsonl", base / "state.json") if f.exists()), default=0.0))
        if t > stamp:
            best, stamp = name, t
    return best


def _last_journal_time(path):
    """Отметка времени последней записи журнала задачи (строкой ISO) или пустая строка."""
    try:
        with open(path, "rb") as f:
            lines = f.read().decode("utf-8", "replace").strip().split("\n")
        for line in reversed(lines):
            m = re.search(r'"(?:ts|time|at|when)"\s*:\s*"([^"]+)"', line)
            if m:
                return m.group(1)
    except OSError:
        pass
    return ""


def check_project_id(name):
    if not re.match(r"^[A-Za-z0-9_Ѐ-ӿ-]{1,60}$", name or ""):
        raise Fail("Имя задачи «%s» не подходит. Нужны буквы, цифры, «_» и «-», до 60 знаков, без пробелов и слэшей." % name)


def resolve_project(root, name=None):
    projs = find_projects(root)
    if name:
        check_project_id(name)
        if name not in projs:
            raise Fail("Проект «%s» не найден. Есть: %s. Создать: python3 tools/rychag.py new <id> --question \"...\"" % (
                name, ", ".join(projs) or "ничего"))
        return Project(root, name)
    cand = [p for p in projs if not p.startswith("_")] or projs
    if not cand:
        raise Fail("Проектов нет. Создайте: python3 tools/rychag.py new <id> --question \"...\"")
    if len(cand) > 1:
        raise Fail("Проектов несколько (%s). Укажите нужный: --project ID." % ", ".join(cand))
    return Project(root, cand[0])


def read_state(proj):
    st = read_json(proj.path("state.json"))
    if not isinstance(st, dict):
        raise Fail("Нет файла %s. Проект создаётся командой new." % proj.where("state.json"))
    return st


def set_state_field(proj, key, value):
    """Меняет одно поле state.json, остальное не трогает."""
    st = read_state(proj)
    st[key] = value
    write_json(proj.path("state.json"), st)


def step_hash(cmd, detail, ts):
    """Короткий отпечаток шага журнала: по нему видно, что шаг записан, и не спутать два одинаковых по виду шага."""
    raw = json.dumps([cmd, detail, ts], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8]


def journal(proj, cmd, detail=None):
    ts = now_iso()
    append_jsonl(proj.path("journal.jsonl"), {"ts": ts, "h": step_hash(cmd, detail, ts), "cmd": cmd, "detail": detail})


# ---------------------------------------------------------------- настройки

def load_config(root):
    cfg_dir = Path(root) / "config"
    sources = dict(DEFAULT_SOURCES)
    style = dict(DEFAULT_STYLE)
    sources.update(read_json(cfg_dir / "sources.json", {}) or {})
    style.update(read_json(cfg_dir / "style.json", {}) or {})
    routing = read_json(cfg_dir / "routing.json", {}) or {}
    process = dict(DEFAULT_PROCESS)
    process.update(read_json(cfg_dir / "process.json", {}) or {})
    return {"sources": sources, "style": style, "routing": routing, "process": process}


def validate_config(root):
    """Возвращает список проблем (пустой, если настройки в порядке)."""
    problems = []
    cfg_dir = Path(root) / "config"
    for name in ("sources.json", "style.json", "routing.json"):
        p = cfg_dir / name
        if not p.exists():
            problems.append("нет файла config/%s (будут взяты значения по умолчанию)" % name)
            continue
        try:
            json.loads(p.read_text(encoding="utf-8"))
        except ValueError as e:
            problems.append("config/%s не читается как JSON: %s" % (name, e))
    try:
        cfg = load_config(root)
    except Fail as e:
        return problems + [str(e)]
    s = cfg["sources"]
    if not isinstance(s.get("allowlist"), list) or not all(isinstance(x, str) for x in s["allowlist"]):
        problems.append("config/sources.json: allowlist должен быть списком строк")
    for key in ("max_sources_per_question", "freshness_days"):
        if not isinstance(s.get(key), int) or isinstance(s.get(key), bool) or s[key] < 1:
            problems.append("config/sources.json: %s должно быть целым числом больше нуля" % key)
    if not isinstance(s.get("kb_freshness_days"), int) or s["kb_freshness_days"] < 1:
        problems.append("config/sources.json: kb_freshness_days должно быть целым числом больше нуля")
    syn = read_json(cfg_dir / "synonyms.json", None)
    if syn is not None and not (isinstance(syn, dict) and isinstance(syn.get("groups"), list)
                                and all(isinstance(g, list) and all(isinstance(x, str) for x in g) for g in syn["groups"])):
        problems.append("config/synonyms.json: нужен объект с полем groups, списком списков слов")
    st = cfg["style"]
    if not isinstance(st.get("max_page_lines"), int) or st["max_page_lines"] < 1:
        problems.append("config/style.json: max_page_lines должно быть целым числом больше нуля")
    if not isinstance(st.get("banned_phrases"), list) or not all(isinstance(x, str) for x in st["banned_phrases"]):
        problems.append("config/style.json: banned_phrases должен быть списком строк")
    ab = st.get("abbreviations")
    if not isinstance(ab, list) or not all(isinstance(x, dict) and isinstance(x.get("abbr"), str) and x.get("abbr", "").strip()
                                           and isinstance(x.get("write"), str) for x in ab):
        problems.append("config/style.json: abbreviations должен быть списком объектов вида {\"abbr\": \"п.п.\", \"write\": \"процентных пункта\"}")
    r = cfg["routing"]
    if r and not isinstance(r.get("table"), list):
        problems.append("config/routing.json: нужен список table")
    elif r:
        for i, row in enumerate(r["table"], 1):
            if not isinstance(row, dict) or row.get("model_class") not in MODEL_CLASSES:
                problems.append("config/routing.json: в строке %d model_class должен быть одним из: %s" % (i, ", ".join(MODEL_CLASSES)))
            elif "method" in row and not isinstance(row["method"], str):
                problems.append("config/routing.json: в строке %d method должен быть строкой" % i)
    return problems


# ---------------------------------------------------------------- текст

_QUOTE_MAP = {
    "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"', "\u00ab": '"', "\u00bb": '"',
    "\u2033": '"', "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'", "\u2032": "'", "`": "'",
}
_DASH_CHARS = "\u2010\u2011\u2012\u2013\u2014\u2015\u2212"


def norm_match(text):
    """Нормализация для сверки цитаты: регистр, пробелы, типографские кавычки и тире."""
    s = unicodedata.normalize("NFKC", text or "")
    s = s.replace("­", "")
    for a, b in _QUOTE_MAP.items():
        s = s.replace(a, b)
    for ch in _DASH_CHARS:
        s = s.replace(ch, "-")
    s = s.lower().replace("ё", "е")
    return re.sub(r"\s+", " ", s).strip()


def quote_in_text(quote, text):
    q = norm_match(quote)
    return bool(q) and q in norm_match(text)


def normalize_copy(text):
    t = text.replace("\r\n", "\n").replace("\r", "\n").replace("﻿", "")
    t = "\n".join(line.rstrip() for line in t.split("\n"))
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    return t + "\n"


_NUM_RE = re.compile(r"\d{1,3}(?:[   ]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?")


def canon_number(token):
    s = re.sub(r"[   ]", "", token).replace(",", ".")
    try:
        return format(Decimal(s).normalize(), "f")
    except InvalidOperation:
        return s


def numbers_in(text):
    """Множество чисел текста в каноническом виде (запятая и точка равны, % и пробелы не важны)."""
    return set(canon_number(m.group(0)) for m in _NUM_RE.finditer(text or ""))


_EXEMPT = [
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
    re.compile(r"\b\d{1,2}\.\d{1,2}\.\d{4}\b"),
    re.compile(r"\b[A-Za-zЀ-ӿ]{1,3}-?\d+\b"),
    re.compile(r"^\s*\d+[.)]\s", re.M),
    re.compile(r"\b(?:19|20)\d{2}\b"),
]


def page_numbers(text):
    """Числа итоговой страницы. Даты, номера списка, годы и коды вроде K001 или Q3 не считаются."""
    t = text
    for rx in _EXEMPT:
        t = rx.sub(" ", t)
    return [(m.group(0), canon_number(m.group(0))) for m in _NUM_RE.finditer(t)]


def next_id(prefix, existing_ids, width=3):
    best = 0
    for i in existing_ids:
        m = re.match(r"^%s-?(\d+)$" % re.escape(prefix), str(i))
        if m:
            best = max(best, int(m.group(1)))
    return "%s%0*d" % (prefix, width, best + 1)


def split_ids(value):
    if not value:
        return []
    return [x.strip() for x in re.split(r"[,\s;]+", value) if x.strip()]


def short(text, n=70):
    t = re.sub(r"\s+", " ", text or "").strip()
    return t if len(t) <= n else t[: n - 3] + "..."
