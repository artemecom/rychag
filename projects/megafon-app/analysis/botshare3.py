# Базы для L002 (самоподключение и списания) и L003 (сбои) среди отзывов 1-2 (устойчиво к потоку пятёрок) и число отзывов в неделю.
import csv
import re
import sys
from datetime import date

THEMES = {
    "самоподключение и списания": r"списыва|списал|снима|снял|подключа|подключил|подключен|навязыва|платн|подписк|развод|обман|воруют|воры|мошен|без моего|без спроса|без ведома|ева\b",
    "сбои приложения": r"не открыва|вылета|белый экран|глюч|тормоз|завис|не грузит|не загружа|ошибк|не работает|баг|лагает|крашит|слетает|не запуска",
}

with open(sys.argv[1], encoding="utf-8", newline="") as f:
    rows = list(csv.DictReader(f))

WINDOWS = (("2026-09-01..2026-11-18", "2026-09-01", "2026-11-18"), ("2026-10-07..2026-11-18", "2026-10-07", "2026-11-18"), ("2026-01-01..2026-06-30", "2026-01-01", "2026-06-30"))
for lab, a, b in WINDOWS:
    sel = [r for r in rows if a <= r["date"] <= b]
    low = [r for r in sel if int(r["rating"]) <= 2]
    weeks = ((date.fromisoformat(b) - date.fromisoformat(a)).days + 1) / 7.0
    print("Окно %s: отзывов 1-2 в неделю %.1f (всего %d из %d отзывов)" % (lab, len(low) / weeks, len(low), len(sel)))
    for t, rx in THEMES.items():
        k = [r for r in low if re.search(rx, r["text"].lower())]
        print("  %s: среди отзывов 1-2 %.1f%% (%d из %d), в неделю %.1f" % (t, 100 * len(k) / len(low), len(k), len(low), len(k) / weeks))
