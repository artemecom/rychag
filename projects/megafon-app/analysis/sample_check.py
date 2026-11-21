# Выборка для проверки словаря тем: 150 случайных отзывов 1-2 (зерно 7).
# Пишет файл для слепой разметки (без флагов словаря) и файл-ключ с флагами словаря.
import csv
import json
import random
import re
import sys

src, out_dir = sys.argv[1], sys.argv[2]
code = open("projects/megafon-app/analysis/themes.py", encoding="utf-8").read()
start = code.index("THEMES = ")
end = code.index("\n}\n", start) + 3
ns = {}
exec(code[start:end], ns)
T = ns["THEMES"]
rows = [r for r in csv.DictReader(open(src, encoding="utf-8", newline="")) if int(r["rating"]) <= 2]
random.seed(7)
idx = random.sample(range(len(rows)), 150)
blind, key = [], {}
for n, i in enumerate(idx, 1):
    t = rows[i]["text"].replace("\n", " ").strip()
    blind.append("%03d | %s" % (n, t))
    low = t.lower()
    key[n] = {k: bool(re.search(rx, low)) for k, rx in T.items()}
open(out_dir + "/sample_blind.txt", "w", encoding="utf-8").write("\n".join(blind) + "\n")
json.dump({"themes": list(T), "flags": key}, open(out_dir + "/sample_key.json", "w", encoding="utf-8"), ensure_ascii=False)
print(len(rows), "отзывов 1-2; в выборке", len(idx))
