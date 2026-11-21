# -*- coding: utf-8 -*-
"""Создание проекта, этапы, статус, отчёт о расходе, проверка окружения."""
import os
import sys
import tempfile

from .common import (Fail, Project, STAGE_NAMES, HUMAN_STOPS, PLACEHOLDER, STATUS_OK, STATUS_DOUBT, STATUS_REPLACED,
                     STATUS_REJECTED, check_project_id, write_text_atomic, write_json, read_state, set_state_field,
                     journal, today, now_iso, read_json, validate_config, find_projects, parse_date, read_jsonl)
from .checks import (stage_report, format_layers, guard_reset, STAGE_REQUIREMENTS, run_layers)
from .sources import list_sources, is_stale
from . import kb as kbase
from .layers import support_counts, support_line
from .ledger import (load_claims, load_conclusions, load_levers, load_decisions, load_done, cost_summary, cost_detail, cost_rows,
                     KIND_MEASURED)
from . import strategy as strat
from . import diagnosis as diag
from . import reqs
from . import incidents
from . import route
from . import common

BRIEF_TEMPLATE = """# Постановка

Вопрос руководителя: {question}

Дата начала просадки: %(p)s

Что менялось в продукте, тарифах и рекламе на эту дату: %(p)s

Какой показатель и в какую сторону изменился (с числами и источником): %(p)s

Что решает руководитель по итогам: %(p)s

## Запрос дословно

{question}
""" % {"p": PLACEHOLDER}

OPTIONS_TEMPLATE = """# Варианты и возражения

Формат: для каждого варианта заголовок `## K005 Название` (код вывода вида option), ниже строка
`Возражение: ...` с сильным возражением. Вариантов не меньше трёх, среди них «оставить как есть».
Вариант «закрыть направление» либо входит в варианты, либо отклоняется строкой, которая начинается с
«Закрыть направление: не рассматриваем, потому что ...».
"""

ERRORS_TEMPLATE = incidents.TEMPLATE


def create_project(root, pid, question):
    check_project_id(pid)
    if not (question or "").strip():
        raise Fail("Нужен вопрос: --question \"что случилось и что решать\".")
    proj = Project(root, pid)
    if proj.dir.exists():
        raise Fail("Папка %s уже есть. Выберите другое имя или работайте с существующим проектом." % proj.where())
    for d in ("materials", "sources", "ledger", "strategy", "decisions", "analysis"):
        proj.path(d).mkdir(parents=True)
    write_text_atomic(proj.path("brief.md"), BRIEF_TEMPLATE.format(question=question.strip()))
    write_json(proj.path("done.json"), {"criteria": [], "budget_usd": 0})
    write_json(proj.path("state.json"), {"version": 1, "id": pid, "question": question.strip(),
                                         "created": today().isoformat(), "stage": 1,
                                         "open_questions": [], "gate": {"fails": 0, "fp": ""}})
    for rel in ("journal.jsonl", "ledger/claims.jsonl", "ledger/conclusions.jsonl", "cost.jsonl"):
        write_text_atomic(proj.path(rel), "")
    write_json(proj.path("levers.json"), {"levers": []})
    write_text_atomic(proj.path("options.md"), OPTIONS_TEMPLATE)
    for name in strat.STRATEGY_PARTS:
        write_text_atomic(proj.path("strategy", name), strat.template(name))
    write_text_atomic(proj.path("analysis", diag.DIAG_FILE), diag.diagnosis_template())
    write_text_atomic(proj.path("analysis", diag.LAYERS_FILE), diag.layers_template())
    reqs.save(proj, [])
    write_text_atomic(proj.path("page.md"), "# Итоговая страница\n\n" + PLACEHOLDER + "\n")
    write_text_atomic(proj.path("errors.md"), ERRORS_TEMPLATE)
    journal(proj, "new", {"question": question.strip()})
    return proj


# ---------------------------------------------------------------- этапы

def stage_show(proj):
    cur = read_state(proj)["stage"]
    lines = []
    for n in range(1, 9):
        mark = "сделан" if n < cur else ("ТЕКУЩИЙ" if n == cur else "впереди")
        stop = "  Остановка для человека №%d." % HUMAN_STOPS[n] if n in HUMAN_STOPS else ""
        lines.append("%d. %s (%s). Нужно для выхода: %s.%s" % (n, STAGE_NAMES[n], mark, STAGE_REQUIREMENTS[n], stop))
    return lines


def stage_next(proj, cfg, from_stage=None, answer=None):
    """Возвращает (код, строки). С from_stage повтор команды после перезапуска ничего не делает."""
    cur = read_state(proj)["stage"]
    if from_stage is not None:
        if not 1 <= from_stage <= 7:
            raise Fail("--from: номер этапа от 1 до 7, который закрываете.")
        if cur > from_stage:
            return 0, ["Этап %d уже закрыт, сейчас этап %d (%s). Повторно ничего не делаю." % (from_stage, cur, STAGE_NAMES[cur])]
        if cur < from_stage:
            raise Fail("Сейчас этап %d, а вы закрываете этап %d. Сначала закройте этап %d." % (cur, from_stage, cur))
    if cur >= 8:
        return 0, ["Этап 8 последний. Дальше только пересмотр: sweep и impact."]
    arts, res = stage_report(proj, cfg, cur)
    issues = list(arts) + [i for r in res for i in r.issues]
    if issues:
        out = ["Этап %d (%s) не закрыт. Не хватает:" % (cur, STAGE_NAMES[cur])]
        for i in issues:
            out.append("  - [%s] %s. Как исправить: %s." % (i["where"], i["what"], i["fix"]))
        out.append("Исправьте и повторите: python3 tools/rychag.py stage next")
        return 2, out
    need = cur in HUMAN_STOPS and common.stops_need_answer(cfg)
    answer = (answer or "").strip()
    if need and len(answer) < 2:
        return 3, ["Этап %d (%s): проверки пройдены, но дальше нельзя без ответа руководителя." % (cur, STAGE_NAMES[cur]),
                   common.stop_hint(cur)]
    if need:
        answers = dict(read_state(proj).get("stop_answers") or {})
        answers[str(cur)] = {"answer": answer, "date": today().isoformat()}
        set_state_field(proj, "stop_answers", answers)
        journal(proj, "stop answer", {"stage": cur, "stop": HUMAN_STOPS[cur], "answer": answer})
    set_state_field(proj, "stage", cur + 1)
    set_state_field(proj, "fail_track", None)
    guard_reset(proj)
    journal(proj, "stage next", {"from": cur, "to": cur + 1})
    out = ["Этап %d (%s) закрыт. Теперь этап %d из 8: %s." % (cur, STAGE_NAMES[cur], cur + 1, STAGE_NAMES[cur + 1])]
    if need:
        out.append("Ответ руководителя на остановке №%d записан." % HUMAN_STOPS[cur])
        if cur + 1 in HUMAN_STOPS:
            out.append(common.stop_hint(cur + 1))
        return 0, out
    if cur in HUMAN_STOPS:
        out.append("Остановка для человека №%d: покажите результат этапа руководителю и дождитесь ответа, "
                   "дальше без его решения не идите." % HUMAN_STOPS[cur])
    return 0, out


# ---------------------------------------------------------------- статус

def due_for_review(proj, cfg, horizon=14):
    out = []
    for d in load_decisions(proj):
        if d.get("status") == "заменено" or not d.get("review_date"):
            continue
        try:
            left = (parse_date(d["review_date"]) - today()).days
        except Fail:
            continue
        if left < 0:
            out.append("%s: пересмотр просрочен на %d дн. (срок %s)" % (d["id"], -left, d["review_date"]))
        elif left <= horizon:
            out.append("%s: пересмотр через %d дн. (срок %s)" % (d["id"], left, d["review_date"]))
        if d.get("doubt") == STATUS_DOUBT:
            out.append("%s: основания менялись, решение под вопросом" % d["id"])
    for m in list_sources(proj):
        if is_stale(m, cfg):
            out.append("%s: источник устарел (опубликован %s)" % (m["id"], m["published"]))
    for k in load_conclusions(proj):
        if k["status"] == STATUS_DOUBT:
            out.append("%s: вывод под вопросом" % k["id"])
    return out


def status_lines(proj, cfg):
    st = read_state(proj)
    cur = st["stage"]
    claims = load_claims(proj)
    concl = load_conclusions(proj)
    srcs = list_sources(proj)
    levers = load_levers(proj)
    decs = load_decisions(proj)
    done = load_done(proj)
    per, _, total = cost_summary(proj)
    arts, res = stage_report(proj, cfg, cur)

    out = ["Проект: %s" % proj.name, "Вопрос: %s" % st.get("question", ""),
           "Этап %d из 8: %s" % (cur, STAGE_NAMES[cur])]
    made = []
    if cur > 1:
        made.append("этапы 1-%d пройдены" % (cur - 1))
    made.append("источников %d" % len(srcs))
    made.append("рычагов %d" % len(levers))
    made.append("решений %d" % len(decs))
    if done["criteria"]:
        made.append("критериев «готово» выполнено %d из %d" % (sum(1 for c in done["criteria"] if c.get("met")), len(done["criteria"])))
    out.append("Сделано: " + "; ".join(made) + ".")
    spans = [(m["period_from"], m["period_to"]) for m in srcs if m.get("period_from") and not m.get("replaced_by")]
    if spans:
        out.append("Данные за период: с %s по %s." % (min(a for a, _b in spans), max(b for _a, b in spans)))
    qs = st.get("open_questions", [])
    if qs:
        out.append("Открытые вопросы:")
        for q in qs:
            out.append("  %d. %s (если да: %s; если нет: %s)" % (q["n"], q["text"], q["if_yes"], q["if_no"]))
    else:
        out.append("Открытые вопросы: нет.")
    for k, v in sorted((st.get("stop_answers") or {}).items()):
        out.append("Ответ руководителя на остановке №%d (этап %s): «%s»." % (HUMAN_STOPS[int(k)], k, common.short(v.get("answer", ""), 160)))

    nxt = None
    for i in arts:
        nxt = "%s. %s: %s." % (i["where"], i["what"], i["fix"])
        break
    if nxt is None:
        for r in res:
            if r.issues:
                i = r.issues[0]
                nxt = "[%s] %s. Как исправить: %s." % (i["where"], i["what"], i["fix"])
                break
    if nxt is None:
        if cur < 8:
            nxt = "проверки этапа пройдены. Выполните: python3 tools/rychag.py stage next"
            if cur in HUMAN_STOPS and common.stops_need_answer(cfg):
                nxt = "проверки этапа пройдены. " + common.stop_hint(cur)
            elif cur in HUMAN_STOPS:
                nxt += " (после показа результата руководителю: остановка №%d)" % HUMAN_STOPS[cur]
        else:
            nxt = "запускайте sweep по расписанию и пересматривайте решения в срок."
    out.append("Следующий шаг: " + nxt)
    budget = done.get("budget_usd") or 0
    det = cost_detail(proj)
    meas = sum(d["measured"] for d in det.values())
    est = sum(d["estimate"] for d in det.values())
    if meas:
        out.append("Потрачено: %.2f USD (замер %.2f, оценка агента %.2f; в бюджет идёт замер, где он есть)%s." % (
            total, meas, est, ", бюджет %.2f USD" % budget if budget else ""))
    else:
        out.append("Потрачено: %.2f USD (оценка)%s." % (total, ", бюджет %.2f USD" % budget if budget else ""))
    out.append(reqs.line(proj) + ".")
    out.append(incidents.status_line(proj))
    out.append("Исправлений выбора модели или метода: %d." % route.correction_count(proj))
    by_type = {}
    for c in claims:
        if c["type"] not in ("plan", "assumption"):
            by_type[c["type"]] = by_type.get(c["type"], 0) + 1
    out.append("Утверждения: %s." % (", ".join("%s %d" % (t, n) for t, n in sorted(by_type.items())) or "нет"))
    out.append("Параметры плана (наш выбор, не доказательства): %d." % sum(1 for c in claims if c["type"] == "plan"))
    acts = [c for c in claims if c["type"] == "assumption" and c["status"] == STATUS_OK]
    if acts:
        out.append("Допущения (приняты до проверки): %d, без порога смены решения: %d. Сводка: python3 tools/rychag.py claim assumptions" % (
            len(acts), sum(1 for c in acts if not (c.get("range") or {}).get("switch"))))
    from . import document
    if document.exists(proj):
        d = document.load(proj)
        ps = document.Parsed(proj, d)
        out.append("Документ по частям заказчика (%s): заполнено частей %d из %d. Проверка: python3 tools/rychag.py doc check" % (
            document.DOC_FILE, sum(1 for i in range(len(d["parts"])) if ps.part_words(i) >= document.MIN_WORDS), len(d["parts"])))
    by_st = {}
    for k in concl:
        by_st[k["status"]] = by_st.get(k["status"], 0) + 1
    out.append("Выводы: %s." % (", ".join("%s %d" % (t, n) for t, n in sorted(by_st.items())) or "нет"))
    out.append(support_line(support_counts(proj)) + ".")
    out.append("База знаний: действующих записей %d. Ориентиров в проекте: %d." % (
        kbase.active_count(proj.root), sum(1 for c in claims if c["type"] == "benchmark")))
    from . import kbmap
    nn, nl, na, nh = kbmap.counts(proj.root)
    out.append("Карта причин: узлов %d, связей %d (действует %d, гипотез %d). Гипотез проекта из карты: %d." % (
        nn, nl, na, nh, sum(1 for c in claims if c.get("from_map"))))
    due = due_for_review(proj, cfg)
    out.append("Пора пересмотреть: " + ("; ".join(due) if due else "ничего."))
    return out


# ---------------------------------------------------------------- расход

def cost_report_lines(proj):
    det = cost_detail(proj)
    if not det:
        return ["Расход пока не записан. Запись оценки: python3 tools/rychag.py cost log --stage 3 --usd 0.5; "
                "замер из отчёта сессии: python3 tools/rychag.py cost import-session отчёт.json --stage 3"]
    out = ["Расход по этапам (замер: из отчёта сессии; оценка агента: то, что агент назвал сам):"]
    warns = []
    for s in sorted(det):
        d = det[s]
        parts = []
        if d["has_measured"]:
            parts.append("замер %.2f USD" % d["measured"])
        if d["estimate"]:
            parts.append("оценка агента %.2f USD" % d["estimate"])
        tk = ", токенов %d" % d["tokens"] if d["tokens"] else ""
        out.append("  Этап %d (%s): %s%s" % (s, STAGE_NAMES[s], "; ".join(parts) or "0.00 USD", tk))
        if d["has_measured"] and d["estimate"] and d["measured"] > 0 and abs(d["estimate"] - d["measured"]) / d["measured"] > 0.2:
            warns.append("Этап %d: оценка агента %.2f USD расходится с замером %.2f USD на %d процентов. Верьте замеру, оценку агента впредь делайте точнее." % (
                s, d["estimate"], d["measured"], round(abs(d["estimate"] - d["measured"]) / d["measured"] * 100)))
    meas = sum(d["measured"] for d in det.values())
    est = sum(d["estimate"] for d in det.values())
    ms = sum(d["ms"] for d in det.values())
    turns = sum(d["turns"] for d in det.values())
    per, _tk, total = cost_summary(proj)
    out.append("Итого замер: %.2f USD. Итого оценка агента: %.2f USD." % (meas, est))
    if ms or turns:
        out.append("Время работы модели по замерам: %s, ходов: %d." % (_dur(ms), turns))
    else:
        out.append("Замеров по сессиям пока нет: время и число ходов неизвестны.")
    budget = load_done(proj).get("budget_usd") or 0
    out.append("Принято к бюджету (замер, где он есть, иначе оценка): %.2f USD%s." % (
        total, ", бюджет %.2f USD, осталось %.2f" % (budget, budget - total) if budget else ""))
    out.append("Исправлений выбора модели или метода: %d." % route.correction_count(proj))
    for w in warns:
        out.append("Предупреждение: " + w)
    return out


def _dur(ms):
    sec = ms / 1000.0
    if sec < 90:
        return "%.0f с" % sec
    return "%d мин %02d с" % (sec // 60, sec % 60)


# ---------------------------------------------------------------- журнал простыми словами

def _journal_text(cmd, d):
    d = d or {}
    g = d.get
    m = {
        "new": lambda: "Создана задача.",
        "source add": lambda: "Сохранён источник %s (%s)%s." % (g("id"), g("kind"), ", заменяет %s" % g("replaces") if g("replaces") else ""),
        "source set-layer": lambda: "У источника %s слой изменён с %s на %s." % (g("id"), g("from"), g("to")),
        "source accept-stale": lambda: "Старый источник %s признан допустимым: %s." % (g("id"), g("reason")),
        "claim add": lambda: "Добавлено утверждение %s (%s)." % (g("id"), g("type")),
        "claim reject": lambda: "Утверждение %s отброшено: %s." % (g("id"), g("reason")),
        "conclusion add": lambda: "Добавлен вывод %s (%s)." % (g("id"), g("kind")),
        "conclusion set-status": lambda: "Вывод %s получил статус «%s»." % (g("id"), g("status")),
        "lever add": lambda: "Добавлен рычаг %s." % g("id"),
        "lever set-status": lambda: "Рычаг %s: статус «%s»." % (g("id"), g("to")),
        "decision add": lambda: "Записано решение %s." % g("id"),
        "decision set-status": lambda: "Решение %s: статус «%s»." % (g("id"), g("status")),
        "calc run": lambda: "Выполнен расчёт %s, сохранён как источник %s." % (g("script"), g("id")),
        "calc ready": lambda: "Выполнен готовый расчёт «%s» по параметрам %s, сохранён как источник %s." % (g("kind"), g("params"), g("id")),
        "doc init": lambda: "Задана структура документа заказчика: частей %s, обязательных элементов начала %s." % (g("parts"), g("opening")),
        "doc page": lambda: "Страница для руководителя собрана из начала документа.",
        "cost log": lambda: "Записан расход этапа %s: %s USD (%s)." % (g("stage"), g("usd"), g("kind") or "оценка агента"),
        "cost import-session": lambda: "Импортирован замер сессии %s: %s USD, этапы %s." % (g("session"), g("added_usd"), g("stages")),
        "done add": lambda: "Добавлен критерий готовности %s." % g("id"),
        "done mark": lambda: "Критерий %s %s." % (g("id"), "выполнен" if g("met") else "снят"),
        "done budget": lambda: "Задан бюджет %s USD." % g("usd"),
        "question add": lambda: "Задан вопрос руководителю №%s." % g("n"),
        "question close": lambda: "Закрыт вопрос руководителю №%s." % g("n"),
        "stage next": lambda: "Переход с этапа %s на этап %s." % (g("from"), g("to")),
        "impact": lambda: "Проверено, что задето: поставлен статус «под вопросом» у %s." % (", ".join(g("marked") or []) or "никого"),
        "gate": lambda: "Замок: %s." % g("result"),
        "req add": lambda: "Записано требование %s." % g("id"),
        "req close": lambda: "Требование %s закрыто (%s)%s." % (g("id"), g("by"), ", место: %s" % g("where") if g("where") else ""),
        "req drop": lambda: "Требование %s снято: %s." % (g("id"), g("reason")),
        "req note": lambda: "Сохранено новое сообщение человека в requests.md.",
        route.CORRECTION: lambda: "Исправление выбора на этапе %s: %s." % (g("stage"), g("how")),
        "feedback add": lambda: "Записан отзыв руководителя.",
        "incident add": lambda: "Записано происшествие %s (%s): %s" % (g("id"), g("kind"), g("what")),
        "kb search": lambda: "Поиск по базе знаний «%s»%s: найдено %s." % (g("query") or "", ", слой %s" % g("layer") if g("layer") else "", g("results")),
        "kb show": lambda: "Открыта запись базы знаний %s%s." % (g("id"), "" if g("results") else " (не найдена)"),
        "map causes": lambda: "Карта причин, что влияет на «%s»: %s." % (g("query"), "связей %s" % g("results") if g("node") else "узла на карте нет"),
        "map effects": lambda: "Карта причин, на что влияет «%s»: %s." % (g("query"), "связей %s" % g("results") if g("node") else "узла на карте нет"),
        "map path": lambda: "Карта причин, цепочки %s: найдено %s." % (g("query"), g("results")),
        "state receipt": lambda: "Выдана строка состояния (контрольная сумма %s)." % g("sum"),
        "outcome add": lambda: "Записан фактический результат решения.",
    }
    f = m.get(cmd)
    try:
        return f() if f else "%s." % cmd
    except Exception:
        return "%s." % cmd


def journal_lines(proj, n):
    """Последние n шагов журнала простыми словами."""
    rows = read_jsonl(proj.path("journal.jsonl"))
    if not rows:
        return ["Журнал пуст: ничего ещё не сделано."]
    take = rows[-n:]
    out = ["Последние шаги (%d из %d), старые сверху. В скобках короткий номер шага:" % (len(take), len(rows))]
    for r in take:
        out.append("  %s [%s] %s" % ((r.get("ts") or "")[:16].replace("T", " "), r.get("h") or "без номера",
                                     _journal_text(r.get("cmd"), r.get("detail"))))
    out.append("Что уже сделано, повторно не делайте: проверьте списки source list, claim list, conclusion list, req list.")
    return out


# ---------------------------------------------------------------- doctor

def doctor(root, cfg_loader):
    """Возвращает (код, строки)."""
    lines, bad = [], 0

    def row(ok, text, fix=""):
        nonlocal bad
        lines.append("%s: %s%s" % ("OK" if ok else "ПРОБЛЕМА", text, "" if ok else ". Как исправить: " + fix))
        if not ok:
            bad += 1

    v = sys.version_info
    row(v >= (3, 9), "Python %d.%d.%d" % v[:3], "нужен Python 3.9 или новее")
    try:
        projects_dir = os.path.join(str(root), "projects")
        os.makedirs(projects_dir, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=projects_dir, prefix=".doctor-")
        os.close(fd)
        os.remove(tmp)
        row(True, "запись в папку projects/ возможна")
    except OSError as e:
        row(False, "нет права записи в projects/ (%s)" % e, "проверьте права на папку или запускайте из своей копии")
    probs = validate_config(root)
    row(not probs, "настройки config/ в порядке" if not probs else "настройки config/: " + "; ".join(probs),
        "исправьте файлы в config/ (подсказки в config/README.md)")
    ex = Project(root, "_example")
    if not ex.dir.exists():
        row(False, "нет примера projects/_example", "восстановите папку из поставки")
    elif probs:
        row(False, "пример _example не проверен: сначала исправьте настройки", "исправьте config/ и повторите doctor")
    else:
        cfg = cfg_loader(root)
        res = run_layers(ex, cfg)
        fails = sum(len(r.issues) for r in res)
        row(fails == 0, "пример _example проходит verify" if not fails else
            "пример _example не проходит verify (%d замечаний)" % fails,
            "выполните: python3 tools/rychag.py verify --project _example")
    lines.append("Проектов в работе: %d." % len([p for p in find_projects(root) if not p.startswith("_")]))
    lines.append("Всё в порядке." if not bad else "Проблем: %d." % bad)
    return (0 if not bad else 2), lines
