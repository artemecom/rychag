#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Создаёт навыки (skills) в открытом формате Agent Skills из файлов methods/.

Содержимое методик не копируется: навык это короткая обёртка с описанием
«когда применять» и указанием прочитать файл методики. Источник один: methods/.

Запуск:
  python3 tools/sync_skills.py           пересоздать .claude/skills/
  python3 tools/sync_skills.py --check   только проверить, код 2 если что-то устарело
"""
import argparse
import re
import sys
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parents[1]
MAX_DESCRIPTION = 900

START_NAME = "rychag-start"
START_DESCRIPTION = (
    "Начало любого разговора с агентом «Рычаг»: новая сессия, новый чат, возвращение после перерыва "
    "или первая реплика человека. Показывает, где остановились, и ведёт к следующему шагу."
)
START_BODY = """# Ритуал старта «Рычага»

Прочитай раздел «Начало любого разговора» в файле `AGENTS.md` (путь от корня репозитория) и выполни его по порядку:

1. Выполни `python3 tools/rychag.py status`. Он назовёт этап, что сделано, открытые вопросы и следующий шаг.
2. Задачи нет: спроси у человека вопрос одной фразой и создай её командой `python3 tools/rychag.py new <имя> --question "<вопрос>"`.
3. Задач несколько: спроси, с какой работаем, и добавляй `--project <имя>` ко всем командам.
4. Прочитай `methods/INDEX.md`, выбери методики для текущего этапа, открой их навыки и действуй.
5. Заказчик сам назвал части результата (например, «один документ из пяти частей»): действуй по разделу «Если заказчик задал структуру результата» в `AGENTS.md` и по разделу «Документ по частям заказчика» в `methods/INDEX.md`.

После перерыва или в новом чате не начинай заново: продолжай с того, что показал `status`. Перед концом ответа выполни `python3 tools/rychag.py gate`.
"""


def yaml_quote(text):
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def skill_name(method_path):
    stem = method_path.stem
    return re.sub(r"^\d+-", "", stem)


def method_title(text):
    first = text.splitlines()[0] if text else ""
    m = re.match(r"#\s*(\d+)\.\s*(.+)", first)
    if not m:
        raise ValueError("нет заголовка вида «# NN. Название»")
    return m.group(1), m.group(2).strip()


def when_to_apply(text):
    """Первый абзац раздела «Когда применять», без части «Когда не применять»."""
    m = re.search(r"^##\s*Когда применять\s*\n(.*?)(?=^##\s|\Z)", text, re.S | re.M)
    if not m:
        raise ValueError("нет раздела «Когда применять»")
    body = m.group(1).strip()
    first = body.split("\n\n")[0]
    first = re.sub(r"\s+", " ", first).strip()
    return first.replace("`", "")


def build_method_skill(method_path, root):
    text = method_path.read_text(encoding="utf-8")
    number, title = method_title(text)
    when = when_to_apply(text)
    desc = "Методика {} «{}». Когда применять: {}".format(number, title, when)
    if len(desc) > MAX_DESCRIPTION:
        desc = desc[: MAX_DESCRIPTION - 1].rstrip() + "…"
    rel = method_path.relative_to(root).as_posix()
    body = (
        "# {title}\n\n"
        "Прочитай файл `{rel}` целиком (путь от корня репозитория) и действуй строго по нему: "
        "там шаги, команды записи, шаблон результата и проверка. "
        "Не пересказывай методику по памяти, единственный источник это файл.\n\n"
        "Команды пишутся как `rychag ...`, это `python3 tools/rychag.py ...`. "
        "Задач несколько: добавляй `--project <имя>`. "
        "Общие правила работы лежат в `AGENTS.md`.\n"
    ).format(title="{}. {}".format(number, title), rel=rel)
    return skill_name(method_path), desc, body


def render(name, desc, body):
    return "---\nname: {}\ndescription: {}\n---\n\n{}".format(name, yaml_quote(desc), body)


def expected_skills(root):
    root = Path(root)
    out = {}
    for mp in sorted((root / "methods").glob("[0-9][0-9]-*.md")):
        name, desc, body = build_method_skill(mp, root)
        out[name] = render(name, desc, body)
    out[START_NAME] = render(START_NAME, START_DESCRIPTION, START_BODY)
    return out


def check(root):
    """Список проблем (пустой, если всё актуально)."""
    root = Path(root)
    skills_dir = root / ".claude" / "skills"
    problems = []
    expected = expected_skills(root)
    for name, content in expected.items():
        p = skills_dir / name / "SKILL.md"
        if not p.exists():
            problems.append("нет навыка {} (файл {})".format(name, p.relative_to(root).as_posix()))
        elif p.read_text(encoding="utf-8") != content:
            problems.append("навык {} устарел: описание или текст не совпадает с методикой".format(name))
    if skills_dir.exists():
        for d in sorted(skills_dir.iterdir()):
            if d.is_dir() and d.name not in expected and (d / "SKILL.md").exists():
                problems.append("лишний навык {}: для него нет методики".format(d.name))
    return problems


def sync(root):
    root = Path(root)
    skills_dir = root / ".claude" / "skills"
    expected = expected_skills(root)
    changed = 0
    for name, content in expected.items():
        p = skills_dir / name / "SKILL.md"
        if p.exists() and p.read_text(encoding="utf-8") == content:
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        changed += 1
    return len(expected), changed


def main(argv=None):
    ap = argparse.ArgumentParser(description="Пересоздать навыки .claude/skills/ из методик methods/")
    ap.add_argument("--root", default=str(DEFAULT_ROOT), help="корень репозитория")
    ap.add_argument("--check", action="store_true", help="только проверить, ничего не писать (код 2 при расхождении)")
    args = ap.parse_args(argv)
    if args.check:
        problems = check(args.root)
        if problems:
            for p in problems:
                print("Не так: " + p)
            print("Исправить: python3 tools/sync_skills.py")
            return 2
        print("Навыки актуальны.")
        return 0
    total, changed = sync(args.root)
    print("Навыков: {}, обновлено: {}. Папка: .claude/skills/".format(total, changed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
