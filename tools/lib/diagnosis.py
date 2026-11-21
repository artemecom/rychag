# -*- coding: utf-8 -*-
"""Полнота диагноза (analysis/diagnoz.md) и прохождение слоёв близости (analysis/sloi.md): обязательные заголовки и что под ними."""
import re

from .common import PLACEHOLDER, norm_match
from . import strategy as st
from . import kb as kbase
from . import trace
from .ledger import load_claims, load_conclusions

DIAG_FILE = "diagnoz.md"
LAYERS_FILE = "sloi.md"
FROM_STAGE = 4  # с этого этапа обе проверки обязательны

DIAGNOSIS_PARTS = [
    ("Что произошло с показателем", "Какой показатель, на сколько и когда изменился, с числами из реестра."),
    ("Шум и сезонность", "Как показатель колебался раньше и бывает ли в эти месяцы сезонный спад: изменение должно быть больше обычных колебаний."),
    ("Что менялось в эти даты", "Что менялось в продукте, ценах, рекламе и у конкурентов на дату начала просадки."),
    ("Где сосредоточено изменение", "В каких срезах (платформа, тариф, регион, когорта) просадка видна сильнее всего."),
    ("Вклад среза", "Какую долю общей просадки даёт этот срез и какая доля это от всей аудитории."),
    ("Проверка на срезе, которого причина не касается", "Что происходит там, где предполагаемая причина не действует: если там тоже просадка, причина другая."),
    ("Вероятная причина и уверенность", "Одна причина и честная уверенность: высокая, средняя или низкая, и почему."),
    ("Отброшенные причины", "Какие причины рассматривали и почему отвергли, по одной строке на причину."),
    ("Чего не знаем", "Каких данных не хватает и кого или что нужно спросить, чтобы уверенность выросла."),
    ("За какой период данные", "Две даты: с какой по какую взяты данные диагноза, например 2025-01-01 и 2025-06-30."),
]
NO_SEARCH_TEXT = "Слой помечен пустым без поиска по базе знаний"
PERIOD_HEAD = "За какой период данные"

LAYER_PARTS = [
    (1, "Данные самого продукта", "Что нашли в выгрузках самого продукта и как использовали: коды утверждений или записей."),
    (2, "Данные компании", "Что есть у компании вокруг продукта (поддержка, продажи, другие продукты): коды или «Пусто, потому что ...»."),
    (3, "Другие компании в России", "Опыт российских компаний из базы знаний (коды записей) или «Пусто, потому что ...»."),
    (4, "Компании в мире", "Опыт зарубежных компаний из базы знаний (коды записей) или «Пусто, потому что ...»."),
    (5, "Смежные отрасли", "Что подсказывают смежные отрасли (коды записей) или «Пусто, потому что ...»."),
]
EMPTY_RX = re.compile(r"^\W*пусто,\s*потому\s*что\s+(\S.*)$", re.I)
ID_RX = re.compile(r"(?<![\w/.\-])([BCK]\d{3,})(?!\w)")

_MONTHS = "январ|феврал|март|апрел|ма[йя]|июн|июл|август|сентябр|октябр|ноябр|декабр"
DATE_RX = re.compile(r"\d{1,2}\.\d{1,2}\.\d{4}|\d{4}-\d{2}(?:-\d{2})?|(?:\d{1,2}\s+)?(?:%s)[а-я]*\s+\d{4}" % _MONTHS, re.I)


def diagnosis_template():
    out = ["# Диагноз", "",
           "Под каждым заголовком напишите хотя бы одно законченное предложение. Подсказку и пометку замените своим текстом.", ""]
    for head, hint in DIAGNOSIS_PARTS:
        out += ["## " + head, "", "%s %s" % (st.HINT_PREFIX, hint), PLACEHOLDER, ""]
    return "\n".join(out)


def layers_template():
    out = ["# Слои близости", "",
           "Пройдите слои по порядку от 1 до 5. Под каждым заголовком: коды записей (утверждения C..., выводы K... или записи базы знаний B...), "
           "что найдено и как использовано, либо строка «Пусто, потому что ...» с причиной.", ""]
    for _n, head, hint in LAYER_PARTS:
        out += ["## " + head, "", "%s %s" % (st.HINT_PREFIX, hint), PLACEHOLDER, ""]
    return "\n".join(out)


def diagnosis_states(proj):
    """[(заголовок, состояние, пояснение)]. Состояние: «есть», «пусто», «нет раздела», «нет файла», «нет дат»."""
    path = proj.path("analysis", DIAG_FILE)
    if not path.exists():
        return [(h, "нет файла", "нет файла analysis/" + DIAG_FILE) for h, _ in DIAGNOSIS_PARTS]
    heads = st.sections_of(path)
    out = []
    for head, _hint in DIAGNOSIS_PARTS:
        lines = st.section_body(heads, head)
        if lines is None:
            out.append((head, "нет раздела", "нет заголовка «%s»" % head))
            continue
        text = st._body_text(lines)
        if len(re.findall(r"\w+", text)) < 3:
            out.append((head, "пусто", "под заголовком «%s» нет ни одного предложения" % head))
        elif head == PERIOD_HEAD and len(DATE_RX.findall(text)) < 2:
            out.append((head, "нет дат", "под заголовком «%s» нужны две даты: с какой по какую, например 2025-01-01 и 2025-06-30" % head))
        else:
            out.append((head, "есть", ""))
    return out


def layers_states(proj):
    """[(номер слоя, заголовок, состояние, пояснение)]. Состояние: «есть», «пусто, причина записана», «пусто», «нет раздела», «нет файла», «нет записи»."""
    path = proj.path("analysis", LAYERS_FILE)
    if not path.exists():
        return [(n, h, "нет файла", "нет файла analysis/" + LAYERS_FILE) for n, h, _ in LAYER_PARTS]
    claims = {c["id"] for c in load_claims(proj)}
    concl = {k["id"] for k in load_conclusions(proj)}
    recs = {r["id"] for r in kbase.load_records(proj.root)}
    heads = st.sections_of(path)
    out = []
    for n, head, _hint in LAYER_PARTS:
        lines = st.section_body(heads, head)
        if lines is None:
            out.append((n, head, "нет раздела", "нет заголовка «%s»" % head))
            continue
        body = [l.strip() for l in lines if l.strip() and PLACEHOLDER not in l and not l.strip().startswith(st.HINT_PREFIX)
                and not re.match(r"^#{1,6}\s", l.strip())]
        if any(EMPTY_RX.match(re.sub(r"^[-*\d.)\s]+", "", l)) for l in body):
            if n >= 3 and not trace.searched_layer(proj, n):
                out.append((n, head, "пусто без поиска", NO_SEARCH_TEXT))
            else:
                out.append((n, head, "пусто, причина записана", ""))
            continue
        ids = [i for l in body for i in ID_RX.findall(l)]
        known = [i for i in ids if i in claims or i in concl or i in recs]
        if known:
            out.append((n, head, "есть", ""))
        elif ids:
            out.append((n, head, "нет записи", "кода %s нет ни в реестре, ни в базе знаний" % ids[0]))
        else:
            out.append((n, head, "пусто", "под заголовком «%s» нет ни кода записи, ни строки «Пусто, потому что ...»" % head))
    return out


def diagnosis_issues(proj):
    """Замечания (где, что, как исправить) для слоя 3."""
    res = []
    where = proj.where("analysis", DIAG_FILE)
    for head, s, why in diagnosis_states(proj):
        if s == "есть":
            continue
        if s == "нет файла":
            if not any(w[0] == where for w in res):
                res.append((where, "нет файла диагноза", "создайте analysis/%s с разделами по шаблону (команда new делает такой шаблон)" % DIAG_FILE))
        elif s == "нет дат":
            res.append((where, "не хватает части «%s»: %s" % (head, why), "впишите под заголовком две даты: начало и конец периода данных"))
        else:
            res.append((where, "не хватает части «%s»: %s" % (head, why), "добавьте заголовок «## %s» и под ним хотя бы одно предложение" % head))
    return res


def layers_issues(proj):
    res = []
    where = proj.where("analysis", LAYERS_FILE)
    for _n, head, s, why in layers_states(proj):
        if s in ("есть", "пусто, причина записана"):
            continue
        if s == "нет файла":
            if not any(w[0] == where for w in res):
                res.append((where, "нет файла прохода по слоям близости", "создайте analysis/%s с пятью разделами по шаблону (команда new делает такой шаблон)" % LAYERS_FILE))
        elif s == "пусто без поиска":
            res.append((where, "слой «%s»: %s" % (head, why),
                        "выполните: python3 tools/rychag.py kb search \"%s\" --layer %d --project %s, затем перечитайте результат и обновите раздел" % (
                            trace.question_words(proj), _n, proj.name)))
        elif s == "нет записи":
            res.append((where, "слой «%s»: %s" % (head, why), "укажите существующий код записи или замените строкой «Пусто, потому что ...»"))
        else:
            res.append((where, "слой «%s»: %s" % (head, why),
                        "добавьте заголовок «## %s» и под ним код записи из реестра или базы знаний либо строку «Пусто, потому что ...» с причиной" % head))
    return res


def diagnosis_lines(proj):
    sts = diagnosis_states(proj)
    ok = sum(1 for _h, s, _w in sts if s == "есть")
    lines = ["Диагноз (analysis/%s): заполнено %d из %d" % (DIAG_FILE, ok, len(sts))]
    words = {"пусто": "заголовок есть, текста нет", "нет раздела": "нет такого заголовка", "нет файла": "нет файла",
             "нет дат": "нет двух дат периода"}
    for head, s, _w in sts:
        lines.append("  %s: %s" % (head, "заполнено" if s == "есть" else words[s]))
    return lines, len(sts) - ok


def map_issues(proj):
    """С этапа 4 диагноз обязан заглянуть в карту причин: в журнале нужен хотя бы один запрос map causes или map effects."""
    if trace.map_consulted(proj):
        return []
    return [(proj.where("journal.jsonl"), "карта причин не открывалась: в журнале нет ни map causes, ни map effects",
             "выполните: python3 tools/rychag.py map causes \"%s\" --project %s. Если узла для слов вопроса на карте нет, команда это скажет, и запрос всё равно засчитается" % (
                 trace.question_words(proj), proj.name))]


def layers_lines(proj):
    sts = layers_states(proj)
    ok = sum(1 for _n, _h, s, _w in sts if s in ("есть", "пусто, причина записана"))
    lines = ["Проход по слоям близости (analysis/%s): готово %d из %d" % (LAYERS_FILE, ok, len(sts))]
    words = {"есть": "есть записи", "пусто, причина записана": "пусто, причина записана", "пусто": "ни записей, ни причины",
             "нет раздела": "нет такого заголовка", "нет файла": "нет файла", "нет записи": "указан несуществующий код",
             "пусто без поиска": "помечен пустым без поиска по базе знаний"}
    for n, head, s, _w in sts:
        lines.append("  Слой %d. %s: %s" % (n, head, words[s]))
        if s == "пусто без поиска":
            lines.append("    %s. Выполните: python3 tools/rychag.py kb search \"%s\" --layer %d --project %s" % (
                NO_SEARCH_TEXT, trace.question_words(proj), n, proj.name))
    return lines, len(sts) - ok
