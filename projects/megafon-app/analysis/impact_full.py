# Служебный: отмечает под-вопросом всё, что опирается на утверждения, пересчитанные по полной выгрузке. Запуск из корня папки rychag.
import subprocess

IDS = ["C005", "C006", "C007", "C009", "C014", "C016", "C017", "C019", "C020", "C021", "C022", "C023", "C034"]
for c in IDS:
    r = subprocess.run(["python3", "tools/rychag.py", "impact", c, "--mark", "--project", "megafon-app"], capture_output=True, text=True)
    out = (r.stdout + r.stderr).splitlines()
    print(c, "|", [l for l in out if l.startswith("Задето") or l.startswith("Поставлен")])
