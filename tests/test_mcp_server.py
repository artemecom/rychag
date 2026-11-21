# -*- coding: utf-8 -*-
"""Проверки сервера MCP без интернета: сервер запускается как отдельная программа,
сеть для store_reviews подменяется локальным сервером на этом же компьютере."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "tools" / "mcp_server.py"

EXPECTED_TOOLS = {"rychag_status", "kb_search", "map_causes", "rychag_verify", "rychag_impact", "store_reviews",
                  "req_list", "strategy_check", "route_suggest", "cost_report", "incident_add", "incident_list", "state_receipt",
                  "doc_check", "assumptions_list"}


def run_session(messages, root, extra_env=None):
    """Отправить сообщения серверу, закрыть ввод, вернуть ответы по номеру."""
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    env.update(extra_env or {})
    data = "".join(json.dumps(m, ensure_ascii=False) + "\n" for m in messages)
    proc = subprocess.run([sys.executable, str(SERVER), "--root", str(root)], input=data.encode("utf-8"),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120, env=env)
    lines = [l for l in proc.stdout.decode("utf-8").splitlines() if l.strip()]
    replies = [json.loads(l) for l in lines]
    return proc, replies


def init_msg():
    return {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}}}


def call_msg(msg_id, name, arguments):
    return {"jsonrpc": "2.0", "id": msg_id, "method": "tools/call", "params": {"name": name, "arguments": arguments}}


class FakeRuStore(BaseHTTPRequestHandler):
    hits = []

    def do_GET(self):
        FakeRuStore.hits.append(self.path)
        item = {"commentId": 1, "appRating": 2, "firstName": "СекретноеИмя", "commentDate": "2026-11-18 10:00:00.000",
                "commentText": "Очень\nплохо работает", "devResponse": None}
        body = json.dumps({"code": "OK", "body": {"content": [item] * 100}}, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class McpServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="rychag-mcp-"))
        cls.root = cls.tmp / "repo"
        for name in ("config", "knowledge"):
            shutil.copytree(str(ROOT / name), str(cls.root / name))
        for name in ("nodes.jsonl", "links.jsonl"):  # в поставку попала настоящая карта причин: для проверки пустой карты убираем её из копии
            (cls.root / "knowledge" / "map" / name).unlink()
        shutil.copytree(str(ROOT / "projects" / "_example"), str(cls.root / "projects" / "_example"),
                        ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(str(ROOT / "tools"), str(cls.root / "tools"), ignore=shutil.ignore_patterns("__pycache__"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), True)

    def test_initialize_and_list(self):
        proc, replies = run_session([init_msg(),
                                     {"jsonrpc": "2.0", "method": "notifications/initialized"},
                                     {"jsonrpc": "2.0", "id": 2, "method": "ping"},
                                     {"jsonrpc": "2.0", "id": 3, "method": "tools/list"}], self.root)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8"))
        self.assertEqual([r["id"] for r in replies], [1, 2, 3], "на уведомление отвечать нельзя")
        init = replies[0]["result"]
        self.assertEqual(init["protocolVersion"], "2025-06-18")
        self.assertIn("tools", init["capabilities"])
        self.assertEqual(init["serverInfo"]["name"], "rychag")
        self.assertEqual(replies[1]["result"], {})
        tools = replies[2]["result"]["tools"]
        self.assertEqual({t["name"] for t in tools}, EXPECTED_TOOLS)
        for t in tools:
            self.assertTrue(t["description"].strip())
            self.assertEqual(t["inputSchema"]["type"], "object")
            self.assertIn("properties", t["inputSchema"])

    def test_unknown_protocol_version_gets_supported_one(self):
        msg = init_msg()
        msg["params"]["protocolVersion"] = "1999-01-01"
        _, replies = run_session([msg], self.root)
        self.assertIn(replies[0]["result"]["protocolVersion"], ("2025-06-18", "2025-03-26", "2024-11-05"))

    def test_status_on_example(self):
        _, replies = run_session([init_msg(), call_msg(2, "rychag_status", {"project": "_example"})], self.root)
        res = replies[1]["result"]
        self.assertFalse(res["isError"])
        self.assertIn("Проект: _example", res["content"][0]["text"])

    def test_verify_on_example(self):
        _, replies = run_session([init_msg(), call_msg(2, "rychag_verify", {"project": "_example"})], self.root)
        res = replies[1]["result"]
        self.assertFalse(res["isError"])
        self.assertIn("все проверенные слои пройдены", res["content"][0]["text"])

    def test_impact_and_unknown_id(self):
        _, replies = run_session([init_msg(), call_msg(2, "rychag_impact", {"project": "_example", "id": "C001"}),
                                  call_msg(3, "rychag_impact", {"project": "_example", "id": "NOPE"})], self.root)
        self.assertIn("K002", replies[1]["result"]["content"][0]["text"])
        self.assertTrue(replies[2]["result"]["isError"])
        self.assertIn("нет в реестре", replies[2]["result"]["content"][0]["text"])

    def test_kb_search_and_map_causes(self):
        _, replies = run_session([init_msg(), call_msg(2, "kb_search", {"query": "отток", "limit": 2}),
                                  call_msg(3, "map_causes", {"metric": "отток"})], self.root)
        text = replies[1]["result"]["content"][0]["text"]
        self.assertIn("Слой", text)
        self.assertLessEqual(len([l for l in text.splitlines() if l.startswith("B")]), 2)
        self.assertIn("map node", replies[2]["result"]["content"][0]["text"])  # карта пока пуста: понятное сообщение

    def test_requirements_strategy_route_cost(self):
        _, replies = run_session([init_msg(), call_msg(2, "req_list", {"project": "_example"}),
                                  call_msg(3, "strategy_check", {"project": "_example"}),
                                  call_msg(4, "route_suggest", {"step": "диагностика причины просадки"}),
                                  call_msg(5, "cost_report", {"project": "_example"}),
                                  call_msg(6, "route_suggest", {"step": "qqq"}),
                                  call_msg(7, "route_suggest", {})], self.root)
        texts = [r["result"]["content"][0]["text"] for r in replies[1:]]
        for r in replies[1:5]:
            self.assertFalse(r["result"]["isError"])
        self.assertIn("Требований из запроса", texts[0])
        self.assertIn("Все обязательные части на месте", texts[1])
        self.assertIn("Класс модели: сильная", texts[2])
        self.assertIn("Расход по этапам", texts[3])
        self.assertTrue(replies[5]["result"]["isError"])
        self.assertTrue(replies[6]["result"]["isError"])

    def test_document_check_and_assumptions(self):
        _, replies = run_session([init_msg(), call_msg(2, "doc_check", {"project": "_example"}),
                                  call_msg(3, "assumptions_list", {"project": "_example"})], self.root)
        self.assertFalse(replies[1]["result"]["isError"])
        self.assertIn("Структура документа не задана", replies[1]["result"]["content"][0]["text"])
        self.assertFalse(replies[2]["result"]["isError"])
        self.assertIn("Допущений нет", replies[2]["result"]["content"][0]["text"])

    def test_bad_input_is_a_tool_error_not_a_crash(self):
        msgs = [init_msg(), call_msg(2, "kb_search", {}), call_msg(3, "rychag_status", {"project": "--x"}),
                call_msg(4, "no_such_tool", {}), {"jsonrpc": "2.0", "id": 5, "method": "nothing/here"},
                call_msg(6, "store_reviews", {"package_name": "a b;c"})]
        proc, replies = run_session(msgs, self.root)
        self.assertEqual(proc.returncode, 0)
        self.assertTrue(replies[1]["result"]["isError"])
        self.assertTrue(replies[2]["result"]["isError"])
        self.assertEqual(replies[3]["error"]["code"], -32602)
        self.assertEqual(replies[4]["error"]["code"], -32601)
        self.assertTrue(replies[5]["result"]["isError"])

    def test_garbage_line_gives_parse_error_and_server_continues(self):
        env = dict(os.environ)
        data = b"not json\n" + (json.dumps({"jsonrpc": "2.0", "id": 7, "method": "ping"}) + "\n").encode("utf-8")
        proc = subprocess.run([sys.executable, str(SERVER), "--root", str(self.root)], input=data,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60, env=env)
        replies = [json.loads(l) for l in proc.stdout.decode("utf-8").splitlines()]
        self.assertEqual(replies[0]["error"]["code"], -32700)
        self.assertEqual(replies[1]["id"], 7)


class StoreReviewsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = HTTPServer(("127.0.0.1", 0), FakeRuStore)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def test_reviews_limit_no_names_and_pause(self):
        import time
        FakeRuStore.hits = []
        env = {"RYCHAG_RUSTORE_URL": "http://127.0.0.1:{}/comment".format(self.port)}
        t0 = time.time()
        _, replies = run_session([init_msg(), call_msg(2, "store_reviews",
                                  {"package_name": "ru.example.app", "max_pages": 2, "delay_seconds": 0.5})], ROOT, env)
        elapsed = time.time() - t0
        res = replies[1]["result"]
        self.assertFalse(res["isError"])
        text = res["content"][0]["text"]
        self.assertEqual(len(FakeRuStore.hits), 2, "страниц ровно столько, сколько просили")
        self.assertIn("packageName=ru.example.app", FakeRuStore.hits[0])
        self.assertIn("pageSize=100", FakeRuStore.hits[0])
        self.assertIn("sortBy=NEW_FIRST", FakeRuStore.hits[0])
        self.assertIn("pageNumber=1", FakeRuStore.hits[1])
        self.assertNotIn("СекретноеИмя", text)
        self.assertIn("2026-11-18 | 2 | Очень плохо работает", text)
        self.assertIn("отзывов 200", text)
        self.assertGreaterEqual(elapsed, 0.5)

    def test_page_limit_is_enforced(self):
        _, replies = run_session([init_msg(), call_msg(2, "store_reviews", {"package_name": "ru.example.app", "max_pages": 50})], ROOT)
        self.assertTrue(replies[1]["result"]["isError"])

    def test_network_error_is_clear(self):
        env = {"RYCHAG_RUSTORE_URL": "http://127.0.0.1:9/comment"}  # порт, на котором никто не слушает
        _, replies = run_session([init_msg(), call_msg(2, "store_reviews", {"package_name": "ru.example.app", "max_pages": 1})], ROOT, env)
        res = replies[1]["result"]
        self.assertTrue(res["isError"])
        self.assertIn("Не удалось связаться с RuStore", res["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()
