#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Рычаг: одна программа со всеми командами. Только стандартная библиотека Python 3.9+.

Запуск: python3 tools/rychag.py <команда> [параметры]. Справка: --help у любой команды.
Коды возврата: 0 всё хорошо, 2 проверки не пройдены, 1 ошибка использования или внутренняя.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import common, sources, ledger, checks, graph, stages, kb as kbase, layers, kbmap, learn, reqs, route, strategy, diagnosis, incidents, receipt, trace  # noqa: E402
from lib import calcs, document  # noqa: E402
from lib.common import Fail, resolve_project, load_config, default_root  # noqa: E402

PROG = "python3 tools/rychag.py"


# ---------------------------------------------------------------- разбор параметров

class RFormatter(argparse.HelpFormatter):
    def add_usage(self, usage, actions, groups, prefix=None):
        return super().add_usage(usage, actions, groups, prefix or "Использование: ")


_TRANSLATE = [
    ("the following arguments are required:", "не указаны обязательные параметры:"),
    ("unrecognized arguments:", "лишние параметры:"),
    ("invalid choice:", "недопустимое значение:"),
    ("expected one argument", "после параметра нужно значение"),
    ("invalid int value:", "нужно целое число, получено:"),
    ("invalid float value:", "нужно число, получено:"),
    ("not allowed with argument", "нельзя вместе с параметром"),
    ("argument", "параметр"),
]


class RParser(argparse.ArgumentParser):
    def __init__(self, *a, **kw):
        kw["add_help"] = False
        kw.setdefault("formatter_class", RFormatter)
        argparse.ArgumentParser.__init__(self, *a, **kw)
        self._positionals.title = "Аргументы"
        self._optionals.title = "Параметры"
        self.add_argument("-h", "--help", action="help", default=argparse.SUPPRESS,
                          help="показать справку и выйти")

    def error(self, message):
        for a, b in _TRANSLATE:
            message = message.replace(a, b)
        sys.stderr.write("Ошибка: %s\nСправка: %s --help\n" % (message, self.prog))
        raise SystemExit(1)


def build_parser():
    p = RParser(prog=PROG, description="Рычаг: агент и проверки для разбора просадки показателя. "
                                       "Одна программа, все команды. Подробнее у каждой команды: --help.")
    p.add_argument("--root", help="корень репозитория (по умолчанию папка над tools/)")
    p.add_argument("--today", metavar="ГГГГ-ММ-ДД", help="подменить сегодняшнюю дату (для проверок и тестов)")
    sub = p.add_subparsers(dest="cmd", title="Команды", metavar="<команда>")
    sub.required = True

    def add(name, help_, **kw):
        sp = sub.add_parser(name, help=help_, description=help_, prog="%s %s" % (PROG, name), **kw)
        return sp

    def proj_opt(sp):
        sp.add_argument("--project", "-p", metavar="ID", help="код задачи (можно опустить, если задача одна)")

    sp = add("new", "создать папку задачи projects/<id>/ со всеми файлами, этап 1")
    sp.add_argument("id", help="код задачи: буквы, цифры, «_» и «-»")
    sp.add_argument("--question", required=True, help="размытый вопрос руководителя, как он его задал")

    sp = add("status", "где мы: этап, сделано, вопросы, следующий шаг, расход, счётчики, что пора пересмотреть")
    proj_opt(sp)
    sp.add_argument("--journal", type=int, metavar="N", help="показать последние N шагов журнала простыми словами (после перерыва: что уже сделано)")
    sp.add_argument("--receipt", action="store_true",
                    help="одна строка состояния с контрольной суммой: агент вставляет её в конец ответа, руками её не пишут")
    sp.add_argument("--check-receipt", metavar="СТРОКА",
                    help="проверить строку состояния: совпадает ли она с текущим состоянием или с более ранним записанным (код 2, если не совпадает)")

    sp = add("incident", "происшествия: add (записать), list. Всё, о чём агент сообщает как о случившемся, оставляет след в errors.md и в журнале")
    ssub = sp.add_subparsers(dest="sub", title="Действия", metavar="<действие>")
    ssub.required = True
    s2 = ssub.add_parser("add", help="записать происшествие в errors.md и в журнал", prog=PROG + " incident add",
                         description="Добавляет запись I001... с датой в errors.md в фиксированном формате и строку в журнал. "
                                     "Вручную в errors.md не пишите: агент, который сообщил «записал», обязан иметь здесь номер записи.")
    proj_opt(s2)
    s2.add_argument("--kind", required=True, choices=incidents.KINDS, help="вид происшествия")
    s2.add_argument("--what", required=True, help="что произошло, простыми словами")
    s2.add_argument("--caught-by", metavar="КТО_ЗАМЕТИЛ", help="кто или что заметило: проверка, руководитель, сам агент")
    s2.add_argument("--fix", help="что исправлено или какая проверка теперь это ловит")
    s2.add_argument("--source", metavar="S003", help="источник проекта, к которому относится происшествие")
    s2 = ssub.add_parser("list", help="список происшествий", description="Список происшествий, включая записанные вручную.",
                         prog=PROG + " incident list")
    proj_opt(s2)

    sp = add("stage", "этапы: show (список) и next (перейти дальше, если проверки пройдены)")
    ssub = sp.add_subparsers(dest="sub", title="Действия", metavar="<действие>")
    ssub.required = True
    for n, h in (("next", "перейти на следующий этап, если выполнено всё нужное"),
                 ("show", "показать все этапы и что нужно для выхода из каждого")):
        s2 = ssub.add_parser(n, help=h, description=h, prog="%s stage %s" % (PROG, n))
        proj_opt(s2)
        if n == "next":
            s2.add_argument("--from", dest="from_stage", type=int, metavar="N",
                            help="номер этапа, который закрываете: если он уже закрыт (повтор после перерыва), команда ничего не делает")
            s2.add_argument("--answer", metavar="\"слова руководителя\"",
                            help="ответ руководителя на остановке (этапы 1, 2, 5, 7): без него с остановки дальше не перейти")

    sp = add("source", "источники: add (сохранить копию), list, accept-stale")
    ssub = sp.add_subparsers(dest="sub", title="Действия", metavar="<действие>")
    ssub.required = True
    s2 = ssub.add_parser("add", help="сохранить копию источника с датами",
                         description="Сохраняет нормализованную копию текста в sources/S001.txt и паспорт S001.meta.json. "
                                     "Проверяет разрешённый список сайтов, потолок на вопрос и свежесть.",
                         prog=PROG + " source add")
    proj_opt(s2)
    s2.add_argument("--url", help="адрес страницы")
    s2.add_argument("--text-file", metavar="ФАЙЛ", help="файл с текстом страницы или расшифровкой медиафайла (внутри папки проекта)")
    s2.add_argument("--fetch", action="store_true", help="скачать страницу самому (нужна сеть; HTML очищается от тегов)")
    s2.add_argument("--file", metavar="ПУТЬ", help="файл из projects/<id>/materials/")
    s2.add_argument("--kind", choices=["файл", "собеседник", "агент"],
                    help="вид файла-источника: ответ ИИ-собеседника и вывод агента не годятся как основание факта")
    s2.add_argument("--published", metavar="ГГГГ[-ММ[-ДД]]", help="дата публикации: год, месяц или день (без неё свежесть не проверить: предупреждение)")
    s2.add_argument("--title", help="название источника")
    s2.add_argument("--question", help="к какому подвопросу относится (для потолка источников)")
    s2.add_argument("--allow-stale", action="store_true", help="принять источник старше порога (запись в журнал)")
    s2.add_argument("--layer", type=int, metavar="N",
                    help="слой близости 1-5 (%s). Для файлов из materials/ по умолчанию 1, для страниц из сети обязателен" % common.LAYER_HELP)
    s2.add_argument("--period-from", metavar="ГГГГ-ММ-ДД", help="начало периода, за который данные источника (вместе с --period-to)")
    s2.add_argument("--period-to", metavar="ГГГГ-ММ-ДД", help="конец периода, за который данные источника")
    s2 = ssub.add_parser("list", help="список источников", description="Список источников.", prog=PROG + " source list")
    proj_opt(s2)
    s2 = ssub.add_parser("set-layer", help="сменить слой близости источника", description="Меняет слой близости источника. Слои: %s." % common.LAYER_HELP,
                         prog=PROG + " source set-layer")
    proj_opt(s2)
    s2.add_argument("id", help="код источника, например S003")
    s2.add_argument("--layer", type=int, required=True, metavar="N", help="слой 1-5")
    s2 = ssub.add_parser("accept-stale", help="признать старый источник допустимым",
                         description="Снимает проверку свежести с источника, причина записывается.",
                         prog=PROG + " source accept-stale")
    proj_opt(s2)
    s2.add_argument("id", help="код источника, например S001")
    s2.add_argument("--reason", required=True, help="почему старые данные допустимы")

    sp = add("claim", "утверждения: add, reject, list, assumptions (сводка допущений)")
    ssub = sp.add_subparsers(dest="sub", title="Действия", metavar="<действие>")
    ssub.required = True
    s2 = ssub.add_parser("add", help="добавить утверждение (для факта нужна дословная цитата)",
                         description="Добавляет утверждение C001... Факт требует --source и --quote: цитата сверяется "
                                     "с сохранённой копией (регистр, пробелы и тип кавычек не важны). Допущение (assumption) это значение, "
                                     "принятое для расчёта до проверки: ему нужны --low, --high, --why и --verify-by.",
                         prog=PROG + " claim add")
    proj_opt(s2)
    s2.add_argument("--type", required=True, choices=common.CLAIM_TYPES, help="тип утверждения")
    s2.add_argument("--text", required=True, help="само утверждение одной фразой")
    s2.add_argument("--source", help="код источника, например S001")
    s2.add_argument("--quote", help="дословная цитата из копии источника")
    s2.add_argument("--number", help="число утверждения (для факта оно должно быть в цитате)")
    s2.add_argument("--kb", metavar="B012", help="запись базы знаний (для типа benchmark обязательно, для hypothesis можно)")
    s2.add_argument("--contradicts", metavar="C001", help="с каким утверждением это противоречит")
    s2.add_argument("--from-map", metavar="R012", help="связь карты причин, из которой родилась гипотеза (только для --type hypothesis)")
    s2.add_argument("--method", choices=common.CALC_METHODS, help="для --type calc: как получено число: словарь слов, разметка вручную или расчёт (по умолчанию как у расчёта, иначе расчёт)")
    s2.add_argument("--accuracy", type=float, metavar="ПРОЦЕНТ", help="для счёта по словарю: точность на случайной выборке, 0-100")
    s2.add_argument("--sample", type=int, metavar="N", help="для счёта по словарю: размер проверенной выборки")
    s2.add_argument("--low", metavar="ЧИСЛО", help="для --type assumption: нижняя граница диапазона (обязательно)")
    s2.add_argument("--high", metavar="ЧИСЛО", help="для --type assumption: верхняя граница диапазона (обязательно)")
    s2.add_argument("--base", metavar="ЧИСЛО", help="для --type assumption: основное значение внутри диапазона")
    s2.add_argument("--unit", metavar="ЕДИНИЦА", help="для --type assumption: единица измерения, например «%%» или «групп»")
    s2.add_argument("--why", metavar="ТЕКСТ", help="для --type assumption: почему границы именно такие (обязательно)")
    s2.add_argument("--verify-by", metavar="ТЕКСТ", help="для --type assumption: как и когда проверим значение (обязательно)")
    s2.add_argument("--switch-if", metavar="ТЕКСТ", help="для --type assumption: при каком значении выберем другой путь и какой (без него предупреждение)")
    s2 = ssub.add_parser("assumptions", help="сводка допущений: диапазон, способ проверки, порог смены решения",
                         description="Печатает все действующие допущения задачи: список с номерами записей и готовую таблицу для документа без номеров.",
                         prog=PROG + " claim assumptions")
    proj_opt(s2)
    s2 = ssub.add_parser("reject", help="отбросить утверждение с причиной",
                         description="Помечает утверждение как намеренно не используемое.", prog=PROG + " claim reject")
    proj_opt(s2)
    s2.add_argument("id")
    s2.add_argument("--reason", required=True, help="почему не используем")
    s2 = ssub.add_parser("list", help="список утверждений", description="Список утверждений.", prog=PROG + " claim list")
    proj_opt(s2)

    sp = add("conclusion", "выводы: add, set-status, list")
    ssub = sp.add_subparsers(dest="sub", title="Действия", metavar="<действие>")
    ssub.required = True
    s2 = ssub.add_parser("add", help="добавить вывод с основаниями", description="Добавляет вывод K001... со статусом «действует».",
                         prog=PROG + " conclusion add")
    proj_opt(s2)
    s2.add_argument("--text", required=True, help="сам вывод")
    s2.add_argument("--rests-on", required=True, metavar="C001,C002", help="на чём держится: коды утверждений или выводов")
    s2.add_argument("--kind", choices=common.CONCLUSION_KINDS, default="finding", help="вид вывода (по умолчанию finding)")
    s2.add_argument("--contradicts", metavar="K001", help="с каким выводом это противоречит")
    s2 = ssub.add_parser("set-status", help="сменить статус вывода", description="Меняет статус вывода.",
                         prog=PROG + " conclusion set-status")
    proj_opt(s2)
    s2.add_argument("id")
    s2.add_argument("--status", required=True, choices=[common.STATUS_OK, common.STATUS_DOUBT, common.STATUS_REPLACED])
    s2.add_argument("--replaced-by", metavar="K009", help="чем заменён")
    s2 = ssub.add_parser("list", help="список выводов", description="Список выводов.", prog=PROG + " conclusion list")
    proj_opt(s2)

    sp = add("lever", "рычаги: add, list")
    ssub = sp.add_subparsers(dest="sub", title="Действия", metavar="<действие>")
    ssub.required = True
    s2 = ssub.add_parser("add", help="добавить рычаг в levers.json",
                         description="Рычаг: показатель, где просадка, причина, точка нажима, эффект в трёх вариантах, проверка.",
                         prog=PROG + " lever add")
    proj_opt(s2)
    for name, h in (("metric", "показатель"), ("where", "где просадка (срез)"), ("cause", "причина"),
                    ("action", "точка нажима: что меняем"), ("check", "как проверить")):
        s2.add_argument("--" + name, required=True, help=h)
    for name in ("low", "base", "high"):
        s2.add_argument("--effect-" + name, required=True, metavar="ЧИСЛО", help="эффект: %s сценарий" % name)
    s2.add_argument("--rests-on", required=True, metavar="C001,K001", help="на чём держится")
    s2 = ssub.add_parser("set-status", help="подтвердить, поставить под вопрос или снять рычаг",
                         description="Меняет статус рычага. Снятый рычаг не даёт чисел странице и не учитывается в покрытии.",
                         prog=PROG + " lever set-status")
    proj_opt(s2)
    s2.add_argument("id", help="код рычага, например L001")
    s2.add_argument("--status", required=True, choices=ledger.LEVER_STATUSES)
    s2.add_argument("--reason", help="почему (что перепроверили или почему снят)")
    s2 = ssub.add_parser("list", help="список рычагов", description="Список рычагов.", prog=PROG + " lever list")
    proj_opt(s2)

    sp = add("calc", "расчёты: run (свой скрипт из analysis/), ready (готовый расчёт по файлу параметров), list, template")
    ssub = sp.add_subparsers(dest="sub", title="Действия", metavar="<действие>")
    ssub.required = True
    s2 = ssub.add_parser("run", help="запустить скрипт расчёта",
                         description="Запускает скрипт из projects/<id>/analysis/ с входными файлами, печатный вывод "
                                     "сохраняет как источник вида «расчёт» с отпечатками скрипта и входов.",
                         prog=PROG + " calc run")
    proj_opt(s2)
    s2.add_argument("script", help="файл .py из analysis/")
    s2.add_argument("--inputs", default="", metavar="a.csv,b.csv", help="входные файлы через запятую (из materials/ или analysis/)")
    s2.add_argument("--question", help="подвопрос")
    s2.add_argument("--method", choices=common.CALC_METHODS, default="расчёт",
                    help="как считаем: словарь слов, разметка вручную или расчёт (по умолчанию расчёт). Счёт по словарю требует точности при записи числа")
    s2.add_argument("--rests-on", metavar="C001,C002", help="записи реестра, из которых взяты входные числа; если среди них допущение, итог наследует пометку")
    s2 = ssub.add_parser("ready", help="готовый расчёт: формулы в программе, параметры в файле JSON",
                         description="Считает один из готовых расчётов (%s) по файлу параметров из папки задачи и сохраняет вывод как источник "
                                     "вида «расчёт». При verify расчёт повторяется и сверяется. Доли в параметрах задаются в процентах." % ", ".join(calcs.KINDS),
                         prog=PROG + " calc ready")
    proj_opt(s2)
    s2.add_argument("kind", metavar="вид", choices=list(calcs.KINDS), help="вид расчёта: %s" % ", ".join(calcs.KINDS))
    s2.add_argument("--params", required=True, metavar="analysis/файл.json", help="файл параметров внутри папки задачи")
    s2.add_argument("--rests-on", required=True, metavar="C001,C002",
                    help="записи реестра, из которых взяты параметры: факт, параметр плана, допущение или другой расчёт")
    s2.add_argument("--question", help="подвопрос")
    s2 = ssub.add_parser("list", help="список готовых расчётов и их полей", description="Какие готовые расчёты есть и какие поля нужны каждому.",
                         prog=PROG + " calc list")
    s2 = ssub.add_parser("template", help="положить образец файла параметров в analysis/",
                         description="Создаёт образец файла параметров готового расчёта. Числа в образце условные: замените своими.",
                         prog=PROG + " calc template")
    proj_opt(s2)
    s2.add_argument("kind", metavar="вид", choices=list(calcs.KINDS), help="вид расчёта: %s" % ", ".join(calcs.KINDS))
    s2.add_argument("--out", metavar="analysis/файл.json", help="куда положить (по умолчанию analysis/<вид латиницей>.json)")

    sp = add("verify", "прогнать слои проверки 1-5 и напечатать, что исправить (код 0 или 2)")
    proj_opt(sp)
    sp.add_argument("--layer", type=int, choices=[1, 2, 3, 4, 5], help="только один слой")
    sp.add_argument("--json", action="store_true", help="вывести результат в JSON")

    sp = add("gate", "замок завершения: проверки текущего этапа, код 2 при провале, защита от зацикливания")
    proj_opt(sp)

    sp = add("impact", "что задето: цепочка от утверждения, с --mark ставит «под-вопросом»")
    proj_opt(sp)
    sp.add_argument("id", nargs="?", help="код утверждения, вывода или рычага")
    sp.add_argument("--mark", action="store_true", help="поставить задетым статус «под-вопросом» и записать в журнал")
    sp.add_argument("--stale", action="store_true", help="для всех утверждений со старыми источниками")

    sp = add("sweep", "уборка: выводы без оснований, ненужные утверждения, просрочки, старое, противоречия")
    proj_opt(sp)
    sp.add_argument("--strict", action="store_true", help="вернуть код 2, если есть замечания")

    sp = add("decision", "записи решений: add, set-status, list")
    ssub = sp.add_subparsers(dest="sub", title="Действия", metavar="<действие>")
    ssub.required = True
    s2 = ssub.add_parser("add", help="добавить запись решения DR-001.md", description="Создаёт decisions/DR-001.md.",
                         prog=PROG + " decision add")
    proj_opt(s2)
    s2.add_argument("--title", required=True)
    s2.add_argument("--owner", required=True, help="кто отвечает")
    s2.add_argument("--metric", required=True, help="по какому показателю судим")
    s2.add_argument("--review-date", required=True, metavar="ГГГГ-ММ-ДД", help="когда пересмотреть")
    s2.add_argument("--review-if", required=True, help="при каком условии пересмотреть раньше")
    s2.add_argument("--rests-on", required=True, metavar="K001,L001")
    s2.add_argument("--status", choices=ledger.DECISION_STATUSES, default="предложено")
    s2 = ssub.add_parser("set-status", help="сменить статус решения", description="Меняет статус решения.",
                         prog=PROG + " decision set-status")
    proj_opt(s2)
    s2.add_argument("id")
    s2.add_argument("--status", required=True, choices=ledger.DECISION_STATUSES)
    s2.add_argument("--note", help="что перепроверили (обязательно, чтобы снять пометку «под вопросом»)")
    s2 = ssub.add_parser("list", help="список решений", description="Список решений.", prog=PROG + " decision list")
    proj_opt(s2)

    sp = add("cost", "расход: log (записать), report (отчёт по этапам)")
    ssub = sp.add_subparsers(dest="sub", title="Действия", metavar="<действие>")
    ssub.required = True
    s2 = ssub.add_parser("log", help="записать расход", description="Дописывает строку в cost.jsonl.", prog=PROG + " cost log")
    proj_opt(s2)
    s2.add_argument("--stage", type=int, required=True, help="номер этапа 1-8")
    s2.add_argument("--usd", type=float, required=True, help="сколько потрачено, USD (по умолчанию это оценка агента)")
    s2.add_argument("--tokens", type=int, help="сколько токенов")
    s2.add_argument("--note", help="пояснение")
    s2.add_argument("--measured", action="store_true", help="это замер (цифра из счёта или отчёта), а не оценка агента")
    s2 = ssub.add_parser("import-session", help="записать замер из отчёта сессии Claude Code (JSON)",
                         description="Читает отчёт с полями session_id, total_cost_usd (накопленная стоимость сессии), duration_api_ms, num_turns, "
                                     "считает прирост с прошлого импорта той же сессии, делит его по этапам и записывает как замер.",
                         prog=PROG + " cost import-session")
    proj_opt(s2)
    s2.add_argument("file", metavar="файл.json", help="отчёт сессии")
    s2.add_argument("--stage", required=True, metavar="N[,N]", help="этап или несколько этапов через запятую")
    s2.add_argument("--split", metavar="0.6,0.4", help="доли по этапам (в сумме 1); без параметра делится поровну")
    s2 = ssub.add_parser("report", help="отчёт по этапам и итого", description="Расход по этапам: замеры и оценки агента отдельно, время, ходы, расхождения.",
                         prog=PROG + " cost report")
    proj_opt(s2)

    sp = add("req", "требования человека из его запроса: add, import, list, close, drop, note")
    ssub = sp.add_subparsers(dest="sub", title="Действия", metavar="<действие>")
    ssub.required = True
    s2 = ssub.add_parser("add", help="записать требование с дословной цитатой", prog=PROG + " req add",
                         description="Требование R01... Цитата должна найтись в дословном запросе (brief.md, раздел «Запрос дословно»), "
                                     "в requests.md или в копии источника.")
    proj_opt(s2)
    s2.add_argument("--text", required=True, help="что требуется, одной фразой")
    s2.add_argument("--quote", required=True, help="дословный фрагмент запроса")
    s2.add_argument("--source", default="brief", metavar="brief|S001", help="где искать цитату: brief (по умолчанию) или код источника")
    s2 = ssub.add_parser("import", help="записать много требований из файла", prog=PROG + " req import",
                         description="Записывает требования пачкой. В файле одна строка на требование: «что требуется || дословная цитата». "
                                     "Пустые строки и строки с # в начале пропускаются. Каждая цитата проверяется так же, как в req add.")
    proj_opt(s2)
    s2.add_argument("--file", required=True, metavar="ПУТЬ", help="текстовый файл со строками «требование || цитата»")
    s2.add_argument("--source", default="brief", metavar="brief|S001", help="где искать цитаты: brief (по умолчанию) или код источника")
    s2 = ssub.add_parser("list", help="список требований", description="Список требований.", prog=PROG + " req list")
    proj_opt(s2)
    s2 = ssub.add_parser("close", help="закрыть требование выполненным", prog=PROG + " req close",
                         description="Закрывает требование. Закрыть можно выполненным критерием, действующим выводом, рычагом, решением или файлом проекта.")
    proj_opt(s2)
    s2.add_argument("id", nargs="?", help="например R01; несколько кодов через запятую: R01,R02 (не нужен вместе с --file)")
    s2.add_argument("--by", required=True, metavar="D1|K001|L001|DR-001|путь", help="чем закрыто")
    s2.add_argument("--phrase", metavar="ФРАЗА", help="дословная фраза из названного места документа, в которой требование выполнено "
                                                     "(от 4 слов). Если при переписывании она пропадёт, doc check скажет об этом")
    s2.add_argument("--file", metavar="ФАЙЛ", help="закрыть списком: строка «R01 || часть 2 || дословная фраза из документа»")
    s2.add_argument("--where", metavar="МЕСТО", help="где в результате это выполнено: «начало», «часть 2», название части документа "
                                                     "или путь к файлу задачи; после места можно дописать уточнение через запятую")
    s2 = ssub.add_parser("drop", help="снять требование с причиной", prog=PROG + " req drop",
                         description="Снимает требование: человек отказался от него или оно не относится к задаче.")
    proj_opt(s2)
    s2.add_argument("id")
    s2.add_argument("--reason", required=True)
    s2 = ssub.add_parser("note", help="сохранить новое сообщение человека дословно", prog=PROG + " req note",
                         description="Дописывает сообщение в requests.md. После этого его цитаты принимает req add.")
    proj_opt(s2)
    s2.add_argument("message", help="текст сообщения дословно")

    sp = add("route", "выбор модели и методики: suggest, escalate")
    ssub = sp.add_subparsers(dest="sub", title="Действия", metavar="<действие>")
    ssub.required = True
    s2 = ssub.add_parser("suggest", help="какую модель и методику взять для вида шага", prog=PROG + " route suggest",
                         description="Ищет вид шага в config/routing.json и печатает класс модели, методику и причину.")
    s2.add_argument("--step", required=True, help="вид шага словами, например «диагностика причины»")
    s2 = ssub.add_parser("escalate", help="записать ручную смену подхода", prog=PROG + " route escalate",
                         description="Записывает исправление выбора в журнал и подсказывает класс модели выше и методику для перечитывания.")
    proj_opt(s2)
    s2.add_argument("--stage", type=int, required=True, help="номер этапа 1-8")
    s2.add_argument("--reason", required=True, help="что не получается")

    sp = add("strategy", "стратегии: check (состояние каждой обязательной части)")
    ssub = sp.add_subparsers(dest="sub", title="Действия", metavar="<действие>")
    ssub.required = True
    s2 = ssub.add_parser("check", help="показать, какие обязательные части стратегий и плана проверки заполнены",
                         prog=PROG + " strategy check", description="Печатает состояние каждой обязательной части. Код 2, если чего-то не хватает.")
    proj_opt(s2)

    sp = add("doc", "документ по частям заказчика: init (задать структуру), check (проверить), page (собрать page.md из начала)")
    ssub = sp.add_subparsers(dest="sub", title="Действия", metavar="<действие>")
    ssub.required = True
    s2 = ssub.add_parser("init", help="задать структуру документа словами заказчика и создать каркас document.md", prog=PROG + " doc init",
                         description="Когда заказчик сам задал структуру результата. Записывает document.json (части и обязательные элементы начала "
                                     "берутся из запроса, в программе они не зашиты) и создаёт каркас document.md. С этого момента три файла strategy/ "
                                     "не обязательны, а page.md собирается из начала документа.")
    proj_opt(s2)
    s2.add_argument("--title", required=True, help="название документа")
    s2.add_argument("--opening", action="append", default=[], metavar="ЭЛЕМЕНТ",
                    help="что заказчик велел назвать в начале; параметр повторяется по одному на элемент")
    s2.add_argument("--part", action="append", default=[], metavar="ЧАСТЬ", help="название части; параметр повторяется, порядок как у заказчика")
    s2.add_argument("--ending", metavar="ЭЛЕМЕНТ", help="чем заказчик велел закончить документ, например «Просьба руководителю»: "
                                                       "этот абзац должен стоять последним")
    s2.add_argument("--quote", help="дословные слова заказчика о составе результата (сверяются с запросом или источником)")
    s2.add_argument("--source", default="brief", metavar="brief|S001", help="где искать цитату: brief (по умолчанию) или код источника")
    s2.add_argument("--replace", action="store_true", help="заменить уже заданную структуру (текст document.md не трогается)")
    s2 = ssub.add_parser("check", help="проверить документ: части, начало, числа, стиль, место каждого требования", prog=PROG + " doc check",
                         description="Все части на месте, в порядке заказчика и не пусты; в начале есть каждый обязательный элемент, и оно не длиннее страницы; "
                                     "каждое число есть в реестре и стоит с нужной пометкой; нет внутренних номеров записей, пустых оборотов, сокращений "
                                     "и длинных тире; у закрытых требований указано место; page.md совпадает с началом. Код 2, если есть что исправить.")
    proj_opt(s2)
    s2 = ssub.add_parser("page", help="собрать page.md из начала документа", prog=PROG + " doc page",
                         description="Страница для руководителя это начало документа (до первой части) и список файлов. Руками page.md в такой задаче не пишут.")
    proj_opt(s2)

    sp = add("diagnosis", "диагноз: check (состояние каждой обязательной части analysis/diagnoz.md)")
    ssub = sp.add_subparsers(dest="sub", title="Действия", metavar="<действие>")
    ssub.required = True
    s2 = ssub.add_parser("check", help="показать, какие обязательные части диагноза заполнены",
                         prog=PROG + " diagnosis check", description="Печатает состояние каждой части диагноза. Код 2, если чего-то не хватает.")
    proj_opt(s2)

    sp = add("layers", "слои близости: check (проход по слоям 1-5 в analysis/sloi.md)")
    ssub = sp.add_subparsers(dest="sub", title="Действия", metavar="<действие>")
    ssub.required = True
    s2 = ssub.add_parser("check", help="показать, какие слои близости пройдены",
                         prog=PROG + " layers check", description="Печатает состояние каждого слоя: есть записи, пусто с причиной или не заполнено. Код 2, если чего-то не хватает.")
    proj_opt(s2)

    sp = add("done", "договор «что значит готово»: add, mark, budget, list")
    ssub = sp.add_subparsers(dest="sub", title="Действия", metavar="<действие>")
    ssub.required = True
    s2 = ssub.add_parser("add", help="добавить критерий", description="Добавляет критерий в done.json.", prog=PROG + " done add")
    proj_opt(s2)
    s2.add_argument("--text", required=True)
    s2 = ssub.add_parser("mark", help="отметить критерий выполненным", description="Отмечает критерий.", prog=PROG + " done mark")
    proj_opt(s2)
    s2.add_argument("id", help="например D1")
    s2.add_argument("--unmark", action="store_true", help="снять отметку")
    s2 = ssub.add_parser("budget", help="задать бюджет", description="Бюджет задачи в USD.", prog=PROG + " done budget")
    proj_opt(s2)
    s2.add_argument("--usd", type=float, required=True)
    s2 = ssub.add_parser("list", help="показать критерии", description="Критерии готовности.", prog=PROG + " done list")
    proj_opt(s2)

    sp = add("question", "открытые вопросы руководителю (не больше трёх): add, close")
    ssub = sp.add_subparsers(dest="sub", title="Действия", metavar="<действие>")
    ssub.required = True
    s2 = ssub.add_parser("add", help="записать вопрос", description="Вопрос с пометкой «если да, так; если нет, так».",
                         prog=PROG + " question add")
    proj_opt(s2)
    s2.add_argument("--text", required=True)
    s2.add_argument("--if-yes", required=True, help="что делаю, если да")
    s2.add_argument("--if-no", required=True, help="что делаю, если нет")
    s2 = ssub.add_parser("close", help="закрыть вопрос", description="Закрывает вопрос по номеру.", prog=PROG + " question close")
    proj_opt(s2)
    s2.add_argument("n", type=int)
    s2.add_argument("--answer", help="ответ руководителя")

    sp = add("kb", "база знаний отрасли (knowledge/): source, add, import, search, show, link, list, retire, replace, stale, stats, index")
    ks = sp.add_subparsers(dest="sub", title="Действия", metavar="<действие>")
    ks.required = True

    def kadd(name, h, desc=None):
        return ks.add_parser(name, help=h, description=desc or h, prog="%s kb %s" % (PROG, name))

    s2 = kadd("source", "источники базы знаний: add")
    s3 = s2.add_subparsers(dest="sub2", title="Действия", metavar="<действие>")
    s3.required = True
    s4 = s3.add_parser("add", help="сохранить копию источника в knowledge/sources/", prog=PROG + " kb source add",
                       description="Сохраняет текст в knowledge/sources/KS001.txt с паспортом KS001.meta.json.")
    s4.add_argument("--url", required=True)
    s4.add_argument("--text-file", metavar="ФАЙЛ", help="файл с текстом страницы (внутри репозитория)")
    s4.add_argument("--fetch", action="store_true", help="скачать страницу самому")
    s4.add_argument("--published", metavar="ГГГГ[-ММ[-ДД]]", help="год, месяц или день; для свежести берётся последний день периода")
    s4.add_argument("--title")

    s2 = kadd("add", "добавить запись-ориентир", "Запись базы знаний B001... Цитата сверяется с копией источника. "
                                                  "Записи это ориентиры, а не факты о продукте. Слои: %s." % common.LAYER_HELP)
    s2.add_argument("--rule", required=True, help="правило или наблюдение одной фразой")
    s2.add_argument("--applies-when", required=True, help="когда применимо")
    s2.add_argument("--not-when", help="когда не применимо")
    s2.add_argument("--theme", required=True, metavar="t1,t2", help="темы через запятую")
    s2.add_argument("--tags", metavar="a,b", help="метки через запятую")
    s2.add_argument("--layer", type=int, required=True, metavar="N", help="слой близости 2-5 (слой 1 только в проектах)")
    s2.add_argument("--source", metavar="KS001", help="источник базы знаний (не нужен для --kind урок)")
    s2.add_argument("--quote", help="дословная цитата из копии источника")
    s2.add_argument("--strength", choices=kbase.STRENGTHS, help="сила: независимый-замер, данные-компании, мнение")
    s2.add_argument("--place", help="страна, компания")
    s2.add_argument("--number", help="число записи (должно быть в цитате)")
    s2.add_argument("--kind", choices=kbase.KINDS, default="правило", help="правило, наблюдение или урок (собственный урок агента)")

    s2 = kadd("import", "импорт записей из файла JSON Lines",
              "Каждая строка: rule, applies_when, not_when, themes, tags, place, date_published, url, title, source_file, "
              "quote, number, strength, kind, layer. Отклонённые записи попадают в knowledge/rejected.jsonl.")
    s2.add_argument("file", help="файл .jsonl")
    s2.add_argument("--sources-dir", required=True, metavar="ПАПКА", help="папка с текстами, на которые указывает source_file")

    s2 = kadd("search", "поиск по базе знаний", "Поиск по правилу, условию, меткам и цитате: регистр, «ё/е» и окончания не важны, "
                                                 "учитываются синонимы из config/synonyms.json. Запись подходит, если совпала хотя бы половина значимых слов "
                                                 "запроса (все, если слов одно или два). Порядок: ближний слой, число совпавших слов, сила, дата.")
    s2.add_argument("words", nargs="?", default="", help="слова запроса")
    s2.add_argument("--theme")
    s2.add_argument("--tag")
    s2.add_argument("--related", metavar="B012", help="записи, связанные с этой")
    s2.add_argument("--limit", type=int, default=10)
    s2.add_argument("--all", action="store_true", help="включая отозванные и заменённые")
    s2.add_argument("--layer", type=int, metavar="N", help="показать только записи этого слоя близости 2-5 (в конце поиска всегда печатается число результатов по слоям)")
    proj_opt(s2)

    s2 = kadd("show", "показать запись")
    s2.add_argument("id")
    proj_opt(s2)
    s2 = kadd("link", "связать две записи")
    s2.add_argument("a")
    s2.add_argument("b")
    s2.add_argument("--note")
    s2 = kadd("list", "список записей")
    s2.add_argument("--theme")
    s2.add_argument("--stale", action="store_true", help="только устаревшие")
    s2.add_argument("--all", action="store_true", help="включая отозванные и заменённые")
    s2 = kadd("retire", "отозвать запись (не удаляется)")
    s2.add_argument("id")
    s2.add_argument("--reason", required=True)
    s2 = kadd("replace", "заменить запись другой")
    s2.add_argument("id")
    s2.add_argument("--by", required=True, metavar="B040")
    s2.add_argument("--reason")
    kadd("stats", "как используются действующие записи: ориентиры, выводы, отзывы, исходы")
    kadd("stale", "устаревшие записи и записи без файла источника")
    kadd("index", "пересоздать knowledge/INDEX.md")

    sp = add("map", "карта причин в базе знаний: node, link, import, causes, effects, path, check, export")
    ms = sp.add_subparsers(dest="sub", title="Действия", metavar="<действие>")
    ms.required = True

    def madd(name, h):
        return ms.add_parser(name, help=h, description=h, prog="%s map %s" % (PROG, name))

    s2 = madd("node", "узлы карты: add, list")
    s3 = s2.add_subparsers(dest="sub2", title="Действия", metavar="<действие>")
    s3.required = True
    s4 = s3.add_parser("add", help="добавить узел", description="Узел N001... Вид: %s." % ", ".join(kbmap.KINDS), prog=PROG + " map node add")
    s4.add_argument("--name", required=True, help="название по-русски")
    s4.add_argument("--kind", required=True, choices=kbmap.KINDS)
    s4.add_argument("--alias", metavar="a,b", help="другие названия через запятую")
    s3.add_parser("list", help="список узлов", description="Список узлов.", prog=PROG + " map node list")

    s2 = madd("link", "связи карты: add, list, retire")
    s3 = s2.add_subparsers(dest="sub2", title="Действия", metavar="<действие>")
    s3.required = True
    s4 = s3.add_parser("add", help="добавить связь", prog=PROG + " map link add",
                       description="Связь R001...: откуда, куда, знак, условия, записи-основания (действующие записи базы знаний). "
                                   "Без записей связь остаётся гипотезой. Повтор той же тройки откуда, куда, знак объединяется: записи добавляются.")
    s4.add_argument("--from", dest="frm", required=True, metavar="N001", help="узел-причина: код или название")
    s4.add_argument("--to", required=True, metavar="N002", help="узел-следствие: код или название")
    s4.add_argument("--sign", required=True, choices=kbmap.SIGNS)
    s4.add_argument("--conditions", help="при каких условиях связь верна")
    s4.add_argument("--evidence", metavar="B012,B031", help="записи базы знаний")
    s4.add_argument("--note", help="заметка; у гипотезы напишите, каких доказательств не хватает")
    s4.add_argument("--contradicted-by", metavar="B072", help="записи базы знаний, которые возражают против связи (через запятую)")
    s3.add_parser("list", help="список связей", description="Список связей.", prog=PROG + " map link list")
    s4 = s3.add_parser("retire", help="отозвать связь", description="Связь не удаляется, получает статус «отозвана».",
                       prog=PROG + " map link retire")
    s4.add_argument("id")
    s4.add_argument("--reason", required=True)

    s2 = madd("import", "массовый импорт узлов и связей из файла JSON Lines")
    s2.description = ("Каждая строка: объект с полем type. Узел: {\"type\":\"node\",\"name\":...,\"kind\":...,\"aliases\":[...]}. "
                      "Связь: {\"type\":\"link\",\"from\":код или название,\"to\":...,\"sign\":...,\"conditions\":...,\"evidence\":[\"B012\"],\"contradicted_by\":[\"B072\"],\"note\":...}. "
                      "Повторный импорт безопасен: одинаковое пропускается, новые записи вливаются в существующие связи, отклоняются только конфликты. "
                      "Отклонённые строки попадают в knowledge/map/rejected.jsonl.")
    s2.add_argument("file", help="файл .jsonl")
    s2 = madd("causes", "что влияет на показатель: цепочка вверх по слоям")
    s2.add_argument("node", help="показатель: код, название или слова руководителя (например «оценка в магазине»)")
    s2.add_argument("--proven-only", action="store_true", help="на гипотезах обход останавливается (по умолчанию идёт дальше, шаги помечены)")
    s2.add_argument("--depth", type=int, default=kbmap.DEFAULT_DEPTH)
    s2.add_argument("--layer-max", type=int, metavar="N", help="не показывать связи, у которых самые близкие данные дальше этого уровня: %s" % common.LAYER_HELP)
    proj_opt(s2)
    s2 = madd("effects", "на что влияет фактор: цепочка вниз")
    s2.add_argument("node", help="фактор: код, название или слова руководителя")
    s2.add_argument("--proven-only", action="store_true", help="на гипотезах обход останавливается (по умолчанию идёт дальше, шаги помечены)")
    s2.add_argument("--depth", type=int, default=kbmap.DEFAULT_DEPTH)
    s2.add_argument("--layer-max", type=int, metavar="N", help="уровень близости данных, как в causes")
    proj_opt(s2)
    s2 = madd("path", "кратчайшие цепочки между двумя узлами")
    s2.add_argument("a", help="откуда")
    s2.add_argument("b", help="куда")
    proj_opt(s2)
    s2 = madd("check", "проверка карты: связи без записей, узлы без связей, противоречия, циклы")
    s2.add_argument("--strict", action="store_true", help="вернуть код 2, если есть замечания")
    s2 = madd("export", "выгрузка карты в файл Mermaid knowledge/map/map.mmd")
    s2.add_argument("--format", required=True, choices=["mermaid"])
    s2.add_argument("--around", metavar="УЗЕЛ", help="только окрестность этого узла")
    s2.add_argument("--depth", type=int, default=2)

    sp = add("feedback", "отзывы руководителя: add, list, reasons (отзыв ничего не меняет в статусах)")
    fs = sp.add_subparsers(dest="sub", title="Действия", metavar="<действие>")
    fs.required = True
    s2 = fs.add_parser("add", help="записать отзыв", prog=PROG + " feedback add",
                       description="Вердикт руководителя о странице, выводе, рычаге или решении. Статус объекта не меняется.")
    proj_opt(s2)
    s2.add_argument("--target", required=True, metavar="page|K003|L001|DR-001")
    s2.add_argument("--verdict", required=True, metavar="Принято|Отклонено", help="Принято или Отклонено (регистр не важен)")
    s2.add_argument("--reason", metavar="НОМЕР", help="причина отклонения (обязательна при отклонении): номер или код из списка feedback reasons")
    s2.add_argument("--note")
    s2 = fs.add_parser("list", help="список отзывов", description="Список отзывов.", prog=PROG + " feedback list")
    proj_opt(s2)
    fs.add_parser("reasons", help="коды причин", description="Коды причин отклонения.", prog=PROG + " feedback reasons")

    sp = add("outcome", "исходы решений: add (что случилось на самом деле)")
    os_ = sp.add_subparsers(dest="sub", title="Действия", metavar="<действие>")
    os_.required = True
    s2 = os_.add_parser("add", help="записать исход решения", prog=PROG + " outcome add",
                        description="Что произошло после решения. Если решение держится на рычаге, значение сравнивается с низкой, базовой и высокой оценкой.")
    proj_opt(s2)
    s2.add_argument("--decision", required=True, metavar="DR-001")
    s2.add_argument("--metric", required=True)
    s2.add_argument("--actual", required=True, metavar="ЧИСЛО", help="фактическое значение в тех же единицах, что эффект рычага")
    s2.add_argument("--period", required=True, help="за какой период")
    s2.add_argument("--source", metavar="S012", help="источник проекта; слой 1 или 2 даёт сильный исход, без него «со слов человека»")
    s2.add_argument("--note")
    s2 = os_.add_parser("list", help="список исходов", description="Список исходов.", prog=PROG + " outcome list")
    proj_opt(s2)

    sp = add("learn", "обучение волнами: wave, apply, reject, history (применяется только по явной команде)")
    ls = sp.add_subparsers(dest="sub", title="Действия", metavar="<действие>")
    ls.required = True
    s2 = ls.add_parser("wave", help="собрать отзывы и исходы всех задач и написать предложения", prog=PROG + " learn wave",
                       description="Пишет learn/proposals-<дата>.md и .json. Ничего не применяет.")
    s2.add_argument("--since", metavar="ГГГГ-ММ-ДД", help="брать данные с этой даты вместо данных после прошлой волны")
    s2 = ls.add_parser("apply", help="применить одно предложение", prog=PROG + " learn apply",
                       description="Применяет предложение (настройки стиля или урок в базу знаний) и пишет в learn/history.jsonl.")
    s2.add_argument("id", help="например P001")
    s2.add_argument("--approved-by", metavar="ИМЯ", help="кто утвердил")
    s2 = ls.add_parser("reject", help="отклонить предложение", prog=PROG + " learn reject", description="Отклоняет предложение с причиной.")
    s2.add_argument("id")
    s2.add_argument("--reason", required=True)
    ls.add_parser("history", help="история волн и решений", description="История волн и решений.", prog=PROG + " learn history")

    add("doctor", "проверить окружение: Python, права, настройки, пример")
    return p


# ---------------------------------------------------------------- команды

def say(lines):
    for l in lines:
        print(l)


def get_proj(args):
    return resolve_project(args.root_path, getattr(args, "project", None))


def c_new(a, cfg):
    proj = stages.create_project(a.root_path, a.id, a.question)
    if cfg is None:  # для new настройки не загружаются заранее: нужна только отметка об остановках
        try:
            cfg = load_config(a.root_path)
        except Exception:
            cfg = None
    say(["Создана задача %s." % proj.where(),
         "Запрос сохранён дословно в %s (раздел «Запрос дословно»)." % proj.where("brief.md"),
         "Этап 1 из 8: %s. Выпишите каждое требование из запроса: python3 tools/rychag.py req add --text \"...\" --quote \"...\"" % common.STAGE_NAMES[1]]
        + (["На этапе 1 только постановка и вопросы. " + common.stop_hint(1),
            "Расчёты, допущения и части документа начинаются после ответов руководителя на остановках №1 и №2."]
           if common.stops_need_answer(cfg) else [])
        + ["Дальше: python3 tools/rychag.py status"])
    return 0


def several_projects_overview(a, cfg):
    """Задач несколько, а имя не названо: показать все и не падать. Так начало сессии не обрывается ошибкой."""
    root = a.root_path
    last = common.latest_project(root)
    print("Задач несколько. Спросите человека, с какой работаем, и добавляйте --project <имя> ко всем командам.")
    for name in common.work_projects(root):
        proj = common.Project(root, name)
        st = common.read_state(proj)
        cur = st.get("stage", 1)
        print("- %s: этап %d из 8 (%s)%s. %s" % (
            name, cur, common.STAGE_NAMES[cur], ", менялась последней" if name == last else "",
            common.short(str(st.get("question") or ""), 110)))
    print("Состояние одной задачи: python3 tools/rychag.py status --project <имя>. Новая задача: python3 tools/rychag.py new <имя> --question \"...\".")
    return 0


def c_status(a, cfg):
    if not getattr(a, "project", None) and not a.receipt and a.check_receipt is None and len(common.work_projects(a.root_path)) > 1:
        return several_projects_overview(a, cfg)
    proj = get_proj(a)
    if a.receipt and a.check_receipt is not None:
        raise Fail("--receipt и --check-receipt вместе не нужны: выберите одно.")
    if a.receipt:
        print(receipt.issue(proj, cfg))
        return 0
    if a.check_receipt is not None:
        ok, lines = receipt.check(proj, cfg, a.check_receipt)
        say(lines)
        return 0 if ok else 2
    say(stages.status_lines(proj, cfg))
    if a.journal is not None:
        if a.journal < 1:
            raise Fail("--journal: число шагов не меньше 1.")
        say(stages.journal_lines(proj, a.journal))
    return 0


def c_incident(a, cfg):
    proj = get_proj(a)
    if a.sub == "add":
        r = incidents.add(proj, a.kind, a.what, a.caught_by, a.fix, a.source)
        say(["Записано происшествие %s (%s, %s): %s" % (r["id"], r["date"], r["kind"], common.short(r["what"], 100)),
             "Файл: %s. Запись есть и в журнале." % proj.where("errors.md")])
        return 0
    say(incidents.list_lines(proj))
    return 0


def c_stage(a, cfg):
    proj = get_proj(a)
    if a.sub == "show":
        say(stages.stage_show(proj))
        return 0
    code, lines = stages.stage_next(proj, cfg, a.from_stage, getattr(a, "answer", None))
    say(lines)
    return code


def c_source(a, cfg):
    proj = get_proj(a)
    if a.sub == "add":
        meta, warns = sources.add_source(proj, cfg, url=a.url, text_file=a.text_file, file=a.file, kind=a.kind,
                                         published=a.published, title=a.title, question=a.question,
                                         allow_stale=a.allow_stale, fetch=a.fetch, layer=a.layer,
                                         period_from=a.period_from, period_to=a.period_to)
        say(["Сохранён %s: %s (вид: %s, дата публикации: %s, обращение: %s)." % (
            meta["id"], meta["title"], meta["kind"], meta["published"] or "нет", meta["accessed"]) + " Слой близости: %s." % meta["layer"],
            "Копия: %s" % proj.where("sources", meta["id"] + ".txt")])
        for w in warns:
            print("Предупреждение: " + w)
        if meta["kind"] in sources.NON_GROUND_KINDS:
            print("Помечено: источник вида «%s» не может быть основанием факта." % meta["kind"])
        return 0
    if a.sub == "set-layer":
        m = sources.set_layer(proj, a.id, a.layer)
        print("Источник %s: слой %d (%s)." % (a.id, m["layer"], common.LAYER_RU[m["layer"]]))
        return 0
    if a.sub == "accept-stale":
        sources.accept_stale(proj, a.id, a.reason)
        print("Источник %s принят как допустимый, причина записана." % a.id)
        return 0
    rows = sources.list_sources(proj)
    if not rows:
        print("Источников нет. Добавить: python3 tools/rychag.py source add --url ... --text-file ...")
    for m in rows:
        print("%s [%s, слой %s] %s, опубликован %s, вопрос «%s»%s" % (
            m["id"], m["kind"], sources.source_layer(m) or "не указан", m["title"], m.get("published") or "дата неизвестна",
            m.get("question"), ", устарел" if sources.is_stale(m, cfg) else ""))
    return 0


def c_claim(a, cfg):
    proj = get_proj(a)
    if a.sub == "add":
        if a.type == "assumption":
            common.early_work_guard(proj, cfg, "запись допущений")
        assume = {"low": a.low, "base": a.base, "high": a.high, "why": a.why, "how": a.verify_by, "switch": a.switch_if, "unit": a.unit}
        c, notes = ledger.add_claim(proj, a.type, a.text, a.source, a.quote, a.number, a.kb, a.contradicts, a.from_map,
                                  a.method, a.accuracy, a.sample, assume=assume)
        print("Добавлено %s (%s)." % (c["id"], c["type"]))
        say(notes)
        return 0
    if a.sub == "assumptions":
        say(ledger.assumption_lines(proj))
        return 0
    if a.sub == "reject":
        c, users = ledger.reject_claim(proj, a.id, a.reason)
        print("Утверждение %s отброшено: %s." % (a.id, a.reason))
        if users:
            print("Внимание: на него опираются выводы %s. Пересмотрите их: python3 tools/rychag.py impact %s --mark" % (
                ", ".join(users), a.id))
        return 0
    rows = ledger.load_claims(proj)
    lm = layers.claim_layers(proj)
    if not rows:
        print("Утверждений нет.")
    for c in rows:
        print("%s [%s%s, %s] %s%s" % (c["id"], common.CLAIM_TYPE_RU.get(c["type"], c["type"]),
                                      ", слой %d" % lm[c["id"]] if c["id"] in lm else "", c["status"], common.short(c["text"], 90),
                                    " (источник %s)" % c["source"] if c.get("source") else "") +
              (" [%s]" % common.UNMEASURED_FLAG if common.UNMEASURED_FLAG in (c.get("flags") or []) else ""))
    return 0


def c_conclusion(a, cfg):
    proj = get_proj(a)
    if a.sub == "add":
        k, notes = ledger.add_conclusion(proj, a.text, a.rests_on, a.kind, a.contradicts)
        print("Добавлен вывод %s (%s), статус «%s»." % (k["id"], k["kind"], k["status"]))
        say(notes)
        return 0
    if a.sub == "set-status":
        k = ledger.set_conclusion_status(proj, a.id, a.status, a.replaced_by)
        print("Вывод %s: статус «%s»." % (k["id"], k["status"]))
        return 0
    rows = ledger.load_conclusions(proj)
    if not rows:
        print("Выводов нет.")
    cl = {c["id"]: c for c in ledger.load_claims(proj)}
    cc = {k["id"]: k for k in rows}
    lm = layers.claim_layers(proj)
    for k in rows:
        lay = layers.conclusion_layer(k, cl, cc, lm)
        print("%s [%s, %s%s] %s (держится на %s)" % (k["id"], k["kind"], k["status"], ", слой %d" % lay if lay else "",
                                                   common.short(k["text"], 80), ", ".join(k.get("rests_on", []))))
    return 0


def c_lever(a, cfg):
    proj = get_proj(a)
    if a.sub == "set-status":
        lv = ledger.set_lever_status(proj, a.id, a.status, a.reason)
        print("Рычаг %s: статус «%s»." % (lv["id"], lv["status"]))
        return 0
    if a.sub == "add":
        lv = ledger.add_lever(proj, a.metric, a.where, a.cause, a.action, a.effect_low, a.effect_base,
                              a.effect_high, a.check, a.rests_on)
        print("Добавлен рычаг %s: эффект %s / %s / %s." % (lv["id"], lv["effect"]["low"], lv["effect"]["base"], lv["effect"]["high"]))
        return 0
    rows = ledger.load_levers(proj)
    if not rows:
        print("Рычагов нет.")
    for lv in rows:
        e = lv["effect"]
        print("%s [%s] %s: %s. Причина: %s. Эффект %s / %s / %s. Проверка: %s. Держится на %s." % (
            lv["id"], lv.get("status", common.STATUS_OK), lv["metric"], lv["action"], lv["cause"],
            e["low"], e["base"], e["high"], lv["check"], ", ".join(lv.get("rests_on", []))))
    return 0


def c_calc(a, cfg):
    if a.sub == "list":
        say(calcs.list_lines())
        return 0
    proj = get_proj(a)
    if a.sub == "template":
        rel = sources.write_template(proj, a.kind, a.out)
        say(["Образец параметров расчёта «%s» записан: %s. Числа в нём условные: замените своими." % (a.kind, proj.where(rel)),
             "Поля: %s." % calcs.KINDS[a.kind]["fields"],
             "Затем: python3 tools/rychag.py calc ready %s --params %s --rests-on <записи, из которых взяты числа>" % (a.kind, rel)])
        return 0
    if a.sub in ("ready", "run"):
        common.early_work_guard(proj, cfg, "расчёт")
    if a.sub == "ready":
        meta, out, warns = sources.run_ready(proj, a.kind, a.params, a.rests_on, a.question)
        print("Готовый расчёт «%s» сохранён как источник %s (вид: расчёт). При verify он будет повторён и сверен." % (a.kind, meta["id"]))
        print("Вывод расчёта:")
        for l in out.rstrip().split("\n"):
            print("  " + l)
        for w in warns:
            print("Предупреждение: " + w)
        print("Числа цитируйте так: claim add --type calc --source %s --quote \"строка из вывода\" --number \"...\" --text \"...\"" % meta["id"])
        return 0
    inputs = [x.strip() for x in a.inputs.split(",") if x.strip()]
    meta, out = sources.run_calc(proj, a.script, inputs, a.question, method=a.method, rests_on=a.rests_on)
    print("Расчёт сохранён как источник %s (вид: расчёт). Отпечаток скрипта %s..." % (meta["id"], meta["script_sha256"][:10]))
    print("Вывод скрипта:")
    for l in out.rstrip().split("\n")[:30]:
        print("  " + l)
    if a.method == "словарь":
        print("Счёт по словарю слов: проверьте случайную выборку и запишите точность: claim add --type calc --method словарь --accuracy <процент> --sample <размер>. "
              "Без этого число помечается «точность не измерена» и на странице идёт со словом «оценка».")
    print("Числа цитируйте так: claim add --type calc --source %s --quote \"строка из вывода\" --number \"...\" --text \"...\"" % meta["id"])
    return 0


def c_verify(a, cfg):
    proj = get_proj(a)
    which = (a.layer,) if a.layer else (1, 2, 3, 4, 5)
    res = checks.run_layers(proj, cfg, which)
    if a.json:
        import json as _json
        d = _json.loads(checks.result_json(proj, res))
        d["support"] = {str(k): v for k, v in layers.support_counts(proj).items()}
        rd, ry, rz = reqs.counts(proj)
        d["requirements"] = {"done": rd, "of": ry, "dropped": rz}
        issues = [i for r in res for i in r.issues]
        route.record_result(proj, cfg, common.read_state(proj)["stage"], issues)
        print(_json.dumps(d, ensure_ascii=False, indent=2))
        return 0 if all(r.ok for r in res) else 2
    lines, total = checks.format_layers(res)
    print("Проверка задачи «%s»" % proj.name)
    say(lines)
    print(layers.support_line(layers.support_counts(proj)) + ".")
    print(reqs.line(proj) + ".")
    say(route.record_result(proj, cfg, common.read_state(proj)["stage"], [i for r in res for i in r.issues]))
    if total:
        print("Итого: не пройдено, замечаний %d. Код возврата 2." % total)
        return 2
    print("Итого: все проверенные слои пройдены.")
    return 0


def c_gate(a, cfg):
    if not getattr(a, "project", None) and len(common.work_projects(a.root_path)) > 1:
        # Замок завершения запускается без имени задачи. Проверяем ту, с которой работали последней: иначе замок не срабатывал бы вовсе.
        a.project = common.latest_project(a.root_path)
        print("Замок проверяет задачу «%s»: она менялась последней. Другую: gate --project <имя>." % a.project)
    proj = get_proj(a)
    cur = common.read_state(proj)["stage"]
    arts, res = checks.stage_report(proj, cfg, cur)
    issues = list(arts) + [i for r in res for i in r.issues]
    print(reqs.line(proj) + ".")
    wait = common.stops_need_answer(cfg) and cur in common.HUMAN_STOPS
    asked = len(common.read_state(proj).get("open_questions") or [])
    if wait and cur == 1 and asked and reqs.load(proj):
        # Постановку нельзя дописать без ответов: вопросы заданы, значит ждём человека, а не гадаем за него.
        rest = [i for i in issues if "brief.md" not in i["where"]]
        if not rest:
            print("Замок: этап 1, руководителю задано вопросов: %d. Ждём его ответа, можно завершать. Постановку допишете после ответа." % asked)
            return 0
    advice = route.record_result(proj, cfg, cur, issues)
    if not issues:
        checks.guard_reset(proj)
        print("Замок: этап %d (%s), проверки пройдены. Можно завершать." % (cur, common.STAGE_NAMES[cur]))
        if wait:
            print(common.stop_hint(cur))
        return 0
    if checks.guard_after_failure(proj):
        print("ПРЕДУПРЕЖДЕНИЕ: замок выпускает без прохождения. %d провалов подряд, а файлы проекта не менялись. "
              "Это записано в журнал. Покажите руководителю список ниже." % checks.GUARD_LIMIT)
        for i in issues:
            print("  - [%s] %s." % (i["where"], i["what"]))
        return 0
    print("Замок: этап %d (%s) не готов. Исправьте %d:" % (cur, common.STAGE_NAMES[cur], len(issues)))
    for i in issues:
        print("  - [%s] %s. Как исправить: %s." % (i["where"], i["what"], i["fix"]))
    say(advice)
    return 2


def c_impact(a, cfg):
    proj = get_proj(a)
    say(graph.impact(proj, cfg, a.id, a.mark, a.stale))
    if a.id and a.id.startswith("B") and a.id[1:].isdigit():
        ls = kbmap.links_using(a.root_path, a.id)
        if ls:
            nodes = {n["id"]: n for n in kbmap.load_nodes(a.root_path)}
            print("Связи карты причин, которые держатся на %s:" % a.id)
            for l in ls:
                print("  " + kbmap.link_line(a.root_path, l, nodes))
            print("Если запись отозвана или заменена, связь без других действующих записей становится гипотезой: python3 tools/rychag.py map check")
        else:
            print("Связей карты причин на %s нет." % a.id)
    return 0


def c_sweep(a, cfg):
    proj = get_proj(a)
    total = 0
    for title, rows in graph.sweep(proj, cfg):
        print("%s: %s" % (title, "замечаний нет" if not rows else len(rows)))
        for r in rows:
            print("  - " + r)
        total += len(rows)
    print("Итого замечаний: %d." % total)
    return 2 if (total and a.strict) else 0


def c_decision(a, cfg):
    proj = get_proj(a)
    if a.sub == "add":
        did = ledger.add_decision(proj, a.title, a.owner, a.metric, a.review_date, a.review_if, a.rests_on, a.status)
        print("Записано %s: decisions/%s.md" % (did, did))
        return 0
    if a.sub == "set-status":
        ledger.set_decision_status(proj, a.id, a.status, a.note)
        print("Решение %s: статус «%s»." % (a.id, a.status))
        return 0
    rows = ledger.load_decisions(proj)
    if not rows:
        print("Решений нет.")
    for d in rows:
        print("%s [%s] %s, владелец %s, пересмотр %s" % (d["id"], d.get("status"), d.get("title"), d.get("owner"), d.get("review_date")))
    return 0


def c_cost(a, cfg):
    proj = get_proj(a)
    if a.sub == "log":
        row = ledger.log_cost(proj, a.stage, a.usd, a.tokens, a.note, a.measured)
        print("Записано: этап %d, %.2f USD (%s)." % (row["stage"], row["usd"], row["kind"]))
        return 0
    if a.sub == "import-session":
        lines, _added = ledger.import_session(proj, a.file, a.stage, a.split)
        say(lines)
        return 0
    say(stages.cost_report_lines(proj))
    return 0


def c_done(a, cfg):
    proj = get_proj(a)
    if a.sub == "add":
        print("Добавлен критерий %s." % ledger.add_criterion(proj, a.text))
    elif a.sub == "mark":
        c = ledger.mark_criterion(proj, a.id, not a.unmark)
        print("Критерий %s: %s%s." % (c["id"], "выполнен" if c["met"] else "снят",
                                    " (уже был в этом состоянии, повторно не записано)" if c.get("unchanged") else ""))
    elif a.sub == "budget":
        ledger.set_budget(proj, a.usd)
        print("Бюджет: %.2f USD." % a.usd)
    else:
        d = ledger.load_done(proj)
        print("Бюджет: %s USD." % (d["budget_usd"] or "не задан"))
        for c in d["criteria"]:
            print("%s [%s] %s" % (c["id"], "x" if c["met"] else " ", c["text"]))
        if not d["criteria"]:
            print("Критериев нет.")
    return 0


def c_req(a, cfg):
    proj = get_proj(a)
    if a.sub == "add":
        it = reqs.add(proj, a.text, a.quote, a.source)
        print("Записано требование %s: %s" % (it["id"], it["text"]))
    elif a.sub == "import":
        ok, bad = reqs.import_file(proj, a.file, a.source)
        print("Записано требований: %d." % len(ok))
        if ok:
            print("Коды: %s ... %s" % (ok[0]["id"], ok[-1]["id"]))
        for n, line, why in bad:
            print("Строка %d не записана: %s\n  %s" % (n, why, line))
        if bad:
            print("Не записано строк: %d. Исправьте их в файле и повторите: уже записанные требования повторно не добавятся." % len(bad))
            return 1
    elif a.sub == "close" and common.early_work_guard(proj, cfg, "закрытие требований"):
        pass
    elif a.sub == "close" and a.file:
        done, same, bad = reqs.close_file(proj, a.file, a.by)
        print("Закрыто требований: %d, уже были закрыты так же: %d." % (done, same))
        for n, why in bad:
            print("  строка %d не принята: %s" % (n, why))
        if bad:
            print("Не принято строк: %d. Исправьте их в файле и повторите: принятые повторно не запишутся." % len(bad))
            return 1
    elif a.sub == "close":
        ids = common.split_ids(a.id or "")
        if not ids:
            raise Fail("Укажите код требования, например R01, или файл со списком: --file.")
        for rid in ids:
            it, changed = reqs.close(proj, rid, a.by, a.where, a.phrase)
            print("Требование %s %s (%s%s)." % (rid, "закрыто" if changed else "уже было закрыто так же, повторно не записано", a.by,
                                               ", место: %s" % it["where"] if it.get("where") else ""))
        if not a.where and document.exists(proj):
            print("Подсказка: не указано место в документе. Добавьте --where \"часть N\" или --where \"начало\": doc check предупредит о требованиях без места.")
    elif a.sub == "drop":
        it, changed = reqs.drop(proj, a.id, a.reason)
        print("Требование %s %s." % (a.id, "снято: " + a.reason if changed else "уже было снято"))
    elif a.sub == "note":
        print("Сообщение сохранено в %s. Теперь его цитаты принимает req add." % proj.where("requests.md")
              if reqs.note(proj, a.message) else "Это сообщение уже сохранено, повторно не записываю.")
        return 0
    else:
        items = reqs.load(proj)
        if not items:
            print("Требований нет. Записать: python3 tools/rychag.py req add --text \"...\" --quote \"...\"")
        for it in items:
            extra = ", закрыто: %s" % it["closed_by"] if it.get("closed_by") and it["status"] == reqs.R_DONE else (
                ", причина: %s" % it.get("drop_reason") if it["status"] == reqs.R_DROP else "")
            if it.get("where") and it["status"] == reqs.R_DONE:
                extra += ", место: %s" % it["where"]
            print("%s [%s] %s. Цитата: «%s»%s" % (it["id"], it["status"], it["text"], common.short(it["quote"], 70), extra))
    print(reqs.line(proj) + ".")
    return 0


def c_route(a, cfg):
    if a.sub == "suggest":
        say(route.suggest_lines(route.row_for_step(cfg, a.step)))
        return 0
    proj = get_proj(a)
    say(route.escalate(proj, cfg, a.stage, a.reason))
    return 0


def c_doc(a, cfg):
    proj = get_proj(a)
    if a.sub == "init":
        doc, made = document.init(proj, a.title, a.opening, a.part, a.quote, a.source, a.replace, a.ending)
        say(["Структура документа записана в %s: частей %d, обязательных элементов начала %d." % (
            proj.where(document.DOC_JSON), len(doc["parts"]), len(doc["opening"])),
            ("Каркас создан: %s. Замените пометки %s своим текстом." % (proj.where(document.DOC_FILE), common.PLACEHOLDER)) if made
            else "Файл %s уже был: его текст не тронут." % proj.where(document.DOC_FILE),
            "Теперь результат задачи это один документ: три файла strategy/ не обязательны, page.md собирается из начала документа (doc page).",
            "Каждое требование закрывайте с местом: req close R01 --by %s --where \"часть N\". Проверка: python3 tools/rychag.py doc check" % document.DOC_FILE])
        if not doc["opening"]:
            print("Предупреждение: не задано, что должно быть в начале документа. Если заказчик это назвал, добавьте --opening и --replace.")
        return 0
    if not document.exists(proj):
        print("Структура документа не задана (нет %s). Если заказчик сам назвал части результата, начните с doc init." % proj.where(document.DOC_JSON))
        return 0
    if a.sub == "page":
        changed = document.write_page(proj)
        print("Страница %s %s." % (proj.where("page.md"), "собрана из начала документа" if changed else "уже совпадает с началом документа"))
        return 0
    res = [checks.layer_doc(proj, cfg)]
    lines, total = checks.format_layers(res)
    say([l.replace("Слой %d. " % checks.DOC_LAYER, "", 1) for l in lines])
    print(reqs.line(proj) + ".")
    if total:
        print("Итого: документ не готов, замечаний %d. Код возврата 2." % total)
        return 2
    print("Итого: документ проходит проверку.")
    return 0


def c_strategy(a, cfg):
    proj = get_proj(a)
    if document.exists(proj):
        print("В этой задаче заказчик задал структуру результата: три файла strategy/ не обязательны. Состав проверяет: python3 tools/rychag.py doc check")
        return 0
    lines, missing = strategy.check_lines(proj)
    say(lines)
    if missing:
        print("Не хватает частей: %d. Добавьте заголовок «## Название части» и под ним хотя бы одно предложение." % missing)
        return 2
    print("Все обязательные части на месте.")
    return 0


def c_diagnosis(a, cfg):
    proj = get_proj(a)
    lines, missing = diagnosis.diagnosis_lines(proj)
    say(lines)
    if missing:
        print("Не хватает частей: %d. Добавьте заголовок «## Название части» и под ним хотя бы одно предложение (в «За какой период данные» две даты)." % missing)
        return 2
    print("Все части диагноза на месте.")
    return 0


def c_layers(a, cfg):
    proj = get_proj(a)
    lines, missing = diagnosis.layers_lines(proj)
    say(lines)
    if missing:
        print("Не пройдено слоёв: %d. Под заголовком слоя нужен код записи (реестр или база знаний) либо строка «Пусто, потому что ...»." % missing)
        return 2
    print("Все пять слоёв пройдены.")
    return 0


def c_question(a, cfg):
    proj = get_proj(a)
    if a.sub == "add":
        print("Записан вопрос №%d." % ledger.add_question(proj, a.text, a.if_yes, a.if_no))
    else:
        ledger.close_question(proj, a.n, a.answer)
        print("Вопрос №%d закрыт." % a.n)
    return 0


def c_kb(a, cfg):
    root = a.root_path
    if a.sub == "source":
        m = kbase.add_source(root, cfg, a.url, a.text_file, a.fetch, a.published, a.title)
        print("Сохранён %s: %s (опубликован: %s, обращение: %s). Копия: knowledge/sources/%s.txt" % (
            m["id"], m["title"], m["published"] or "дата неизвестна", m["accessed"], m["id"]))
        if not m["published"]:
            print("Предупреждение: нет даты публикации, свежесть не проверить.")
        return 0
    if a.sub == "add":
        r = kbase.create_record(root, {"rule": a.rule, "applies_when": a.applies_when, "not_when": a.not_when,
                                       "themes": a.theme, "tags": a.tags, "layer": a.layer, "source": a.source,
                                       "quote": a.quote, "strength": a.strength, "place": a.place, "number": a.number,
                                       "kind": a.kind})
        kbase.build_index(root)
        print("Добавлена запись %s (%s, слой %s). Это ориентир, а не факт о продукте." % (r["id"], r["kind"], r["layer"]))
        if r["kind"] == "урок":
            print("Урок агента: годится только для гипотезы.")
        return 0
    if a.sub == "import":
        warns = []
        ok, bad = kbase.import_records(root, a.file, a.sources_dir, warns)
        kbase.build_index(root)
        print("Принято: %d. Отклонено: %d." % (ok, len(bad)))
        if warns:
            print("Предупреждение: у %d принятых записей нет даты публикации, свежесть не проверить (строки %s)." % (
                len(warns), ", ".join(str(n) for n, _w in warns[:20])))
        for n, why in bad:
            print("  - строка %d: %s" % (n, why))
        if bad:
            print("Отклонённые записи сохранены в knowledge/rejected.jsonl. Исправьте и импортируйте только их.")
        return 2 if bad else 0
    if a.sub == "search":
        if a.layer is not None:
            common.check_layer(a.layer, 2, 5)
        tp = trace.trace_project(root, a.project)
        res_all, nterms, near = kbase.search_ranked(root, a.words, a.theme, a.tag, a.related, 10 ** 9, a.all)
        per = {n: sum(1 for r, _h in res_all if (r.get("layer") or 5) == n) for n in range(2, 6)}
        res = [(r, h) for r, h in res_all if a.layer is None or (r.get("layer") or 5) == a.layer]
        total = len(res)
        res = res[:a.limit]
        if a.layer is not None:
            near = [(r, h) for r, h in near if (r.get("layer") or 5) == a.layer]
        rows = [r for r, _h in res]
        if not rows:
            if near:
                print("Ни одна запись не набрала допуск: нужно совпадение минимум %d из %d значимых слов запроса. Ближайшие три по числу совпавших слов:" % (
                    kbase.need_terms(nterms), nterms))
                for r, h in near:
                    print(kbase.short_line(r) + ". Совпало слов запроса: %d из %d" % (h, nterms))
            else:
                print("Ничего не найдено. Попробуйте другие слова или уберите фильтры.")
        for r, h in res:
            print(kbase.short_line(r) + (". Совпало слов запроса: %d из %d" % (h, nterms) if nterms else ""))
        if rows:
            print("Это ориентиры, а не факты о продукте. Чтобы использовать: claim add --type benchmark --kb %s ..." % rows[0]["id"])
        print("Результатов по слоям: " + "; ".join("слой %d: %d" % (n, per[n]) for n in range(2, 6)) + "." +
              (" Показан только слой %d." % a.layer if a.layer is not None else ""))
        trace.record_query(tp, trace.SEARCH_CMD, {"query": a.words, "results": total, "layer": a.layer,
                                                  "per_layer": {str(n): per[n] for n in per}, "theme": a.theme, "tag": a.tag})
        hint = trace.no_project_hint(root, a.project)
        if hint:
            print(hint)
        return 0
    if a.sub == "show":
        tp = trace.trace_project(root, a.project)
        try:
            lines = kbase.show_lines(kbase.get_record(root, a.id))
        except Fail:
            trace.record_query(tp, trace.SHOW_CMD, {"id": a.id, "results": 0})
            raise
        trace.record_query(tp, trace.SHOW_CMD, {"id": a.id, "results": 1})
        say(lines)
        hint = trace.no_project_hint(root, a.project)
        if hint:
            print(hint)
        return 0
    if a.sub == "link":
        kbase.link(root, a.a, a.b, a.note)
        print("Связаны %s и %s." % (a.a, a.b))
        return 0
    if a.sub == "list":
        if a.stale:
            rows = [r for r, _w in kbase.stale_records(root, cfg)]
        else:
            rows = [r for r in kbase.load_records(root) if a.all or r["status"] == kbase.R_ACTIVE]
        if a.theme:
            t = common.norm_match(a.theme)
            rows = [r for r in rows if any(common.norm_match(x) == t for x in r["themes"])]
        if not rows:
            print("Записей нет.")
        for r in rows:
            print(kbase.short_line(r))
        return 0
    if a.sub == "retire":
        kbase.retire(root, a.id, a.reason)
        kbase.build_index(root)
        print("Запись %s отозвана: %s. Проверьте, на что она влияла: python3 tools/rychag.py impact %s -p <задача>" % (a.id, a.reason, a.id))
        _report_links(root)
        return 0
    if a.sub == "replace":
        kbase.replace(root, a.id, a.by, a.reason)
        kbase.build_index(root)
        print("Запись %s заменена записью %s. Проверьте, на что она влияла: python3 tools/rychag.py impact %s -p <задача>" % (a.id, a.by, a.id))
        _report_links(root)
        return 0
    if a.sub == "stats":
        st = learn.kb_stats(root)
        recs = {r["id"]: r for r in kbase.load_records(root)}
        lines = []
        if not st:
            print("Действующих записей нет.")
        for bid in sorted(st):
            x = st[bid]
            line = ("%s: %s. Использована как ориентир в проектах: %d раз. Выводов на ней: принято %d, отклонено %d. "
                    "Фактических результатов: подтвердили %d, не подтвердили %d, без сравнения %d." % (
                        bid, common.short(recs[bid]["rule"], 60), x["used"], x["concl_ok"], x["concl_bad"], x["out_yes"], x["out_no"], x["out_none"]))
            if x["reasons"]:
                line += " Замечания руководителя: " + "; ".join("«%s» %d" % (learn.REASON_RU[k], v) for k, v in sorted(x["reasons"].items())) + "."
            lines.append(line)
        lines.append("Результат подтвердил запись, если факт попал в диапазон оценки от низкой до высокой, и не подтвердил, если вышел за него. "
                     "Оценка берётся из рычага, на котором держится решение.")
        say(common.explain_lever(lines))
        return 0
    if a.sub == "stale":
        rows = kbase.stale_records(root, cfg)
        if not rows:
            print("Устаревших записей нет.")
        for r, why in rows:
            print("%s: %s. Найдите свежее подтверждение и замените: kb replace %s --by B..." % (r["id"], why, r["id"]))
        return 0
    n = kbase.build_index(root)
    print("Индекс обновлён: knowledge/INDEX.md, действующих записей %d." % n)
    return 0


def _report_links(root):
    for lid, old, new in kbmap.refresh_links(root):
        print("Карта причин: связь %s стала «%s» (была «%s»): действующих записей-оснований не осталось." % (lid, new, old))


def c_map(a, cfg):
    root = a.root_path
    if a.sub == "node":
        if a.sub2 == "add":
            n = kbmap.add_node(root, a.name, a.kind, a.alias)
            print("Добавлен узел %s «%s» (%s)." % (n["id"], n["name"], n["kind"]))
            return 0
        rows = kbmap.load_nodes(root)
        if not rows:
            print("Узлов нет. Добавить: python3 tools/rychag.py map node add --name \"...\" --kind показатель")
        for n in rows:
            print("%s [%s] %s%s" % (n["id"], n["kind"], n["name"], " (также: %s)" % ", ".join(n["aliases"]) if n.get("aliases") else ""))
        return 0
    if a.sub == "link":
        nodes = {n["id"]: n for n in kbmap.load_nodes(root)}
        if a.sub2 == "add":
            l, merged = kbmap.add_link(root, a.frm, a.to, a.sign, a.conditions, a.evidence, a.note, a.contradicted_by)
            print("%s связь %s: %s." % ("Объединено с существующей" if merged else "Добавлена", l["id"], kbmap.link_line(root, l, nodes)))
            if l["status"] == kbmap.L_HYPOTHESIS:
                print("Записей-оснований нет: связь это гипотеза, знанием не считается. Добавьте --evidence B012.")
            return 0
        if a.sub2 == "retire":
            l = kbmap.retire_link(root, a.id, a.reason)
            print("Связь %s отозвана: %s." % (l["id"], a.reason))
            return 0
        rows = kbmap.load_links(root)
        if not rows:
            print("Связей нет.")
        for l in rows:
            print(kbmap.link_line(root, l, nodes))
        return 0
    if a.sub == "import":
        st, bad = kbmap.import_map(root, a.file)
        print("Принято: узлов %d, связей %d. Отклонено: %d." % (st["nodes_ok"], st["links_ok"], len(bad)))
        print("Уже есть: узлов %d, связей %d. Дополнено существующих связей: %d." % (st["nodes_same"], st["links_same"], st["links_merged"]))
        for n, why in bad:
            print("  - строка %d: %s" % (n, why))
        if bad:
            print("Отклонённые строки сохранены в knowledge/map/rejected.jsonl. Исправьте и импортируйте только их.")
        return 2 if bad else 0
    if a.sub in ("causes", "effects"):
        if a.depth < 1:
            raise Fail("Глубина должна быть не меньше 1.")
        if a.layer_max is not None:
            common.check_layer(a.layer_max)
        tp = trace.trace_project(root, a.project)
        cmd = "map " + a.sub
        try:
            node = kbmap.resolve_node(root, a.node)
        except kbmap.NoNode as e:
            trace.record_query(tp, cmd, {"query": a.node, "results": 0, "node": None, "note": "на карте нет узла под эти слова"})
            if tp is not None:
                raise kbmap.NoNode("%s\nЗапрос записан в журнал: карту просмотрели, подходящего узла нет." % e)
            raise
        except Fail as e:
            trace.record_query(tp, cmd, {"query": a.node, "results": 0, "node": None, "note": "запрос подошёл к нескольким узлам"})
            raise
        direction = "up" if a.sub == "causes" else "down"
        found = len(kbmap.traverse(root, node["id"], direction, a.depth, a.layer_max, a.proven_only))
        trace.record_query(tp, cmd, {"query": a.node, "results": found, "node": node["id"]})
        say(kbmap.chain_lines(root, node, direction, a.depth, a.layer_max, a.proven_only))
        hint = trace.no_project_hint(root, a.project)
        if hint:
            print(hint)
        return 0
    if a.sub == "path":
        tp = trace.trace_project(root, a.project)
        q = "%s -> %s" % (a.a, a.b)
        try:
            lines = kbmap.path_lines(root, a.a, a.b)
        except Fail:
            trace.record_query(tp, "map path", {"query": q, "results": 0, "note": "узел не найден"})
            raise
        n = int(lines[0].split(": ")[-1].rstrip(".")) if lines[0].startswith("Кратчайшие") else 0
        trace.record_query(tp, "map path", {"query": q, "results": n})
        say(lines)
        hint = trace.no_project_hint(root, a.project)
        if hint:
            print(hint)
        return 0
    if a.sub == "check":
        total = 0
        for title, rows, problem in kbmap.check(root):
            print("%s: %s" % (title, "замечаний нет" if not rows else len(rows)))
            for r in rows:
                print("  - " + r)
            if problem:
                total += len(rows)
        print("Итого замечаний: %d." % total)
        return 2 if (total and a.strict) else 0
    path = kbmap.export_mermaid(root, a.around, a.depth)
    print("Карта записана: knowledge/map/%s" % path.name)
    return 0


def c_feedback(a, cfg):
    if a.sub == "reasons":
        say(learn.reasons_lines())
        return 0
    proj = get_proj(a)
    if a.sub == "add":
        r = learn.add_feedback(proj, a.target, a.verdict, a.reason, a.note)
        common.journal(proj, "feedback add", {"target": r["target"]})
        say(common.explain_lever(["Записан отзыв %s об объекте %s (%s): %s%s. Статусы выводов, утверждений и записей базы знаний не менялись." % (
            r["id"], r["target"], learn.ELEMENT_RU[r["element"]], learn.VERDICT_RU[r["verdict"]], ". Причина: «%s»" % learn.REASON_RU[r["reason"]] if r["reason"] else "")]))
        return 0
    rows = learn.load_feedback(proj)
    lines = []
    if not rows:
        lines.append("Отзывов нет.")
    for r in rows:
        lines.append("%s. Объект %s (%s): %s%s. Дата %s.%s" % (r["id"], r["target"], learn.ELEMENT_RU[r["element"]], learn.VERDICT_RU[r["verdict"]],
                                                          ". Причина: «%s»" % learn.REASON_RU[r["reason"]] if r["reason"] else "", r["date"],
                                                          " Пояснение: " + r["note"] if r["note"] else ""))
    say(common.explain_lever(lines))
    return 0


def c_outcome(a, cfg):
    proj = get_proj(a)
    if a.sub == "add":
        o = learn.add_outcome(proj, a.decision, a.metric, a.actual, a.period, a.source, a.note)
        common.journal(proj, "outcome add", {"decision": o["decision"]})
        lines = ["Записан фактический результат %s по решению %s: показатель «%s» за %s равен %s. Надёжность: %s." % (
            o["id"], o["decision"], o["metric"], o["period"], o["actual"], o["strength"])]
        if not o["comparisons"]:
            lines.append("Решение не опирается на рычаг, поэтому сравнить результат с оценкой эффекта не с чем.")
        for c in o["comparisons"]:
            e = c["effect"]
            lines.append("Рычаг %s: оценка эффекта была %s (низкая), %s (базовая), %s (высокая). Фактический результат %s: %s." % (
                c["lever"], e["low"], e["base"], e["high"], o["actual"], c["position"]))
        say(common.explain_lever(lines))
        return 0
    rows = learn.load_outcomes(proj)
    lines = []
    if not rows:
        lines.append("Фактических результатов нет.")
    for o in rows:
        lines.append("%s. Решение %s, показатель «%s» за %s: %s. Надёжность: %s. Сравнение с оценкой: %s." % (
            o["id"], o["decision"], o["metric"], o["period"], o["actual"], o["strength"],
            "; ".join(c["position"] for c in o["comparisons"]) or "нет"))
    say(common.explain_lever(lines))
    return 0


def c_learn(a, cfg):
    root = a.root_path
    if a.sub == "wave":
        if a.since:
            common.parse_date(a.since)
        props, hints, base = learn.wave(root, a.since)
        lines = ["Подсказка: " + h for h in hints]
        if not props:
            lines.append("Поводов для предложений пока нет: новых отзывов и фактических результатов недостаточно. Ничего не записано.")
            say(common.explain_lever(lines))
            return 0
        lines.append("Предложений: %d. Файлы: learn/%s.md и learn/%s.json. Ничего не применено." % (len(props), base, base))
        for p in props:
            lines.append("  %s. %s. Вид: %s. Основания: отзывов %d, фактических результатов %d." % (
                p["id"], p["title"], p["kind"], len(p["grounds"]["feedback"]), len(p["grounds"]["outcomes"])))
        lines.append("Применить одно предложение: python3 tools/rychag.py learn apply P001 --approved-by \"имя\"")
        say(common.explain_lever(lines))
        return 0
    if a.sub == "apply":
        pr, result = learn.apply_proposal(root, a.id, a.approved_by)
        print("Предложение %s применено: %s." % (a.id, result))
        return 0
    if a.sub == "reject":
        learn.reject_proposal(root, a.id, a.reason)
        print("Предложение %s отклонено: %s." % (a.id, a.reason))
        return 0
    say(common.explain_lever(learn.history_lines(root)))
    return 0


def c_doctor(a, cfg):
    code, lines = stages.doctor(a.root_path, load_config)
    say(lines)
    return code


HANDLERS = {"new": c_new, "status": c_status, "stage": c_stage, "source": c_source, "claim": c_claim,
            "incident": c_incident, "conclusion": c_conclusion, "lever": c_lever, "calc": c_calc, "verify": c_verify, "gate": c_gate,
            "impact": c_impact, "sweep": c_sweep, "decision": c_decision, "cost": c_cost, "done": c_done,
            "question": c_question, "req": c_req, "route": c_route, "strategy": c_strategy, "doc": c_doc, "diagnosis": c_diagnosis, "layers": c_layers, "kb": c_kb, "map": c_map, "feedback": c_feedback, "outcome": c_outcome,
            "learn": c_learn, "doctor": c_doctor}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 1
    try:
        common.set_today(args.today)
        args.root_path = os.path.abspath(args.root) if args.root else str(default_root())
        cfg = None if args.cmd in ("doctor", "new") else load_config(args.root_path)
        return HANDLERS[args.cmd](args, cfg)
    except Fail as e:
        print("Ошибка: %s" % e, file=sys.stderr)
        return 1
    except Exception as e:  # непредвиденное: не прячем, но говорим по-русски
        print("Внутренняя ошибка (%s: %s). Сообщите, какая команда вызвала её." % (type(e).__name__, e), file=sys.stderr)
        return 1
    finally:
        common.set_today(None)


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    sys.exit(main())
