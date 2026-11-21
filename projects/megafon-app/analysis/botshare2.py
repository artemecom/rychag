# Уточнение базы рычага L001 по замечанию критика: доля всех отзывов зависит от потока пятёрок (знаменатель вырос с сентября).
# Метрики, устойчивые к потоку пятёрок: (а) число отзывов с ботом в неделю, (б) доля бота среди отзывов 1-2.
import csv
import re
import sys
from collections import defaultdict
from datetime import date

BOT = r"\bбот\w*|\bробот(?!у)\w*|\bии\b|нейросет|ассистент|виртуальн|елен[аыуе]\b|автоответ|по кругу"

with open(sys.argv[1], encoding="utf-8", newline="") as f:
    rows = list(csv.DictReader(f))

by = defaultdict(lambda: [0, 0, 0, 0])  # всего, бот, отзывов 1-2, бот среди 1-2
for r in rows:
    m = r["date"][:7]
    low = int(r["rating"]) <= 2
    bot = bool(re.search(BOT, r["text"].lower()))
    by[m][0] += 1
    by[m][1] += bot
    by[m][2] += low
    by[m][3] += bot and low

print("месяц | всего | с ботом | отзывов 1-2 | бот среди 1-2, %")
for m in sorted(by):
    t, b, l, bl = by[m]
    print("%s | %d | %d | %d | %.1f" % (m, t, b, l, 100 * bl / l))


def window(a, b):
    sel = [r for r in rows if a <= r["date"] <= b]
    days = (date.fromisoformat(b) - date.fromisoformat(a)).days + 1
    weeks = days / 7.0
    bot = [r for r in sel if re.search(BOT, r["text"].lower())]
    low = [r for r in sel if int(r["rating"]) <= 2]
    botlow = [r for r in low if re.search(BOT, r["text"].lower())]
    return len(sel), len(bot) / weeks, len(low) / weeks, len(botlow), len(low), weeks


for lab, a, b in (("2026-09-01..2026-11-18", "2026-09-01", "2026-11-18"), ("2026-10-07..2026-11-18 (6 недель)", "2026-10-07", "2026-11-18")):
    n, bw, lw, bl, l, w = window(a, b)
    print("Окно %s: отзывов %d, с ботом в неделю %.1f, отзывов 1-2 в неделю %.1f, бот среди 1-2 %.1f%% (%d из %d)" % (lab, n, bw, lw, 100 * bl / l, bl, l))

n, bw, lw, bl, l, w = window("2026-09-01", "2026-11-18")
p = bl / l
print("Размер выборки для доли среди 1-2 (16*p*(1-p)/d^2), p = %.3f, отзывов 1-2 в неделю %.0f:" % (p, lw))
for d in (0.05, 0.07, 0.10):
    need = 16 * p * (1 - p) / d ** 2
    print("d = %.0f п.п.: %d отзывов 1-2 на период, около %.1f недель" % (100 * d, need, need / lw))
print("Разброс одной месячной оценки доли (биномиальный, при n=%d): около %.1f п.п." % (l, 100 * (p * (1 - p) / l) ** 0.5))
