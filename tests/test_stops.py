# -*- coding: utf-8 -*-
"""Остановки для руководителя: без его слов с этапа-остановки дальше не перейти, ранняя работа не принимается."""
import json
import unittest

from helpers import Env


class StopsTest(Env):
    def setUp(self):
        super().setUp()
        self.set_config("process.json", {"stops_need_answer": True})
        self.proj = self.new_project("s", "Что делать с направлением?")
        self.ok("req", "add", "-p", "s", "--text", "ответить на вопрос", "--quote", "Что делать")
        brief = self.proj / "brief.md"
        brief.write_text(brief.read_text(encoding="utf-8").replace("<<заполнить>>", "не относится"), encoding="utf-8")

    def state(self):
        return json.loads((self.proj / "state.json").read_text(encoding="utf-8"))

    def test_new_project_tells_about_first_stop(self):
        out = self.ok("new", "s2", "--question", "Почему упало?")
        self.assertIn("Остановка для человека №1", out)
        self.assertIn("после ответов руководителя", out)

    def test_stage_next_waits_for_the_answer(self):
        code, out = self.run_cmd("stage", "next", "-p", "s")
        self.assertEqual(code, 3, out)
        self.assertIn("нельзя без ответа руководителя", out)
        self.assertIn("--answer", out)
        self.assertEqual(self.state()["stage"], 1)

    def test_answer_is_saved_and_shown_in_status(self):
        out = self.ok("stage", "next", "-p", "s", "--answer", "Данных нет, работаем на допущениях")
        self.assertIn("Теперь этап 2", out)
        self.assertIn("Ответ руководителя на остановке №1 записан", out)
        self.assertIn("Остановка для человека №2", out)
        self.assertEqual(self.state()["stop_answers"]["1"]["answer"], "Данных нет, работаем на допущениях")
        self.assertIn("Ответ руководителя на остановке №1 (этап 1): «Данных нет", self.ok("status", "-p", "s"))

    def test_early_work_is_refused_before_stage_three(self):
        for args, what in ((("claim", "add", "-p", "s", "--type", "assumption", "--text", "доля", "--low", "1", "--base", "2",
                             "--high", "3", "--why", "так", "--verify-by", "проверка", "--switch-if", "ниже 1"), "запись допущений"),
                           (("req", "close", "R01", "-p", "s", "--by", "document.md"), "закрытие требований"),
                           (("calc", "ready", "выборка", "-p", "s", "--params", "analysis/x.json", "--rests-on", "C001"), "расчёт")):
            code, out = self.run_cmd(*args)
            self.assertEqual(code, 1, out)
            self.assertIn("Рано: %s начинается с этапа 3" % what, out)
            self.assertIn("Остановка для человека №1", out)

    def test_facts_are_allowed_at_stage_one(self):
        code, out = self.run_cmd("claim", "add", "-p", "s", "--type", "hypothesis", "--text", "возможно, дело в цене")
        self.assertEqual(code, 0, out)

    def test_gate_lets_stop_when_questions_are_asked(self):
        brief = self.proj / "brief.md"
        brief.write_text(brief.read_text(encoding="utf-8").replace("не относится", "<<заполнить>>", 1), encoding="utf-8")
        code, out = self.run_cmd("gate", "-p", "s")
        self.assertEqual(code, 2, out)
        self.ok("question", "add", "-p", "s", "--text", "Есть ли свои данные?", "--if-yes", "беру их", "--if-no", "допущения")
        code, out = self.run_cmd("gate", "-p", "s")
        self.assertEqual(code, 0, out)
        self.assertIn("Ждём его ответа", out)

    def test_gate_reminds_about_the_stop(self):
        code, out = self.run_cmd("gate", "-p", "s")
        self.assertEqual(code, 0, out)
        self.assertIn("Остановка для человека №1", out)

    def test_old_order_without_the_setting(self):
        self.set_config("process.json", {"stops_need_answer": False})
        self.assertIn("Теперь этап 2", self.ok("stage", "next", "-p", "s"))


if __name__ == "__main__":
    unittest.main()
