# -*- coding: utf-8 -*-
"""Обязательные части стратегий и плана проверки: какие заголовки должны быть и что под ними написано."""
import re

from .common import PLACEHOLDER, norm_match, read_text

# файл -> (название документа, [(обязательный заголовок, подсказка для шаблона)])
STRATEGY_PARTS = {
    "product.md": ("Продуктовая стратегия", [
        ("Аудитория и её задача", "Кто эти люди и какую задачу они решают с помощью продукта. Только то, что подтверждено материалами."),
        ("Альтернативы", "Чем люди решают эту задачу сейчас, кроме нашего продукта, и почему часть выбирает их."),
        ("Выбранное направление", "Что именно делаем и для какой части аудитории. Одно направление, не список."),
        ("От чего отказываемся", "Что осознанно не делаем и почему. Отказ без причины не считается."),
        ("Связь пользы с затратами и доходами", "Как польза для человека превращается в затраты и доход компании, с числами из реестра."),
    ]),
    "communication.md": ("Коммуникационная стратегия", [
        ("Аудитория и ситуация", "Кому говорим и в какой момент человек нас слышит."),
        ("Что мешает понять или выбрать", "Какой барьер стоит между человеком и решением: непонимание, недоверие, цена, привычка."),
        ("Ключевое сообщение", "Одна фраза, которую человек должен унести. Обещание не больше того, что умеет продукт."),
        ("Чем подтверждаем", "Какие факты о продукте стоят за сообщением. Каждое обещание держится на факте."),
        ("Роль каналов", "Что делает каждый канал: привлекает, объясняет, убеждает или удерживает."),
    ]),
    "test-plan.md": ("План проверки", [
        ("Ожидаемое изменение", "Какой показатель и на сколько должен измениться, в трёх вариантах с пометкой «оценка»."),
        ("С чем сравниваем", "Контрольная группа, прошлый период или другое сравнение, и почему оно честное."),
        ("Срок наблюдения", "Сколько времени смотрим и когда принимаем решение."),
        ("Нежелательные последствия", "Что может ухудшиться из-за изменения и какое значение показателя останавливает проверку."),
    ]),
}

HINT_PREFIX = "> Подсказка:"


def template(filename):
    """Текст файла стратегии для новой задачи: заголовки и одна строка подсказки под каждым."""
    title, parts = STRATEGY_PARTS[filename]
    out = ["# %s" % title, "",
           "Под каждым заголовком напишите хотя бы одно законченное предложение. Подсказку и пометку замените своим текстом.", ""]
    for head, hint in parts:
        out += ["## " + head, "", "%s %s" % (HINT_PREFIX, hint), PLACEHOLDER, ""]
    return "\n".join(out)


def _head_key(text):
    t = re.sub(r"^[\s*_`\d.)\-]+", "", text)
    return norm_match(t.replace("*", "").replace("_", ""))


def _body_text(lines):
    keep = []
    for ln in lines:
        s = ln.strip()
        if not s or PLACEHOLDER in s or s.startswith(HINT_PREFIX) or re.match(r"^#{1,6}\s", s):
            continue
        keep.append(s)
    return " ".join(keep)


def sections_of(path):
    """Разбор файла на заголовки: [[уровень, ключ, строки]]."""
    heads = []
    cur = None
    for ln in read_text(path).split("\n"):
        m = re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", ln)
        if m:
            cur = [len(m.group(1)), _head_key(m.group(2)), []]
            heads.append(cur)
        elif cur is not None:
            cur[2].append(ln)
    return heads


def section_body(heads, head):
    """Текст под заголовком (по первым словам, без учёта регистра) вместе с вложенными разделами. None, если заголовка нет."""
    key = norm_match(head)
    found = None
    for i, hd in enumerate(heads):
        if hd[1].startswith(key):
            found = i
            break
    if found is None:
        return None
    lvl = heads[found][0]
    lines = list(heads[found][2])
    for hd in heads[found + 1:]:
        if hd[0] <= lvl:
            break
        lines.append("#" * hd[0] + " x")
        lines += hd[2]
    return lines


def part_states(proj, filename):
    """Список (заголовок, состояние, пояснение). Состояние: «есть», «пусто», «нет раздела», «нет файла»."""
    _title, parts = STRATEGY_PARTS[filename]
    path = proj.path("strategy", filename)
    if not path.exists():
        return [(h, "нет файла", "нет файла strategy/" + filename) for h, _ in parts]
    heads = sections_of(path)
    out = []
    for head, _hint in parts:
        lines = section_body(heads, head)
        if lines is None:
            out.append((head, "нет раздела", "нет заголовка «%s»" % head))
            continue
        text = _body_text(lines)
        if len(re.findall(r"\w+", text)) < 3:
            out.append((head, "пусто", "под заголовком «%s» нет ни одного предложения" % head))
        else:
            out.append((head, "есть", ""))
    return out


def issues(proj):
    """Список замечаний (где, что, как исправить) по всем трём файлам."""
    res = []
    for fn in STRATEGY_PARTS:
        where = proj.where("strategy", fn)
        for head, st, why in part_states(proj, fn):
            if st == "есть":
                continue
            if st == "нет файла":
                res.append((where, "нет файла", "создайте файл с разделами по шаблону (команда new делает такой шаблон) и заполните «%s»" % head))
            else:
                res.append((where, "не хватает части «%s»: %s" % (head, why),
                            "добавьте заголовок «## %s» и под ним хотя бы одно предложение" % head))
    return res


def check_lines(proj):
    """Строки для команды strategy check и число недостающих частей."""
    lines, missing = [], 0
    for fn, (title, _parts) in STRATEGY_PARTS.items():
        sts = part_states(proj, fn)
        ok = sum(1 for _h, s, _w in sts if s == "есть")
        lines.append("%s (strategy/%s): заполнено %d из %d" % (title, fn, ok, len(sts)))
        for head, st, _why in sts:
            lines.append("  %s: %s" % (head, "заполнено" if st == "есть" else
                                       {"пусто": "заголовок есть, текста нет", "нет раздела": "нет такого заголовка",
                                        "нет файла": "нет файла"}[st]))
            if st != "есть":
                missing += 1
    return lines, missing
