# -*- coding: utf-8 -*-
"""Проверки правок после первого настоящего запуска: поиск узла словами, гипотезы в обходе, повторный импорт,
возражения против связи, полнота диагноза, проход по слоям близости, точность счёта по словарю, период данных."""
import json
import unittest
from pathlib import Path

from helpers import Env
import test_map_learn as tm

EX = ("-p", "_example")


def set_stage(proj_dir, n):
    p = Path(proj_dir) / "state.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    d["stage"] = n
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")


class NodeLookupTests(tm.MapBase):
    def setUp(self):
        tm.MapBase.setUp(self)
        self.ok("map", "node", "add", "--name", "Оценка приложения в магазине", "--kind", "показатель", "--alias", "рейтинг")  # N004
        self.ok("map", "node", "add", "--name", "Ответы на отзывы в магазине", "--kind", "фактор")                            # N005
        self.ok("map", "link", "add", "--from", "N005", "--to", "N004", "--sign", "усиливает", "--evidence", "B003")

    def test_words_with_endings_find_node(self):
        out = self.ok("map", "causes", "оценка в магазине")
        self.assertIn("N004 «Оценка приложения в магазине»", out)
        self.assertIn("N005", out)
        self.assertIn("N004", self.ok("map", "causes", "оценки магазина"))

    def test_alias_is_found(self):
        self.ok("map", "causes", "рейтинг")  # псевдоним целиком

    def test_several_matches_are_listed_with_numbers(self):
        code, out = self.run_cmd("map", "causes", "магазине")
        self.assertEqual(code, 1)
        self.assertIn("1. N004", out)
        self.assertIn("2. N005", out)
        self.assertIn("код", out)

    def test_nothing_found_shows_five_closest(self):
        code, out = self.run_cmd("map", "causes", "квантовая физика")
        self.assertEqual(code, 1)
        self.assertIn("Пять ближайших", out)
        self.assertIn("5. N", out)

    def test_other_commands_use_words_too(self):
        self.assertIn("Цепочка 1", self.ok("map", "path", "ответы на отзывы", "оценка в магазине"))
        self.assertIn("Следствия", self.ok("map", "effects", "ответы на отзывы"))
        self.ok("map", "export", "--format", "mermaid", "--around", "оценка в магазине", "--depth", "1")
        text = (self.root / "knowledge" / "map" / "map.mmd").read_text(encoding="utf-8")
        self.assertIn("N005", text)
        self.assertNotIn("N003", text)


class HypothesisTraversalTests(tm.MapBase):
    def setUp(self):
        tm.MapBase.setUp(self)
        a = ["map", "link", "add"]
        self.ok(*a, "--from", "N002", "--to", "N001", "--sign", "усиливает", "--note", "Нужна запись о доле ушедших после повышения цены")  # R001 гипотеза
        self.ok(*a, "--from", "N003", "--to", "N002", "--sign", "ослабляет", "--evidence", "B002", "--note", "только в одной стране")        # R002 доказана

    def test_note_hypothesis_mark_and_continuation(self):
        out = self.ok("map", "causes", "N001", "--depth", "2")
        self.assertIn("[ГИПОТЕЗА, не доказана] R001", out)
        self.assertIn("чего не хватает: Нужна запись о доле ушедших", out)
        self.assertIn("[цепочка идёт через гипотезу] R002", out)
        self.assertIn("примечание: только в одной стране", out)
        self.assertIn("Показано связей: 2, из них доказано 1, гипотез 1.", out)

    def test_proven_only_stops_at_hypothesis(self):
        out = self.ok("map", "causes", "N001", "--depth", "2", "--proven-only")
        self.assertIn("R001", out)
        self.assertNotIn("R002", out)
        self.assertIn("Показано связей: 1, из них доказано 0, гипотез 1.", out)

    def test_effects_also_continue(self):
        out = self.ok("map", "effects", "N003", "--depth", "2")
        self.assertIn("R002", out)
        self.assertIn("[ГИПОТЕЗА, не доказана] R001", out)


class ImportAgainTests(tm.MapBase):
    def lines(self, extra_ev=("B002",)):
        rows = [{"type": "node", "name": "Конкуренты", "kind": "фактор", "aliases": ["рынок"]},
                {"type": "link", "from": "Конкуренты", "to": "N001", "sign": "ослабляет", "evidence": ["B003"], "conditions": "в регионах"},
                {"type": "link", "from": "N002", "to": "N001", "sign": "усиливает", "evidence": list(extra_ev)}]
        f = self.root / "m.jsonl"
        f.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        return f

    def test_second_import_skips_and_merges(self):
        f = self.lines()
        out = self.ok("map", "import", str(f))
        self.assertIn("Принято: узлов 1, связей 2. Отклонено: 0", out)
        out = self.ok("map", "import", str(f))
        self.assertIn("Принято: узлов 0, связей 0. Отклонено: 0", out)
        self.assertIn("Уже есть: узлов 1, связей 2. Дополнено существующих связей: 0", out)
        self.assertEqual(len(tm.jl(self.mp("links.jsonl"))), 2)
        out = self.ok("map", "import", str(self.lines(("B002", "B001"))))
        self.assertIn("Уже есть: узлов 1, связей 1. Дополнено существующих связей: 1", out)
        l = [x for x in tm.jl(self.mp("links.jsonl")) if x["from"] == "N002"][0]
        self.assertEqual(sorted(l["evidence"]), ["B001", "B002"])
        self.assertEqual(len(tm.jl(self.mp("links.jsonl"))), 2)

    def test_real_conflict_is_rejected(self):
        f = self.root / "c.jsonl"
        f.write_text(json.dumps({"type": "node", "name": "Цена тарифа", "kind": "показатель"}, ensure_ascii=False) + "\n", encoding="utf-8")
        code, out = self.run_cmd("map", "import", str(f))
        self.assertEqual(code, 2)
        self.assertIn("Отклонено: 1", out)


class ContradictedTests(tm.MapBase):
    def test_link_add_and_show(self):
        self.ok("map", "link", "add", "--from", "N002", "--to", "N001", "--sign", "усиливает", "--evidence", "B002", "--contradicted-by", "B003")
        l = tm.jl(self.mp("links.jsonl"))[0]
        self.assertEqual(l["contradicted_by"], ["B003"])
        out = self.ok("map", "causes", "N001")
        self.assertIn("записи против связи: B003 (", out)

    def test_check_lists_links_with_both(self):
        self.ok("map", "link", "add", "--from", "N002", "--to", "N001", "--sign", "усиливает", "--evidence", "B002")
        self.assertIn("Связи, у которых есть и подтверждающие, и возражающие записи: замечаний нет", self.ok("map", "check"))
        self.ok("map", "link", "add", "--from", "N002", "--to", "N001", "--sign", "усиливает", "--contradicted-by", "B003")
        out = self.ok("map", "check")
        self.assertIn("подтверждают записи B002, а возражают записи B003", out)

    def test_same_record_both_sides_and_unknown(self):
        code, out = self.run_cmd("map", "link", "add", "--from", "N002", "--to", "N001", "--sign", "усиливает",
                                 "--evidence", "B002", "--contradicted-by", "B002")
        self.assertEqual(code, 1)
        code, _ = self.run_cmd("map", "link", "add", "--from", "N002", "--to", "N001", "--sign", "усиливает", "--contradicted-by", "B999")
        self.assertEqual(code, 1)

    def test_import_field(self):
        f = self.root / "m.jsonl"
        f.write_text(json.dumps({"type": "link", "from": "N002", "to": "N001", "sign": "усиливает", "evidence": ["B002"],
                                 "contradicted_by": ["B003"]}) + "\n", encoding="utf-8")
        self.ok("map", "import", str(f))
        self.assertEqual(tm.jl(self.mp("links.jsonl"))[0]["contradicted_by"], ["B003"])


class DiagnosisTests(Env):
    def test_new_creates_template(self):
        p = self.new_project("d")
        text = (p / "analysis" / "diagnoz.md").read_text(encoding="utf-8")
        for h in ("Что произошло с показателем", "Шум и сезонность", "Что менялось в эти даты", "Где сосредоточено изменение", "Вклад среза",
                  "Проверка на срезе, которого причина не касается", "Вероятная причина и уверенность", "Отброшенные причины",
                  "Чего не знаем", "За какой период данные"):
            self.assertIn("## " + h, text)
        self.assertEqual(text.count("> Подсказка:"), 10)

    def test_layer3_fails_from_stage_4_naming_part(self):
        p = self.new_project("d")
        code, data = self.verify_json("-p", "d", "--layer", "3")
        self.assertNotIn("диагноз", self.issues_text(data, 3).lower())  # до этапа 4 не требуется
        set_stage(p, 4)
        code, data = self.verify_json("-p", "d", "--layer", "3")
        self.assertEqual(code, 2)
        self.assertIn("Шум и сезонность", self.issues_text(data, 3))
        fixes = " ".join(i["fix"] for i in data["layers"]["3"]["issues"])
        self.assertIn("добавьте заголовок «## Шум и сезонность»", fixes)

    def test_check_states_and_two_dates(self):
        p = self.new_project("d")
        self.write(p / "analysis" / "diagnoz.md",
                   "# Диагноз\n\n## что произошло с показателем: кратко\n\nПродление упало на шесть пунктов.\n\n"
                   "## За какой период данные\n\nДанные только за 2026-04-01.\n\n## Шум и сезонность\n\n> Подсказка: напишите\n")
        code, out = self.run_cmd("diagnosis", "check", "-p", "d")
        self.assertEqual(code, 2)
        self.assertIn("Что произошло с показателем: заполнено", out)
        self.assertIn("Шум и сезонность: заголовок есть, текста нет", out)
        self.assertIn("За какой период данные: нет двух дат периода", out)
        self.assertIn("Вклад среза: нет такого заголовка", out)
        self.write(p / "analysis" / "diagnoz.md", (p / "analysis" / "diagnoz.md").read_text(encoding="utf-8").replace(
            "только за 2026-04-01", "с 1 апреля 2026 года по 30.09.2026"))
        self.assertIn("За какой период данные: заполнено", self.run_cmd("diagnosis", "check", "-p", "d")[1])

    def test_example_diagnosis_ok(self):
        self.assertIn("Все части диагноза на месте", self.ok("diagnosis", "check", *EX))

    def test_missing_file(self):
        p = self.new_project("d")
        (p / "analysis" / "diagnoz.md").unlink()
        set_stage(p, 5)
        code, data = self.verify_json("-p", "d", "--layer", "3")
        self.assertIn("нет файла диагноза", self.issues_text(data, 3))


class ProximityPassTests(Env):
    def test_template_and_check(self):
        p = self.new_project("l")
        text = (p / "analysis" / "sloi.md").read_text(encoding="utf-8")
        for h in ("Данные самого продукта", "Данные компании", "Другие компании в России", "Компании в мире", "Смежные отрасли"):
            self.assertIn("## " + h, text)
        code, out = self.run_cmd("layers", "check", "-p", "l")
        self.assertEqual(code, 2)
        self.assertIn("Слой 1. Данные самого продукта: ни записей, ни причины", out)

    def test_layer3_requires_from_stage_4(self):
        p = self.new_project("l")
        set_stage(p, 4)
        _c, data = self.verify_json("-p", "l", "--layer", "3")
        self.assertIn("Компании в мире", self.issues_text(data, 3))

    def test_ids_and_empty_reason(self):
        self.write(self.root / "projects" / "_example" / "analysis" / "sloi.md",
                   "## Данные самого продукта\nСм. C005.\n\n## Данные компании\nКод C999 не существует.\n\n"
                   "## Другие компании в России\nПусто, потому что в базе нет записей.\n\n"
                   "## Компании в мире\nПусто.\n\n## Смежные отрасли\nпусто, потому что\n")
        code, out = self.run_cmd("layers", "check", *EX)
        self.assertEqual(code, 2)
        self.assertIn("Слой 1. Данные самого продукта: есть записи", out)
        self.assertIn("Слой 2. Данные компании: указан несуществующий код", out)
        self.assertIn("Слой 3. Другие компании в России: пусто, причина записана", out)
        self.assertIn("Слой 4. Компании в мире: ни записей, ни причины", out)
        self.assertIn("Слой 5. Смежные отрасли: ни записей, ни причины", out)  # после «потому что» нет причины

    def test_example_ok(self):
        self.assertIn("Все пять слоёв пройдены", self.ok("layers", "check", *EX))


class MethodAccuracyTests(Env):
    def setUp(self):
        Env.setUp(self)
        self.p = self.root / "projects" / "_example"
        self.write(self.p / "analysis" / "words.py", "print('Жалоб на цену по словарю: 47 процентов')\n")

    def calc(self, *extra):
        self.ok("calc", "run", "-p", "_example", "words.py", *extra)

    def test_default_method_and_meta(self):
        self.calc()
        self.assertEqual(json.loads((self.p / "sources" / "S005.meta.json").read_text(encoding="utf-8"))["method"], "расчёт")
        self.ok("claim", "add", *EX, "--type", "calc", "--source", "S005", "--quote", "Жалоб на цену по словарю: 47", "--number", "47", "--text", "Жалоб на цену 47 процентов.")
        c = json.loads((self.p / "ledger" / "claims.jsonl").read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(c["method"], "расчёт")
        self.assertEqual(c["flags"], [])

    def test_dictionary_without_accuracy_is_marked(self):
        self.calc("--method", "словарь")
        out = self.ok("claim", "add", *EX, "--type", "calc", "--source", "S005", "--quote", "Жалоб на цену по словарю: 47",
                      "--number", "47", "--text", "Жалоб на цену 47 процентов.")
        self.assertIn("точность не измерена", out)
        c = json.loads((self.p / "ledger" / "claims.jsonl").read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(c["method"], "словарь")
        self.assertIn("точность не измерена", c["flags"])

    def test_accuracy_and_sample_remove_mark(self):
        self.calc()
        out = self.ok("claim", "add", *EX, "--type", "calc", "--source", "S005", "--quote", "Жалоб на цену по словарю: 47", "--number", "47",
                      "--text", "Жалоб на цену 47 процентов.", "--method", "словарь", "--accuracy", "88", "--sample", "100")
        self.assertNotIn("точность не измерена", out)
        c = json.loads((self.p / "ledger" / "claims.jsonl").read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual((c["accuracy"], c["sample"]), (88.0, 100))

    def test_options_only_for_calc_and_valid(self):
        code, out = self.run_cmd("claim", "add", *EX, "--type", "hypothesis", "--text", "тест", "--method", "словарь")
        self.assertEqual(code, 1)
        self.calc()
        code, out = self.run_cmd("claim", "add", *EX, "--type", "calc", "--source", "S005", "--number", "47", "--text", "x 47", "--accuracy", "150")
        self.assertEqual(code, 1)

    def _page(self, line):
        page = self.p / "page.md"
        t = page.read_text(encoding="utf-8")
        page.write_text(t.replace("Рынок в среднем", line + " Рынок в среднем"), encoding="utf-8")

    def test_layer5_requires_word_estimate_for_unmeasured(self):
        self.calc("--method", "словарь")
        self.ok("claim", "add", *EX, "--type", "calc", "--source", "S005", "--quote", "Жалоб на цену по словарю: 47", "--number", "47", "--text", "Жалоб на цену 47 процентов.")
        self._page("Жалоб на цену 47%.")
        code, data = self.verify_json(*EX, "--layer", "5")
        self.assertEqual(code, 2)
        self.assertIn("по словарю", self.issues_text(data, 5))
        page = self.p / "page.md"
        page.write_text(page.read_text(encoding="utf-8").replace("Жалоб на цену 47%.", "Жалоб на цену 47% (оценка)."), encoding="utf-8")
        code, data = self.verify_json(*EX, "--layer", "5")
        self.assertEqual(code, 0, data["layers"]["5"]["issues"])

    def test_layer5_free_when_measured(self):
        self.calc()
        self.ok("claim", "add", *EX, "--type", "calc", "--source", "S005", "--quote", "Жалоб на цену по словарю: 47", "--number", "47",
                "--text", "Жалоб на цену 47 процентов.", "--method", "словарь", "--accuracy", "90", "--sample", "50")
        self._page("Жалоб на цену 47%.")
        self.assertEqual(self.verify_json(*EX, "--layer", "5")[0], 0)


class PeriodTests(Env):
    def test_status_shows_widest_period(self):
        p = self.new_project("p")
        self.write(p / "materials" / "a.txt", "первая выгрузка")
        self.write(p / "materials" / "b.txt", "вторая выгрузка")
        self.assertNotIn("Данные за период", self.ok("status", "-p", "p"))
        self.ok("source", "add", "-p", "p", "--file", "materials/a.txt", "--period-from", "2025-03-01", "--period-to", "2025-06-30")
        self.ok("source", "add", "-p", "p", "--file", "materials/b.txt", "--period-from", "2025-01-15", "--period-to", "2025-04-10")
        out = self.ok("status", "-p", "p")
        self.assertIn("Данные за период: с 2025-01-15 по 2025-06-30.", out)

    def test_period_needs_both_and_order(self):
        p = self.new_project("p")
        self.write(p / "materials" / "a.txt", "выгрузка")
        self.assertEqual(self.run_cmd("source", "add", "-p", "p", "--file", "materials/a.txt", "--period-from", "2025-03-01")[0], 1)
        self.assertEqual(self.run_cmd("source", "add", "-p", "p", "--file", "materials/a.txt", "--period-from", "2025-03-01", "--period-to", "2025-02-01")[0], 1)


if __name__ == "__main__":
    unittest.main()
