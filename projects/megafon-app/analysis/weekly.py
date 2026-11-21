# Недельный ряд вокруг июля-октября 2026 и сравнение с датами релизов RuStore (S007).
import csv
import sys
from datetime import date, timedelta
from collections import defaultdict
from statistics import mean

with open(sys.argv[1], encoding="utf-8", newline="") as f:
    rows = list(csv.DictReader(f))

RELEASES = ["2026-06-18", "2026-07-20", "2026-08-18", "2026-09-17", "2026-10-15"]


def monday(d):
    y, m, dd = map(int, d.split("-"))
    x = date(y, m, dd)
    return x - timedelta(days=x.weekday())


wk = defaultdict(list)
for r in rows:
    wk[monday(r["date"])].append(int(r["rating"]))

print("неделя с | отзывов | средняя | доля 1, % | доля 5, % | релиз на неделе")
for w in sorted(wk):
    if w < date(2026, 6, 1):
        continue
    v = wk[w]
    rel = [x for x in RELEASES if w <= date.fromisoformat(x) < w + timedelta(days=7)]
    print("%s | %d | %.2f | %.1f | %.1f | %s" % (w, len(v), mean(v), 100 * sum(x == 1 for x in v) / len(v), 100 * sum(x == 5 for x in v) / len(v), ",".join(rel)))

# Сентябрь: до и после релиза 17.09
pre = [int(r["rating"]) for r in rows if "2026-08-18" <= r["date"] < "2026-09-01"]
mid = [int(r["rating"]) for r in rows if "2026-09-01" <= r["date"] < "2026-09-17"]
post = [int(r["rating"]) for r in rows if "2026-09-17" <= r["date"] < "2026-10-15"]
for lab, v in (("18.08-31.08", pre), ("01.09-16.09", mid), ("17.09-14.10", post)):
    print("Окно %s: отзывов %d, средняя %.2f, доля 5 %.1f%%" % (lab, len(v), mean(v), 100 * sum(x == 5 for x in v) / len(v)))
