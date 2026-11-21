# Расчёт уровня продления по кварталам и срезам. Печатает результат, он становится источником.
import csv
import sys


def rows(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


cohorts = rows(sys.argv[1])
segments = rows(sys.argv[2])


def rate(due, ren):
    return 100.0 * ren / due


def quarter(months):
    due = sum(int(r["subscribers_due"]) for r in cohorts if r["month"] in months)
    ren = sum(int(r["renewed"]) for r in cohorts if r["month"] in months)
    return due, ren, rate(due, ren)


q2 = quarter(("2026-04", "2026-05", "2026-06"))
q3 = quarter(("2026-07", "2026-08", "2026-09"))
print("Q2 всего: к продлению %d, продлили %d, уровень %.1f%%" % q2)
print("Q3 всего: к продлению %d, продлили %d, уровень %.1f%%" % q3)
print("Падение: %.1f п.п." % (q2[2] - q3[2]))
for seg in ("новые (первый год)", "давние (больше года)"):
    r = {x["period"]: rate(int(x["subscribers_due"]), int(x["renewed"])) for x in segments if x["segment"] == seg}
    print("%s: Q2 %.1f%%, Q3 %.1f%%, падение %.1f п.п." % (seg, r["Q2"], r["Q3"], r["Q2"] - r["Q3"]))
