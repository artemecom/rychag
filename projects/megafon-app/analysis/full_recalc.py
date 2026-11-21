# Пересчёт задетых выводов по полной выгрузке (11 221 отзыв, 2022-08..2026-11).
# 1) оценки без текста; 2) темы жалоб по полугодиям (словарь из themes.py); 3) месяцы вокруг просадки 2025 и 2024: версии приложения.
import csv
import re
import sys
from collections import Counter, defaultdict

rows = list(csv.DictReader(open(sys.argv[1], encoding="utf-8", newline="")))
import os

code = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "themes.py"), encoding="utf-8").read()
start = code.index("THEMES = ")
end = code.index("\n}\n", start) + 3
ns = {}
exec(code[start:end], ns)
T = ns["THEMES"]
RX = {k: re.compile(v) for k, v in T.items()}
short = {"бот": [k for k in T if k.startswith("бот")][0], "человек": [k for k in T if k.startswith("нет живого")][0],
         "самоподключение": [k for k in T if k.startswith("самоподключение")][0], "сбои": [k for k in T if k.startswith("сбои")][0],
         "цены": [k for k in T if k.startswith("цены")][0], "связь": [k for k in T if k.startswith("связь")][0]}

# 1) молчаливые оценки
N_RATINGS, AVG = 29700, 3.2
n = len(rows)
mean = sum(int(r["rating"]) for r in rows) / n
for lo, hi, lab in ((3.15, 3.25, "диапазон рейтинга 3,15-3,25"), (AVG, AVG, "рейтинг 3,2")):
    pass
sil = N_RATINGS - n
est = lambda avg: (avg * N_RATINGS - mean * n) / sil
print("Отзывов %d, средняя по отзывам %.2f, оценок без текста %d (%.1f%%): их средняя %.2f (рейтинг 3,15: %.2f, 3,25: %.2f)" % (n, mean, sil, 100 * sil / N_RATINGS, est(3.2), est(3.15), est(3.25)))

# 2) темы по полугодиям среди отзывов 1-2
low = [r for r in rows if int(r["rating"]) <= 2]
half = lambda d: d[:4] + ("-H1" if d[5:7] <= "06" else "-H2")
tot = Counter(half(r["date"]) for r in low)
hit = defaultdict(Counter)
for r in low:
    t = r["text"].lower()
    for key, name in short.items():
        if RX[name].search(t):
            hit[key][half(r["date"])] += 1
print("полугодие | отзывов 1-2 | " + " | ".join(short))
for h in sorted(tot):
    print("%s | %d | " % (h, tot[h]) + " | ".join("%.1f" % (100 * hit[k][h] / tot[h]) for k in short))

# 3) версии вокруг просадок
by_m = defaultdict(list)
for r in rows:
    by_m[r["date"][:7]].append(r)
for m in ("2024-01", "2024-02", "2025-05", "2025-06", "2025-07", "2025-08"):
    rs = by_m[m]
    v = Counter(r["app_version_code"] for r in rs).most_common(3)
    print("месяц %s: отзывов %d, средняя %.2f, версии: %s" % (m, len(rs), sum(int(r["rating"]) for r in rs) / len(rs), ", ".join("%s (%d)" % x for x in v)))
# первые даты по кодам версий в 2025
first = {}
for r in sorted(rows, key=lambda r: r["date"]):
    first.setdefault(r["app_version_code"], r["date"])
vs = sorted((d, c) for c, d in first.items() if "2025-04" <= d[:7] <= "2025-08")
print("первые отзывы по кодам версий (2025-04..2025-08): " + ", ".join("%s %s" % (d, c) for d, c in vs[:14]))
# средняя по версии для версий с 30+ отзывами в 2025-05..2025-08
agg = defaultdict(list)
for r in rows:
    if "2025-05" <= r["date"][:7] <= "2025-08":
        agg[r["app_version_code"]].append(int(r["rating"]))
print("версии 2025-05..08 с 30+ отзывами: " + ", ".join("%s: %d отзывов, средняя %.2f" % (c, len(v), sum(v) / len(v)) for c, v in sorted(agg.items()) if len(v) >= 30))
