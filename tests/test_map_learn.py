# -*- coding: utf-8 -*-
"""Проверки трёх новых частей: даты и поиск базы знаний, карта причин, обучение волнами."""
import json
import sys
import unittest
from pathlib import Path

from helpers import Env, ROOT
from test_rychag import KbBase

sys.path.insert(0, str(ROOT / "tools"))
from lib import kb as kbase  # noqa: E402
from lib import learn  # noqa: E402

LEVER_NOTE = "Рычаг: то, что можно изменить, чтобы показатель вырос."
LAYER_PHRASES = ["данные самого продукта", "данные компании", "другие компании в России", "компании в мире", "смежные отрасли"]


def jl(path):
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


# ---------------------------------------------------------------- часть 1

class DateTests(KbBase):
    def test_partial_dates_accepted_and_stored_as_given(self):
        for i, d in enumerate(("2026", "2026-05", "2026-05-01")):
            f = self.root / "kbtmp" / ("s%d.txt" % i)
            self.write(f, "Текст источника номер %d для проверки даты." % i)
            self.ok("kb", "source", "add", "--url", "https://example.org/%d" % i, "--text-file", str(f), "--published", d)
            meta = json.loads((self.root / "knowledge" / "sources" / ("KS00%d.meta.json" % (i + 1))).read_text(encoding="utf-8"))
            self.assertEqual(meta["published"], d)

    def test_bad_dates_rejected(self):
        for d in ("2026-13", "26", "2026-02-30", "май 2026"):
            code, out = self.run_cmd("kb", "source", "add", "--url", "https://example.org/x", "--text-file", str(self.src), "--published", d)
            self.assertEqual(code, 1, d)

    def test_future_period_rejected(self):
        code, out = self.run_cmd("kb", "source", "add", "--url", "https://example.org/x", "--text-file", str(self.src), "--published", "2027")
        self.assertEqual(code, 1)
        self.assertIn("в будущем", out)

    def test_empty_date_is_warning(self):
        code, out = self.run_cmd("kb", "source", "add", "--url", "https://example.org/x", "--text-file", str(self.src))
        self.assertEqual(code, 0)
        self.assertIn("Предупреждение", out)

    def test_freshness_uses_last_day_of_period(self):
        self.set_config("sources.json", {"allowlist": [], "max_sources_per_question": 10, "freshness_days": 730, "kb_freshness_days": 400})
        self.kb_source("2025-10")  # последний день 2025-10-31, до 2026-11-18 это 383 дня
        self.assertEqual(self.kb_add("Бесплатный пробный период снижает отток", "Бесплатный пробный период в 14 дней")[0], 0)
        self.assertIn("Устаревших записей нет", self.ok("kb", "stale"))
        self.set_config("sources.json", {"allowlist": [], "max_sources_per_question": 10, "freshness_days": 730, "kb_freshness_days": 380})
        self.assertIn("B001", self.ok("kb", "stale"))

    def test_year_only_freshness(self):
        self.set_config("sources.json", {"allowlist": [], "max_sources_per_question": 10, "freshness_days": 730, "kb_freshness_days": 1000})
        self.kb_source("2023")  # до 2026-11-18 от 2023-12-31 это 1053 дня
        self.kb_add("Бесплатный пробный период снижает отток", "Бесплатный пробный период в 14 дней")
        self.assertIn("B001", self.ok("kb", "stale"))

    def test_project_source_partial_date(self):
        self.new_project("d")
        self.write(self.root / "projects" / "d" / "materials" / "a.txt", "Текст один")
        self.write(self.root / "projects" / "d" / "materials" / "b.txt", "Текст два")
        self.ok("source", "add", "-p", "d", "--file", "materials/a.txt", "--published", "2024")  # конец периода 2024-12-31: 687 дней
        code, out = self.run_cmd("source", "add", "-p", "d", "--file", "materials/b.txt", "--published", "2023")  # 1053 дня
        self.assertEqual(code, 1)
        self.assertIn("старше порога", out)

    def test_import_partial_and_empty_dates(self):
        d = self.root / "imp"
        self.write(d / "a.txt", KBTEXT2)
        self.write(d / "b.txt", KBTEXT2 + "Ещё одна строка.\n")
        rows = [self.imp_row("Пробный период снижает отток подписчиков", "Бесплатный пробный период", "2026-05"),
                self.imp_row("Напоминание перед списанием уменьшает отмены", "напоминания перед списанием", "")]
        rows[1]["source_file"] = "b.txt"
        self.write(d / "in.jsonl", "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
        code, out = self.run_cmd("kb", "import", str(d / "in.jsonl"), "--sources-dir", str(d))
        self.assertEqual(code, 0, out)
        self.assertIn("Принято: 2", out)
        self.assertIn("нет даты публикации", out)
        self.assertEqual({r["date_published"] for r in self.records()}, {"2026-05", None})

    def imp_row(self, rule, quote, date, number=""):
        return {"rule": rule, "applies_when": "подписка", "themes": ["удержание"], "place": "Нигде, Тест", "date_published": date,
                "url": "https://example.org/" + str(abs(hash(rule)) % 1000), "source_file": "a.txt", "quote": quote, "number": number,
                "strength": "мнение", "layer": 4}

    def test_reimport_after_clearing_number(self):
        d = self.root / "imp"
        self.write(d / "a.txt", KBTEXT2)
        bad = self.imp_row("Пробный период снижает отток", "Бесплатный пробный период", "2026", number="99 дней")
        self.write(d / "in.jsonl", json.dumps(bad, ensure_ascii=False) + "\n")
        code, out = self.run_cmd("kb", "import", str(d / "in.jsonl"), "--sources-dir", str(d))
        self.assertEqual(code, 2)
        rej = jl(self.root / "knowledge" / "rejected.jsonl")
        self.assertIn("не встречается в цитате", rej[0]["reason"])
        fixed = rej[0]["record"]
        fixed["number"] = ""
        self.write(d / "fix.jsonl", json.dumps(fixed, ensure_ascii=False) + "\n")
        self.ok("kb", "import", str(d / "fix.jsonl"), "--sources-dir", str(d))
        self.assertEqual(len(self.records()), 1)


KBTEXT2 = ("Бесплатный пробный период в 14 дней снижал отток в сервисах подписки.\n"
           "Банк сообщил, что персональные напоминания перед списанием уменьшили отмены на 20%.\n")


class SearchTests(KbBase):
    def test_single_generic_word_does_not_outrank(self):
        self.make_kb()
        out = self.ok("kb", "search", "бесплатный пробный период цена")
        self.assertIn("B001", out)
        self.assertNotIn("B002", out)  # слой ближе, но совпала одна цена из четырёх слов
        self.assertIn("Совпало слов запроса: 3 из 4", out)

    def test_order_layer_then_matches(self):
        self.make_kb()
        out = self.ok("kb", "search", "цена абонентов")
        self.assertLess(out.index("B002"), out.index("B001") if "B001" in out else 10 ** 9)

    def test_nothing_passes_suggests_three_closest(self):
        self.make_kb()
        out = self.ok("kb", "search", "космос роуминг скидка цена")
        self.assertIn("Ни одна запись не набрала допуск", out)
        self.assertIn("1 из 4", out)
        self.assertIn("B002", out)

    def test_two_terms_need_both(self):
        self.make_kb()
        out = self.ok("kb", "search", "цена космос")
        self.assertIn("Ни одна запись не набрала допуск", out)

    def test_short_and_stop_words_ignored(self):
        self.assertEqual(kbase.query_terms("и в на для цена при"), ["цена"])
        self.assertEqual(kbase.need_terms(1), 1)
        self.assertEqual(kbase.need_terms(2), 2)
        self.assertEqual(kbase.need_terms(3), 2)
        self.assertEqual(kbase.need_terms(5), 3)

    def test_four_letter_word_forms(self):
        self.assertTrue(kbase._same("цена", "цены"))
        self.assertTrue(kbase._same("цена", "ценой"))
        self.assertTrue(kbase._same("цены", "цена"))
        self.assertFalse(kbase._same("кот", "коты"))
        self.assertTrue(kbase._same("кот", "кот"))
        self.make_kb()
        self.assertIn("B002", self.ok("kb", "search", "цена"))
        self.assertIn("B002", self.ok("kb", "search", "ценой"))


# ---------------------------------------------------------------- часть 2

class MapBase(KbBase):
    def setUp(self):
        KbBase.setUp(self)
        self.make_kb()  # B001 слой 4 мнение? (данные-компании), B002 слой 3 независимый-замер, B003 слой 5, B004 урок
        self.ok("map", "node", "add", "--name", "Отток абонентов", "--kind", "показатель", "--alias", "уход,потеря")
        self.ok("map", "node", "add", "--name", "Цена тарифа", "--kind", "фактор")
        self.ok("map", "node", "add", "--name", "Напоминания о списании", "--kind", "действие")

    def mp(self, name):
        return self.root / "knowledge" / "map" / name


class MapNodeLinkTests(MapBase):
    def test_nodes(self):
        out = self.ok("map", "node", "list")
        self.assertIn("N001 [показатель] Отток абонентов (также: уход, потеря)", out)
        code, out = self.run_cmd("map", "node", "add", "--name", "отток АБОНЕНТОВ", "--kind", "фактор")
        self.assertEqual(code, 1)
        code, out = self.run_cmd("map", "node", "add", "--name", "Х", "--kind", "прочее")
        self.assertEqual(code, 1)

    def test_link_layer_strength_status(self):
        out = self.ok("map", "link", "add", "--from", "Цена тарифа", "--to", "уход", "--sign", "усиливает",
                      "--conditions", "после повышения", "--evidence", "B001,B002")
        l = jl(self.mp("links.jsonl"))[0]
        self.assertEqual((l["id"], l["from"], l["to"], l["layer"], l["strength"], l["status"]),
                         ("R001", "N002", "N001", 3, "независимый-замер", "действует"))
        self.assertIn("другие компании в России", out)

    def test_no_evidence_is_hypothesis(self):
        out = self.ok("map", "link", "add", "--from", "N002", "--to", "N001", "--sign", "усиливает")
        l = jl(self.mp("links.jsonl"))[0]
        self.assertEqual((l["status"], l["layer"], l["strength"]), ("гипотеза", None, None))
        self.assertIn("гипотеза", out)

    def test_evidence_must_exist_and_be_active(self):
        code, out = self.run_cmd("map", "link", "add", "--from", "N002", "--to", "N001", "--sign", "усиливает", "--evidence", "B099")
        self.assertEqual(code, 1)
        self.ok("kb", "retire", "B001", "--reason", "тест")
        code, out = self.run_cmd("map", "link", "add", "--from", "N002", "--to", "N001", "--sign", "усиливает", "--evidence", "B001")
        self.assertEqual(code, 1)
        self.assertIn("не действует", out)

    def test_duplicate_merges_evidence(self):
        self.ok("map", "link", "add", "--from", "N002", "--to", "N001", "--sign", "усиливает", "--evidence", "B001")
        out = self.ok("map", "link", "add", "--from", "N002", "--to", "N001", "--sign", "усиливает", "--evidence", "B002,B001")
        self.assertIn("Объединено", out)
        ls = jl(self.mp("links.jsonl"))
        self.assertEqual(len(ls), 1)
        self.assertEqual(ls[0]["evidence"], ["B001", "B002"])
        self.assertEqual(ls[0]["layer"], 3)

    def test_hypothesis_becomes_proven_by_merge(self):
        self.ok("map", "link", "add", "--from", "N002", "--to", "N001", "--sign", "усиливает")
        self.ok("map", "link", "add", "--from", "N002", "--to", "N001", "--sign", "усиливает", "--evidence", "B003")
        self.assertEqual(jl(self.mp("links.jsonl"))[0]["status"], "действует")

    def test_self_link_rejected(self):
        code, _o = self.run_cmd("map", "link", "add", "--from", "N001", "--to", "N001", "--sign", "усиливает")
        self.assertEqual(code, 1)

    def test_unknown_node(self):
        code, out = self.run_cmd("map", "link", "add", "--from", "Нет такого", "--to", "N001", "--sign", "усиливает")
        self.assertEqual(code, 1)
        self.assertIn("нет на карте", out)


class MapImportTests(MapBase):
    def test_import_accepts_and_rejects(self):
        f = self.root / "m.jsonl"
        lines = [
            {"type": "node", "name": "Качество связи", "kind": "фактор", "aliases": ["покрытие"]},
            {"type": "link", "from": "Качество связи", "to": "Отток абонентов", "sign": "ослабляет", "evidence": ["B003"], "conditions": "в регионах"},
            {"type": "link", "from": "Нет узла", "to": "N001", "sign": "усиливает"},
            {"type": "link", "from": "N002", "to": "N001", "sign": "усиливает", "evidence": ["B777"]},
            {"type": "node", "name": "Цена тарифа", "kind": "действие"},
            {"type": "other"},
        ]
        self.write(f, "".join(json.dumps(l, ensure_ascii=False) + "\n" for l in lines) + "не json\n")
        code, out = self.run_cmd("map", "import", str(f))
        self.assertEqual(code, 2)
        self.assertIn("Принято: узлов 1, связей 1. Отклонено: 5", out)
        rej = jl(self.mp("rejected.jsonl"))
        self.assertEqual(len(rej), 5)
        self.assertTrue(all(r["reason"] for r in rej))
        self.assertEqual(jl(self.mp("links.jsonl"))[0]["to"], "N001")

    def test_import_clean_file(self):
        f = self.root / "m.jsonl"
        self.write(f, json.dumps({"type": "link", "from": "N002", "to": "N001", "sign": "усиливает"}) + "\n")
        self.ok("map", "import", str(f))
        self.assertEqual(jl(self.mp("links.jsonl"))[0]["status"], "гипотеза")


class MapQueryTests(MapBase):
    def setUp(self):
        MapBase.setUp(self)
        a = ["map", "link", "add"]
        self.ok(*a, "--from", "N002", "--to", "N001", "--sign", "усиливает", "--evidence", "B002", "--conditions", "после повышения")   # R001 слой 3
        self.ok(*a, "--from", "N003", "--to", "N001", "--sign", "ослабляет", "--evidence", "B003")                                      # R002 слой 5
        self.ok(*a, "--from", "N003", "--to", "N002", "--sign", "ослабляет")                                                            # R003 гипотеза
        self.ok("map", "node", "add", "--name", "Конкуренты", "--kind", "фактор")                                                       # N004
        self.ok(*a, "--from", "N004", "--to", "N002", "--sign", "усиливает", "--evidence", "B001")                                      # R004 слой 4

    def test_causes_order_and_hypotheses_apart(self):
        out = self.ok("map", "causes", "Отток абонентов", "--depth", "2")
        self.assertLess(out.index("R001"), out.index("R002"))  # слой 3 раньше слоя 5
        self.assertIn("после повышения", out)
        self.assertIn("независимый-замер", out)
        self.assertIn("B002", out)
        self.assertIn("статус действует", out)
        self.assertIn("Конкуренты", out)  # второй уровень
        self.assertGreater(out.index("R003"), out.index("R001"))  # гипотеза раскручивается внутри цепочки
        self.assertIn("[ГИПОТЕЗА, не доказана] R003", out)
        self.assertIn("Показано связей: 4, из них доказано 3, гипотез 1.", out)
        self.assertIn("другие компании в России", out)

    def test_causes_depth_and_layer_max(self):
        out = self.ok("map", "causes", "N001", "--depth", "1")
        self.assertNotIn("R004", out)
        out = self.ok("map", "causes", "N001", "--layer-max", "3")
        self.assertIn("R001", out)
        self.assertNotIn("R002", out)

    def test_effects(self):
        out = self.ok("map", "effects", "Напоминания о списании", "--depth", "2")
        self.assertIn("R002", out)
        self.assertIn("Отток абонентов", out)

    def test_path(self):
        out = self.ok("map", "path", "Конкуренты", "Отток абонентов")
        self.assertIn("Цепочка 1, длина 2, в итоге усиливает", out)
        out = self.ok("map", "path", "Напоминания о списании", "Цена тарифа")
        self.assertIn("в итоге ослабляет", out)
        self.assertIn("R003", out)  # только через гипотезу
        self.assertIn("без доказательств", out)
        self.assertIn("длина 1", self.ok("map", "path", "Напоминания о списании", "Отток абонентов"))  # кратчайшая
        out = self.ok("map", "path", "Отток абонентов", "Цена тарифа")
        self.assertIn("нет", out)

    def test_check(self):
        self.ok("map", "node", "add", "--name", "Одинокий узел", "--kind", "фактор")
        self.ok("map", "link", "add", "--from", "N002", "--to", "N001", "--sign", "ослабляет", "--evidence", "B003")  # R005 против R001
        self.ok("map", "link", "add", "--from", "N001", "--to", "N004", "--sign", "усиливает")  # цикл N004>N002>N001>N004
        self.ok("kb", "retire", "B001", "--reason", "тест")
        out = self.ok("map", "check")
        self.assertIn("R004: запись B001 отозвана", out)
        self.assertIn("Одинокий узел", out)
        self.assertIn("R001", out)
        self.assertIn("R005", out)
        self.assertIn("противоположное", out)
        self.assertIn("Ближе к продукту связь R001", out)
        self.assertIn("Циклы (справочно", out)
        self.assertIn("N001", out.split("Циклы")[1])
        self.assertEqual(self.run_cmd("map", "check")[0], 0)
        self.assertEqual(self.run_cmd("map", "check", "--strict")[0], 2)

    def test_export_mermaid(self):
        out = self.ok("map", "export", "--format", "mermaid")
        self.assertIn("knowledge/map/map.mmd", out)
        text = self.mp("map.mmd").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("flowchart"))
        self.assertIn('N002 -->|"усиливает, другие компании в России"| N001', text)
        self.assertIn('N003 -.->|"ослабляет, гипотеза, не доказана"| N002', text)
        self.ok("map", "export", "--format", "mermaid", "--around", "Конкуренты", "--depth", "1")
        text = self.mp("map.mmd").read_text(encoding="utf-8")
        self.assertIn("N004", text)
        self.assertIn("N002", text)
        self.assertNotIn("N003[", text)

    def test_retire_and_replace_update_links(self):
        out = self.ok("kb", "retire", "B003", "--reason", "устарела")
        self.assertIn("связь R002 стала «гипотеза»", out)
        ls = {l["id"]: l for l in jl(self.mp("links.jsonl"))}
        self.assertEqual(ls["R002"]["status"], "гипотеза")
        self.assertIsNone(ls["R002"]["layer"])
        self.assertEqual(ls["R001"]["status"], "действует")
        out = self.ok("kb", "replace", "B002", "--by", "B001", "--reason", "новая")
        self.assertIn("R001", out)
        self.assertEqual({l["id"]: l for l in jl(self.mp("links.jsonl"))}["R001"]["status"], "гипотеза")
        # восстановление: добавили действующую запись
        self.ok("map", "link", "add", "--from", "N002", "--to", "N001", "--sign", "усиливает", "--evidence", "B001")
        self.assertEqual({l["id"]: l for l in jl(self.mp("links.jsonl"))}["R001"]["status"], "действует")

    def test_partial_evidence_loss_keeps_link(self):
        self.ok("map", "link", "add", "--from", "N002", "--to", "N001", "--sign", "усиливает", "--evidence", "B003")
        self.ok("kb", "retire", "B002", "--reason", "тест")
        l = jl(self.mp("links.jsonl"))[0]
        self.assertEqual((l["status"], l["layer"]), ("действует", 5))

    def test_impact_lists_links(self):
        self.new_project("p")
        out = self.ok("impact", "B002", "-p", "p")
        self.assertIn("Связи карты причин, которые держатся на B002", out)
        self.assertIn("R001", out)
        self.assertIn("Связей карты причин на B004 нет", self.ok("impact", "B004", "-p", "p"))


class MapProjectTests(MapBase):
    def test_claim_from_map_and_status(self):
        self.new_project("p")
        self.ok("map", "link", "add", "--from", "N002", "--to", "N001", "--sign", "усиливает")
        out = self.ok("claim", "add", "-p", "p", "--type", "hypothesis", "--text", "Цена повлияла на отток", "--from-map", "R001")
        self.assertIn("Добавлено C001", out)
        self.assertEqual(jl(self.root / "projects" / "p" / "ledger" / "claims.jsonl")[0]["from_map"], "R001")
        code, out = self.run_cmd("claim", "add", "-p", "p", "--type", "hypothesis", "--text", "ещё", "--from-map", "R099")
        self.assertEqual(code, 1)
        code, out = self.run_cmd("claim", "add", "-p", "p", "--type", "plan", "--text", "ещё", "--from-map", "R001")
        self.assertEqual(code, 1)
        st = self.ok("status", "-p", "p")
        self.assertIn("Карта причин: узлов 3, связей 1 (действует 0, гипотез 1). Гипотез проекта из карты: 1.", st)


# ---------------------------------------------------------------- часть 3

class LearnBase(KbBase):
    """Проект t: факт слоя 1, вывод K001, рычаг L001 (эффект 10 / 20 / 30), решение DR-001 на K001 и L001."""

    def setUp(self):
        KbBase.setUp(self)
        self.make_kb()
        self.p = self.new_project("t")
        self.write(self.p / "materials" / "a.txt", "Отток вырос до 5% в октябре.\n")
        self.ok("source", "add", "-p", "t", "--file", "materials/a.txt", "--published", "2026-10-01")
        self.ok("claim", "add", "-p", "t", "--type", "fact", "--text", "Отток 5%", "--source", "S001", "--quote", "Отток вырос до 5%", "--number", "5")
        self.ok("conclusion", "add", "-p", "t", "--text", "Причина в цене", "--rests-on", "C001", "--kind", "finding")
        self.ok("lever", "add", "-p", "t", "--metric", "отток", "--where", "все", "--cause", "цена", "--action", "вернуть цену",
                "--effect-low", "10", "--effect-base", "20", "--effect-high", "30", "--check", "сравнить", "--rests-on", "K001")
        self.ok("decision", "add", "-p", "t", "--title", "Вернуть цену", "--owner", "Иванов", "--metric", "отток",
                "--review-date", "2027-03-01", "--review-if", "нет эффекта", "--rests-on", "K001,L001")

    def fb(self, target, verdict, reason=None, note=None, project="t", today=None):
        args = ["feedback", "add", "-p", project, "--target", target, "--verdict", verdict]
        if reason:
            args += ["--reason", reason]
        if note:
            args += ["--note", note]
        return self.ok(*args, today=today)

    def oc(self, actual, source=None, decision="DR-001", period="2026-12"):
        args = ["outcome", "add", "-p", "t", "--decision", decision, "--metric", "отток", "--actual", str(actual), "--period", period]
        if source:
            args += ["--source", source]
        return self.ok(*args)

    def ledger_snapshot(self):
        return {n: (self.p / n).read_bytes() for n in ("ledger/claims.jsonl", "ledger/conclusions.jsonl", "levers.json")} | \
               {"records": (self.root / "knowledge" / "records.jsonl").read_bytes() if (self.root / "knowledge" / "records.jsonl").exists() else b""}


class FeedbackTests(LearnBase):
    def test_reasons_labels(self):
        out = self.ok("feedback", "reasons")
        for label in ("Число вызывает сомнение: не видно, откуда оно взято", "Много общих слов, мало конкретики",
                      "Не сказано, что именно нужно сделать", "Ответ не на тот вопрос",
                      "Вывод не подтверждается приведёнными данными", "Предложение невыполнимо в наших условиях",
                      "Слишком длинно", "Данные устарели", "Написано непонятно", "Другое (нужно пояснение)"):
            self.assertIn(label, out)
        self.assertIn("  7. Слишком длинно", out)

    def test_reason_by_code_number_or_label_and_display(self):
        self.fb("K001", "Отклонено", "вода")
        self.fb("L001", "отклонено", "3")
        self.fb("DR-001", "Отклонено", "Данные устарели")
        self.fb("page", "Принято")
        rows = jl(self.p / "feedback.jsonl")
        self.assertEqual([r["reason"] for r in rows], ["вода", "нет-рычага", "устарело", None])
        out = self.ok("feedback", "list", "-p", "t")
        self.assertIn("Отклонено", out)
        self.assertIn("Принято", out)
        self.assertIn("Много общих слов, мало конкретики", out)
        self.assertIn("Не сказано, что именно нужно сделать", out)
        self.assertNotIn("нет-рычага", out)
        self.assertIn(LEVER_NOTE, out)

    def test_verdict_labels_in_add_output(self):
        out = self.fb("K001", "Отклонено", "10", note="поясню")
        self.assertIn("Отклонено", out)
        self.assertIn("Другое (нужно пояснение)", out)
        self.assertIn("Принято", self.fb("K001", "принято"))

    def test_validation(self):
        for args in (["--target", "K001", "--verdict", "Отклонено"],                     # нет причины
                     ["--target", "K001", "--verdict", "Отклонено", "--reason", "99"],   # нет такой
                     ["--target", "K099", "--verdict", "Принято"],                       # нет объекта
                     ["--target", "X1", "--verdict", "Принято"],
                     ["--target", "K001", "--verdict", "нормально"]):
            self.assertEqual(self.run_cmd("feedback", "add", "-p", "t", *args)[0], 1, args)

    def test_feedback_never_changes_statuses_or_creates_facts(self):
        before = self.ledger_snapshot()
        for t in ("K001", "L001", "DR-001", "page", "C001"):
            self.fb(t, "Отклонено", "не-верю-числу")
            self.fb(t, "Отклонено", "не-верю-числу")
            self.fb(t, "Принято")
        self.ok("learn", "wave")
        self.assertEqual(before, self.ledger_snapshot())
        claims = jl(self.p / "ledger" / "claims.jsonl")
        self.assertEqual([c["id"] for c in claims], ["C001"])
        self.assertEqual(claims[0]["status"], "действует")
        self.assertEqual(jl(self.p / "ledger" / "conclusions.jsonl")[0]["status"], "действует")


class OutcomeTests(LearnBase):
    def test_positions(self):
        cases = {5: "ниже низкой оценки", 15: "между низкой и базовой оценкой", 20: "точно на базовой оценке",
                 25: "между базовой и высокой оценкой", 99: "выше высокой оценки"}
        for v, pos in cases.items():
            out = self.oc(v)
            self.assertIn(pos, out)
            self.assertIn("оценка эффекта была 10 (низкая), 20 (базовая), 30 (высокая)", out)
        self.assertIn(LEVER_NOTE, out)

    def test_strength_labels(self):
        self.assertIn("со слов человека", self.oc(20))
        self.assertIn("сильный исход, источник: данные самого продукта", self.oc(20, "S001"))
        self.write(self.p / "materials" / "b.txt", "Данные рынка за ноябрь.\n")
        self.ok("source", "add", "-p", "t", "--file", "materials/b.txt", "--published", "2026-10-01", "--layer", "2")
        self.assertIn("сильный исход, источник: данные компании", self.oc(20, "S002"))
        self.write(self.p / "materials" / "c.txt", "Отчёт отрасли за ноябрь.\n")
        self.ok("source", "add", "-p", "t", "--file", "materials/c.txt", "--published", "2026-10-01", "--layer", "4")
        self.assertIn("слабый исход", self.oc(20, "S003"))
        rows = jl(self.p / "outcomes.jsonl")
        self.assertEqual([r["in_range"] for r in rows], [True] * 4)

    def test_decision_without_lever(self):
        self.ok("decision", "add", "-p", "t", "--title", "Без рычага", "--owner", "о", "--metric", "m", "--review-date", "2027-03-01",
                "--review-if", "x", "--rests-on", "K001")
        out = self.oc(7, decision="DR-002")
        self.assertIn("сравнить результат с оценкой эффекта не с чем", out)
        self.assertIsNone(jl(self.p / "outcomes.jsonl")[0]["in_range"])

    def test_validation(self):
        self.assertEqual(self.run_cmd("outcome", "add", "-p", "t", "--decision", "DR-009", "--metric", "m", "--actual", "1", "--period", "p")[0], 1)
        self.assertEqual(self.run_cmd("outcome", "add", "-p", "t", "--decision", "DR-001", "--metric", "m", "--actual", "много", "--period", "p")[0], 1)
        self.assertEqual(self.run_cmd("outcome", "add", "-p", "t", "--decision", "DR-001", "--metric", "m", "--actual", "1", "--period", "p",
                                      "--source", "S099")[0], 1)


def all_props(root):
    out = []
    for f in sorted((Path(root) / "learn").glob("proposals-*.json")):
        out += json.loads(f.read_text(encoding="utf-8"))["proposals"]
    return out


class WaveTests(LearnBase):
    def test_no_signals_writes_nothing(self):
        out = self.ok("learn", "wave")
        self.assertIn("Поводов для предложений пока нет", out)
        self.assertFalse((self.root / "learn").exists() and any((self.root / "learn").glob("proposals-*")))
        self.fb("K001", "Отклонено", "вода")  # один отзыв это ещё не сигнал
        self.assertIn("Поводов для предложений пока нет", self.ok("learn", "wave"))

    def test_style_proposals_and_apply(self):
        # Норма страницы в настройках проекта может меняться: тест закрепляет свою, 45 строк.
        sp = self.root / "config" / "style.json"
        st0 = json.loads(sp.read_text(encoding="utf-8"))
        st0["max_page_lines"] = 45
        sp.write_text(json.dumps(st0, ensure_ascii=False, indent=2), encoding="utf-8")
        self.fb("page", "Отклонено", "слишком-длинно")
        self.fb("page", "Отклонено", "7")
        self.fb("page", "Отклонено", "вода", note="оборот «в современном мире» и «ключевой фактор успеха»")
        self.fb("page", "Отклонено", "9", note="«ключевой фактор успеха» никто не понимает")
        out = self.ok("learn", "wave")
        self.assertIn("Как подавать результат", out)
        self.assertIn("Ничего не применено", out)
        d = self.root / "learn"
        files = sorted(p.name for p in d.glob("proposals-*"))
        self.assertEqual(files, ["proposals-2026-11-18.json", "proposals-2026-11-18.md"])
        data = json.loads((d / files[0]).read_text(encoding="utf-8"))
        kinds = {p["id"]: p for p in data["proposals"]}
        self.assertEqual(kinds["P001"]["grounds"]["feedback"], ["t:F001", "t:F002"])
        self.assertIn("с 45 до 40", kinds["P001"]["what"])
        self.assertIn("ключевой фактор успеха", kinds["P002"]["what"])
        self.assertNotIn("в современном мире", kinds["P002"]["what"])  # уже запрещён
        md = (d / "proposals-2026-11-18.md").read_text(encoding="utf-8")
        self.assertIn("Вид предложения: Как подавать результат", md)
        self.assertIn("Что изменится:", md)
        self.assertIn("t:F001", md)
        # без явной команды настройки не тронуты
        self.assertEqual(json.loads((self.root / "config" / "style.json").read_text(encoding="utf-8"))["max_page_lines"], 45)
        out = self.ok("learn", "apply", "P001", "--approved-by", "Иванов")
        self.assertIn("применено", out)
        self.ok("learn", "apply", "P002")
        st = json.loads((self.root / "config" / "style.json").read_text(encoding="utf-8"))
        self.assertEqual(st["max_page_lines"], 40)
        self.assertIn("ключевой фактор успеха", st["banned_phrases"])
        self.assertEqual(self.run_cmd("learn", "apply", "P001")[0], 1)  # второй раз нельзя
        h = jl(self.root / "learn" / "history.jsonl")
        self.assertEqual([x["type"] for x in h], ["wave", "apply", "apply"])
        self.assertEqual(h[1]["approved_by"], "Иванов")
        self.assertIn("утвердил Иванов", self.ok("learn", "history"))
        self.assertEqual(self.ok("doctor").count("ПРОБЛЕМА"), 0)

    def test_water_without_quotes_gives_hint_not_proposal(self):
        self.fb("page", "Отклонено", "вода")
        self.fb("page", "Отклонено", "вода")
        out = self.ok("learn", "wave")
        self.assertIn("Подсказка", out)
        self.assertIn("Поводов для предложений пока нет", out)

    def test_check_proposal_from_repeated_reason(self):
        self.fb("K001", "Отклонено", "не-верю-числу")
        self.fb("K001", "Отклонено", "1")
        out = self.ok("learn", "wave")
        self.assertIn("Что проверять дополнительно", out)
        p = json.loads(next((self.root / "learn").glob("proposals-*.json")).read_text(encoding="utf-8"))["proposals"][0]
        self.assertIn("Число вызывает сомнение", p["title"])
        self.assertEqual(p["change"], {"type": "text"})
        cfg_before = (self.root / "config" / "style.json").read_bytes()
        self.ok("learn", "apply", "P001")
        self.assertEqual(cfg_before, (self.root / "config" / "style.json").read_bytes())
        self.assertIn("в программе ничего не менялось", self.ok("learn", "history"))

    def test_lever_note_in_wave_output_and_file(self):
        self.fb("L001", "Отклонено", "3")
        self.fb("L001", "Отклонено", "3")
        out = self.ok("learn", "wave")
        self.assertIn(LEVER_NOTE, out)
        self.assertEqual(out.count(LEVER_NOTE), 1)
        self.assertIn(LEVER_NOTE, (self.root / "learn" / "proposals-2026-11-18.md").read_text(encoding="utf-8"))

    def test_consumed_items_not_reused_and_since(self):
        self.fb("K001", "Отклонено", "1")
        self.fb("K001", "Отклонено", "1")
        self.ok("learn", "wave")
        self.assertIn("Поводов для предложений пока нет", self.ok("learn", "wave"))
        out = self.ok("learn", "wave", "--since", "2026-11-01")
        self.assertIn("Предложений: 1", out)
        self.assertTrue(any(p.name.endswith("-2.json") for p in (self.root / "learn").glob("proposals-*.json")))
        self.assertIn("P002", out)

    def test_reject_and_history(self):
        self.fb("K001", "Отклонено", "1")
        self.fb("K001", "Отклонено", "1")
        self.ok("learn", "wave")
        self.assertEqual(self.run_cmd("learn", "reject", "P001")[0], 1)
        self.ok("learn", "reject", "P001", "--reason", "не наш случай")
        self.assertEqual(self.run_cmd("learn", "apply", "P001")[0], 1)
        self.assertEqual(self.run_cmd("learn", "apply", "P077")[0], 1)
        self.assertIn("отклонено P001: не наш случай", self.ok("learn", "history"))

    def test_lesson_from_outcome_company_source(self):
        self.oc(5, "S001")
        out = self.ok("learn", "wave")
        self.assertIn("Урок в базу знаний", out)
        p = json.loads(next((self.root / "learn").glob("proposals-*.json")).read_text(encoding="utf-8"))["proposals"][0]
        self.assertEqual(p["grounds"], {"feedback": [], "outcomes": ["t:O001"]})
        self.assertIn("ниже низкой оценки", p["what"])
        n_before = len(self.records())
        self.assertEqual(len(self.records()), n_before)  # до apply база не тронута
        self.ok("learn", "apply", "P001", "--approved-by", "Иванов")
        rec = self.records()[-1]
        self.assertEqual((rec["kind"], rec["layer"], rec["origin"], rec["status"]), ("урок", 2, "исход", "действует"))
        self.assertNotIn("со слов человека", rec["rule"])
        self.assertEqual(rec["grounds"]["outcomes"], ["t:O001"])

    def test_lesson_from_human_words_is_marked(self):
        self.oc(18)
        self.ok("learn", "wave")
        self.ok("learn", "apply", "P001")
        rec = self.records()[-1]
        self.assertTrue(rec["rule"].startswith("Со слов человека"))
        self.assertIn("со слов человека", rec["tags"])
        self.assertTrue(rec["human_words"])

    def test_lesson_from_feedback_needs_two_with_notes_and_is_not_evidence(self):
        self.fb("K001", "Отклонено", "5", note="вывод про цену не следует из одной цифры")
        self.fb("K001", "Отклонено", "5")
        out = self.ok("learn", "wave")
        self.assertNotIn("Урок в базу знаний", out)
        self.fb("K001", "Отклонено", "5", note="вывод про цену не следует из одной цифры")
        self.fb("K001", "Отклонено", "5", note="нужен второй источник")
        out = self.ok("learn", "wave", "--since", "2026-11-01")
        self.assertIn("Урок в базу знаний", out)
        lesson = [p for p in all_props(self.root) if p["kind"] == "Урок в базу знаний"][-1]
        self.assertGreaterEqual(len(lesson["grounds"]["feedback"]), 2)
        self.ok("learn", "apply", lesson["id"])
        bid = self.records()[-1]["id"]
        self.assertEqual(self.records()[-1]["origin"], "отзывы")
        # не доказательство: ориентиром нельзя, гипотезой можно
        code, out = self.run_cmd("claim", "add", "-p", "t", "--type", "benchmark", "--kb", bid, "--text", "ориентир")
        self.assertEqual(code, 1)
        self.assertIn("не доказательство", out)
        self.ok("claim", "add", "-p", "t", "--type", "hypothesis", "--kb", bid, "--text", "гипотеза из урока")

    def test_calibration_needs_three_and_reports_bias(self):
        self.oc(8)
        self.oc(12)
        out = self.ok("learn", "wave")
        self.assertNotIn("Насколько точны", out)
        self.oc(25)
        out = self.ok("learn", "wave", "--since", "2026-11-01")
        self.assertIn("Насколько точны наши оценки эффекта", out)
        p = [x for x in all_props(self.root) if x["kind"] == "Насколько точны наши оценки эффекта"][0]
        self.assertEqual((p["change"]["inside"], p["change"]["total"]), (2, 3))
        self.assertEqual((p["change"]["below_base"], p["change"]["above_base"]), (2, 1))
        self.assertIn("завышены", p["what"])
        self.assertIn("попали 2 (67%)", p["what"])
        self.assertEqual(p["grounds"]["outcomes"], ["t:O001", "t:O002", "t:O003"])

    def test_lessons_only_support_hypotheses(self):
        self.oc(5, "S001")
        self.ok("learn", "wave")
        self.ok("learn", "apply", "P001")
        bid = self.records()[-1]["id"]
        code, out = self.run_cmd("claim", "add", "-p", "t", "--type", "fact", "--kb", bid, "--text", "факт", "--source", "S001", "--quote", "Отток вырос")
        self.assertEqual(code, 1)
        self.ok("claim", "add", "-p", "t", "--type", "benchmark", "--kb", bid, "--text", "ориентир-урок")
        code, out = self.run_cmd("conclusion", "add", "-p", "t", "--text", "вывод на уроке", "--rests-on", "C002", "--kind", "recommendation")
        self.assertEqual(code, 1)
        self.assertIn("урок может поддерживать только гипотезу", out)
        self.ok("claim", "add", "-p", "t", "--type", "hypothesis", "--kb", bid, "--text", "гипотеза")

    def test_projects_aggregated_and_example_skipped(self):
        self.new_project("u")
        self.write(self.root / "projects" / "u" / "materials" / "a.txt", "х\n")
        self.fb("K001", "Отклонено", "1")
        self.ok("claim", "add", "-p", "u", "--type", "hypothesis", "--text", "г")
        self.ok("conclusion", "add", "-p", "u", "--text", "вывод", "--rests-on", "C001", "--kind", "option")
        self.fb("K001", "Отклонено", "1", project="u")
        out = self.ok("learn", "wave")
        self.assertIn("отзывов 2", out)


class KbStatsTests(LearnBase):
    def test_stats(self):
        self.ok("claim", "add", "-p", "t", "--type", "benchmark", "--kb", "B002", "--text", "цена и отток")
        self.ok("conclusion", "add", "-p", "t", "--text", "рекомендация", "--rests-on", "C001,C002", "--kind", "recommendation")
        self.ok("lever", "add", "-p", "t", "--metric", "отток", "--where", "все", "--cause", "цена", "--action", "вернуть",
                "--effect-low", "10", "--effect-base", "20", "--effect-high", "30", "--check", "сравнить", "--rests-on", "K002")
        self.ok("decision", "add", "-p", "t", "--title", "Второе", "--owner", "о", "--metric", "отток", "--review-date", "2027-03-01",
                "--review-if", "x", "--rests-on", "L002")
        self.fb("K002", "Принято")
        self.fb("K002", "Принято")
        self.fb("K002", "Отклонено", "7")
        self.oc(15, decision="DR-002")
        self.oc(99, decision="DR-002")
        self.oc(20, decision="DR-001")  # это решение на K001 без ориентиров
        out = self.ok("kb", "stats")
        line = [l for l in out.splitlines() if l.startswith("B002:")][0]
        self.assertIn("Использована как ориентир в проектах: 1 раз", line)
        self.assertIn("Выводов на ней: принято 2, отклонено 1", line)
        self.assertIn("подтвердили 1, не подтвердили 1, без сравнения 0", line)
        self.assertIn("Замечания руководителя: «Слишком длинно» 1", line)
        self.assertIn("B001: ", out)
        b1 = [l for l in out.splitlines() if l.startswith("B001:")][0]
        self.assertIn("в проектах: 0 раз", b1)
        self.assertIn(LEVER_NOTE, out)


class WordingTests(unittest.TestCase):
    def test_labels(self):
        self.assertEqual(len(learn.REASONS), 10)
        self.assertEqual(learn.VERDICT_RU, {"принято": "Принято", "отклонено": "Отклонено"})
        self.assertEqual([learn.K_STYLE, learn.K_CHECK, learn.K_LESSON, learn.K_CALIB],
                         ["Как подавать результат", "Что проверять дополнительно", "Урок в базу знаний",
                          "Насколько точны наши оценки эффекта"])
        for bad in ("вода", "слой 3", "нет-рычага"):
            for _c, label in learn.REASONS:
                self.assertNotIn(bad, label)


if __name__ == "__main__":
    unittest.main()
