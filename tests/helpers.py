# -*- coding: utf-8 -*-
"""Помощники для тестов: временная копия репозитория и запуск команд в процессе."""
import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import rychag  # noqa: E402


class Env(unittest.TestCase):
    TODAY = "2026-11-18"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rychag-test-"))
        self.addCleanup(shutil.rmtree, str(self.tmp), True)
        self.root = self.tmp / "repo"
        shutil.copytree(str(ROOT / "config"), str(self.root / "config"))
        shutil.copytree(str(ROOT / "projects" / "_example"), str(self.root / "projects" / "_example"),
                        ignore=shutil.ignore_patterns("__pycache__"))
        # Большинство тестов проходят этапы без человека. Обязательный ответ на остановках проверяет tests/test_stops.py.
        (self.root / "config" / "process.json").write_text('{"stops_need_answer": false}', encoding="utf-8")

    def run_cmd(self, *args, today=None):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            code = rychag.main(["--root", str(self.root), "--today", today or self.TODAY] + list(args))
        return code, buf.getvalue()

    def ok(self, *args, **kw):
        code, out = self.run_cmd(*args, **kw)
        self.assertEqual(code, 0, "ожидался код 0, вывод:\n" + out)
        return out

    def new_project(self, pid="t", question="Почему упало?"):
        self.ok("new", pid, "--question", question)
        return self.root / "projects" / pid

    def write(self, path, text):
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def set_config(self, name, data):
        (self.root / "config" / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def verify_json(self, *args):
        code, out = self.run_cmd("verify", "--json", *args)
        return code, json.loads(out)

    def issues_text(self, data, layer):
        return " ".join(i["what"] for i in data["layers"][str(layer)]["issues"])
