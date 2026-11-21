# -*- coding: utf-8 -*-
"""Следы действий агента: происшествия, журнал запросов, «пусто» только после поиска, карта причин, строка состояния."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import Env, ROOT  # noqa: E402

NO_SEARCH = "Слой помечен пустым без поиска по базе знаний"
QUOTE = "Бесплатный пробный период в 14 дней снижал отток в сервисах подписки"


def jrows(p):
    return [json.loads(l) for l in (Path(p) / "journal.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]


class Base(Env):
    def drop_journal(self, proj_dir, *cmds):
        path = Path(proj_dir) / "journal.jsonl"
        rows = [r for r in jrows(proj_dir) if r["cmd"] not in cmds]
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")

    def make_kb(self, layers=("4",)):
        src = self.write(self.root / "kb.txt", QUOTE + ".\n")
        self.ok("kb", "source", "add", "--url", "https://example.org/kb", "--text-file", str(src), "--published", "2026-05-01")
        for layer in layers:
            self.ok("kb", "add", "--rule", "Бесплатный пробный период снижает отток (слой %s)" % layer, "--applies-when", "когда есть подписка",
                    "--theme", "удержание", "--layer", layer, "--source", "KS001", "--quote", QUOTE, "--strength", "данные-компании",
                    "--place", "страна Нигде, Вымышленная связь")

    def ex(self):
        return self.root / "projects" / "_example"


class IncidentTests(Base):
    def test_new_puts_note_at_top_of_errors(self):
        p = self.new_project()
        text = (p / "errors.md").read_text(encoding="utf-8")
        self.assertIn("incident add", text.split("\n\n")[1])
        self.assertIn("Происшествий записано: 0", self.ok("status", "-p", "t"))

    def test_add_list_number_and_journal(self):
        p = self.new_project()
        out = self.ok("incident", "add", "--kind", "ошибка-агента", "--what", "Написал «записал в errors.md», файл пуст",
                      "--caught-by", "руководитель", "--fix", "теперь запись только командой", "-p", "t")
        self.assertIn("I001", out)
        self.ok("incident", "add", "--kind", "другое", "--what", "второе", "-p", "t")
        text = (p / "errors.md").read_text(encoding="utf-8")
        self.assertIn("## I001. 2026-11-18. ошибка-агента", text)
        self.assertIn("## I002. 2026-11-18. другое", text)
        self.assertIn("- Кто заметил: руководитель", text)
        self.assertIn("- Что исправлено: теперь запись только командой", text)
        lst = self.ok("incident", "list", "-p", "t")
        self.assertIn("I001", lst)
        self.assertIn("I002", lst)
        j = [r for r in jrows(p) if r["cmd"] == "incident add"]
        self.assertEqual([r["detail"]["id"] for r in j], ["I001", "I002"])
        st = self.ok("status", "-p", "t", "--journal", "5")
        self.assertIn("Происшествий записано: 2 (последнее: I002 от 2026-11-18, другое: второе)", st)
        self.assertIn("Записано происшествие I002", st)

    def test_bad_kind_empty_what_unknown_source(self):
        self.new_project()
        code, _ = self.run_cmd("incident", "add", "--kind", "выдумка", "--what", "х", "-p", "t")
        self.assertEqual(code, 1)
        code, out = self.run_cmd("incident", "add", "--kind", "другое", "--what", "  ", "-p", "t")
        self.assertEqual(code, 1)
        code, out = self.run_cmd("incident", "add", "--kind", "другое", "--what", "х", "--source", "S003", "-p", "t")
        self.assertEqual(code, 1)
        self.assertIn("S003", out)

    def test_source_is_recorded(self):
        p = self.new_project()
        f = self.write(p / "t.txt", "Текст страницы про отток")
        self.ok("source", "add", "--url", "https://example.org/a", "--text-file", str(f), "--published", "2026", "--layer", "3", "-p", "t")
        self.ok("incident", "add", "--kind", "команда-в-источнике", "--what", "В тексте страницы просили выполнить команду", "--source", "S001", "-p", "t")
        self.assertIn("- Источник: S001", (p / "errors.md").read_text(encoding="utf-8"))

    def test_legacy_free_text_still_works(self):
        p = self.new_project()
        (p / "errors.md").write_text("# Ошибки агента\n\n- перепутал источники\n- забыл про сезонность\n", encoding="utf-8")
        st = self.ok("status", "-p", "t")
        self.assertIn("Происшествий записано: 2", st)
        self.assertIn("записано вручную", st)
        self.assertIn("записано вручную", self.ok("incident", "list", "-p", "t"))
        self.ok("incident", "add", "--kind", "другое", "--what", "новое", "-p", "t")
        text = (p / "errors.md").read_text(encoding="utf-8")
        self.assertIn("- перепутал источники", text)
        self.assertIn("incident add", text)
        self.assertIn("## I001.", text)
        self.assertIn("Происшествий записано: 3", self.ok("status", "-p", "t"))

    def test_example_errors_use_program_format(self):
        out = self.ok("incident", "list", "-p", "_example")
        self.assertIn("I001", out)
        self.assertNotIn("вручную", out)


class QueryTraceTests(Base):
    def setUp(self):
        super().setUp()
        self.p = self.new_project()
        self.make_kb()

    def last(self):
        return jrows(self.p)[-1]

    def test_kb_search_records_query_and_count(self):
        out = self.ok("kb", "search", "пробный период отток", "-p", "t")
        self.assertIn("Результатов по слоям: слой 2: 0; слой 3: 0; слой 4: 1; слой 5: 0.", out)
        r = self.last()
        self.assertEqual(r["cmd"], "kb search")
        self.assertEqual(r["detail"]["query"], "пробный период отток")
        self.assertEqual(r["detail"]["results"], 1)
        self.assertEqual(r["detail"]["per_layer"]["4"], 1)

    def test_single_active_project_is_traced_without_flag(self):
        self.ok("kb", "search", "пробный период")
        self.assertEqual(self.last()["cmd"], "kb search")

    def test_several_projects_need_explicit_flag(self):
        self.new_project("u")
        n = len(jrows(self.p))
        out = self.ok("kb", "search", "пробный период")
        self.assertIn("--project", out)
        self.assertEqual(len(jrows(self.p)), n)
        self.ok("kb", "search", "пробный период", "-p", "u")
        self.assertEqual(jrows(self.root / "projects" / "u")[-1]["cmd"], "kb search")

    def test_status_and_gate_work_with_several_projects(self):
        """Замки запускаются без имени задачи. При нескольких задачах они не должны падать с ошибкой."""
        self.new_project("u")
        code, out = self.run_cmd("status")
        self.assertEqual(code, 0, out)
        self.assertIn("Задач несколько", out)
        self.assertIn("- t:", out)
        self.assertIn("- u:", out)
        self.assertIn("менялась последней", out)
        code, out = self.run_cmd("gate")
        self.assertIn("Замок проверяет задачу «u»", out)
        self.assertIn(code, (0, 2))
        code, out = self.run_cmd("gate", "-p", "t")
        self.assertNotIn("Замок проверяет задачу", out)

    def test_layer_filter(self):
        out = self.ok("kb", "search", "пробный период", "--layer", "3", "-p", "t")
        self.assertIn("Показан только слой 3", out)
        self.assertNotIn("B001", out.split("Результатов")[0])
        self.assertEqual(self.last()["detail"]["layer"], 3)
        self.assertEqual(self.last()["detail"]["results"], 0)
        out = self.ok("kb", "search", "пробный период", "--layer", "4", "-p", "t")
        self.assertIn("B001", out)
        code, _ = self.run_cmd("kb", "search", "х", "--layer", "1", "-p", "t")
        self.assertEqual(code, 1)

    def test_kb_show_recorded_even_when_missing(self):
        self.ok("kb", "show", "B001", "-p", "t")
        self.assertEqual(self.last()["detail"], {"id": "B001", "results": 1})
        code, _ = self.run_cmd("kb", "show", "B999", "-p", "t")
        self.assertEqual(code, 1)
        self.assertEqual(self.last()["detail"], {"id": "B999", "results": 0})

    def map_fixture(self):
        self.ok("map", "node", "add", "--name", "Отток подписчиков", "--kind", "показатель")
        self.ok("map", "node", "add", "--name", "Пробный период", "--kind", "фактор")
        self.ok("map", "link", "add", "--from", "Пробный период", "--to", "Отток подписчиков", "--sign", "ослабляет", "--evidence", "B001")

    def test_map_queries_recorded(self):
        self.map_fixture()
        self.ok("map", "causes", "Отток подписчиков", "-p", "t")
        self.assertEqual((self.last()["cmd"], self.last()["detail"]["results"]), ("map causes", 1))
        self.ok("map", "effects", "Пробный период", "-p", "t")
        self.assertEqual((self.last()["cmd"], self.last()["detail"]["results"]), ("map effects", 1))
        self.ok("map", "path", "Пробный период", "Отток подписчиков", "-p", "t")
        self.assertEqual((self.last()["cmd"], self.last()["detail"]["results"]), ("map path", 1))

    def test_map_without_matching_node_is_recorded_as_looked(self):
        self.map_fixture()
        code, out = self.run_cmd("map", "causes", "совсем другое слово", "-p", "t")
        self.assertEqual(code, 1)
        self.assertIn("записан в журнал", out)
        r = self.last()
        self.assertEqual(r["cmd"], "map causes")
        self.assertEqual(r["detail"]["results"], 0)
        self.assertIsNone(r["detail"]["node"])
        self.assertIn("нет узла", r["detail"]["note"])
        self.assertIn("узла на карте нет", self.ok("status", "-p", "t", "--journal", "1"))

    def test_status_journal_shows_queries_in_words(self):
        self.ok("kb", "search", "пробный период", "-p", "t")
        out = self.ok("status", "-p", "t", "--journal", "3")
        self.assertIn("Поиск по базе знаний «пробный период»: найдено 1.", out)


class EmptyLayerTests(Base):
    def test_example_passes(self):
        for cmd in (("verify",), ("gate",)):
            self.ok(*cmd, "-p", "_example")
        self.ok("layers", "check", "-p", "_example")
        self.ok("doctor")

    def test_empty_without_search_fails_layer3_and_layers_check(self):
        self.drop_journal(self.ex(), "kb search")
        code, data = self.verify_json("-p", "_example")
        self.assertEqual(code, 2)
        text = self.issues_text(data, 3)
        self.assertIn(NO_SEARCH, text)
        fixes = " ".join(i["fix"] for i in data["layers"]["3"]["issues"])
        self.assertIn('kb search "', fixes)
        self.assertIn("--layer 4", fixes)
        self.assertIn("--layer 5", fixes)
        code, out = self.run_cmd("layers", "check", "-p", "_example")
        self.assertEqual(code, 2)
        self.assertIn(NO_SEARCH, out)
        self.assertIn('python3 tools/rychag.py kb search "', out)

    def test_layer_filtered_search_unlocks_that_layer_only(self):
        self.drop_journal(self.ex(), "kb search")
        self.make_kb(("4", "5"))
        self.ok("kb", "search", "пробный период отток", "--layer", "4", "-p", "_example")
        _c, data = self.verify_json("-p", "_example")
        text = self.issues_text(data, 3)
        self.assertNotIn("Компании в мире", text)
        self.assertIn("Смежные отрасли", text)

    def test_zero_count_in_layer_unlocks(self):
        self.drop_journal(self.ex(), "kb search")
        self.ok("kb", "search", "подписка чтение", "-p", "_example")  # в пустой базе по всем слоям ноль результатов: смотрели, нашли ноль
        code, _ = self.run_cmd("verify", "-p", "_example")
        self.assertEqual(code, 0)

    def test_nonzero_count_does_not_unlock(self):
        self.drop_journal(self.ex(), "kb search")
        self.make_kb(("4", "5"))
        self.ok("kb", "search", "пробный период отток", "-p", "_example")  # в слоях 4 и 5 есть результаты: «пусто» не подтверждено
        _c, data = self.verify_json("-p", "_example")
        text = self.issues_text(data, 3)
        self.assertIn("Компании в мире", text)
        self.assertIn("Смежные отрасли", text)

    def test_search_before_project_creation_does_not_count(self):
        self.drop_journal(self.ex(), "kb search")
        old = {"ts": "2026-01-01T10:00:00", "h": "old00000", "cmd": "kb search",
               "detail": {"query": "что-то", "results": 0, "layer": 4, "per_layer": {"2": 0, "3": 0, "4": 0, "5": 0}}}
        with open(str(self.ex() / "journal.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(old, ensure_ascii=False) + "\n")
        _c, data = self.verify_json("-p", "_example")
        self.assertIn(NO_SEARCH, self.issues_text(data, 3))

    def test_layers_one_two_not_affected(self):
        p = self.ex() / "analysis" / "sloi.md"
        text = p.read_text(encoding="utf-8").replace(
            "Продление по кварталам и срезам посчитано по выгрузке продукта (C005, C006, C007).",
            "Пусто, потому что выгрузок нет.")
        p.write_text(text, encoding="utf-8")
        self.drop_journal(self.ex(), "kb search")
        _c, data = self.verify_json("-p", "_example")
        self.assertNotIn("Данные самого продукта", self.issues_text(data, 3))


class MapConsultedTests(Base):
    def test_stage4_requires_map_query(self):
        self.drop_journal(self.ex(), "map causes", "map effects")
        code, data = self.verify_json("-p", "_example")
        self.assertEqual(code, 2)
        self.assertIn("карта причин не открывалась", self.issues_text(data, 3))
        fixes = " ".join(i["fix"] for i in data["layers"]["3"]["issues"])
        self.assertIn('python3 tools/rychag.py map causes "', fixes)

    def test_path_alone_does_not_count(self):
        self.drop_journal(self.ex(), "map causes", "map effects")
        with open(str(self.ex() / "journal.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": "2026-11-18T23:00:00", "h": "x", "cmd": "map path", "detail": {"query": "a -> b", "results": 0}}) + "\n")
        code, _ = self.run_cmd("verify", "-p", "_example")
        self.assertEqual(code, 2)

    def test_query_with_no_matching_node_still_counts(self):
        self.drop_journal(self.ex(), "map causes", "map effects")
        code, out = self.run_cmd("map", "causes", "продление подписки читалка", "-p", "_example")
        self.assertEqual(code, 1)  # узла нет: об этом сказано
        self.assertEqual(jrows(self.ex())[-1]["detail"]["node"], None)
        self.ok("verify", "-p", "_example")

    def test_not_required_before_stage4(self):
        p = self.new_project()
        self.assertEqual(json.loads((p / "state.json").read_text(encoding="utf-8"))["stage"], 1)
        _c, data = self.verify_json("-p", "t", "--layer", "3")
        self.assertNotIn("карта причин не открывалась", self.issues_text(data, 3))


class ReceiptTests(Base):
    def test_receipt_line_format(self):
        out = self.ok("status", "-p", "_example", "--receipt").strip()
        self.assertEqual(len(out.splitlines()), 1)
        self.assertRegex(out, r"^Состояние по программе: этап 8 из 8; источников 4; фактов 4; требований закрыто 3 из 3; происшествий 1; "
                              r"замера расхода нет, оценка агента 1,30 USD; проверка этапа пройдена; контрольная сумма [0-9a-f]{6}\.$")
        self.assertNotIn(chr(0x2014), out)

    def test_receipt_uses_measured_cost(self):
        self.ok("cost", "log", "--stage", "3", "--usd", "3.01", "--measured", "-p", "_example")
        self.assertIn("расход по замеру 3,01 USD", self.ok("status", "-p", "_example", "--receipt"))

    def test_check_current_and_stale(self):
        line = self.ok("status", "-p", "_example", "--receipt").strip()
        out = self.ok("status", "-p", "_example", "--check-receipt", line)
        self.assertIn("совпадает с текущим", out)
        self.ok("incident", "add", "--kind", "другое", "--what", "ещё одно", "-p", "_example")
        code, out = self.run_cmd("status", "-p", "_example", "--check-receipt", line)
        self.assertEqual(code, 2)
        self.assertIn("более ранним состоянием", out)
        self.assertRegex(out, r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}")
        new = self.ok("status", "-p", "_example", "--receipt").strip()
        self.assertNotEqual(new, line)
        self.assertIn("происшествий 2", new)
        self.ok("status", "-p", "_example", "--check-receipt", new)

    def test_invented_and_edited_lines_are_caught(self):
        line = self.ok("status", "-p", "_example", "--receipt").strip()
        code, out = self.run_cmd("status", "-p", "_example", "--check-receipt",
                                 "Состояние по программе: этап 8 из 8; источников 40; контрольная сумма 123abc.")
        self.assertEqual(code, 2)
        self.assertIn("придумана", out)
        edited = line.replace("фактов 4", "фактов 14")
        code, out = self.run_cmd("status", "-p", "_example", "--check-receipt", edited)
        self.assertEqual(code, 2)
        self.assertIn("правили руками", out)
        code, out = self.run_cmd("status", "-p", "_example", "--check-receipt", "всё хорошо")
        self.assertEqual(code, 2)
        self.assertIn("не строка состояния", out)

    def test_state_change_in_files_changes_checksum(self):
        a = self.ok("status", "-p", "_example", "--receipt").strip()
        self.write(self.ex() / "analysis" / "extra.txt", "новый файл")
        b = self.ok("status", "-p", "_example", "--receipt").strip()
        self.assertNotEqual(a.rsplit(" ", 1)[1], b.rsplit(" ", 1)[1])

    def test_receipt_recorded_in_journal_once_per_state(self):
        self.ok("status", "-p", "_example", "--receipt")
        self.ok("status", "-p", "_example", "--receipt")
        self.assertEqual(len([r for r in jrows(self.ex()) if r["cmd"] == "state receipt"]), 1)

    def test_receipt_failed_check_reported(self):
        p = self.new_project()
        out = self.ok("status", "-p", "t", "--receipt")
        self.assertIn("этап 1 из 8", out)
        self.assertIn("проверка этапа не пройдена", out)

    def test_both_flags_refused(self):
        code, _ = self.run_cmd("status", "-p", "_example", "--receipt", "--check-receipt", "x")
        self.assertEqual(code, 1)


class McpTraceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import shutil
        import tempfile
        cls.tmp = Path(tempfile.mkdtemp(prefix="rychag-mcp-trace-"))
        cls.root = cls.tmp / "repo"
        shutil.copytree(str(ROOT / "config"), str(cls.root / "config"))
        shutil.copytree(str(ROOT / "projects" / "_example"), str(cls.root / "projects" / "_example"),
                        ignore=shutil.ignore_patterns("__pycache__"))

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(str(cls.tmp), True)

    def call(self, name, args):
        from test_mcp_server import run_session, init_msg, call_msg
        _p, replies = run_session([init_msg(), call_msg(2, name, args)], self.root)
        return [r for r in replies if r.get("id") == 2][0]["result"]

    def test_incident_tools_and_receipt(self):
        r = self.call("incident_add", {"kind": "недоступный-инструмент", "what": "Поиск в сети не отвечал", "fix": "взяли материалы из папки"})
        self.assertFalse(r["isError"], r)
        self.assertIn("I002", r["content"][0]["text"])
        r = self.call("incident_list", {})
        self.assertIn("I002", r["content"][0]["text"])
        self.assertIn("Поиск в сети не отвечал", r["content"][0]["text"])
        r = self.call("state_receipt", {})
        line = r["content"][0]["text"].strip()
        self.assertTrue(line.startswith("Состояние по программе: "), line)
        self.assertIn("происшествий 2", line)
        r = self.call("state_receipt", {"check": line})
        self.assertFalse(r["isError"])
        self.assertIn("совпадает", r["content"][0]["text"])
        r = self.call("state_receipt", {"check": "Состояние по программе: этап 1 из 8; контрольная сумма 000000."})
        self.assertIn("не совпадает", r["content"][0]["text"])

    def test_bad_arguments(self):
        r = self.call("incident_add", {"kind": "другое"})
        self.assertTrue(r["isError"])
        r = self.call("incident_add", {"kind": "выдумка", "what": "х"})
        self.assertTrue(r["isError"])

    def test_kb_search_via_mcp_leaves_trace(self):
        self.call("kb_search", {"query": "подписка", "layer": 3})
        rows = jrows(self.root / "projects" / "_example")
        self.assertEqual(rows[-1]["cmd"], "kb search")
        self.assertEqual(rows[-1]["detail"]["layer"], 3)


if __name__ == "__main__":
    unittest.main()
