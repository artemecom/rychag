# -*- coding: utf-8 -*-
"""Навыки в .claude/skills/ должны совпадать с методиками methods/."""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import sync_skills  # noqa: E402


class SkillsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rychag-skills-"))
        self.addCleanup(shutil.rmtree, str(self.tmp), True)
        self.root = self.tmp / "repo"
        shutil.copytree(str(ROOT / "methods"), str(self.root / "methods"))
        shutil.copytree(str(ROOT / ".claude" / "skills"), str(self.root / ".claude" / "skills"))

    def test_repository_skills_are_current(self):
        self.assertEqual(sync_skills.check(ROOT), [], "запустите: python3 tools/sync_skills.py")

    def test_every_method_has_a_skill_with_description(self):
        methods = sorted((ROOT / "methods").glob("[0-9][0-9]-*.md"))
        self.assertEqual(len(methods), 26)
        for m in methods:
            skill = ROOT / ".claude" / "skills" / sync_skills.skill_name(m) / "SKILL.md"
            self.assertTrue(skill.exists(), "нет навыка для " + m.name)
            text = skill.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("---\nname: " + sync_skills.skill_name(m) + "\n"))
            self.assertIn("description: ", text)
            self.assertIn("methods/" + m.name, text, "навык не указывает на файл методики")
            self.assertLess(len(text), 2000, "обёртка не должна копировать методику")
        self.assertTrue((ROOT / ".claude" / "skills" / "rychag-start" / "SKILL.md").exists())

    def test_missing_skill_is_detected(self):
        shutil.rmtree(str(self.root / ".claude" / "skills" / "vklad-sreza"))
        problems = sync_skills.check(self.root)
        self.assertTrue(any("vklad-sreza" in p and "нет навыка" in p for p in problems), problems)

    def test_outdated_description_is_detected(self):
        method = self.root / "methods" / "03-poisk-prichiny-prosadki.md"
        method.write_text(method.read_text(encoding="utf-8").replace("Этап 4, после сбора", "Этап 9, после сбора"), encoding="utf-8")
        problems = sync_skills.check(self.root)
        self.assertTrue(any("poisk-prichiny-prosadki" in p and "устарел" in p for p in problems), problems)

    def test_sync_repairs_and_check_passes(self):
        shutil.rmtree(str(self.root / ".claude" / "skills" / "vklad-sreza"))
        sync_skills.sync(self.root)
        self.assertEqual(sync_skills.check(self.root), [])

    def test_orphan_skill_is_detected(self):
        orphan = self.root / ".claude" / "skills" / "lishniy"
        orphan.mkdir(parents=True)
        (orphan / "SKILL.md").write_text("---\nname: lishniy\ndescription: x\n---\n", encoding="utf-8")
        self.assertTrue(any("лишний" in p for p in sync_skills.check(self.root)))

    def test_check_exit_code(self):
        self.assertEqual(sync_skills.main(["--root", str(ROOT), "--check"]), 0)
        shutil.rmtree(str(self.root / ".claude" / "skills" / "vklad-sreza"))
        self.assertEqual(sync_skills.main(["--root", str(self.root), "--check"]), 2)


if __name__ == "__main__":
    unittest.main()
