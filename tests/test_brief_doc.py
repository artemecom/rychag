# -*- coding: utf-8 -*-
"""Бриф заказчика с заданной структурой результата: документ по частям, допущения, готовые расчёты, место требований."""
import json
import unittest

from helpers import Env, ROOT

from lib import calcs, checks, common  # noqa: E402  (путь к tools добавляет helpers)
from lib.common import Fail, Project  # noqa: E402

EX = ("-p", "_example")

DOC_OK = """# Продление подписки: что менять

**Первые клиенты:** новые подписчики, пришедшие после первого июля.

**Выбранная проблема:** пробный период сократили с 14 до 7 дней, и продление новых упало с 73% до 64%.

**Предложение:** вернуть новым пробный период в 14 дней.

**Ожидаемый результат:** оценка эффекта на общее продление от 1 до 4 процентных пунктов, вероятно около 2.

## 1. Клиент и его проблема

Уровень продления упал с 71% до 65%. Новый подписчик не успевает привыкнуть к сервису.

## 2. Предложение и путь к клиенту

Возвращаем пробный период новым. Цена остаётся 490 рублей.

## 3. Проверка и прибыль

Тест идёт 4 недели, половине новых даём прежний срок.

## Почему провалится

Причина может быть в цене, а не в сроке.
"""

INIT = ("doc", "init", "--title", "Продление подписки: что менять",
        "--opening", "Первые клиенты", "--opening", "Выбранная проблема", "--opening", "Предложение", "--opening", "Ожидаемый результат",
        "--part", "Клиент и его проблема", "--part", "Предложение и путь к клиенту", "--part", "Проверка и прибыль")


def text_of(lines):
    return "\n".join(lines)


class CalcFormulaTests(unittest.TestCase):
    """Формулы готовых расчётов на числах из брифа заказчика."""

    def test_number_format(self):
        self.assertEqual(calcs.fmt(12000), "12 000")
        self.assertEqual(calcs.fmt(62.5), "62,5")
        self.assertEqual(calcs.fmt(-300000), "минус 300 000")
        self.assertEqual(calcs.pct(2 / 3), "66,7 %")

    def test_balance_goal_and_gap_to_no_change_forecast(self):
        out = text_of(calcs.compute("сведение", {"единица": "групп", "на_начало": 6500, "новые": 6800, "выбывшие": 1300,
                                                "цель": 12000, "без_изменений": 8000}))
        self.assertIn("на начало 6 500 плюс новые 6 800 минус выбывшие 1 300 равно 12 000", out)
        self.assertIn("нужен чистый прирост 5 500", out)  # 12 000 минус 6 500
        self.assertIn("целью 12 000 составляет 4 000", out)  # 12 000 минус 8 000
        self.assertIn("только эту разницу можно относить к изменениям", out)
        self.assertIn("новых подключений нужно 6 800", out)

    def test_balance_short_of_goal(self):
        out = text_of(calcs.compute("сведение", {"на_начало": 6500, "новые": 3000, "выбывшие": 1000, "цель": 12000, "без_изменений": 8000}))
        self.assertIn("не хватает 3 500", out)
        self.assertIn("План закрывает из этого разрыва 500, это 12,5 %", out)

    def test_funnel_shares_by_step(self):
        # создали 100 групп, приглашение приняли в 60, действие в срок выполнили в 30: доля 30 из 100
        out = text_of(calcs.compute("воронка", {"единица": "групп", "шаги": ["приняли приглашение", "совершили действие"],
                                               "каналы": [{"название": "приложение", "увидели": 100, "доли_процентов": [60, 50]}]}))
        self.assertIn("приняли приглашение 60 (60 % от предыдущего шага)", out)
        self.assertIn("совершили действие 30 (50 % от предыдущего шага)", out)
        self.assertIn("Всего дошли до конца 30 из 100 увидевших, это 30 %", out)

    def test_funnel_channels_without_double_count_and_cost_of_extra(self):
        p = {"шаги": ["подключились"],
             "каналы": [{"название": "приложение", "увидели": 1000, "доли_процентов": [10], "и_так_подключились": 40},
                        {"название": "поддержка", "увидели": 400, "доли_процентов": [25], "и_так_подключились": 50, "расходы": 100000}],
             "пересечения": [{"каналы": ["приложение", "поддержка"], "число": 200}], "правило_отнесения": ["поддержка", "приложение"]}
        out = text_of(calcs.compute("воронка", p))
        self.assertIn("200 отнесены к каналу «поддержка»", out)
        self.assertIn("после вычета пересечений 800", out)
        self.assertIn("без двойного счёта: увидели 1 200; подключились 180", out)  # 80 и 100, а не 100 и 100
        self.assertIn("при обычном обслуживании было бы 50, прирост 50. Расходы 100 000: одно дополнительное подключение стоит 2 000", out)
        self.assertIn("Суммарный прирост против обычного обслуживания: 90", out)
        p["правило_отнесения"] = ["приложение", "поддержка"]  # правило отнесения это параметр: меняем его, меняется разнесение
        out = text_of(calcs.compute("воронка", p))
        self.assertIn("200 отнесены к каналу «приложение»", out)
        self.assertIn("увидели 1 200; подключились 150", out)
        del p["правило_отнесения"]
        with self.assertRaises(Fail):
            calcs.compute("воронка", p)

    def test_active_share_and_split_of_growth(self):
        out = text_of(calcs.compute("активность", {"база_подключённые": 8000, "база_активные": 5000,
                                                  "план_подключённые": 12000, "план_активные": 8000}))
        self.assertIn("активных 5 000 из 8 000 подключённых, это 62,5 % (5 из 8)", out)
        self.assertIn("активных 8 000 из 12 000 подключённых, это 66,7 % (2 из 3)", out)  # две трети
        self.assertIn("равно 2 500", out)  # за счёт числа групп
        self.assertIn("равно 500", out)    # за счёт доли
        self.assertIn("Изменение числа активных: 3 000", out)

    def test_breakeven_base_line_and_three_variants(self):
        p = {"единица": "дополнительных оплаченных месяцев", "разрыв": 6000000, "ставка": 500,
             "варианты": {"слабый": {"единиц": 6000, "прямые_расходы": 1000000}, "основной": {"единиц": 14000, "прямые_расходы": 1000000},
                          "сильный": {"единиц": 20000, "прямые_расходы": 1500000}}}
        out = text_of(calcs.compute("граница", p))
        self.assertIn("6 000 000 разделить на 500 равно 12 000", out)
        self.assertIn("Вариант «слабый»: ожидаем 6 000, прямые расходы 1 000 000, ставка 500. Граница: нужно 14 000", out)
        self.assertIn("Разрыв закрыт на 33,3 %, не хватает 4 000 000", out)
        self.assertIn("Вариант «сильный»", out)
        self.assertIn("Разрыв закрыт, запас 2 500 000", out)
        del p["варианты"]["слабый"]
        with self.assertRaises(Fail):
            calcs.compute("граница", p)

    def test_retention_by_launch_month_and_last_month_cap(self):
        out = text_of(calcs.compute("удержание", {"ставка": 500, "запуски": [{"месяц": 5, "число": 100, "доп_месяцев_на_единицу": 2},
                                                                           {"месяц": 12, "число": 100, "доп_месяцев_на_единицу": 2}]}))
        self.assertIn("200 умножить на 500 равно 100 000", out)  # 100 номеров на два месяца по 500 рублей
        self.assertIn("в период попадает 1;", out)               # работа последнего месяца даёт максимум один месяц
        self.assertIn("100 умножить на 500 равно 50 000", out)
        self.assertIn("Итого в периоде: дополнительных оплаченных месяцев 300, вклад 150 000", out)
        self.assertIn("За пределами периода остаётся дополнительных оплаченных месяцев 100", out)

    def test_retention_by_paying_shares(self):
        out = text_of(calcs.compute("удержание", {"ставка": 500, "запуски": [
            {"месяц": 11, "число": 1000, "платят_новое_процентов": [100, 96, 93], "платят_обычное_процентов": [100, 90, 85]}]}))
        self.assertIn("всего дополнительных оплаченных месяцев 60", out)  # в год попадают два месяца: 0 и 6 процентов
        self.assertIn("остаётся дополнительных оплаченных месяцев 80", out)

    def test_payback_by_quarters_and_investment_limit(self):
        p = {"доп_прибыль_по_кварталам": [0, 200000, 600000, 900000], "прямые_расходы_по_кварталам": [50000, 100000, 100000, 100000],
             "вложения_по_кварталам": [300000, 500000, 0, 0]}
        out = text_of(calcs.compute("окупаемость", p))
        self.assertIn("Квартал 3: дополнительная прибыль 600 000, прямые расходы 100 000, после расходов 500 000; накоплено 550 000; "
                      "вложения накоплено 800 000: не покрыты, не хватает 250 000", out)
        self.assertIn("Расчётный срок окупаемости: квартал 4", out)
        self.assertIn("(кварталов: 4): 1 350 000", out)
        del p["вложения_по_кварталам"]
        p["срок_кварталов"] = 3
        out = text_of(calcs.compute("окупаемость", p))
        self.assertIn("Вложения не заданы", out)
        self.assertIn("(кварталов: 3): 550 000", out)
        out = text_of(calcs.compute("окупаемость", {"доп_прибыль_по_кварталам": [0, 0], "прямые_расходы_по_кварталам": [10, 10],
                                                   "вложения_по_кварталам": [100, 0]}))
        self.assertIn("вложения не возвращаются", out)
        self.assertIn("ноль", out)

    def test_sample_size_for_two_shares(self):
        out = text_of(calcs.compute("выборка", {"доля_обычная_процентов": 12, "доля_ожидаемая_процентов": 9}))
        self.assertIn("Разница в процентных пунктах: 3; относительно обычной доли это снижение на 25 %", out)
        self.assertIn("Нужно в каждой группе: 1 636. Всего (групп: 2): 3 272", out)   # двусторонние 5 % и мощность 80 %
        self.assertIn("односторонняя проверка при тех же условиях: 1 289", out)
        one = text_of(calcs.compute("выборка", {"доля_обычная_процентов": 12, "доля_ожидаемая_процентов": 9, "стороны": 1}))
        self.assertIn("Нужно в каждой группе: 1 289", one)
        # проверка формулы независимым счётом
        from statistics import NormalDist
        z = NormalDist().inv_cdf(0.975) + NormalDist().inv_cdf(0.8)
        n = z * z * (0.12 * 0.88 + 0.09 * 0.91) / 0.03 ** 2
        self.assertAlmostEqual(calcs.group_size(0.12, 0.09, 0.05, 0.8, 2), n, places=6)

    def test_sample_reverse_and_recruitment_pace(self):
        out = text_of(calcs.compute("выборка", {"доля_обычная_процентов": 12, "участников_в_группе": 300,
                                               "нужно_участников": 600, "набор_недель": 6, "наблюдение_недель": 1}))
        self.assertIn("чтобы набрать 600 за срок набора (недель: 6), каждую неделю должно появляться в среднем 100", out)
        self.assertIn("на 300 в каждой группе видно изменение не меньше чем на 6,5", out)
        d = calcs.smallest_visible(0.12, 300, 0.05, 0.8, 2)
        self.assertLessEqual(calcs.group_size(0.12, 0.12 - d, 0.05, 0.8, 2), 300.0001)
        self.assertGreater(calcs.group_size(0.12, 0.12 - d + 0.002, 0.05, 0.8, 2), 300)
        flow = text_of(calcs.compute("выборка", {"доля_обычная_процентов": 12, "доля_ожидаемая_процентов": 9, "поток_в_неделю": 100, "наблюдение_недель": 1}))
        self.assertIn("на набор 3 272 нужно недель: 33", flow)
        self.assertIn("через недель: 34", flow)

    def test_bad_parameters_are_explained(self):
        for kind, p in (("сведение", {"на_начало": 10}), ("выборка", {"доля_обычная_процентов": 12}),
                        ("выборка", {"доля_обычная_процентов": 12, "доля_ожидаемая_процентов": 12}),
                        ("активность", {"база_подключённые": 10, "база_активные": 20, "план_подключённые": 10, "план_активные": 5}),
                        ("нет такого", {})):
            with self.assertRaises(Fail, msg=kind):
                calcs.compute(kind, p)

    def test_every_template_computes(self):
        for kind, spec in calcs.KINDS.items():
            self.assertTrue(calcs.compute(kind, spec["template"]), kind)


class BriefEnv(Env):
    TODAY = "2026-11-19"

    def brief(self, pid="b"):
        p = self.new_project(pid, "Сдайте один документ из трёх частей. В начале назовите первых клиентов и ожидаемый результат.")
        self.write(p / "materials" / "brief.txt",
                   "На начало года подключено 6 500 групп. Без изменений ожидается 8 000 групп, цель не ниже 12 000.\n"
                   "До цели по прибыли не хватает 6 000 000 рублей. Ставка: 500 рублей за один дополнительный оплаченный месяц.\n")
        self.ok("source", "add", "-p", pid, "--file", "materials/brief.txt", "--published", "2026-11-19")
        self.ok("claim", "add", "-p", pid, "--type", "fact", "--source", "S001", "--quote", "не хватает 6 000 000 рублей",
                "--number", "6 000 000", "--text", "До цели по прибыли не хватает 6 000 000 рублей")
        self.ok("claim", "add", "-p", pid, "--type", "fact", "--source", "S001", "--quote", "Ставка: 500 рублей",
                "--number", "500", "--text", "Ставка 500 рублей за дополнительный оплаченный месяц")
        return p

    def assume(self, pid="b", *extra):
        return self.ok("claim", "add", "-p", pid, "--type", "assumption", "--text", "Дополнительных оплаченных месяцев за год",
                       "--low", "6000", "--base", "14000", "--high", "20000", "--why", "нижняя граница: половина нужного, верхняя: охват всех групп",
                       "--verify-by", "платежи групп сравнения через два квартала", *extra)

    def breakeven(self, p, pid="b", rests="C001,C002,C003"):
        self.write(p / "analysis" / "granica.json", json.dumps({
            "разрыв": 6000000, "ставка": 500,
            "варианты": {"слабый": {"единиц": 6000}, "основной": {"единиц": 14000}, "сильный": {"единиц": 20000}}}, ensure_ascii=False))
        return self.ok("calc", "ready", "-p", pid, "граница", "--params", "analysis/granica.json", "--rests-on", rests)


class ReadyCalcTests(BriefEnv):
    def test_list_and_template(self):
        out = self.ok("calc", "list")
        for kind in ("сведение", "воронка", "активность", "граница", "удержание", "окупаемость", "выборка"):
            self.assertIn(kind + ":", out)
        p = self.brief()
        out = self.ok("calc", "template", "-p", "b", "выборка")
        self.assertTrue((p / "analysis" / "vyborka.json").exists())
        self.assertIn("calc ready выборка --params analysis/vyborka.json", out)
        code, out = self.run_cmd("calc", "template", "-p", "b", "выборка")
        self.assertEqual(code, 1)
        self.assertIn("уже есть", out)

    def test_ready_calc_is_saved_quoted_and_rechecked(self):
        p = self.brief()
        self.write(p / "analysis" / "granica.json", "{}")
        code, out = self.run_cmd("calc", "ready", "-p", "b", "граница", "--params", "analysis/granica.json")
        self.assertEqual(code, 1, "без --rests-on расчёт не принимается")
        code, out = self.run_cmd("calc", "ready", "-p", "b", "граница", "--params", "analysis/granica.json", "--rests-on", "C099")
        self.assertEqual(code, 1)
        self.assertIn("такого утверждения нет", out)
        self.assume()
        out = self.breakeven(p)
        self.assertIn("сохранён как источник S002", out)
        self.assertIn("6 000 000 разделить на 500 равно 12 000", out)
        self.assertNotIn("Чисел параметров нет в записях", out)
        meta = json.loads((p / "sources" / "S002.meta.json").read_text(encoding="utf-8"))
        self.assertEqual((meta["kind"], meta["ready"], meta["rests_on"]), ("расчёт", "граница", ["C001", "C002", "C003"]))
        self.ok("claim", "add", "-p", "b", "--type", "calc", "--source", "S002", "--quote", "6 000 000 разделить на 500 равно 12 000",
                "--number", "12 000", "--text", "Без новых расходов нужно 12 000 дополнительных оплаченных месяцев")
        code, data = self.verify_json("-p", "b", "--layer", "1")
        self.assertTrue(data["layers"]["1"]["ok"], data)
        again = self.breakeven(p)
        self.assertIn("уже сохранён как S002", again)
        # параметры поменяли после расчёта: verify это видит
        self.write(p / "analysis" / "granica.json", (p / "analysis" / "granica.json").read_text(encoding="utf-8").replace("14000", "15000"))
        code, data = self.verify_json("-p", "b", "--layer", "1")
        self.assertIn("файл параметров analysis/granica.json изменён", self.issues_text(data, 1))
        # отпечаток файла подогнали, но повторный расчёт всё равно даёт другой вывод
        meta["inputs"][0]["sha256"] = common.sha256_file(p / "analysis" / "granica.json")
        self.write(p / "sources" / "S002.meta.json", json.dumps(meta, ensure_ascii=False))
        code, data = self.verify_json("-p", "b", "--layer", "1")
        self.assertIn("повторный расчёт дал другой вывод", self.issues_text(data, 1))

    def test_parameter_without_record_is_reported(self):
        p = self.brief()
        self.write(p / "analysis" / "g.json", json.dumps({"разрыв": 6000000, "ставка": 500, "варианты": {
            "слабый": {"единиц": 777}, "основной": {"единиц": 888}, "сильный": {"единиц": 999}}}, ensure_ascii=False))
        out = self.ok("calc", "ready", "-p", "b", "граница", "--params", "analysis/g.json", "--rests-on", "C001,C002")
        self.assertIn("Чисел параметров нет в записях из --rests-on: 777, 888, 999", out)

    def test_script_calc_can_name_its_grounds(self):
        p = self.brief()
        self.assume()
        self.write(p / "analysis" / "s.py", "print('итог: 4242')\n")
        self.ok("calc", "run", "-p", "b", "s.py", "--rests-on", "C003")
        out = self.ok("claim", "add", "-p", "b", "--type", "calc", "--source", "S002", "--quote", "итог: 4242", "--number", "4242", "--text", "Итог 4242")
        self.assertIn("стоит на допущениях (C003)", out)


class AssumptionTests(BriefEnv):
    def test_assumption_needs_range_reason_and_check(self):
        self.brief()
        base = ("claim", "add", "-p", "b", "--type", "assumption", "--text", "Доля подключившихся")
        for args, word in ((("--high", "12", "--why", "x", "--verify-by", "y"), "--low"),
                           (("--low", "5", "--high", "12", "--verify-by", "y"), "--why"),
                           (("--low", "5", "--high", "12", "--why", "x"), "--verify-by"),
                           (("--low", "15", "--high", "12", "--why", "x", "--verify-by", "y"), "перепутаны"),
                           (("--low", "5", "--high", "12", "--base", "20", "--why", "x", "--verify-by", "y"), "между границами"),
                           (("--low", "много", "--high", "12", "--why", "x", "--verify-by", "y"), "числом"),
                           (("--low", "5", "--high", "12", "--why", "x", "--verify-by", "y", "--source", "S001", "--quote", "Ставка"), "не нужны")):
            code, out = self.run_cmd(*base, *args)
            self.assertEqual(code, 1, args)
            self.assertIn(word, out)
        code, out = self.run_cmd("claim", "add", "-p", "b", "--type", "hypothesis", "--text", "гипотеза", "--low", "5")
        self.assertEqual(code, 1)
        self.assertIn("только для типа assumption", out)

    def test_missing_switch_threshold_warns_and_summary_is_a_table(self):
        p = self.brief()
        out = self.assume()
        self.assertIn("не задан порог смены решения", out)
        out = self.ok("claim", "add", "-p", "b", "--type", "assumption", "--text", "Доля групп, принявших приглашение", "--low", "40", "--base", "60",
                      "--high", "70", "--unit", "%", "--why", "по прошлым запускам", "--verify-by", "небольшой запуск на одном тарифе",
                      "--switch-if", "ниже 40 % меняем способ приглашения")
        self.assertNotIn("не задан порог", out)
        row = [json.loads(l) for l in (p / "ledger" / "claims.jsonl").read_text(encoding="utf-8").splitlines()][-1]
        self.assertEqual(row["range"], {"low": "40", "high": "70", "why": "по прошлым запускам", "how": "небольшой запуск на одном тарифе",
                                        "base": "60", "switch": "ниже 40 % меняем способ приглашения", "unit": "%"})
        out = self.ok("claim", "assumptions", "-p", "b")
        self.assertIn("Допущений: 2", out)
        self.assertIn("| Допущение | Низкое | Основное | Высокое | Почему такие границы | Как проверим | Когда выберем другой путь |", out)
        self.assertIn("| Доля групп, принявших приглашение | 40 % | 60 % | 70 % | по прошлым запускам | небольшой запуск на одном тарифе | ниже 40 % меняем способ приглашения |", out)
        self.assertIn("у допущений C003 не задан порог смены решения", out)
        table = out.split("Таблица допущений")[1]
        self.assertIsNone(checks.CODE_RE.search(table.split("Предупреждение")[0]), "в таблице для документа не должно быть номеров записей")
        self.assertIn("Допущения (приняты до проверки): 2, без порога смены решения: 1", self.ok("status", "-p", "b"))
        code, data = self.verify_json("-p", "b", "--layer", "2")
        self.assertIn("не задан порог смены решения", " ".join(w["what"] for w in data["layers"]["2"]["warnings"]))

    def test_assumption_number_on_page_needs_the_word(self):
        self.ok("claim", "add", *EX, "--type", "assumption", "--text", "Новых подписчиков в месяц", "--low", "800", "--base", "1000", "--high", "1200",
                "--why", "разброс трёх месяцев", "--verify-by", "выгрузка подключений", "--switch-if", "ниже 800 продлеваем тест")
        page = self.root / "projects" / "_example" / "page.md"
        orig = page.read_text(encoding="utf-8")
        self.write(page, orig.replace("## Три пути", "В месяц приходит от 800 до 1200 новых подписчиков.\n\n## Три пути"))
        code, data = self.verify_json(*EX, "--layer", "5")
        self.assertIn("число из допущения (800) без слова «допущение»", self.issues_text(data, 5))
        self.write(page, orig.replace("## Три пути", "Допущение: в месяц приходит от 800 до 1200 новых подписчиков.\n\n## Три пути"))
        code, data = self.verify_json(*EX, "--layer", "5")
        self.assertTrue(data["layers"]["5"]["ok"], data["layers"]["5"]["issues"])
        # в таблице слово может стоять в шапке
        self.write(page, orig.replace("## Три пути", "| Допущение | Низкое | Высокое |\n|---|---|---|\n| Новых в месяц | 800 | 1200 |\n\n## Три пути"))
        code, data = self.verify_json(*EX, "--layer", "5")
        self.assertTrue(data["layers"]["5"]["ok"], data["layers"]["5"]["issues"])

    def test_calc_on_assumption_inherits_the_mark(self):
        p = self.brief()
        self.assume()
        self.breakeven(p)
        out = self.ok("claim", "add", "-p", "b", "--type", "calc", "--source", "S002", "--quote", "Вклад после прямых расходов: 7 000 000",
                      "--number", "7 000 000", "--text", "Основной вариант даёт 7 000 000 рублей")
        self.assertIn("стоит на допущениях (C003)", out)
        proj = Project(self.root, "b")
        nb = checks._eligible_numbers(proj)
        self.assertIn("7000000", nb.derived)
        self.assertNotIn("7000000", nb.ok)
        self.assertEqual(nb.assume, {"6000", "14000", "20000"})
        self.assertIn("C004 [расчёт, действует]", self.ok("claim", "list", "-p", "b"), "у расчёта на допущениях нет слоя близости")
        res = checks.LayerResult(5)
        lines = ["Основной вариант даёт 7 000 000 рублей.", "По оценке основной вариант даёт 7 000 000 рублей.",
                 "Допущение: за год будет 14 000 дополнительных оплаченных месяцев.", "За год будет 14 000 дополнительных оплаченных месяцев."]
        checks.number_issues(res, proj, lambda n: "строка %d" % (n + 1), lines, list(enumerate(lines)))
        got = [(i["where"], i["what"]) for i in res.issues]
        self.assertEqual(got, [("строка 4", "число из допущения (14 000) без слова «допущение»"),
                               ("строка 1", "число из расчёта на допущениях (7 000 000) без слова «допущение» или «оценка»")])

    def test_calc_through_another_calc_still_inherits(self):
        p = self.brief()
        self.assume()
        self.breakeven(p)
        self.ok("claim", "add", "-p", "b", "--type", "calc", "--source", "S002", "--quote", "Вклад после прямых расходов: 7 000 000",
                "--number", "7 000 000", "--text", "Основной вариант даёт 7 000 000 рублей")
        self.write(p / "analysis" / "ok.json", json.dumps({"доп_прибыль_по_кварталам": [0, 0, 0, 7000000]}))
        self.ok("calc", "ready", "-p", "b", "окупаемость", "--params", "analysis/ok.json", "--rests-on", "C004")
        out = self.ok("claim", "add", "-p", "b", "--type", "calc", "--source", "S003", "--quote", "(кварталов: 4): 7 000 000",
                      "--number", "7 000 000", "--text", "Предельная сумма вложений 7 000 000 рублей")
        self.assertIn("стоит на допущениях (C003)", out)

    def test_finding_cannot_stand_on_assumptions_alone(self):
        p = self.brief()
        self.assume()
        self.breakeven(p)
        self.ok("claim", "add", "-p", "b", "--type", "calc", "--source", "S002", "--quote", "Вклад после прямых расходов: 7 000 000",
                "--number", "7 000 000", "--text", "Основной вариант даёт 7 000 000 рублей")
        self.ok("conclusion", "add", "-p", "b", "--kind", "finding", "--text", "Цель по прибыли достижима", "--rests-on", "C003,C004")
        self.ok("conclusion", "add", "-p", "b", "--kind", "finding", "--text", "До цели не хватает шести миллионов", "--rests-on", "C001,C002,C004")
        code, data = self.verify_json("-p", "b", "--layer", "3")
        text = self.issues_text(data, 3)
        self.assertIn("вывод K001 (finding) держится только на допущениях и расчётах на них", text)
        self.assertNotIn("K002", text)
        self.assertNotIn("не использовано", text, "факты, вошедшие параметрами в расчёт, считаются использованными")

    def test_impact_reaches_calcs_and_rejected_assumption_breaks_them(self):
        p = self.brief()
        self.assume()
        self.breakeven(p)
        self.ok("claim", "add", "-p", "b", "--type", "calc", "--source", "S002", "--quote", "Вклад после прямых расходов: 7 000 000",
                "--number", "7 000 000", "--text", "Основной вариант даёт 7 000 000 рублей")
        self.ok("conclusion", "add", "-p", "b", "--kind", "recommendation", "--text", "Идём в пилот", "--rests-on", "C001,C004")
        out = self.ok("impact", "-p", "b", "C003")
        self.assertIn("утверждение допущение", out)
        self.assertIn("C004", out)
        self.assertIn("K001", out)
        self.ok("claim", "reject", "-p", "b", "C003", "--reason", "проверили: значение другое")
        code, data = self.verify_json("-p", "b", "--layer", "2")
        self.assertIn("расчёт S002 опирается на запись C003, которая не действует", self.issues_text(data, 2))


class DocumentTests(BriefEnv):
    def example_doc(self, text=DOC_OK, page=True):
        # Наши обязательные элементы документа проверяет отдельный тест (DocOwnElementsTest); здесь они выключены.
        style_path = self.root / "config" / "style.json"
        style = json.loads(style_path.read_text(encoding="utf-8"))
        style.pop("document_elements", None)
        style.pop("max_paragraph_chars", None)
        style.pop("max_opening_sentence_chars", None)
        style_path.write_text(json.dumps(style, ensure_ascii=False), encoding="utf-8")
        self.ok(*INIT, *EX)
        self.write(self.root / "projects" / "_example" / "document.md", text)
        if page:
            self.ok("doc", "page", *EX)
        return self.root / "projects" / "_example"

    def doc_issues(self, *args):
        code, data = self.verify_json(*(args or EX), "--layer", "5")
        return " | ".join(i["what"] for i in data["layers"]["6"]["issues"]), data

    def test_without_document_json_nothing_changes(self):
        code, data = self.verify_json(*EX)
        self.assertEqual(code, 0)
        self.assertEqual(sorted(data["layers"]), ["1", "2", "3", "4", "5"])
        out = self.ok("doc", "check", *EX)
        self.assertIn("Структура документа не задана", out)
        self.assertIn("заполнено 5 из 5", self.ok("strategy", "check", *EX))

    def test_init_takes_structure_from_request_and_is_repeatable(self):
        p = self.brief()
        code, out = self.run_cmd("doc", "init", "-p", "b", "--title", "Стратегия", "--part", "А", "--quote", "один документ из пяти частей")
        self.assertEqual(code, 1)
        self.assertIn("Цитата о структуре документа не найдена", out)
        out = self.ok("doc", "init", "-p", "b", "--title", "Стратегия", "--opening", "первые клиенты", "--opening", "ожидаемый результат",
                      "--part", "1. Клиент", "--part", "Услуга", "--part", "План", "--quote", "один документ из трёх частей")
        self.assertIn("частей 3, обязательных элементов начала 2", out)
        doc = json.loads((p / "document.json").read_text(encoding="utf-8"))
        self.assertEqual((doc["title"], doc["opening"], doc["parts"]), ("Стратегия", ["первые клиенты", "ожидаемый результат"], ["Клиент", "Услуга", "План"]))
        self.assertEqual(doc["quote"], "один документ из трёх частей")
        text = (p / "document.md").read_text(encoding="utf-8")
        self.assertIn("**первые клиенты:** <<заполнить>>", text)
        self.assertLess(text.index("## 1. Клиент"), text.index("## 2. Услуга"))
        self.assertLess(text.index("## 2. Услуга"), text.index("## 3. План"))
        self.write(p / "document.md", text + "\nмой текст\n")
        again = self.ok("doc", "init", "-p", "b", "--title", "Стратегия", "--opening", "первые клиенты", "--opening", "ожидаемый результат",
                        "--part", "Клиент", "--part", "Услуга", "--part", "План")
        self.assertIn("уже был", again)
        self.assertIn("мой текст", (p / "document.md").read_text(encoding="utf-8"))
        code, out = self.run_cmd("doc", "init", "-p", "b", "--title", "Стратегия", "--part", "Клиент", "--part", "План")
        self.assertEqual(code, 1)
        self.assertIn("--replace", out)
        self.ok("doc", "init", "-p", "b", "--title", "Стратегия", "--part", "Клиент", "--part", "План", "--replace")
        self.assertEqual(json.loads((p / "document.json").read_text(encoding="utf-8"))["parts"], ["Клиент", "План"])
        self.assertIn("мой текст", (p / "document.md").read_text(encoding="utf-8"))
        code, out = self.run_cmd("doc", "init", "-p", "b", "--title", "Стратегия", "--part", "Клиент", "--part", "клиент", "--replace")
        self.assertEqual(code, 1)

    def test_skeleton_fails_and_filled_document_passes(self):
        self.ok(*INIT, *EX)
        code, out = self.run_cmd("doc", "check", *EX)
        self.assertEqual(code, 2)
        self.assertIn("часть 1 «Клиент и его проблема» пуста", out)
        self.assertIn("элемент начала «Первые клиенты» не заполнен", out)
        self.assertIn("остался шаблонный текст", out)
        self.assertIn("не совпадает с началом документа", out)
        self.example_doc()
        out = self.ok("doc", "check", *EX)
        self.assertIn("Документ по частям заказчика: OK", out)
        self.assertIn("частей: 3, заполнено 3", out)
        code, data = self.verify_json(*EX)
        self.assertEqual(code, 0, data)
        self.assertTrue(data["layers"]["6"]["ok"])

    def test_missing_part_wrong_order_and_empty_part(self):
        self.example_doc(DOC_OK.replace("## 2. Предложение и путь к клиенту", "## 2. Что-то другое"))
        text, _ = self.doc_issues()
        self.assertIn("нет части 2 «Предложение и путь к клиенту»", text)
        a = DOC_OK.index("## 1. Клиент")
        b = DOC_OK.index("## 2. Предложение")
        c = DOC_OK.index("## 3. Проверка")
        self.example_doc(DOC_OK[:a] + DOC_OK[b:c] + DOC_OK[a:b] + DOC_OK[c:])
        text, _ = self.doc_issues()
        self.assertIn("часть 2 «Предложение и путь к клиенту» стоит раньше предыдущей", text)
        self.example_doc(DOC_OK.replace("Возвращаем пробный период новым. Цена остаётся 490 рублей.", "> Подсказка: что пишем здесь"))
        text, _ = self.doc_issues()
        self.assertIn("часть 2 «Предложение и путь к клиенту» пуста", text)
        self.assertIn("строка-подсказка", text)

    def test_opening_must_name_every_element_and_fit_the_page(self):
        self.example_doc(DOC_OK.replace("**Предложение:** вернуть новым пробный период в 14 дней.", "Мы предлагаем вернуть пробный период."))
        text, _ = self.doc_issues()
        self.assertIn("в начале документа нет обязательного элемента «Предложение»", text)
        self.example_doc(DOC_OK.replace("**Ожидаемый результат:** оценка эффекта на общее продление от 1 до 4 процентных пунктов, вероятно около 2.",
                                        "**Ожидаемый результат:**"))
        text, _ = self.doc_issues()
        self.assertIn("элемент начала «Ожидаемый результат» не заполнен", text)
        long_open = DOC_OK.replace("## 1. Клиент", "\n".join("Строка начала про клиентов и результат." for _ in range(30)) + "\n\n## 1. Клиент")
        self.example_doc(long_open)
        text, _ = self.doc_issues()
        self.assertIn("начало документа (до первой части) длиннее страницы: 35 непустых строк, можно 32", text)
        # сам документ лимита длины не имеет
        self.example_doc(DOC_OK + "\n" + "\n".join("Длинная часть без чисел, строка за строкой." for _ in range(200)) + "\n")
        text, data = self.doc_issues()
        self.assertEqual(text, "", data["layers"]["6"]["issues"])

    def test_numbers_codes_dashes_and_filler_in_document(self):
        bad = DOC_OK.replace("Тест идёт 4 недели", "Тест идёт 4 недели на 9999 подписчиках (K002), это " + chr(0x2014) + " комплексный подход, т.е. всё сразу")
        self.example_doc(bad)
        text, data = self.doc_issues()
        self.assertIn("числа «9999» нет в реестре", text)
        self.assertIn("внутренний номер записи «K002» в тексте документа", text)
        self.assertIn("длинное тире в тексте документа", text)
        self.assertIn("пустой оборот «комплексный подход»", text)
        self.assertIn("сокращение «т.е.»", text)
        where = [i["where"] for i in data["layers"]["6"]["issues"] if "9999" in i["what"]][0]
        self.assertIn("document.md, строка 21 (часть 3)", where)
        # эффект рычага без слова «оценка» ловится той же проверкой, что и на странице
        self.example_doc(DOC_OK.replace("оценка эффекта на общее продление", "эффект на общее продление"))
        text, _ = self.doc_issues()
        self.assertIn("число эффекта рычага", text)
        self.assertNotIn("числа «1»", text, "номер в заголовке части числом текста не считается")

    def test_page_is_built_from_opening_and_must_stay_in_sync(self):
        p = self.example_doc(page=False)
        text, _ = self.doc_issues()
        self.assertIn("страница для руководителя не совпадает с началом документа", text)
        out = self.ok("doc", "page", *EX)
        self.assertIn("собрана из начала документа", out)
        page = (p / "page.md").read_text(encoding="utf-8")
        self.assertTrue(page.startswith("# Продление подписки: что менять"))
        self.assertIn("**Ожидаемый результат:**", page)
        self.assertNotIn("## 1.", page)
        self.assertIn("- document.md", page)
        self.assertIn("уже совпадает", self.ok("doc", "page", *EX))
        self.assertEqual(self.doc_issues()[0], "")
        self.write(p / "document.md", DOC_OK.replace("новые подписчики, пришедшие", "новые клиенты, пришедшие"))
        self.assertIn("не совпадает с началом документа", self.doc_issues()[0])

    def test_requirement_place_is_checked_and_missing_place_warns(self):
        self.example_doc()
        code, data = self.verify_json(*EX, "--layer", "5")
        warn = " ".join(w["what"] for w in data["layers"]["6"]["warnings"])
        self.assertIn("у закрытых требований не указано место в результате (3): R01, R02, R03", warn)
        code, out = self.run_cmd("req", "close", *EX, "R01", "--by", "document.md", "--where", "часть 9")
        self.assertEqual(code, 1)
        self.assertIn("частей 3, а указана часть 9", out)
        code, out = self.run_cmd("req", "close", *EX, "R01", "--by", "document.md", "--where", "где-то там")
        self.assertEqual(code, 1)
        self.assertIn("«начало», «часть N»", out)
        out = self.ok("req", "close", *EX, "R01,R02", "--by", "document.md", "--where", "часть 1, второй абзац")
        self.assertIn("Требование R01 закрыто (document.md, место: часть 1, второй абзац)", out)
        self.assertIn("Требование R02 закрыто", out)
        self.ok("req", "close", *EX, "R03", "--by", "strategy/test-plan.md", "--where", "Проверка и прибыль")
        self.assertIn("место: часть 1, второй абзац", self.ok("req", "list", *EX))
        code, data = self.verify_json(*EX, "--layer", "5")
        self.assertEqual([w for w in data["layers"]["6"]["warnings"] if "нет фразы" not in w["what"]], [])
        self.assertIn("требований по местам: часть 1: 2, часть 3: 1", " ".join(data["layers"]["6"]["info"]))
        self.ok("req", "close", *EX, "R03", "--by", "document.md", "--where", "начало")
        self.ok("req", "close", *EX, "R02", "--by", "document.md", "--where", "options.md")
        # часть, на которую ссылается требование, потом опустела: это уже замечание
        p = self.root / "projects" / "_example"
        self.write(p / "document.md", DOC_OK.replace("Уровень продления упал с 71% до 65%. Новый подписчик не успевает привыкнуть к сервису.", ""))
        self.assertIn("требование закрыто частью 1, а она пуста", self.doc_issues()[0])

    def test_place_without_document_is_a_file(self):
        code, out = self.run_cmd("req", "close", *EX, "R01", "--by", "K002", "--where", "часть 1")
        self.assertEqual(code, 1)
        self.ok("req", "close", *EX, "R01", "--by", "K002", "--where", "page.md")

    def test_gate_and_stage_eight_wait_for_the_document(self):
        p = self.root / "projects" / "_example"
        st = json.loads((p / "state.json").read_text(encoding="utf-8"))
        st["stage"] = 7
        self.write(p / "state.json", json.dumps(st, ensure_ascii=False))
        self.ok(*INIT, *EX)
        code, out = self.run_cmd("stage", "next", *EX)
        self.assertEqual(code, 2)
        self.assertIn("document.md", out)
        code, out = self.run_cmd("gate", *EX)
        self.assertEqual(code, 2)
        self.assertIn("часть 1 «Клиент и его проблема» пуста", out)
        self.example_doc()
        self.assertIn("проверки пройдены", self.ok("gate", *EX))
        self.assertIn("Теперь этап 8", self.ok("stage", "next", *EX))
        self.assertIn("Документ по частям заказчика (document.md): заполнено частей 3 из 3", self.ok("status", *EX))

    def test_document_replaces_three_strategy_files_at_stage_six(self):
        proj = Project(self.root, "_example")
        for name in ("product.md", "communication.md"):
            (proj.path("strategy", name)).unlink()
        cfg = common.load_config(self.root)
        self.assertIn("стратегия не написана", " ".join(i["what"] for i in checks.stage_artifact_issues(proj, 6)))
        self.assertFalse(checks.layer4(proj, cfg).ok)
        self.ok(*INIT, *EX)
        self.assertIn("пуста", " ".join(i["what"] for i in checks.stage_artifact_issues(proj, 6)))
        self.assertTrue(checks.layer4(proj, cfg).ok, [i["what"] for i in checks.layer4(proj, cfg).issues])
        self.write(proj.path("document.md"), DOC_OK)
        self.assertEqual(checks.stage_artifact_issues(proj, 6), [])
        self.assertIn("не обязательны", self.ok("strategy", "check", *EX))

    def test_premortem_may_live_in_the_document(self):
        proj = Project(self.root, "_example")
        for path in (proj.path("strategy", "test-plan.md"), proj.path("options.md")):
            self.write(path, path.read_text(encoding="utf-8").replace("очему провалится", "очему может не выйти"))
        self.assertFalse(checks._premortem_ok(proj))
        self.write(proj.path("document.md"), DOC_OK)
        self.assertTrue(checks._premortem_ok(proj))


class InstructionFilesTests(unittest.TestCase):
    def test_agents_file_is_short_and_names_the_new_commands(self):
        text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertLessEqual(len(text.splitlines()), 100, "AGENTS.md не длиннее 100 строк")
        for word in ("doc init", "doc check", "doc page", "--type assumption", "calc ready", "--where", "claim assumptions"):
            self.assertIn(word, text, word)

    def test_index_lists_every_method_and_the_brief_route(self):
        index = (ROOT / "methods" / "INDEX.md").read_text(encoding="utf-8")
        methods = sorted((ROOT / "methods").glob("[0-9][0-9]-*.md"))
        for m in methods:
            self.assertIn(m.name, index, "методики нет в указателе: " + m.name)
        self.assertIn("Стратегия направления по брифу заказчика", index)

    def test_every_method_has_the_same_sections(self):
        for m in sorted((ROOT / "methods").glob("[0-9][0-9]-*.md")):
            text = m.read_text(encoding="utf-8")
            for head in ("## Когда применять", "## Шаги", "## Шаблон результата", "## Чем проверяется", "## Частые ошибки"):
                self.assertIn(head, text, "%s: нет раздела %s" % (m.name, head))

    def test_other_instruction_files_know_the_document(self):
        for rel in (".cursor/rules/rychag.mdc", "README.md", "docs/MCP.md", "docs/OTHER-TOOLS.md", "docs/KEY-DECISIONS.md"):
            self.assertIn("doc check", (ROOT / rel).read_text(encoding="utf-8"), rel)


if __name__ == "__main__":
    unittest.main()


class ReqImportTest(Env):
    """Требования пачкой из файла: цитаты проверяются, повторы не добавляются."""

    def test_import_checks_quotes_and_skips_repeats(self):
        self.new_project("t1", question="Сдайте один документ из пяти частей и план на год")
        path = self.root / "projects" / "t1" / "reqs.txt"
        path.write_text("# требования\n"
                        "Один документ из пяти частей || один документ из пяти частей\n"
                        "План на год || план на год\n"
                        "Строка без разделителя\n"
                        "Выдуманное требование || этой цитаты в запросе нет\n", encoding="utf-8")
        code, out = self.run_cmd("req", "import", "-p", "t1", "--file", str(path))
        self.assertEqual(code, 1, out)
        self.assertIn("Записано требований: 2", out)
        self.assertIn("Не записано строк: 2", out)
        code, out = self.run_cmd("req", "import", "-p", "t1", "--file", str(path))
        self.assertIn("Записано требований: 0", out)


class DocEndingTest(Env):
    """Заказчик велел закончить документ просьбой: после неё не должно быть других разделов."""

    def test_ending_must_be_last(self):
        from lib import document
        self.new_project("t2", question="Сдайте один документ из двух частей. Закончите стратегию конкретной просьбой.")
        self.ok("doc", "init", "-p", "t2", "--title", "Стратегия", "--part", "Клиент", "--part", "Решение",
                "--ending", "Просьба руководителю")
        proj = Project(self.root, "t2")
        path = self.root / "projects" / "t2" / "document.md"
        base = "# Стратегия\n\n## 1. Клиент\n\nТекст первой части про клиента и его задачу.\n\n## 2. Решение\n\nТекст второй части про решение.\n\n"
        path.write_text(base + "**Просьба руководителю:** одобрить пробный запуск.\n\n### Почему провалится\n\nРазбор.\n", encoding="utf-8")
        doc = document.load(proj)
        self.assertTrue(document.ending_issues(proj, doc, document.Parsed(proj, doc)))
        path.write_text(base + "### Почему провалится\n\nРазбор.\n\n**Просьба руководителю:** одобрить пробный запуск.\n", encoding="utf-8")
        self.assertEqual(document.ending_issues(proj, doc, document.Parsed(proj, doc)), [])
        path.write_text(base, encoding="utf-8")
        self.assertTrue(document.ending_issues(proj, doc, document.Parsed(proj, doc)))


class DocRetoldTest(unittest.TestCase):
    """Предложение, почти дословно взятое у заказчика, находится; свой ответ не находится."""

    def test_four_gram_overlap(self):
        from lib import document
        brief = "Число подключённых на конец года само по себе не показывает, сколько из них столкнутся с нужной ситуацией."
        pool = document._four_grams(document._plain_words(brief))
        copied = document._plain_words("Число подключённых на конец года само по себе не показывает, сколько столкнутся с ситуацией.")
        own = document._plain_words("Поток первых случаев считаем отдельно: 146 групп в неделю, это допущение с диапазоном.")
        share = lambda w: len(document._four_grams(w) & pool) / float(len(document._four_grams(w)))
        self.assertGreaterEqual(share(copied), document.RETOLD_SHARE)
        self.assertLess(share(own), document.RETOLD_SHARE)


class DocOwnElementsTest(Env):
    """Наши обязательные элементы документа: вклад в цели и коммуникационная часть."""

    def test_missing_and_present(self):
        from lib import document
        self.new_project("t3", question="Сдайте один документ из двух частей.")
        self.ok("doc", "init", "-p", "t3", "--title", "Стратегия", "--part", "Клиент", "--part", "Решение")
        proj = Project(self.root, "t3")
        path = self.root / "projects" / "t3" / "document.md"
        els = [{"name": "Вклад в цели", "hint": ""}, {"name": "Ключевое сообщение", "hint": ""}]
        base = "# Стратегия\n\n## 1. Клиент\n\nТекст первой части про клиента.\n\n## 2. Решение\n\nТекст второй части.\n\n"
        path.write_text(base, encoding="utf-8")
        doc = document.load(proj)
        self.assertEqual(len(document.own_elements_issues(proj, doc, document.Parsed(proj, doc), els)), 2)
        path.write_text(base + "**Вклад в цели.** Таблица ниже.\n\n**Ключевое сообщение:** предупредим заранее.\n", encoding="utf-8")
        self.assertEqual(document.own_elements_issues(proj, doc, document.Parsed(proj, doc), els), [])


class ReqPhraseTest(Env):
    """Требование закрывается дословной фразой из документа; если в новой версии фразы нет, проверка это видит."""

    BASE = ("# Стратегия\n\n## 1. Клиент\n\nПервые клиенты это семьи с двумя номерами и общим пакетом.\n\n"
            "## 2. Решение\n\nПроверка стоит **120 тысяч** рублей за шесть недель.\n")

    def prepare(self):
        self.new_project("t4", question="Сдайте один документ из двух частей. Назовите первых клиентов. Покажите цену проверки.")
        self.ok("doc", "init", "-p", "t4", "--title", "Стратегия", "--part", "Клиент", "--part", "Решение")
        self.ok("req", "add", "-p", "t4", "--text", "Назвать первых клиентов", "--quote", "Назовите первых клиентов")
        self.ok("req", "add", "-p", "t4", "--text", "Цена проверки", "--quote", "Покажите цену проверки")
        path = self.root / "projects" / "t4" / "document.md"
        path.write_text(self.BASE, encoding="utf-8")
        return path

    def report(self):
        from lib import document, checks
        proj = Project(self.root, "t4")
        doc = document.load(proj)
        return checks.req_place_report(proj, doc, document.Parsed(proj, doc))

    def test_phrase_must_be_in_place(self):
        self.prepare()
        code, out = self.run_cmd("req", "close", "-p", "t4", "R01", "--by", "document.md", "--where", "часть 1",
                                 "--phrase", "Первые клиенты это пенсионеры с одним номером")
        self.assertNotEqual(code, 0)
        code, out = self.run_cmd("req", "close", "-p", "t4", "R01", "--by", "document.md", "--where", "часть 2",
                                 "--phrase", "Первые клиенты это семьи с двумя номерами")
        self.assertNotEqual(code, 0, "фраза стоит в другой части")
        code, out = self.run_cmd("req", "close", "-p", "t4", "R01", "--by", "document.md", "--where", "часть 1", "--phrase", "семьи с двумя")
        self.assertNotEqual(code, 0, "короткая фраза")
        self.ok("req", "close", "-p", "t4", "R01", "--by", "document.md", "--where", "часть 1",
                "--phrase", "первые клиенты это семьи с двумя номерами")

    def test_lost_phrase_is_found(self):
        path = self.prepare()
        lst = self.write(self.tmp / "close.txt", "# список\nR01 || часть 1 || Первые клиенты это семьи с двумя номерами\n"
                                                 "R02 || часть 2 || Проверка стоит 120 тысяч рублей\nR02 || часть 2\n")
        code, out = self.run_cmd("req", "close", "-p", "t4", "--by", "document.md", "--file", str(lst))
        self.assertEqual(code, 1, out)
        self.assertIn("Закрыто требований: 2", out)
        fails, warns, _ = self.report()
        self.assertEqual(fails, [])
        self.assertEqual(warns, [])
        path.write_text(self.BASE.replace("семьи с двумя номерами", "владельцы роутеров"), encoding="utf-8")
        fails, warns, _ = self.report()
        self.assertEqual(len(fails), 1)
        self.assertIn("R01", fails[0][0])

    def test_no_phrase_is_warning(self):
        self.prepare()
        self.ok("req", "close", "-p", "t4", "R01", "--by", "document.md", "--where", "часть 1")
        fails, warns, _ = self.report()
        self.assertEqual(fails, [])
        self.assertEqual(len(warns), 1)
        self.assertIn("R01", warns[0][1])


class DocReadabilityTest(Env):
    """Абзац длиннее допустимого и служебная пометка в названии столбца таблицы не проходят проверку документа."""

    def test_long_paragraph_and_head_mark(self):
        self.new_project("t5", question="Сдайте один документ из двух частей.")
        self.ok("doc", "init", "-p", "t5", "--title", "Стратегия", "--part", "Клиент", "--part", "Решение")
        path = self.root / "projects" / "t5" / "document.md"
        long_par = " ".join(["Семья подключает общий пакет и делит его между близкими."] * 20)
        path.write_text("# Стратегия\n\n## 1. Клиент\n\n" + long_par + "\n\n## 2. Решение\n\n"
                        "| Канал (оценка, допущения) | Задача |\n|---|---|\n| Приложение | показать предложение |\n", encoding="utf-8")
        code, out = self.run_cmd("doc", "check", "-p", "t5")
        self.assertNotEqual(code, 0)
        self.assertIn("абзац на", out)
        self.assertIn("служебная пометка в названии столбца", out)
        path.write_text("# Стратегия\n\n## 1. Клиент\n\nСемья подключает общий пакет и делит его между близкими.\n\n## 2. Решение\n\n"
                        "Числа таблицы: оценка на допущениях.\n\n| Канал | Задача |\n|---|---|\n| Приложение | показать предложение |\n", encoding="utf-8")
        code, out = self.run_cmd("doc", "check", "-p", "t5")
        self.assertNotIn("абзац на", out)
        self.assertNotIn("служебная пометка", out)


class DocOpeningSentenceTest(Env):
    """В начале документа слишком длинное предложение не проходит проверку."""

    def test_long_sentence_in_opening(self):
        self.new_project("t6", question="Сдайте один документ из двух частей.")
        self.ok("doc", "init", "-p", "t6", "--title", "Стратегия", "--part", "Клиент", "--part", "Решение")
        path = self.root / "projects" / "t6" / "document.md"
        long_sent = "Основной сценарий двигает цели слабо, " + ", ".join(["а при другом значении допущения итог другой"] * 7) + "."
        tail = "\n\n## 1. Клиент\n\nТекст первой части про клиента и его задачу.\n\n## 2. Решение\n\nТекст второй части про решение.\n"
        path.write_text("# Стратегия\n\n**Итог:** " + long_sent + tail, encoding="utf-8")
        code, out = self.run_cmd("doc", "check", "-p", "t6")
        self.assertIn("в начале документа предложение на", out)
        path.write_text("# Стратегия\n\n**Итог:** Основной сценарий двигает цели слабо. При другом значении допущения итог другой." + tail, encoding="utf-8")
        code, out = self.run_cmd("doc", "check", "-p", "t6")
        self.assertNotIn("в начале документа предложение на", out)
