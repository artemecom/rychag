# Сравнение прежней выгрузки (4000 отзывов) с полной (11 221): что вошло, за какой период, как менялись оценки.
import csv
import sys
from collections import Counter

old = list(csv.DictReader(open(sys.argv[1], encoding="utf-8", newline="")))
full = list(csv.DictReader(open(sys.argv[2], encoding="utf-8", newline="")))
print("строк: прежняя %d, полная %d" % (len(old), len(full)))
print("период прежней: %s .. %s; полной: %s .. %s" % (min(r["date"] for r in old), max(r["date"] for r in old), min(r["date"] for r in full), max(r["date"] for r in full)))
key = lambda r: (r["date"], r["rating"], r["text"].strip())
so, sf = Counter(key(r) for r in old), Counter(key(r) for r in full)
missing = sum((so - sf).values())
print("из прежней нет в полной: %d" % missing)
print("средняя оценка: прежняя %.2f, полная %.2f" % (sum(int(r["rating"]) for r in old) / len(old), sum(int(r["rating"]) for r in full) / len(full)))
print("доля оценок 1-2: прежняя %.1f%%, полная %.1f%%" % (100 * sum(int(r["rating"]) <= 2 for r in old) / len(old), 100 * sum(int(r["rating"]) <= 2 for r in full) / len(full)))
print("с текстом: прежняя %.1f%%, полная %.1f%%" % (100 * sum(bool(r["text"].strip()) for r in old) / len(old), 100 * sum(bool(r["text"].strip()) for r in full) / len(full)))
by = Counter(r["date"][:4] for r in full)
print("по годам (полная): " + ", ".join("%s: %d" % (y, by[y]) for y in sorted(by)))
print("отзывов с оценкой 1-2 в полной: %d" % sum(int(r["rating"]) <= 2 for r in full))
