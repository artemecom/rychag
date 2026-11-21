# Выборка 150 случайных отзывов 1-2 старше 2025-12-06 (зерно 11) для проверки словаря на новой части выгрузки.
# Пишет слепой файл (без флагов) и файл-ключ в папку analysis.
import csv
import json
import os
import random
import re
import sys

here = os.path.dirname(os.path.abspath(__file__))
code = open(os.path.join(here, "themes.py"), encoding="utf-8").read()
start = code.index("THEMES = ")
end = code.index("\n}\n", start) + 3
ns = {}
exec(code[start:end], ns)
T = ns["THEMES"]
rows = [r for r in csv.DictReader(open(sys.argv[1], encoding="utf-8", newline="")) if int(r["rating"]) <= 2 and r["date"] < "2025-12-06"]
random.seed(11)
idx = random.sample(range(len(rows)), 150)
blind, key = [], {}
for n, i in enumerate(idx, 1):
    t = rows[i]["text"].replace("\n", " ").strip()
    blind.append("%03d | %s" % (n, t))
    low = t.lower()
    key[n] = {k: bool(re.search(rx, low)) for k, rx in T.items()}
open(os.path.join(here, "sample_old_blind.txt"), "w", encoding="utf-8").write("\n".join(blind) + "\n")
json.dump({"themes": list(T), "flags": key}, open(os.path.join(here, "sample_old_key.json"), "w", encoding="utf-8"), ensure_ascii=False)
print("отзывов 1-2 до 2025-12-06: %d; в выборке %d" % (len(rows), len(idx)))
