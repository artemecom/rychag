# -*- coding: utf-8 -*-
"""Проверки новых правил: части стратегий, требования человека, защита от повтора, смена подхода, замеры расхода, страница без кодов."""
import json
import unittest
from pathlib import Path

from helpers import Env

EX = ("-p", "_example")


def set_stage(proj_dir, n):
    p = Path(proj_dir) / "state.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    d["stage"] = n
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")


class StrategyPartsTests(Env):
    def test_new_creates_headings_with_hints(self):
        p = self.new_project("s")
        for fn, heads in (("product.md", ["Аудитория и её задача", "Альтернативы", "Выбранное направление", "От чего отказываемся",
                                          "Связь пользы с затратами и доходами"]),
                          ("communication.md", ["Аудитория и ситуация", "Что мешает понять или выбрать", "Ключевое сообщение",
                                                "Чем подтверждаем", "Роль каналов"]),
                          ("test-plan.md", ["Ожидаемое изменение", "С чем сравниваем", "Срок наблюдения", "Нежелательные последствия"])):
            text = (p / "strategy" / fn).read_text(encoding="utf-8")
            for h in heads:
                self.assertIn("## " + h, text)
            self.assertEqual(text.count("> Подсказка:"), len(heads))

    def test_layer4_names_missing_part(self):
        self.new_project("s")
        code, data = self.verify_json("-p", "s", "--layer", "4")
        self.assertEqual(code, 2)
        txt = self.issues_text(data, 4)
        self.assertIn("Нежелательные последствия", txt)
        self.assertIn("Роль каналов", txt)
        fixes = " ".join(i["fix"] for i in data["layers"]["4"]["issues"])
        self.assertIn("добавьте заголовок", fixes)

    def test_hint_does_not_count_and_case_insensitive(self):
        p = self.new_project("s")
        self.write(p / "strategy" / "test-plan.md",
                   "# План\n\n## ожидаемое изменение: рост\n\nПродление вырастет на два процентных пункта.\n\n"
                   "## С ЧЕМ СРАВНИВАЕМ\n\nКонтрольная группа получает прежние условия.\n\n## Срок наблюдения\n\n> Подсказка: напишите срок\n\n"
                   "## Нежелательные последствия\n\nМожет упасть выручка на подписчика.\n")
        code, out = self.run_cmd("strategy", "check", "-p", "s")
        self.assertEqual(code, 2)
        self.assertIn("Срок наблюдения: заголовок есть, текста нет", out)
        self.assertIn("Ожидаемое изменение: заполнено", out)
        self.assertIn("С чем сравниваем: заполнено", out)

    def test_example_strategy_check_ok(self):
        out = self.ok("strategy", "check", *EX)
        self.assertIn("Все обязательные части на месте", out)


class RequirementTests(Env):
    def setUp(self):
        Env.setUp(self)
        self.p = self.new_project("r", "Нужно снизить отток и объяснить, почему он вырос. Ещё покажите план проверки.")

    def test_verbatim_request_stored(self):
        text = (self.p / "brief.md").read_text(encoding="utf-8")
        self.assertIn("## Запрос дословно", text)
        self.assertIn("Нужно снизить отток и объяснить, почему он вырос. Ещё покажите план проверки.", text)

    def test_add_requires_quote_from_request(self):
        code, out = self.run_cmd("req", "add", "-p", "r", "--text", "Снизить отток", "--quote", "снизить отток и")
        self.assertEqual(code, 0, out)
        self.assertIn("R01", out)
        code, out = self.run_cmd("req", "add", "-p", "r", "--text", "Что-то", "--quote", "этого нет в запросе")
        self.assertEqual(code, 1)
        self.assertIn("не найдена", out)
        code, out = self.run_cmd("req", "add", "-p", "r", "--text", "Снизить отток", "--quote", "снизить отток")
        self.assertEqual(code, 1)
        self.assertIn("уже записано", out)

    def test_stage_one_needs_requirement(self):
        self.write(self.p / "brief.md", "# Постановка\n\nВсё заполнено.\n")
        code, out = self.run_cmd("stage", "next", "-p", "r")
        self.assertEqual(code, 2)
        self.assertIn("ни одного требования", out)

    def test_later_message_via_note(self):
        code, out = self.run_cmd("req", "add", "-p", "r", "--text", "Срок", "--quote", "до пятницы")
        self.assertEqual(code, 1)
        self.ok("req", "note", "-p", "r", "Нужен результат до пятницы")
        self.assertTrue((self.p / "requests.md").exists())
        self.ok("req", "add", "-p", "r", "--text", "Срок до пятницы", "--quote", "до пятницы")
        self.assertIn("уже сохранено", self.ok("req", "note", "-p", "r", "Нужен результат до пятницы"))

    def test_quote_from_source(self):
        self.write(self.p / "materials" / "m.txt", "Заказчик требует отчёт на одну страницу.")
        self.ok("source", "add", "-p", "r", "--file", "materials/m.txt", "--published", "2026-10-01")
        self.ok("req", "add", "-p", "r", "--text", "Одна страница", "--quote", "на одну страницу", "--source", "S001")
        code, out = self.run_cmd("req", "add", "-p", "r", "--text", "Т", "--quote", "нет такого", "--source", "S001")
        self.assertEqual(code, 1)

    def test_close_drop_and_counts(self):
        self.ok("req", "add", "-p", "r", "--text", "Снизить отток", "--quote", "снизить отток")
        self.ok("req", "add", "-p", "r", "--text", "План проверки", "--quote", "покажите план проверки")
        self.ok("req", "add", "-p", "r", "--text", "Объяснить рост", "--quote", "объяснить, почему он вырос")
        code, out = self.run_cmd("req", "close", "-p", "r", "R01", "--by", "D1")
        self.assertEqual(code, 1)
        self.ok("done", "add", "-p", "r", "--text", "Готово")
        code, out = self.run_cmd("req", "close", "-p", "r", "R01", "--by", "D1")
        self.assertEqual(code, 1, out)
        self.assertIn("не выполнен", out)
        self.ok("done", "mark", "-p", "r", "D1")
        self.ok("req", "close", "-p", "r", "R01", "--by", "D1")
        self.ok("req", "close", "-p", "r", "R02", "--by", "strategy/test-plan.md")
        code, out = self.run_cmd("req", "close", "-p", "r", "R03", "--by", "нет/такого.md")
        self.assertEqual(code, 1)
        code, out = self.run_cmd("req", "drop", "-p", "r", "R03")
        self.assertEqual(code, 1)
        self.ok("req", "drop", "-p", "r", "R03", "--reason", "человек отказался")
        self.assertIn("Требований из запроса: выполнено 2 из 2, снято 1", self.ok("status", "-p", "r"))
        self.assertIn("Требований из запроса: выполнено 2 из 2, снято 1", self.ok("req", "list", "-p", "r"))
        code, out = self.run_cmd("verify", "-p", "r")
        self.assertIn("Требований из запроса: выполнено 2 из 2, снято 1", out)
        code, out = self.run_cmd("gate", "-p", "r")
        self.assertIn("Требований из запроса: выполнено 2 из 2, снято 1", out)

    def test_stage_seven_blocked_by_open_requirement(self):
        self.ok("req", "add", *EX, "--text", "Ещё одно", "--quote", "что с этим делать")
        set_stage(self.root / "projects" / "_example", 7)
        code, out = self.run_cmd("gate", *EX)
        self.assertEqual(code, 2)
        self.assertIn("требование не закрыто", out)
        self.ok("req", "drop", *EX, "R04", "--reason", "лишнее")
        self.assertEqual(self.run_cmd("gate", *EX)[0], 0)


class NoRepeatTests(Env):
    def setUp(self):
        Env.setUp(self)
        self.p = self.new_project("n")
        self.write(self.p / "page.txt", "Версия один. Выручка 10 рублей.")

    def add_url(self, fname, text, **kw):
        self.write(self.p / fname, text)
        return self.run_cmd("source", "add", "-p", "n", "--url", "https://example.org/a", "--text-file", fname,
                            "--layer", "3", "--published", "2026-10-01")

    def test_source_same_hash_refused_with_id(self):
        self.write(self.p / "materials" / "p.txt", "Один и тот же текст.")
        self.ok("source", "add", "-p", "n", "--file", "materials/p.txt", "--published", "2026-10-01")
        self.write(self.p / "materials" / "q.txt", "Один и тот же текст.")
        code, out = self.run_cmd("source", "add", "-p", "n", "--file", "materials/q.txt", "--published", "2026-10-01")
        self.assertEqual(code, 1)
        self.assertIn("S001", out)

    def test_changed_page_is_new_version(self):
        self.ok("source", "add", "-p", "n", "--url", "https://example.org/a", "--text-file", "page.txt", "--layer", "3", "--published", "2026-10-01")
        self.write(self.p / "page2.txt", "Версия два. Выручка 20 рублей.")
        code, out = self.run_cmd("source", "add", "-p", "n", "--url", "https://example.org/a", "--text-file", "page2.txt",
                                 "--layer", "3", "--published", "2026-10-01")
        self.assertEqual(code, 0, out)
        self.assertIn("заменяет S001", out)
        metas = {m: json.loads((self.p / "sources" / (m + ".meta.json")).read_text(encoding="utf-8")) for m in ("S001", "S002")}
        self.assertEqual(metas["S002"]["replaces"], "S001")
        self.assertEqual(metas["S001"]["replaced_by"], "S002")
        self.ok("claim", "add", "-p", "n", "--type", "fact", "--text", "Выручка 10", "--source", "S001", "--quote", "Выручка 10 рублей")
        out = self.ok("impact", "--stale", "-p", "n")
        self.assertIn("S001", out)
        self.assertIn("C001", out)
        self.assertIn("C001", self.ok("impact", "S001", "-p", "n"))
        self.assertIn("замещён", self.ok("sweep", "-p", "n"))

    def test_same_page_same_text_refused(self):
        self.ok("source", "add", "-p", "n", "--url", "https://example.org/a", "--text-file", "page.txt", "--layer", "3", "--published", "2026-10-01")
        self.write(self.p / "copy.txt", "Версия один. Выручка 10 рублей.")
        code, out = self.run_cmd("source", "add", "-p", "n", "--url", "https://example.org/a", "--text-file", "copy.txt",
                                 "--layer", "3", "--published", "2026-10-01")
        self.assertEqual(code, 1)
        self.assertIn("S001", out)

    def test_claim_conclusion_lever_decision_duplicates(self):
        self.write(self.p / "materials" / "p.txt", "Продление упало на 6 пунктов.")
        self.ok("source", "add", "-p", "n", "--file", "materials/p.txt", "--published", "2026-10-01")
        a = ["claim", "add", "-p", "n", "--type", "fact", "--text", "Продление упало", "--source", "S001", "--quote", "упало на 6"]
        self.ok(*a)
        code, out = self.run_cmd(*a[:7], "ПРОДЛЕНИЕ  упало", *a[8:])
        self.assertEqual(code, 1)
        self.assertIn("C001", out)
        self.ok("conclusion", "add", "-p", "n", "--text", "Падение у новых", "--rests-on", "C001")
        code, out = self.run_cmd("conclusion", "add", "-p", "n", "--text", "падение у новых", "--rests-on", "C001")
        self.assertEqual(code, 1)
        self.assertIn("K001", out)
        lv = ["lever", "add", "-p", "n", "--metric", "Продление", "--where", "новые", "--cause", "срок", "--action", "вернуть 14 дней",
              "--check", "тест", "--effect-low", "1", "--effect-base", "2", "--effect-high", "3", "--rests-on", "C001"]
        self.ok(*lv)
        code, out = self.run_cmd(*lv)
        self.assertEqual(code, 1)
        self.assertIn("L001", out)
        dec = ["decision", "add", "-p", "n", "--title", "Вернуть срок", "--owner", "я", "--metric", "Продление",
               "--review-date", "2027-01-01", "--review-if", "нет роста", "--rests-on", "K001"]
        self.ok(*dec)
        code, out = self.run_cmd(*dec)
        self.assertEqual(code, 1)
        self.assertIn("DR-001", out)

    def test_stage_next_from_is_idempotent(self):
        self.write(self.p / "brief.md", "# Постановка\n\nГотово.\n")
        self.ok("req", "add", "-p", "n", "--text", "Вопрос", "--quote", "Почему упало")
        self.ok("stage", "next", "-p", "n", "--from", "1")
        out = self.ok("stage", "next", "-p", "n", "--from", "1")
        self.assertIn("уже закрыт", out)
        self.assertIn("Этап 2 из 8", self.ok("status", "-p", "n"))

    def test_done_mark_idempotent(self):
        self.ok("done", "add", "-p", "n", "--text", "Т")
        self.ok("done", "mark", "-p", "n", "D1")
        before = (self.p / "journal.jsonl").read_text(encoding="utf-8")
        out = self.ok("done", "mark", "-p", "n", "D1")
        self.assertIn("повторно не записано", out)
        self.assertEqual(before, (self.p / "journal.jsonl").read_text(encoding="utf-8"))

    def test_journal_hash_and_status_journal(self):
        self.ok("done", "add", "-p", "n", "--text", "Т")
        rows = [json.loads(l) for l in (self.p / "journal.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertTrue(all(len(r["h"]) == 8 for r in rows))
        out = self.ok("status", "-p", "n", "--journal", "5")
        self.assertIn("Добавлен критерий готовности D1", out)
        self.assertIn("Создана задача", out)
        self.assertIn("[%s]" % rows[-1]["h"], out)


class RepeatedFailureTests(Env):
    def setUp(self):
        Env.setUp(self)
        self.p = self.new_project("f")

    def test_second_identical_failure_prints_instruction(self):
        code, out = self.run_cmd("gate", "-p", "f")
        self.assertEqual(code, 2)
        self.assertNotIn("Повторная неудача", out)
        code, out = self.run_cmd("gate", "-p", "f")
        self.assertIn("Повторная неудача той же проверки. Смените подход:", out)
        self.assertIn("methods/01-postanovka-i-diagnoz.md", out)
        self.assertIn("сильная", out)
        self.assertIn("Исправлений выбора модели или метода: 1", self.ok("status", "-p", "f"))
        self.assertIn("исправление выбора", (self.p / "journal.jsonl").read_text(encoding="utf-8"))
        self.assertIn("Исправлений выбора модели или метода: 1", self.ok("cost", "log", "-p", "f", "--stage", "1", "--usd", "0.1") + self.ok("cost", "report", "-p", "f"))

    def test_changed_findings_reset_counter(self):
        self.run_cmd("gate", "-p", "f")
        self.write(self.p / "brief.md", "# Постановка\n\nВсё заполнено.\n")
        code, out = self.run_cmd("gate", "-p", "f")
        self.assertNotIn("Повторная неудача", out)

    def test_verify_counts_too(self):
        self.run_cmd("verify", "-p", "f")
        code, out = self.run_cmd("verify", "-p", "f")
        self.assertIn("Повторная неудача", out)

    def test_route_suggest_and_escalate(self):
        out = self.ok("route", "suggest", "--step", "диагностика причины просадки")
        self.assertIn("Класс модели: сильная", out)
        self.assertIn("methods/03-poisk-prichiny-prosadki.md", out)
        out = self.ok("route", "suggest", "--step", "чистка и переименование файлов")
        self.assertIn("дешёвая", out)
        code, out = self.run_cmd("route", "suggest", "--step", "qqq")
        self.assertEqual(code, 1)
        out = self.ok("route", "escalate", "-p", "f", "--stage", "3", "--reason", "цитаты не находятся")
        self.assertIn("средняя", out)
        self.assertIn("Исправлений выбора модели или метода: 1", self.ok("status", "-p", "f"))
        code, out = self.run_cmd("route", "escalate", "-p", "f", "--stage", "3", "--reason", " ")
        self.assertEqual(code, 1)


class CostMeasureTests(Env):
    def setUp(self):
        Env.setUp(self)
        self.p = self.new_project("c")

    def report(self, name, sid, usd, ms, turns):
        return str(self.write(self.tmp / name, json.dumps({"session_id": sid, "total_cost_usd": usd, "duration_api_ms": ms,
                                                           "num_turns": turns, "type": "result"})))

    def rows(self):
        return [json.loads(l) for l in (self.p / "cost.jsonl").read_text(encoding="utf-8").splitlines()]

    def test_log_kinds(self):
        self.ok("cost", "log", "-p", "c", "--stage", "3", "--usd", "1")
        self.ok("cost", "log", "-p", "c", "--stage", "3", "--usd", "2", "--measured")
        self.assertEqual([r["kind"] for r in self.rows()], ["оценка агента", "замер"])

    def test_import_increment_split_and_repeat(self):
        f1 = self.report("a.json", "sess-1", 1.0, 60000, 10)
        out = self.ok("cost", "import-session", "-p", "c", f1, "--stage", "3,4")
        self.assertIn("1.00 USD", out)
        r = self.rows()
        self.assertEqual([x["stage"] for x in r], [3, 4])
        self.assertAlmostEqual(r[0]["usd"], 0.5)
        self.assertEqual(r[0]["kind"], "замер")
        self.assertEqual(r[0]["session"], "sess-1")
        self.assertIn("Ничего не записано", self.ok("cost", "import-session", "-p", "c", f1, "--stage", "3,4"))
        self.assertEqual(len(self.rows()), 2)
        f2 = self.report("b.json", "sess-1", 2.5, 180000, 6)
        self.ok("cost", "import-session", "-p", "c", f2, "--stage", "5,6", "--split", "0.6,0.4")
        r = self.rows()
        self.assertAlmostEqual(r[2]["usd"], 0.9)
        self.assertAlmostEqual(r[3]["usd"], 0.6)
        self.assertEqual(r[2]["duration_ms"], 72000)
        code, out = self.run_cmd("cost", "import-session", "-p", "c", f2, "--stage", "5", "--split", "0.5")
        self.assertEqual(code, 1)
        f3 = self.report("c.json", "sess-1", 0.5, 1000, 1)
        self.assertEqual(self.run_cmd("cost", "import-session", "-p", "c", f3, "--stage", "5")[0], 1)

    def test_report_totals_time_turns_and_warning(self):
        self.ok("cost", "log", "-p", "c", "--stage", "3", "--usd", "0.5")
        self.ok("cost", "import-session", "-p", "c", self.report("a.json", "s", 1.0, 90000, 12), "--stage", "3")
        out = self.ok("cost", "report", "-p", "c")
        self.assertIn("Итого замер: 1.00 USD", out)
        self.assertIn("Итого оценка агента: 0.50 USD", out)
        self.assertIn("ходов: 12", out)
        self.assertIn("Предупреждение: Этап 3", out)
        self.assertIn("Потрачено: 1.00 USD", self.ok("status", "-p", "c"))

    def test_no_warning_within_twenty_percent(self):
        self.ok("cost", "log", "-p", "c", "--stage", "3", "--usd", "0.9")
        self.ok("cost", "import-session", "-p", "c", self.report("a.json", "s", 1.0, 1000, 1), "--stage", "3")
        self.assertNotIn("Предупреждение", self.ok("cost", "report", "-p", "c"))

    def test_bad_report(self):
        bad = str(self.write(self.tmp / "bad.json", json.dumps({"session_id": "x"})))
        code, out = self.run_cmd("cost", "import-session", "-p", "c", bad, "--stage", "3")
        self.assertEqual(code, 1)
        self.assertIn("нет поля", out)


class PageCodesTests(Env):
    def page(self, text):
        (self.root / "projects" / "_example" / "page.md").write_text(text, encoding="utf-8")

    def base(self):
        return (self.root / "projects" / "_example" / "page.md").read_text(encoding="utf-8")

    def test_codes_in_body_fail_with_hint(self):
        t = self.base().replace("Начать с пробного периода.", "Начать с рычага L001 и решения DR-001.")
        self.page(t)
        code, data = self.verify_json(*EX, "--layer", "5")
        self.assertEqual(code, 2)
        txt = self.issues_text(data, 5)
        self.assertIn("L001", txt)
        fixes = " ".join(i["fix"] for i in data["layers"]["5"]["issues"])
        self.assertIn("назовите рычаг и вариант словами", fixes)

    def test_codes_allowed_in_ids_line_and_paths(self):
        t = self.base().rstrip("\n") + "\nНомера записей: L001, K006, DR-001, C002\n"
        self.page(t)
        code, data = self.verify_json(*EX, "--layer", "5")
        self.assertEqual(code, 0, data)

    def test_ids_line_must_be_last(self):
        t = self.base().replace("Файлы:", "Номера записей: L001\n\nФайлы:")
        self.page(t)
        code, data = self.verify_json(*EX, "--layer", "5")
        self.assertEqual(code, 2)
        self.assertIn("L001", self.issues_text(data, 5))

    def test_number_still_matched_by_value_without_codes(self):
        t = self.base().replace("Начать с пробного периода.", "Начать с пробного периода, цифра 9876.")
        self.page(t)
        code, data = self.verify_json(*EX, "--layer", "5")
        self.assertEqual(code, 2)
        self.assertIn("9876", self.issues_text(data, 5))

    def test_abbreviation_reported_and_configurable(self):
        self.page(self.base().replace("процентных пунктов", "п. п."))
        code, data = self.verify_json(*EX, "--layer", "5")
        self.assertEqual(code, 2)
        self.assertIn("п. п.", self.issues_text(data, 5))
        self.page(self.base().replace("Начать с пробного периода.", "Начать с пробного периода, т.е. с условий."))
        self.assertIn("т.е.", self.issues_text(self.verify_json(*EX, "--layer", "5")[1], 5))
        style = json.loads((self.root / "config" / "style.json").read_text(encoding="utf-8"))
        style["abbreviations"] = []
        self.set_config("style.json", style)
        self.assertEqual(self.verify_json(*EX, "--layer", "5")[0], 0)

    def test_config_validates_abbreviations(self):
        style = json.loads((self.root / "config" / "style.json").read_text(encoding="utf-8"))
        style["abbreviations"] = ["п.п."]
        self.set_config("style.json", style)
        self.assertEqual(self.run_cmd("doctor")[0], 2)


class ExampleTests(Env):
    def test_example_passes_everything(self):
        self.assertEqual(self.run_cmd("verify", *EX)[0], 0)
        self.assertEqual(self.run_cmd("gate", *EX)[0], 0)
        self.assertIn("Требований из запроса: выполнено 3 из 3, снято 0", self.ok("status", *EX))


if __name__ == "__main__":
    unittest.main()
