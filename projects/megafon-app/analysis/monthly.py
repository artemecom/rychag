# Ряд оценок по месяцам из выгрузки отзывов RuStore. Печатает таблицу, она становится источником.
import csv
import sys
from collections import defaultdict
from statistics import mean, pstdev

with open(sys.argv[1], encoding="utf-8", newline="") as f:
    rows = list(csv.DictReader(f))

by = defaultdict(list)
for r in rows:
    by[r["date"][:7]].append(int(r["rating"]))

print("Всего отзывов: %d, период %s .. %s" % (len(rows), min(r["date"] for r in rows), max(r["date"] for r in rows)))
print("Средняя оценка по выгрузке: %.2f" % mean(int(r["rating"]) for r in rows))
print("Доля оценок 1-2 по выгрузке: %.1f%%" % (100 * sum(int(r["rating"]) <= 2 for r in rows) / len(rows)))
print("Доля оценок 5 по выгрузке: %.1f%%" % (100 * sum(int(r["rating"]) == 5 for r in rows) / len(rows)))
print("месяц | отзывов | средняя | доля 1-2, % | доля 5, %")
means = []
for m in sorted(by):
    v = by[m]
    means.append(mean(v))
    print("%s | %d | %.2f | %.1f | %.1f" % (m, len(v), mean(v), 100 * sum(x <= 2 for x in v) / len(v), 100 * sum(x == 5 for x in v) / len(v)))
full = [m for m in sorted(by) if m not in ("2025-12", "2026-11")]
vals = [mean(by[m]) for m in full]
print("Полные месяцы (без 2025-12 и 2026-11): средняя месячных средних %.2f, разброс %.2f, мин %.2f, макс %.2f" % (mean(vals), pstdev(vals), min(vals), max(vals)))
for m in ("2025-12", "2026-11"):
    print("Неполный месяц %s: первая/последняя дата %s / %s" % (m, min(r["date"] for r in rows if r["date"][:7] == m), max(r["date"] for r in rows if r["date"][:7] == m)))
