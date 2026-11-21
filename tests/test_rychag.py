# -*- coding: utf-8 -*-
"""Проверки самой программы. Запуск: python3 -m unittest discover -s tests"""
import hashlib
import json
import os
import unittest
from pathlib import Path

from helpers import Env, ROOT

EX = ("-p", "_example")


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


class QuoteTests(Env):
    def setUp(self):
        Env.setUp(self)
        self.p = self.new_project("q")
        self.write(self.p / "materials" / "a.txt",
                   "Выручка выросла на 12% по итогам «осени».\nВторая   строка   с пробелами и “кавычками”.\n")
        self.ok("source", "add", "-p", "q", "--file", "materials/a.txt", "--published", "2026-10-01")

    def claim(self, quote, number=None):
        args = ["claim", "add", "-p", "q", "--type", "fact", "--text", "т " + quote, "--source", "S001", "--quote", quote]
        if number:
            args += ["--number", number]
        return self.run_cmd(*args)

    def test_exact_quote_found(self):
        code, out = self.claim("Выручка выросла на 12% по итогам «осени».", "12%")
        self.assertEqual(code, 0, out)

    def test_quote_normalization(self):
        code, out = self.claim('ВЫРУЧКА выросла на 12% по итогам "осени".')
        self.assertEqual(code, 0, out)
        code, out = self.claim("Вторая строка с пробелами и \"кавычками\"")
        self.assertEqual(code, 0, out)

    def test_quote_not_found(self):
        code, out = self.claim("Выручка выросла на 15%")
        self.assertEqual(code, 1)
        self.assertIn("не найдена", out)

    def test_number_must_be_in_quote(self):
        code, out = self.claim("Выручка выросла на 12%", "15%")
        self.assertEqual(code, 1)
        self.assertIn("не встречается в цитате", out)

    def test_fact_without_source_or_quote_rejected(self):
        code, out = self.run_cmd("claim", "add", "-p", "q", "--type", "fact", "--text", "голое утверждение")
        self.assertEqual(code, 1)
        self.assertIn("без источника", out)
        code, out = self.run_cmd("claim", "add", "-p", "q", "--type", "fact", "--text", "т", "--source", "S001")
        self.assertEqual(code, 1)

    def test_interlocutor_source_cannot_ground_fact(self):
        self.write(self.p / "materials" / "ai.txt", "Собеседник сказал, что цена слишком высокая.")
        self.ok("source", "add", "-p", "q", "--file", "materials/ai.txt", "--kind", "собеседник")
        code, out = self.run_cmd("claim", "add", "-p", "q", "--type", "fact", "--text", "т", "--source", "S002",
                                 "--quote", "цена слишком высокая")
        self.assertEqual(code, 1)
        self.assertIn("не может быть основанием факта", out)

    def test_synthetic_is_flagged(self):
        out = self.ok("claim", "add", "-p", "q", "--type", "synthetic", "--text", "ИИ-собеседник: слишком дорого")
        self.assertIn("не может быть основанием", out)
        row = json.loads((self.p / "ledger" / "claims.jsonl").read_text(encoding="utf-8").splitlines()[0])
        self.assertTrue(row["flags"])

    def test_page_number_only_in_synthetic_fails(self):
        self.ok("claim", "add", "-p", "q", "--type", "synthetic", "--text", "Собеседник назвал 777 рублей")
        self.write(self.p / "page.md", "Цена 777 рублей.\n\nФайлы:\n- brief.md\n")
        code, data = self.verify_json("-p", "q", "--layer", "5")
        self.assertEqual(code, 2)
        self.assertIn("synthetic", self.issues_text(data, 5))

    def test_conclusion_on_synthetic_only_fails_layer3(self):
        self.ok("claim", "add", "-p", "q", "--type", "synthetic", "--text", "Собеседник считает, что дорого")
        self.ok("conclusion", "add", "-p", "q", "--text", "Дорого", "--rests-on", "C001")
        code, data = self.verify_json("-p", "q", "--layer", "3")
        self.assertEqual(code, 2)
        self.assertIn("synthetic/agent", self.issues_text(data, 3))

    def test_promise_needs_fact(self):
        self.ok("claim", "add", "-p", "q", "--type", "hypothesis", "--text", "Люди хотят скидку")
        out = self.ok("conclusion", "add", "-p", "q", "--kind", "promise", "--text", "Скидка 5%", "--rests-on", "C001")
        self.assertIn("Внимание", out)
        code, data = self.verify_json("-p", "q", "--layer", "4")
        self.assertEqual(code, 2)
        self.assertIn("обещание", self.issues_text(data, 4))


class SourceTests(Env):
    def setUp(self):
        Env.setUp(self)
        self.p = self.new_project("s")

    def add_file(self, name, text="Текст источника номер %s." , **extra):
        self.write(self.p / "materials" / name, text % name if "%s" in text else text)
        args = ["source", "add", "-p", "s", "--file", "materials/" + name]
        for k, v in extra.items():
            args += ["--" + k.replace("_", "-"), v]
        return self.run_cmd(*args)

    def test_per_question_ceiling(self):
        self.set_config("sources.json", {"allowlist": [], "max_sources_per_question": 2, "freshness_days": 730})
        for i in (1, 2):
            code, out = self.add_file("f%d.txt" % i, published="2026-10-01", question="Q1")
            self.assertEqual(code, 0, out)
        code, out = self.add_file("f3.txt", published="2026-10-01", question="Q1")
        self.assertEqual(code, 1)
        self.assertIn("Потолок", out)
        code, out = self.add_file("f4.txt", published="2026-10-01", question="Q2")
        self.assertEqual(code, 0, out)

    def test_freshness_refuse_allow_and_missing_date(self):
        code, out = self.add_file("old.txt", published="2020-01-01")
        self.assertEqual(code, 1)
        self.assertIn("старше порога", out)
        self.write(self.p / "materials" / "nodate.txt", "Без даты.")
        code, out = self.run_cmd("source", "add", "-p", "s", "--file", "materials/nodate.txt")
        self.assertEqual(code, 0)
        self.assertIn("Нет даты публикации", out)

    def test_allow_stale_flag(self):
        self.write(self.p / "materials" / "old.txt", "Старый текст.")
        code, out = self.run_cmd("source", "add", "-p", "s", "--file", "materials/old.txt", "--published",
                                 "2020-01-01", "--allow-stale")
        self.assertEqual(code, 0, out)
        code, data = self.verify_json("-p", "s", "--layer", "1")
        self.assertEqual(code, 0)

    def test_stale_source_fails_layer1_and_impact_stale(self):
        code, out = self.run_cmd("verify", "-p", "_example", "--layer", "1", today="2029-01-01")
        self.assertEqual(code, 2)
        self.assertIn("старше порога", out)
        out = self.ok("impact", "-p", "_example", "--stale", "--mark", today="2029-01-01")
        self.assertIn("Источники старше порога", out)
        self.assertIn("под-вопросом", out)
        out = self.ok("conclusion", "list", "-p", "_example")
        self.assertIn("под-вопросом", out)

    def test_allowlist(self):
        self.set_config("sources.json", {"allowlist": ["example.org"], "max_sources_per_question": 10, "freshness_days": 730})
        self.write(self.p / "materials" / "t.txt", "Текст страницы.")
        code, out = self.run_cmd("source", "add", "-p", "s", "--url", "https://evil.test/x", "--text-file",
                                 "materials/t.txt", "--published", "2026-10-01", "--layer", "3")
        self.assertEqual(code, 1)
        self.assertIn("не в разрешённом списке", out)
        code, out = self.run_cmd("source", "add", "-p", "s", "--url", "https://sub.example.org/x", "--text-file",
                                 "materials/t.txt", "--published", "2026-10-01", "--layer", "3")
        self.assertEqual(code, 0, out)

    def test_paths_outside_refused(self):
        code, out = self.run_cmd("source", "add", "-p", "s", "--file", "/etc/hosts")
        self.assertEqual(code, 1)
        self.write(self.p / "brief2.txt", "вне materials")
        code, out = self.run_cmd("source", "add", "-p", "s", "--file", "brief2.txt")
        self.assertEqual(code, 1)
        link = self.p / "materials" / "link.txt"
        os.symlink("/etc/hosts", str(link))
        code, out = self.run_cmd("source", "add", "-p", "s", "--file", "materials/link.txt")
        self.assertEqual(code, 1)
        self.assertIn("должен лежать внутри", out)

    def test_meta_and_copy(self):
        code, out = self.add_file("m.txt", "Строка   один\r\n\r\n\r\n\r\nСтрока два", published="2026-10-01", title="Заголовок")
        self.assertEqual(code, 0, out)
        txt = (self.p / "sources" / "S001.txt").read_text(encoding="utf-8")
        self.assertEqual(txt, "Строка   один\n\nСтрока два\n")
        meta = json.loads((self.p / "sources" / "S001.meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["sha256"], sha(self.p / "sources" / "S001.txt"))
        for k in ("path", "title", "published", "accessed", "question", "kind"):
            self.assertIn(k, meta)
        self.assertEqual(meta["accessed"], self.TODAY)

    def test_html_strip(self):
        from lib.sources import strip_html
        text, title = strip_html("<html><head><title>Т</title><style>x{}</style></head><body><p>Привет</p><script>a()</script><p>мир</p></body></html>")
        self.assertIn("Привет", text)
        self.assertNotIn("a()", text)
        self.assertNotIn("x{}", text)
        self.assertEqual(title, "Т")


class LayerTests(Env):
    def test_example_verifies(self):
        code, out = self.run_cmd("verify", *EX)
        self.assertEqual(code, 0, out)
        code, data = self.verify_json(*EX)
        self.assertEqual(code, 0)
        self.assertTrue(data["ok"])
        self.assertEqual(set(data["layers"]), {"1", "2", "3", "4", "5"})

    def test_coverage_line(self):
        out = self.ok("verify", *EX, "--layer", "3")
        self.assertIn("использовано 7 из 8, отброшено 1", out)

    def test_number_missing_from_ledger_fails_layer5(self):
        page = self.root / "projects" / "_example" / "page.md"
        text = page.read_text(encoding="utf-8")
        page.write_text(text.replace("Рынок в среднем", "Выручка выросла на 99%. Рынок в среднем"), encoding="utf-8")
        code, data = self.verify_json(*EX, "--layer", "5")
        self.assertEqual(code, 2)
        self.assertIn("99", self.issues_text(data, 5))

    def test_number_formats(self):
        page = self.root / "projects" / "_example" / "page.md"
        text = page.read_text(encoding="utf-8")
        page.write_text(text.replace("с 71% во втором", "с 71,0% во втором").replace("от 1 до 4", "от 1.0 до 4,0"), encoding="utf-8")
        code, out = self.run_cmd("verify", *EX, "--layer", "5")
        self.assertEqual(code, 0, out)

    def test_page_length_banned_and_paths(self):
        page = self.root / "projects" / "_example" / "page.md"
        base = page.read_text(encoding="utf-8")
        self.set_config("style.json", {"max_page_lines": 10, "banned_phrases": ["вернуть пробный период"]})
        code, data = self.verify_json(*EX, "--layer", "5")
        txt = self.issues_text(data, 5)
        self.assertIn("длиннее порога", txt)
        self.assertIn("пустой оборот", txt)
        self.set_config("style.json", {"max_page_lines": 45, "banned_phrases": []})
        page.write_text(base.replace("- brief.md", "- net-takogo.md"), encoding="utf-8")
        code, data = self.verify_json(*EX, "--layer", "5")
        self.assertIn("несуществующий файл", self.issues_text(data, 5))
        page.write_text(base.split("Файлы:")[0].rstrip() + "\n", encoding="utf-8")
        code, data = self.verify_json(*EX, "--layer", "5")
        self.assertEqual(code, 2)

    def test_done_criteria_must_be_met(self):
        self.ok("done", "mark", *EX, "D2", "--unmark")
        code, data = self.verify_json(*EX, "--layer", "5")
        self.assertEqual(code, 2)
        self.assertIn("критерий не выполнен", self.issues_text(data, 5))

    def test_option_without_objection_fails(self):
        opt = self.root / "projects" / "_example" / "options.md"
        t = opt.read_text(encoding="utf-8")
        i = t.index("## K004")
        j = t.index("## K005")
        opt.write_text(t[:i] + "## K004 Вернуть пробный период\n\nСуть: вернуть.\n\n" + t[j:], encoding="utf-8")
        code, data = self.verify_json(*EX, "--layer", "4")
        self.assertEqual(code, 2)
        self.assertIn("K004", self.issues_text(data, 4))

    def test_needs_three_options_and_leave_as_is(self):
        self.ok("conclusion", "set-status", *EX, "K003", "--status", "заменён", "--replaced-by", "K004")
        code, data = self.verify_json(*EX, "--layer", "4")
        txt = self.issues_text(data, 4)
        self.assertIn("не меньше трёх", txt)
        self.assertIn("оставить как есть", txt)

    def test_premortem_required(self):
        tp = self.root / "projects" / "_example" / "strategy" / "test-plan.md"
        tp.write_text("# План\n\nТест.\n", encoding="utf-8")
        code, data = self.verify_json(*EX, "--layer", "4")
        self.assertIn("почему провалится", self.issues_text(data, 4))

    def test_tampered_source_copy_fails_layer1(self):
        p = self.root / "projects" / "_example" / "sources" / "S001.txt"
        p.write_text(p.read_text(encoding="utf-8") + "лишнее\n", encoding="utf-8")
        code, data = self.verify_json(*EX, "--layer", "1")
        self.assertEqual(code, 2)
        self.assertIn("копия изменена", self.issues_text(data, 1))

    def test_unused_fact_fails_coverage_until_rejected(self):
        self.ok("claim", "add", *EX, "--type", "fact", "--source", "S002",
                "--quote", "Жалобы на качество каталога встречались реже", "--text", "Жалобы на каталог реже.")
        code, data = self.verify_json(*EX, "--layer", "3")
        self.assertEqual(code, 2)
        self.assertIn("не использовано", self.issues_text(data, 3))
        self.ok("claim", "reject", *EX, "C014", "--reason", "не про причину")
        self.assertEqual(self.run_cmd("verify", *EX, "--layer", "3")[0], 0)

    def test_rejected_ground_breaks_conclusion(self):
        out = self.ok("claim", "reject", *EX, "C005", "--reason", "тест")
        self.assertIn("K001", out)
        code, data = self.verify_json(*EX, "--layer", "3")
        self.assertEqual(code, 2)
        self.assertIn("со статусом «отброшено»", self.issues_text(data, 3))


class PageLoopholeTests(Env):
    def page(self):
        return self.root / "projects" / "_example" / "page.md"

    def append(self, text):
        p = self.page()
        p.write_text(p.read_text(encoding="utf-8").rstrip("\n") + "\n\n" + text + "\n", encoding="utf-8")

    def test_number_in_last_paragraph_is_caught(self):
        self.append("Дополнительно: отток вырос на 37,5%.")
        code, data = self.verify_json(*EX, "--layer", "5")
        txt = self.issues_text(data, 5)
        self.assertEqual(code, 2)
        self.assertIn("37,5", txt)
        self.assertIn("нет блока с путями", txt)

    def test_filler_in_last_paragraph_is_caught(self):
        self.append("В современных реалиях важно отметить ключевые драйверы роста.")
        code, data = self.verify_json(*EX, "--layer", "5")
        txt = self.issues_text(data, 5)
        self.assertIn("в современных реалиях", txt)
        self.assertIn("важно отметить", txt)
        self.assertIn("ключевые драйверы", txt)

    def test_filler_after_path_block_tolerates_yo_and_case(self):
        p = self.page()
        p.write_text(p.read_text(encoding="utf-8").rstrip("\n") + "\nВ СОВРЕМЕННЫХ РЕАЛИЯХ всё ясно.\n", encoding="utf-8")
        code, data = self.verify_json(*EX, "--layer", "5")
        self.assertIn("в современных реалиях", self.issues_text(data, 5))

    def test_path_line_with_number_in_name_not_flagged(self):
        self.write(self.root / "projects" / "_example" / "strategy" / "plan-2027-v3.md", "# план\n")
        p = self.page()
        p.write_text(p.read_text(encoding="utf-8").rstrip("\n") + "\n- Подпись: strategy/plan-2027-v3.md\n", encoding="utf-8")
        code, out = self.run_cmd("verify", *EX, "--layer", "5")
        self.assertEqual(code, 0, out)

    def test_nonexistent_path_line_is_not_exempt(self):
        p = self.page()
        p.write_text(p.read_text(encoding="utf-8").rstrip("\n") + "\n- strategy/net-777.md\n", encoding="utf-8")
        code, data = self.verify_json(*EX, "--layer", "5")
        txt = self.issues_text(data, 5)
        self.assertIn("несуществующий файл", txt)
        self.assertIn("777", txt)

    def test_all_findings_reported_together(self):
        self.set_config("style.json", {"max_page_lines": 5, "banned_phrases": ["важно отметить"]})
        self.append("Важно отметить: отток 37,5%.")
        self.ok("done", "mark", *EX, "D1", "--unmark")
        code, data = self.verify_json(*EX, "--layer", "5")
        txt = self.issues_text(data, 5)
        for part in ("длиннее порога", "важно отметить", "37,5", "нет блока с путями", "критерий не выполнен"):
            self.assertIn(part, txt)

    def test_default_style_has_filler_phrases(self):
        from lib.common import load_config
        phrases = load_config(str(self.root))["style"]["banned_phrases"]
        for ph in ("в современных реалиях", "важно отметить", "ключевые драйверы"):
            self.assertIn(ph, phrases)


class FiveGapsTests(Env):
    def pdir(self):
        return self.root / "projects" / "_example"

    # 1. статус рычага
    def test_lever_set_status_and_retire(self):
        self.ok("impact", *EX, "C002", "--mark")
        self.assertIn("под-вопросом", self.ok("lever", "list", *EX))
        self.ok("lever", "set-status", *EX, "L001", "--status", "действует", "--reason", "перепроверил")
        self.assertIn("[действует]", self.ok("lever", "list", *EX))
        self.ok("lever", "set-status", *EX, "L001", "--status", "снят", "--reason", "не будем делать")
        journal = (self.pdir() / "journal.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(json.loads(journal[-1])["cmd"], "lever set-status")
        code, data = self.verify_json(*EX, "--layer", "5")
        txt = self.issues_text(data, 5)
        self.assertEqual(code, 2)
        self.assertIn("числа «2» нет в реестре", txt)
        code, out = self.run_cmd("lever", "set-status", *EX, "L009", "--status", "снят")
        self.assertEqual(code, 1)

    def test_retired_lever_ignored_by_coverage(self):
        self.ok("claim", "add", *EX, "--type", "fact", "--source", "S002",
                "--quote", "Жалобы на качество каталога встречались реже", "--text", "Жалобы на каталог реже.")
        self.ok("lever", "add", *EX, "--metric", "m", "--where", "w", "--cause", "c", "--action", "a",
                "--effect-low", "1", "--effect-base", "2", "--effect-high", "3", "--check", "x", "--rests-on", "C014")
        self.assertEqual(self.run_cmd("verify", *EX, "--layer", "3")[0], 0)
        self.ok("lever", "set-status", *EX, "L002", "--status", "снят")
        code, data = self.verify_json(*EX, "--layer", "3")
        self.assertEqual(code, 2)
        self.assertIn("не использовано", self.issues_text(data, 3))

    # 2. решение: снять пометку
    def test_decision_clear_doubt_needs_note(self):
        self.ok("impact", *EX, "C002", "--mark")
        code, out = self.run_cmd("decision", "set-status", *EX, "DR-001", "--status", "принято")
        self.assertEqual(code, 1)
        self.assertIn("--note", out)
        self.ok("decision", "set-status", *EX, "DR-001", "--status", "принято", "--note", "пересчитал тест")
        text = (self.pdir() / "decisions" / "DR-001.md").read_text(encoding="utf-8")
        self.assertNotIn("doubt:", text)
        self.assertIn("status: принято", text)
        self.assertIn("recheck_note: пересчитал тест", text)
        last = json.loads((self.pdir() / "journal.jsonl").read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(last["detail"]["note"], "пересчитал тест")
        self.assertNotIn("DR-001 под вопросом", self.ok("sweep", *EX))

    def test_decision_replace_without_note(self):
        self.ok("impact", *EX, "C002", "--mark")
        self.ok("decision", "set-status", *EX, "DR-001", "--status", "заменено")

    # 3. медиа
    def test_media_source(self):
        p = self.new_project("m")
        (p / "materials" / "call.mp3").write_bytes(b"\x00\x01fake")
        code, out = self.run_cmd("source", "add", "-p", "m", "--file", "materials/call.mp3")
        self.assertEqual(code, 1)
        self.assertIn("--text-file", out)
        self.write(p / "materials" / "call.txt", "Клиент сказал: уйду, если не вернут пробный период.")
        self.ok("source", "add", "-p", "m", "--file", "materials/call.mp3", "--text-file", "materials/call.txt",
                "--published", "2026-10-01")
        meta = json.loads((p / "sources" / "S001.meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["kind"], "расшифровка")
        self.assertEqual(meta["path"], "materials/call.mp3")
        self.assertEqual(meta["media_sha256"], sha(p / "materials" / "call.mp3"))
        self.assertIn("уйду", (p / "sources" / "S001.txt").read_text(encoding="utf-8"))
        self.ok("claim", "add", "-p", "m", "--type", "fact", "--source", "S001", "--text", "Клиент грозит уйти",
                "--quote", "уйду, если не вернут пробный период")
        code, out = self.run_cmd("verify", "-p", "m", "--layer", "1")
        self.assertEqual(code, 0, out)
        self.assertIn("не может проверить", out)
        self.assertEqual(self.run_cmd("verify", "-p", "m", "--layer", "2")[0], 0)
        (p / "materials" / "call.mp3").write_bytes(b"changed")
        code, out = self.run_cmd("verify", "-p", "m", "--layer", "1")
        self.assertEqual(code, 2)

    def test_text_file_with_plain_file_refused(self):
        p = self.new_project("m")
        self.write(p / "materials" / "a.txt", "текст")
        self.write(p / "materials" / "b.txt", "другое")
        code, out = self.run_cmd("source", "add", "-p", "m", "--file", "materials/a.txt", "--text-file", "materials/b.txt")
        self.assertEqual(code, 1)

    # 4. закрыть направление
    def test_close_direction_required(self):
        opt = self.pdir() / "options.md"
        t = opt.read_text(encoding="utf-8")
        opt.write_text(t[:t.index("Закрыть направление")], encoding="utf-8")
        code, data = self.verify_json(*EX, "--layer", "4")
        self.assertEqual(code, 2)
        self.assertIn("закрыть направление", self.issues_text(data, 4))
        opt.write_text(t.replace("Закрыть направление: не рассматриваем, потому что", "- ЗАКРЫТЬ направление: не рассматриваем, потому что"), encoding="utf-8")
        self.assertEqual(self.run_cmd("verify", *EX, "--layer", "4")[0], 0)

    def test_close_direction_as_option(self):
        opt = self.pdir() / "options.md"
        t = opt.read_text(encoding="utf-8")
        opt.write_text(t[:t.index("Закрыть направление")] + "\n## K009 Закрыть направление\nВозражение: уйдём с рынка.\n", encoding="utf-8")
        self.ok("conclusion", "add", *EX, "--kind", "option", "--text", "Закрыть направление подписки.", "--rests-on", "C004")
        code, out = self.run_cmd("verify", *EX, "--layer", "4")
        self.assertEqual(code, 0, out)

    # 5. числа рычагов
    def test_lever_text_numbers_not_accepted(self):
        self.ok("claim", "add", *EX, "--type", "fact", "--source", "S002",
                "--quote", "Жалобы на качество каталога встречались реже", "--text", "Жалобы на каталог реже.")
        self.ok("claim", "reject", *EX, "C014", "--reason", "для теста")
        self.ok("lever", "add", *EX, "--metric", "m", "--where", "в 88 городах", "--cause", "причина 99", "--action", "a",
                "--effect-low", "1", "--effect-base", "2", "--effect-high", "3", "--check", "через 56 дней", "--rests-on", "C002")
        p = self.pdir() / "page.md"
        t = p.read_text(encoding="utf-8")
        p.write_text(t.replace("Рынок в среднем", "Города 88, причина 99, срок 56. Рынок в среднем"), encoding="utf-8")
        code, data = self.verify_json(*EX, "--layer", "5")
        txt = self.issues_text(data, 5)
        for n in ("88", "99", "56"):
            self.assertIn("числа «%s» нет в реестре" % n, txt)

    def test_effect_line_needs_word_estimate(self):
        p = self.pdir() / "page.md"
        t = p.read_text(encoding="utf-8")
        p.write_text(t.replace("Оценка эффекта", "Эффект"), encoding="utf-8")
        code, data = self.verify_json(*EX, "--layer", "5")
        self.assertEqual(code, 2)
        self.assertIn("без слова «оценка»", self.issues_text(data, 5))
        p.write_text(t.replace("Оценка эффекта", "ОЦЕНКА эффекта"), encoding="utf-8")
        self.assertEqual(self.run_cmd("verify", *EX, "--layer", "5")[0], 0)

    def test_effect_numbers_still_accepted_when_active_only(self):
        self.ok("lever", "set-status", *EX, "L001", "--status", "под-вопросом")
        code, data = self.verify_json(*EX, "--layer", "5")
        self.assertEqual(code, 2)
        self.assertIn("нет в реестре", self.issues_text(data, 5))


class PlanClaimTests(Env):
    def pdir(self):
        return self.root / "projects" / "_example"

    def add_plan(self, text, number, *extra):
        return self.run_cmd("claim", "add", *EX, "--type", "plan", "--text", text, "--number", number, *extra)

    def test_plan_claim_needs_no_source_and_is_labelled(self):
        code, out = self.add_plan("Размер группы: 500 человек", "500")
        self.assertEqual(code, 0, out)
        self.assertIn("наш выбор, не доказательство", out)
        row = json.loads((self.pdir() / "ledger" / "claims.jsonl").read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(row["type"], "plan")
        self.assertIn("наш выбор, не доказательство", row["flags"])
        code, out = self.add_plan("Размер группы: 600", "600", "--source", "S001")
        self.assertEqual(code, 1)

    def test_page_accepts_plan_number_and_rejects_without(self):
        page = self.pdir() / "page.md"
        t = page.read_text(encoding="utf-8")
        page.write_text(t.replace("Рынок в среднем", "Группа 500 человек. Рынок в среднем"), encoding="utf-8")
        code, data = self.verify_json(*EX, "--layer", "5")
        self.assertIn("числа «500» нет в реестре", self.issues_text(data, 5))
        self.add_plan("Размер группы: 500 человек", "500")
        self.assertEqual(self.run_cmd("verify", *EX, "--layer", "5")[0], 0)
        self.ok("claim", "reject", *EX, "C014", "--reason", "передумали")
        code, data = self.verify_json(*EX, "--layer", "5")
        self.assertEqual(code, 2)

    def test_example_plan_numbers_exact(self):
        text = (self.pdir() / "page.md").read_text(encoding="utf-8")
        self.assertIn("тест 4 недели", text)
        self.assertIn("если рост меньше 1 процентного пункта", text)
        self.assertEqual(self.run_cmd("verify", *EX)[0], 0)

    def test_decision_numbers_accepted_on_page(self):
        self.ok("decision", "add", *EX, "--title", "Т", "--owner", "о", "--metric", "Доля 23 процента",
                "--review-date", "2027-05-01", "--review-if", "если упадёт ниже 41 п.п.", "--rests-on", "K001")
        page = self.pdir() / "page.md"
        t = page.read_text(encoding="utf-8")
        page.write_text(t.replace("Рынок в среднем", "Порог 41, доля 23. Рынок в среднем"), encoding="utf-8")
        self.assertEqual(self.run_cmd("verify", *EX, "--layer", "5")[0], 0)
        self.ok("decision", "set-status", *EX, "DR-002", "--status", "заменено")
        code, data = self.verify_json(*EX, "--layer", "5")
        self.assertEqual(code, 2)
        self.assertIn("41", self.issues_text(data, 5))

    def test_finding_or_cause_only_on_plan_fails_layer3(self):
        out = self.ok("conclusion", "add", *EX, "--kind", "cause", "--text", "Причина в сроке теста", "--rests-on", "C012")
        self.assertIn("Внимание", out)
        code, data = self.verify_json(*EX, "--layer", "3")
        self.assertEqual(code, 2)
        self.assertIn("только на параметрах плана", self.issues_text(data, 3))

    def test_recommendation_on_plan_with_facts_is_fine(self):
        self.ok("conclusion", "add", *EX, "--kind", "finding", "--text", "Снова находка", "--rests-on", "C012,C001")
        self.assertEqual(self.run_cmd("verify", *EX, "--layer", "3")[0], 0)

    def test_coverage_does_not_count_plan(self):
        out = self.ok("verify", *EX, "--layer", "3")
        self.assertIn("использовано 7 из 8, отброшено 1", out)

    def test_status_and_claim_list_show_plan_separately(self):
        out = self.ok("status", *EX)
        self.assertIn("Параметры плана (наш выбор, не доказательства): 2.", out)
        self.assertNotIn("plan 2", out)
        lst = self.ok("claim", "list", *EX)
        self.assertIn("C001 [факт, слой 1, действует]", lst)
        self.assertIn("C012 [параметр плана, действует]", lst)
        self.assertIn("[расчёт, слой 1, действует]", lst)


KB_TEXT = ("Оператор «Вымышленная связь» в стране Нигде после повышения цены на 12% потерял 3% абонентов за квартал.\n"
           "Бесплатный пробный период в 14 дней снижал отток в сервисах подписки.\n"
           "Банк-пример сообщил, что персональные напоминания перед списанием уменьшили отмены на 20%.\n")


class KbBase(Env):
    def setUp(self):
        Env.setUp(self)
        self.src = self.root / "kbtmp" / "a.txt"
        self.write(self.src, KB_TEXT)

    def kb_source(self, published="2026-05-01"):
        return self.ok("kb", "source", "add", "--url", "https://example.org/kb", "--text-file", str(self.src),
                       "--published", published)

    def kb_add(self, rule, quote, layer="4", **kw):
        args = ["kb", "add", "--rule", rule, "--applies-when", "когда есть подписка", "--theme", kw.get("theme", "удержание"),
                "--layer", layer, "--source", "KS001", "--quote", quote, "--strength", kw.get("strength", "данные-компании"),
                "--place", "страна Нигде, Вымышленная связь"]
        if kw.get("number"):
            args += ["--number", kw["number"]]
        if kw.get("tags"):
            args += ["--tags", kw["tags"]]
        return self.run_cmd(*args)

    def make_kb(self):
        self.kb_source()
        self.assertEqual(self.kb_add("Бесплатный пробный период в 14 дней снижает отток",
                                     "Бесплатный пробный период в 14 дней снижал отток в сервисах подписки", "4",
                                     number="14", tags="пробный период")[0], 0)
        self.assertEqual(self.kb_add("Повышение цены на 12% дало потерю 3% абонентов",
                                     "после повышения цены на 12% потерял 3% абонентов за квартал", "3",
                                     number="12%", theme="цена", strength="независимый-замер")[0], 0)
        self.assertEqual(self.kb_add("Напоминание перед списанием уменьшает отмены",
                                     "персональные напоминания перед списанием уменьшили отмены на 20%", "5",
                                     number="20%", strength="мнение")[0], 0)
        self.ok("kb", "add", "--rule", "В прошлой задаче причиной просадки оказалась цена", "--applies-when",
                "просадка после смены цены", "--theme", "цена", "--layer", "4", "--kind", "урок")

    def records(self):
        return [json.loads(l) for l in (self.root / "knowledge" / "records.jsonl").read_text(encoding="utf-8").splitlines()]


class KbCommandTests(KbBase):
    def test_source_add(self):
        out = self.kb_source()
        self.assertIn("KS001", out)
        meta = json.loads((self.root / "knowledge" / "sources" / "KS001.meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["sha256"], sha(self.root / "knowledge" / "sources" / "KS001.txt"))
        for k in ("url", "published", "accessed", "title"):
            self.assertIn(k, meta)
        code, out = self.run_cmd("kb", "source", "add", "--url", "https://example.org/kb", "--text-file", str(self.src))
        self.assertEqual(code, 1)
        self.assertIn("уже сохранён", out)
        code, out = self.run_cmd("kb", "source", "add", "--url", "https://example.org/x")
        self.assertEqual(code, 1)

    def test_add_checks_quote_and_layer(self):
        self.kb_source()
        code, out = self.kb_add("Правило", "ПОСЛЕ  повышения цены на 12% потерял 3% абонентов")
        self.assertEqual(code, 0, out)
        code, out = self.kb_add("Другое", "цены не менялись вообще")
        self.assertEqual(code, 1)
        self.assertIn("не найдена", out)
        code, out = self.kb_add("Третье", "потерял 3% абонентов", layer="1")
        self.assertEqual(code, 1)
        self.assertIn("от 2 до 5", out)
        code, out = self.kb_add("Четвёртое", "потерял 3% абонентов", number="99%")
        self.assertEqual(code, 1)
        self.assertIn("не встречается в цитате", out)
        code, out = self.run_cmd("kb", "add", "--rule", "а", "--applies-when", "б", "--theme", "т", "--source", "KS001",
                                 "--quote", "потерял 3% абонентов", "--strength", "мнение", "--place", "м")
        self.assertEqual(code, 1)
        self.assertEqual(self.records()[0]["id"], "B001")
        self.assertIn("B001", (self.root / "knowledge" / "INDEX.md").read_text(encoding="utf-8"))

    def test_add_without_source_rejected_but_lesson_ok(self):
        code, out = self.run_cmd("kb", "add", "--rule", "а", "--applies-when", "б", "--theme", "т", "--layer", "3",
                                 "--strength", "мнение", "--place", "м")
        self.assertEqual(code, 1)
        self.assertIn("без источника", out)
        out = self.ok("kb", "add", "--rule", "Урок", "--applies-when", "всегда", "--theme", "т", "--layer", "4", "--kind", "урок")
        self.assertIn("только для гипотезы", out)
        r = self.records()[0]
        self.assertEqual((r["kind"], r["source"]), ("урок", None))

    def test_import_verifies_and_writes_rejected(self):
        self.write(self.root / "imp" / "txt" / "s1.txt", KB_TEXT)
        good = {"rule": "Пробный период снижает отток", "applies_when": "подписка", "themes": ["удержание"], "tags": ["пробный"],
                "place": "страна Нигде", "date_published": "2026-05-01", "url": "https://example.org/kb", "title": "Т",
                "source_file": "s1.txt", "quote": "пробный период в 14 дней снижал отток", "number": "14",
                "strength": "данные-компании", "kind": "правило", "layer": 4}
        bad_quote = dict(good, rule="Другое", quote="этого в тексте нет")
        no_layer = {k: v for k, v in dict(good, rule="Третье").items() if k != "layer"}
        no_file = dict(good, rule="Четвёртое", source_file="нет.txt")
        f = self.root / "imp" / "r.jsonl"
        f.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in (good, bad_quote, no_layer, no_file)) + "\n", encoding="utf-8")
        code, out = self.run_cmd("kb", "import", str(f), "--sources-dir", str(self.root / "imp" / "txt"))
        self.assertEqual(code, 2)
        self.assertIn("Принято: 1. Отклонено: 3.", out)
        self.assertIn("цитата не найдена", out)
        self.assertIn("layer", out)
        self.assertIn("нет.txt", out)
        rej = (self.root / "knowledge" / "rejected.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(rej), 3)
        self.assertEqual(len(self.records()), 1)
        self.assertIn("B001", (self.root / "knowledge" / "INDEX.md").read_text(encoding="utf-8"))
        self.assertEqual(len(list((self.root / "knowledge" / "sources").glob("KS*.txt"))), 1)

    def test_search_tolerance_synonyms_ranking(self):
        self.make_kb()
        out = self.ok("kb", "search", "оттока подписок")
        self.assertIn("B001", out)
        self.assertIn("Слой 4 (отрасль в мире)", out)
        self.assertIn("действует", out)
        self.assertIn("B001", self.ok("kb", "search", "ОТТОК"))
        self.assertIn("B001", self.ok("kb", "search", "churn"))  # синоним
        self.assertIn("B002", self.ok("kb", "search", "цены повышение"))
        self.assertIn("Ничего не найдено", self.ok("kb", "search", "космос"))
        # слой важнее числа совпадений: B002 (слой 3) раньше B001 (слой 4), хотя B001 совпал по двум словам
        out = self.ok("kb", "search", "пробный отток цена")
        self.assertLess(out.index("B002"), out.index("B001"))
        self.assertIn("B002", self.ok("kb", "search", "цены", "--theme", "цена"))
        self.assertNotIn("B001", self.ok("kb", "search", "отток", "--theme", "цена"))
        self.assertIn("B001", self.ok("kb", "search", "отток", "--tag", "пробный период"))
        self.assertEqual(sum(1 for l in self.ok("kb", "search", "отток", "--limit", "1").splitlines() if l.startswith("B0")), 1)

    def test_show_link_related_list(self):
        self.make_kb()
        self.assertIn("Это ориентир, а не факт", self.ok("kb", "show", "B001"))
        self.ok("kb", "link", "B001", "B003", "--note", "про удержание")
        out = self.ok("kb", "search", "", "--related", "B001")
        self.assertIn("B003", out)
        self.assertNotIn("B002", out)
        self.assertIn("B001", self.ok("kb", "show", "B003"))
        self.assertIn("B002", self.ok("kb", "list", "--theme", "цена"))
        code, out = self.run_cmd("kb", "show", "B999")
        self.assertEqual(code, 1)

    def test_retire_replace_never_delete(self):
        self.make_kb()
        self.ok("kb", "retire", "B003", "--reason", "источник опровергнут")
        self.ok("kb", "replace", "B001", "--by", "B002")
        recs = {r["id"]: r for r in self.records()}
        self.assertEqual(len(recs), 4)
        self.assertEqual(recs["B003"]["status"], "отозвана")
        self.assertEqual(recs["B003"]["status_date"], self.TODAY)
        self.assertEqual(recs["B003"]["status_reason"], "источник опровергнут")
        self.assertEqual((recs["B001"]["status"], recs["B001"]["replaced_by"]), ("заменена", "B002"))
        idx = (self.root / "knowledge" / "INDEX.md").read_text(encoding="utf-8")
        self.assertNotIn("B003", idx)
        self.assertNotIn("B001 |", idx)
        self.assertIn("B002", idx)
        self.assertIn("Ничего не найдено", self.ok("kb", "search", "напоминание"))
        self.assertIn("B003", self.ok("kb", "search", "напоминание", "--all"))
        self.assertEqual(self.run_cmd("kb", "retire", "B003", "--reason", "")[0], 1)
        self.assertEqual(self.run_cmd("kb", "replace", "B002", "--by", "B003")[0], 1)

    def test_stale_by_age_and_missing_source(self):
        self.make_kb()
        self.assertIn("Устаревших записей нет", self.ok("kb", "stale"))
        out = self.ok("kb", "stale", today="2030-01-01")
        self.assertIn("B001", out)
        self.assertIn("старше порога", out)
        self.assertIn("B002", self.ok("kb", "list", "--stale", today="2030-01-01"))
        (self.root / "knowledge" / "sources" / "KS001.txt").unlink()
        self.assertIn("нет файла источника", self.ok("kb", "stale"))

    def test_index_command_and_grouping(self):
        self.make_kb()
        (self.root / "knowledge" / "INDEX.md").unlink()
        self.ok("kb", "index")
        idx = (self.root / "knowledge" / "INDEX.md").read_text(encoding="utf-8")
        self.assertIn("## удержание", idx)
        self.assertIn("## цена", idx)
        self.assertIn("слой 3", idx)
        self.assertNotIn("Записей пока нет", idx)

    def test_shipped_knowledge_is_empty(self):
        self.assertTrue((ROOT / "knowledge" / "README.md").exists())
        self.assertTrue((ROOT / "knowledge" / "map" / "README.md").exists())
        self.assertIn("README.md", [p.name for p in (ROOT / "knowledge" / "map").iterdir()])
        self.assertEqual(len(json.loads((ROOT / "config" / "synonyms.json").read_text(encoding="utf-8"))["groups"]), 30)


class BenchmarkTests(KbBase):
    def setUp(self):
        KbBase.setUp(self)
        self.make_kb()

    def bench(self, kb="B002", text="Конкуренты теряли абонентов после повышения цены", number=None):
        args = ["claim", "add", *EX, "--type", "benchmark", "--kb", kb, "--text", text]
        if number:
            args += ["--number", number]
        return self.run_cmd(*args)

    def test_benchmark_needs_active_record(self):
        code, out = self.run_cmd("claim", "add", *EX, "--type", "benchmark", "--text", "т")
        self.assertEqual(code, 1)
        self.assertIn("--kb", out)
        code, out = self.bench("B999")
        self.assertEqual(code, 1)
        self.ok("kb", "retire", "B002", "--reason", "тест")
        code, out = self.bench("B002")
        self.assertEqual(code, 1)
        self.assertIn("не действует", out)
        code, out = self.bench("B001", number="77")
        self.assertEqual(code, 1)
        code, out = self.bench("B001", number="14")
        self.assertEqual(code, 0, out)
        self.assertIn("ориентир", out)

    def test_benchmark_cannot_ground_finding_or_cause_alone(self):
        self.bench()
        out = self.ok("conclusion", "add", *EX, "--kind", "finding", "--text", "Цена виновата", "--rests-on", "C014")
        self.assertIn("Внимание", out)
        code, data = self.verify_json(*EX, "--layer", "3")
        self.assertEqual(code, 2)
        self.assertIn("только на ориентирах", self.issues_text(data, 3))

    def test_recommendation_and_option_may_use_benchmark_with_fact(self):
        self.bench()
        self.ok("conclusion", "add", *EX, "--kind", "recommendation", "--text", "Пробуем", "--rests-on", "C014,C002")
        self.ok("conclusion", "add", *EX, "--kind", "option", "--text", "Ещё вариант", "--rests-on", "C014,C005")
        self.assertEqual(self.run_cmd("verify", *EX, "--layer", "3")[0], 0)
        self.ok("conclusion", "add", *EX, "--kind", "recommendation", "--text", "Только ориентир", "--rests-on", "C014")
        code, data = self.verify_json(*EX, "--layer", "3")
        self.assertIn("без единого факта", self.issues_text(data, 3))
        self.assertIn("без факта слоя 1 или 2", self.issues_text(data, 3))

    def test_lesson_supports_only_hypothesis(self):
        out = self.ok("claim", "add", *EX, "--type", "benchmark", "--kb", "B004", "--text", "Раньше виновата была цена")
        code, out = self.run_cmd("conclusion", "add", *EX, "--kind", "option", "--text", "х", "--rests-on", "C014,C002")
        self.assertEqual(code, 1)
        self.assertIn("урок", out)
        self.ok("claim", "add", *EX, "--type", "hypothesis", "--kb", "B004", "--text", "Возможно, снова цена")
        code, out = self.run_cmd("claim", "add", *EX, "--type", "fact", "--kb", "B001", "--text", "х")
        self.assertEqual(code, 1)

    def test_page_number_from_benchmark_needs_word(self):
        self.bench(number="12%", text="Конкуренты потеряли 3% абонентов после повышения цены на 12%")
        page = self.root / "projects" / "_example" / "page.md"
        t = page.read_text(encoding="utf-8")
        page.write_text(t.replace("## Три пути", "Падение у соседей 12%.\n\n## Три пути"), encoding="utf-8")
        code, data = self.verify_json(*EX, "--layer", "5")
        self.assertEqual(code, 2)
        self.assertIn("без слова «ориентир»", self.issues_text(data, 5))
        page.write_text(t.replace("## Три пути", "Ориентир: падение у соседей 12%.\n\n## Три пути"), encoding="utf-8")
        self.assertEqual(self.run_cmd("verify", *EX, "--layer", "5")[0], 0)

    def test_claim_on_retired_record_reported_in_layer3_and_sweep(self):
        self.bench()
        self.ok("conclusion", "add", *EX, "--kind", "option", "--text", "Вариант на ориентире", "--rests-on", "C014,C005")
        self.ok("kb", "retire", "B002", "--reason", "устарела")
        code, data = self.verify_json(*EX, "--layer", "3")
        self.assertEqual(code, 2)
        self.assertIn("со статусом «отозвана»", self.issues_text(data, 3))
        self.assertIn("impact B002", json.dumps(data, ensure_ascii=False))
        out = self.ok("sweep", *EX)
        self.assertIn("C014 опирается на запись B002", out)

    def test_impact_accepts_kb_id(self):
        self.bench()
        self.ok("conclusion", "add", *EX, "--kind", "option", "--text", "Вариант на ориентире", "--rests-on", "C014,C005")
        out = self.ok("impact", *EX, "B002")
        self.assertIn("запись базы знаний", out)
        self.assertIn("C014", out)
        self.assertIn("K009", out)
        out = self.ok("impact", *EX, "B002", "--mark")
        self.assertIn("K009", out)
        self.assertIn("K009 [option, под-вопросом", self.ok("conclusion", "list", *EX))

    def test_status_counts(self):
        self.bench()
        out = self.ok("status", *EX)
        self.assertIn("База знаний: действующих записей 4. Ориентиров в проекте: 1.", out)

    def test_benchmark_not_counted_in_coverage(self):
        self.bench()
        self.assertIn("использовано 7 из 8, отброшено 1", self.ok("verify", *EX, "--layer", "3"))


class ProximityLayerTests(KbBase):
    def test_source_layer_rules(self):
        p = self.new_project("l")
        self.write(p / "materials" / "t.txt", "Текст страницы.")
        code, out = self.run_cmd("source", "add", "-p", "l", "--url", "https://example.org/x", "--text-file", "materials/t.txt",
                                 "--published", "2026-10-01")
        self.assertEqual(code, 1)
        for part in ("--layer", "данные самого продукта", "смежные отрасли"):
            self.assertIn(part, out)
        code, out = self.run_cmd("source", "add", "-p", "l", "--url", "https://example.org/x", "--text-file", "materials/t.txt",
                                 "--published", "2026-10-01", "--layer", "9")
        self.assertEqual(code, 1)
        self.ok("source", "add", "-p", "l", "--url", "https://example.org/x", "--text-file", "materials/t.txt",
                "--published", "2026-10-01", "--layer", "4")
        self.write(p / "materials" / "own.txt", "Свои данные.")
        self.ok("source", "add", "-p", "l", "--file", "materials/own.txt")
        metas = [json.loads((p / "sources" / ("S00%d.meta.json" % i)).read_text(encoding="utf-8")) for i in (1, 2)]
        self.assertEqual([m["layer"] for m in metas], [4, 1])
        self.ok("source", "set-layer", "-p", "l", "S001", "--layer", "3")
        self.assertIn("слой 3", self.ok("source", "list", "-p", "l"))

    def test_claims_inherit_layers(self):
        out = self.ok("claim", "list", *EX)
        self.assertIn("C001 [факт, слой 1, действует]", out)
        self.assertIn("C004 [факт, слой 3, действует]", out)
        self.assertIn("C005 [расчёт, слой 1, действует]", out)
        for line in out.splitlines():
            if line.startswith(("C008", "C009", "C010", "C012")):
                self.assertNotIn("слой", line.split("]")[0])

    def test_calc_inherits_lowest_layer(self):
        p = self.new_project("c")
        self.write(p / "materials" / "a.csv", "x\n1\n")
        self.write(p / "materials" / "b.csv", "x\n2\n")
        self.write(p / "analysis" / "s.py", "import sys\nprint('Итог: %d' % len(sys.argv))\n")
        self.ok("source", "add", "-p", "c", "--file", "materials/a.csv", "--layer", "4")
        self.ok("calc", "run", "-p", "c", "s.py", "--inputs", "a.csv")
        m = json.loads((p / "sources" / "S002.meta.json").read_text(encoding="utf-8"))
        self.assertEqual(m["layer"], 4)
        self.ok("calc", "run", "-p", "c", "s.py", "--inputs", "a.csv,b.csv")
        m = json.loads((p / "sources" / "S003.meta.json").read_text(encoding="utf-8"))
        self.assertEqual(m["layer"], 1)

    def test_kb_layer_required_2_to_5(self):
        self.kb_source()
        for bad in ("1", "6"):
            code, out = self.kb_add("Правило", "потерял 3% абонентов", layer=bad)
            self.assertEqual(code, 1)
        self.assertEqual(self.kb_add("Правило", "потерял 3% абонентов", layer="5")[0], 0)

    def _project_with_layers(self):
        p = self.new_project("g")
        for n, layer in (("one", "1"), ("two", "2"), ("three", "3"), ("four", "4")):
            self.write(p / "materials" / (n + ".txt"), "Факт номер %s: показатель вырос." % n)
            self.ok("source", "add", "-p", "g", "--file", "materials/%s.txt" % n, "--layer", layer)
        for i, n in enumerate(("one", "two", "three", "four"), 1):
            self.ok("claim", "add", "-p", "g", "--type", "fact", "--text", "Факт %s" % n, "--source", "S00%d" % i,
                    "--quote", "Факт номер %s" % n)
        return p

    def test_cause_needs_layer_one(self):
        self._project_with_layers()
        self.ok("conclusion", "add", "-p", "g", "--kind", "cause", "--text", "Далёкая причина", "--rests-on", "C003,C004")
        code, data = self.verify_json("-p", "g", "--layer", "3")
        txt = self.issues_text(data, 3)
        self.assertIn("не опирается на данные самого продукта", txt)
        self.assertIn("слой 3", txt)
        self.ok("conclusion", "set-status", "-p", "g", "K001", "--status", "заменён")
        self.ok("conclusion", "add", "-p", "g", "--kind", "finding", "--text", "Данные компании", "--rests-on", "C002")
        code, data = self.verify_json("-p", "g", "--layer", "3")
        warns = " ".join(w["what"] for w in data["layers"]["3"]["warnings"])
        self.assertIn("слой 2", warns)
        self.assertNotIn("о продукте не опирается", self.issues_text(data, 3))
        self.ok("conclusion", "add", "-p", "g", "--kind", "cause", "--text", "Своя причина", "--rests-on", "C001,C003")
        code, data = self.verify_json("-p", "g", "--layer", "3")
        self.assertNotIn("K003", self.issues_text(data, 3))

    def test_recommendation_needs_layer_one_or_two_fact(self):
        self._project_with_layers()
        self.ok("conclusion", "add", "-p", "g", "--kind", "recommendation", "--text", "Далёкая", "--rests-on", "C003,C004")
        self.ok("conclusion", "add", "-p", "g", "--kind", "option", "--text", "Компания", "--rests-on", "C002")
        code, data = self.verify_json("-p", "g", "--layer", "3")
        txt = self.issues_text(data, 3)
        self.assertIn("(recommendation)", txt)
        self.assertNotIn("K002 (option)", txt)

    def test_conflict_rule(self):
        self._project_with_layers()
        self.ok("claim", "add", "-p", "g", "--type", "fact", "--text", "Наоборот", "--source", "S003",
                "--quote", "Факт номер three", "--contradicts", "C001")
        self.ok("conclusion", "add", "-p", "g", "--kind", "finding", "--text", "Через далёкий", "--rests-on", "C001,C005")
        self.ok("conclusion", "add", "-p", "g", "--kind", "finding", "--text", "Только далёкий", "--rests-on", "C005")
        code, data = self.verify_json("-p", "g", "--layer", "3")
        txt = self.issues_text(data, 3)
        self.assertIn("противоречит более близкому C001", txt)
        self.assertIn("K002", " ".join(i["where"] for i in data["layers"]["3"]["issues"] if "противоречит" in i["what"]))
        self.assertNotIn("K001", " ".join(i["where"] for i in data["layers"]["3"]["issues"] if "противоречит" in i["what"]))
        out = self.ok("sweep", "-p", "g")
        self.assertIn("Ближе C001 (слой 1), дальше C005 (слой 3)", out)

    def test_support_line_in_verify_and_status(self):
        out = self.ok("verify", *EX)
        self.assertIn("Опора: слой 1: 6, слой 2: 0, слой 3: 1, слой 4: 0, слой 5: 0", out)
        self.assertIn("Опора: слой 1: 6", self.ok("status", *EX))
        code, data = self.verify_json(*EX)
        self.assertEqual(data["support"]["1"], 6)

    def test_layer_3_number_needs_word_orientir(self):
        p = self.root / "projects" / "_example"
        self.write(p / "materials" / "rival.txt", "Конкуренты сообщили о падении 12% за квартал.")
        self.ok("source", "add", *EX, "--file", "materials/rival.txt", "--layer", "3", "--published", "2026-10-01")
        self.ok("claim", "add", *EX, "--type", "fact", "--source", "S005", "--quote", "падении 12%", "--number", "12%",
                "--text", "Конкуренты сообщили о падении 12% за квартал.")
        page = p / "page.md"
        t = page.read_text(encoding="utf-8")
        page.write_text(t.replace("## Три пути", "Падение у конкурентов 12%.\n\n## Три пути"), encoding="utf-8")
        code, data = self.verify_json(*EX, "--layer", "5")
        self.assertIn("без слова «ориентир»", self.issues_text(data, 5))
        page.write_text(t.replace("## Три пути", "Ориентир: падение у конкурентов 12%.\n\n## Три пути"), encoding="utf-8")
        self.assertEqual(self.run_cmd("verify", *EX, "--layer", "5")[0], 0)

    def test_source_without_layer_fails_layer1(self):
        m = self.root / "projects" / "_example" / "sources" / "S003.meta.json"
        d = json.loads(m.read_text(encoding="utf-8"))
        del d["layer"]
        m.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        code, data = self.verify_json(*EX, "--layer", "1")
        self.assertEqual(code, 2)
        self.assertIn("не указан слой близости", self.issues_text(data, 1))


class CalcTests(Env):
    def setUp(self):
        Env.setUp(self)
        self.p = self.new_project("c")
        self.write(self.p / "materials" / "in.csv", "a,b\n1,2\n3,4\n")
        self.write(self.p / "analysis" / "s.py",
                   "import csv, sys\nrows = list(csv.DictReader(open(sys.argv[1], encoding='utf-8')))\n"
                   "print('Сумма b: %d' % sum(int(r['b']) for r in rows))\n")

    def test_calc_run_and_fingerprint(self):
        out = self.ok("calc", "run", "-p", "c", "s.py", "--inputs", "in.csv")
        self.assertIn("S001", out)
        meta = json.loads((self.p / "sources" / "S001.meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["kind"], "расчёт")
        self.assertEqual(meta["script_sha256"], sha(self.p / "analysis" / "s.py"))
        self.assertEqual(meta["inputs"][0]["sha256"], sha(self.p / "materials" / "in.csv"))
        self.assertIn("Сумма b: 6", (self.p / "sources" / "S001.txt").read_text(encoding="utf-8"))
        self.ok("claim", "add", "-p", "c", "--type", "calc", "--source", "S001", "--quote", "Сумма b: 6",
                "--number", "6", "--text", "Сумма b равна 6.")
        self.assertEqual(self.run_cmd("verify", "-p", "c", "--layer", "1")[0], 0)
        self.write(self.p / "materials" / "in.csv", "a,b\n1,2\n3,5\n")
        code, out = self.run_cmd("verify", "-p", "c", "--layer", "1")
        self.assertEqual(code, 2)
        self.assertIn("изменён", out)

    def test_calc_errors(self):
        self.write(self.p / "analysis" / "bad.py", "raise SystemExit(3)\n")
        code, out = self.run_cmd("calc", "run", "-p", "c", "bad.py")
        self.assertEqual(code, 1)
        self.assertIn("завершился с ошибкой", out)
        self.write(self.p / "materials" / "outside.py", "print(1)\n")
        code, out = self.run_cmd("calc", "run", "-p", "c", "materials/outside.py")
        self.assertEqual(code, 1)

    def test_calc_claim_needs_calc_source(self):
        self.write(self.p / "materials" / "a.txt", "Текст 5.")
        self.ok("source", "add", "-p", "c", "--file", "materials/a.txt", "--published", "2026-10-01")
        code, out = self.run_cmd("claim", "add", "-p", "c", "--type", "calc", "--source", "S001", "--number", "5", "--text", "т")
        self.assertEqual(code, 1)


class StageTests(Env):
    def test_gate_blocks_then_passes(self):
        p = self.new_project("g")
        code, out = self.run_cmd("stage", "next", "-p", "g")
        self.assertEqual(code, 2)
        self.assertIn("brief.md", out)
        self.assertIn("Как исправить", out)
        self.write(p / "brief.md", "# Постановка\n\nВопрос: упало. Дата: 1 июля. Менялось: цена.\n")
        code, out = self.run_cmd("stage", "next", "-p", "g")
        self.assertEqual(code, 2)
        self.assertIn("требования", out)
        self.ok("req", "add", "-p", "g", "--text", "Назвать причину", "--quote", "Почему упало")
        out = self.ok("stage", "next", "-p", "g")
        self.assertIn("этап 2", out)
        self.assertIn("Остановка", out)
        code, out = self.run_cmd("stage", "next", "-p", "g")
        self.assertEqual(code, 2)
        self.assertIn("бюджет", out)
        self.ok("done", "add", "-p", "g", "--text", "Названа причина")
        self.ok("done", "budget", "-p", "g", "--usd", "3")
        self.ok("stage", "next", "-p", "g")
        self.assertIn("Этап 3 из 8", self.ok("status", "-p", "g"))
        self.assertIn("ТЕКУЩИЙ", self.ok("stage", "show", "-p", "g"))

    def test_new_project_starts_at_stage_one(self):
        self.new_project("w")
        self.assertIn("Этап 1 из 8", self.ok("status", "-p", "w"))
        code, out = self.run_cmd("gate", "-p", "w")
        self.assertEqual(code, 2)

    def test_status_content(self):
        out = self.ok("status", *EX)
        for part in ("Этап 8 из 8", "Открытые вопросы", "Следующий шаг", "Потрачено: 1.30 USD (оценка)",
                     "Утверждения:", "Выводы:", "Пора пересмотреть"):
            self.assertIn(part, out)

    def test_status_review_due(self):
        out = self.ok("status", *EX, today="2027-03-10")
        self.assertIn("просрочен", out)

    def test_project_autoselect(self):
        self.assertIn("Проект: _example", self.ok("status"))
        self.new_project("a")
        self.assertIn("Проект: a", self.ok("status"))
        self.new_project("b")
        code, out = self.run_cmd("status")
        self.assertEqual(code, 0)  # начало сессии не должно обрываться ошибкой: показываем все задачи
        self.assertIn("Задач несколько", out)
        code, out = self.run_cmd("verify")  # остальные команды по-прежнему требуют имя задачи
        self.assertEqual(code, 1)
        self.assertIn("Укажите", out)

    def test_questions_max_three(self):
        self.new_project("qq")
        for i in range(3):
            self.ok("question", "add", "-p", "qq", "--text", "в%d" % i, "--if-yes", "да", "--if-no", "нет")
        code, out = self.run_cmd("question", "add", "-p", "qq", "--text", "в4", "--if-yes", "да", "--if-no", "нет")
        self.assertEqual(code, 1)
        self.assertIn("три", out)
        self.ok("question", "close", "-p", "qq", "1")
        self.assertIn("в1", self.ok("status", "-p", "qq"))


class ImpactSweepTests(Env):
    def test_impact_chain(self):
        out = self.ok("impact", *EX, "C002")
        for part in ("K002", "K004", "K006", "L001", "DR-001", "K007", "обещаний среди них 1"):
            self.assertIn(part, out)

    def test_impact_mark(self):
        before = (self.root / "projects" / "_example" / "journal.jsonl").read_text(encoding="utf-8").splitlines()
        out = self.ok("impact", *EX, "C002", "--mark")
        self.assertIn("Поставлен статус", out)
        concl = self.ok("conclusion", "list", *EX)
        self.assertIn("K007 [promise, под-вопросом, слой 1]", concl)
        self.assertIn("K001 [finding, действует, слой 1]", concl)
        self.assertIn("под-вопросом", self.ok("lever", "list", *EX))
        decs = (self.root / "projects" / "_example" / "decisions" / "DR-001.md").read_text(encoding="utf-8")
        self.assertIn("doubt: под-вопросом", decs)
        after = (self.root / "projects" / "_example" / "journal.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(after[:len(before)], before)
        self.assertEqual(json.loads(after[-1])["cmd"], "impact")
        sw = self.ok("sweep", *EX)
        self.assertIn("K007 под вопросом", sw)
        self.assertIn("DR-001 под вопросом", sw)

    def test_impact_unknown(self):
        code, out = self.run_cmd("impact", *EX, "C999")
        self.assertEqual(code, 1)

    def test_sweep_findings(self):
        self.ok("claim", "add", *EX, "--type", "fact", "--source", "S002",
                "--quote", "Жалобы на качество каталога встречались реже", "--text", "Жалобы на каталог реже.")
        self.ok("conclusion", "add", *EX, "--text", "Главное не цена.", "--rests-on", "C005", "--contradicts", "K002")
        out = self.ok("sweep", *EX, today="2027-06-01")
        self.assertIn("C014", out)
        self.assertIn("пересмотр был назначен на 2027-03-01", out)
        self.assertIn("противоречат", out)
        self.ok("claim", "reject", *EX, "C007", "--reason", "тест")
        out = self.ok("sweep", *EX, today="2027-06-01")
        self.assertIn("со статусом «отброшено»", out)
        code, out = self.run_cmd("sweep", *EX, "--strict", today="2027-06-01")
        self.assertEqual(code, 2)

    def test_clean_sweep(self):
        out = self.ok("sweep", *EX)
        self.assertIn("Итого замечаний: 0", out)


class CostTests(Env):
    def test_cost_report(self):
        self.new_project("k")
        self.ok("done", "budget", "-p", "k", "--usd", "5")
        self.ok("cost", "log", "-p", "k", "--stage", "3", "--usd", "0.5", "--tokens", "1000")
        self.ok("cost", "log", "-p", "k", "--stage", "3", "--usd", "0.25")
        self.ok("cost", "log", "-p", "k", "--stage", "4", "--usd", "0.75", "--note", "диагностика")
        out = self.ok("cost", "report", "-p", "k")
        self.assertIn("оценка агента", out)
        self.assertIn("Этап 3 (Сбор материалов): оценка агента 0.75 USD", out)
        self.assertIn("Этап 4 (Диагностика и выводы): оценка агента 0.75 USD", out)
        self.assertIn("Итого оценка агента: 1.50 USD", out)
        self.assertIn("Итого замер: 0.00 USD", out)
        self.assertIn("осталось 3.50", out)
        code, out = self.run_cmd("cost", "log", "-p", "k", "--stage", "9", "--usd", "1")
        self.assertEqual(code, 1)

    def test_empty_cost(self):
        self.new_project("k")
        self.assertIn("пока не записан", self.ok("cost", "report", "-p", "k"))


class GuardTests(Env):
    def test_loop_guard(self):
        p = self.new_project("lg")
        codes = [self.run_cmd("gate", "-p", "lg")[0] for _ in range(5)]
        self.assertEqual(codes, [2, 2, 2, 2, 2])
        code, out = self.run_cmd("gate", "-p", "lg")
        self.assertEqual(code, 0)
        self.assertIn("ПРЕДУПРЕЖДЕНИЕ", out)
        journal = [json.loads(l) for l in (p / "journal.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertTrue(any(j["cmd"] == "gate" for j in journal))
        self.assertEqual(self.run_cmd("gate", "-p", "lg")[0], 2)

    def test_guard_resets_when_files_change(self):
        p = self.new_project("lg")
        for _ in range(4):
            self.assertEqual(self.run_cmd("gate", "-p", "lg")[0], 2)
        self.write(p / "errors.md", "новая запись\n")
        for _ in range(5):
            self.assertEqual(self.run_cmd("gate", "-p", "lg")[0], 2)

    def test_gate_passes_on_example(self):
        out = self.ok("gate", *EX)
        self.assertIn("проверки пройдены", out)


class MiscTests(Env):
    def test_help_for_every_command_in_russian(self):
        cmds = [["new"], ["status"], ["stage"], ["stage", "next"], ["stage", "show"], ["source"], ["source", "add"],
                ["source", "list"], ["source", "accept-stale"], ["claim"], ["claim", "add"], ["claim", "reject"],
                ["claim", "list"], ["conclusion"], ["conclusion", "add"], ["conclusion", "set-status"],
                ["conclusion", "list"], ["lever"], ["lever", "add"], ["lever", "list"], ["calc"], ["calc", "run"],
                ["verify"], ["gate"], ["impact"], ["sweep"], ["decision"], ["decision", "add"],
                ["decision", "set-status"], ["decision", "list"], ["cost"], ["cost", "log"], ["cost", "report"],
                ["done"], ["done", "add"], ["done", "mark"], ["done", "budget"], ["done", "list"], ["question"],
                ["question", "add"], ["question", "close"], ["doctor"], ["source", "set-layer"], ["kb"], ["kb", "source"],
                ["kb", "source", "add"], ["kb", "add"], ["kb", "import"], ["kb", "search"], ["kb", "show"], ["kb", "link"],
                ["kb", "list"], ["kb", "retire"], ["kb", "replace"], ["kb", "stale"], ["kb", "index"], ["lever", "set-status"]]
        for c in cmds:
            code, out = self.run_cmd(*(c + ["--help"]))
            self.assertEqual(code, 0, c)
            self.assertIn("Использование:", out, c)
            self.assertNotIn("usage:", out, c)
            self.assertNotIn("optional arguments", out, c)
            self.assertNotIn("options:", out, c)

    def test_usage_error_code_1_in_russian(self):
        code, out = self.run_cmd("claim", "add")
        self.assertEqual(code, 1)
        self.assertIn("Ошибка:", out)
        code, out = self.run_cmd("nosuch")
        self.assertEqual(code, 1)

    def test_doctor(self):
        code, out = self.run_cmd("doctor")
        self.assertEqual(code, 0, out)
        self.assertIn("Python", out)
        (self.root / "config" / "style.json").write_text("{не json", encoding="utf-8")
        code, out = self.run_cmd("doctor")
        self.assertNotEqual(code, 0)
        self.assertIn("ПРОБЛЕМА", out)

    def test_state_json_not_rewritten_by_agent_commands(self):
        self.new_project("st")
        before = sha(self.root / "projects" / "st" / "state.json")
        self.write(self.root / "projects" / "st" / "materials" / "a.txt", "Текст 1.")
        self.ok("source", "add", "-p", "st", "--file", "materials/a.txt", "--published", "2026-10-01")
        self.ok("claim", "add", "-p", "st", "--type", "hypothesis", "--text", "гипотеза")
        self.ok("cost", "log", "-p", "st", "--stage", "1", "--usd", "0.1")
        self.assertEqual(before, sha(self.root / "projects" / "st" / "state.json"))

    def test_new_project_layout_and_refusals(self):
        p = self.new_project("lay")
        for rel in ("brief.md", "done.json", "state.json", "journal.jsonl", "materials", "sources",
                    "ledger/claims.jsonl", "ledger/conclusions.jsonl", "levers.json", "options.md", "strategy",
                    "decisions", "page.md", "cost.jsonl", "errors.md", "analysis"):
            self.assertTrue((p / rel).exists(), rel)
        self.assertEqual(json.loads((p / "state.json").read_text(encoding="utf-8"))["stage"], 1)
        code, out = self.run_cmd("new", "lay", "--question", "ещё раз")
        self.assertEqual(code, 1)
        code, out = self.run_cmd("new", "../evil", "--question", "x")
        self.assertEqual(code, 1)

    def test_decision_and_lever_validation(self):
        code, out = self.run_cmd("lever", "add", *EX, "--metric", "m", "--where", "w", "--cause", "c", "--action", "a",
                                 "--effect-low", "5", "--effect-base", "2", "--effect-high", "9", "--check", "x",
                                 "--rests-on", "C001")
        self.assertEqual(code, 1)
        self.assertIn("по возрастанию", out)
        code, out = self.run_cmd("decision", "add", *EX, "--title", "t", "--owner", "o", "--metric", "m",
                                 "--review-date", "01.03.2027", "--review-if", "x", "--rests-on", "K001")
        self.assertEqual(code, 1)
        self.ok("decision", "add", *EX, "--title", "Второе", "--owner", "о", "--metric", "m",
                "--review-date", "2027-05-01", "--review-if", "x", "--rests-on", "K001")
        self.assertTrue((self.root / "projects" / "_example" / "decisions" / "DR-002.md").exists())
        self.ok("decision", "set-status", *EX, "DR-002", "--status", "принято")
        self.assertIn("[принято]", self.ok("decision", "list", *EX))

    def test_no_long_dashes_anywhere(self):
        bad = (chr(0x2014), chr(0x2013))
        copies = ROOT / "knowledge" / "sources"  # дословные копии чужих страниц хранятся как есть
        for p in ROOT.rglob("*"):
            if not p.is_file() or p.suffix not in (".py", ".md", ".json", ".txt", ".csv", ".jsonl") or "__pycache__" in p.parts:
                continue
            if copies in p.parents or (ROOT / "docs" / "evidence") in p.parents:
                continue  # тексты сверок и ответ обычного чата сохранены как есть
            # материалы и копии источников в проектах это чужие тексты (отзывы, выгрузки): правило про длинные тире касается только наших текстов
            rel = p.relative_to(ROOT).parts
            # Чужие слова храним как есть: входящие файлы руководителя, копии источников,
            # материалы и реестр с дословными цитатами.
            if rel[0] == "inbox":
                continue
            if len(rel) >= 3 and rel[0] == "projects" and rel[2] in ("materials", "sources", "ledger"):
                continue
            if len(rel) >= 3 and rel[0] == "projects" and rel[2] == "analysis" and p.suffix in (".txt", ".json"):
                continue  # выборки отзывов для проверки точности: тоже чужие тексты
            text = p.read_text(encoding="utf-8")
            for b in bad:
                self.assertNotIn(b, text, str(p))


if __name__ == "__main__":
    unittest.main()
