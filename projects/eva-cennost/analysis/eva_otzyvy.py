# Упоминания Евы в отзывах RuStore: блокировщик звонков против чата поддержки. Счёт по словарю слов.
import csv
import re
import sys
import collections

with open(sys.argv[1], encoding="utf-8", newline="") as f:
    rows = list(csv.DictReader(f))

EVA = re.compile(r"\bев[аыуе]\b|\bевой\b", re.I)
SPAM = re.compile(r"блокир|спам|мошенн|секретар|автоответчик|нежелательн|ненужн|не нужн|подним", re.I)
SUPPORT = re.compile(r"поддержк|бот|оператор|чат|ассистент|ии\b|нейросет|переключ|переводит|связаться|тупая|бестолков", re.I)
PAID = re.compile(r"платн|подписк|списал|рубл|руб\b|подключ", re.I)

total = len(rows)
print("Всего отзывов: %d, период %s - %s" % (total, min(r["date"] for r in rows), max(r["date"] for r in rows)))

eva = [r for r in rows if EVA.search(r["text"])]
print("С упоминанием Евы: %d (%.2f%%)" % (len(eva), 100.0 * len(eva) / total))

groups = collections.defaultdict(list)
for r in eva:
    t = r["text"]
    s, p = bool(SPAM.search(t)), bool(SUPPORT.search(t))
    if s and not p:
        g = "блокировщик/спам"
    elif p and not s:
        g = "чат поддержки"
    elif s and p:
        g = "смешано"
    else:
        g = "неясно"
    groups[g].append(r)

for g, lst in groups.items():
    avg = sum(int(r["rating"]) for r in lst) / len(lst)
    low = sum(1 for r in lst if int(r["rating"]) <= 2)
    print("%s: %d, средняя оценка %.2f, оценок 1-2: %d" % (g, len(lst), avg, low))

paid = [r for r in eva if PAID.search(r["text"])]
print("Упоминают Еву и платное/подписку/списание: %d" % len(paid))

by_year = collections.Counter(r["date"][:4] for r in eva)
print("Упоминаний Евы по годам: %s" % dict(sorted(by_year.items())))
by_year_all = collections.Counter(r["date"][:4] for r in rows)
print("Всего отзывов по годам: %s" % dict(sorted(by_year_all.items())))

spam_all = [r for r in rows if re.search(r"спам|мошенн", r["text"], re.I)]
print("Отзывов про спам или мошенников (без слова Ева): %d" % len([r for r in spam_all if not EVA.search(r["text"])]))
print("Средняя оценка всех отзывов: %.2f" % (sum(int(r["rating"]) for r in rows) / total))

# файл для ручной проверки точности: 30 случайных упоминаний с присвоенной группой
import random
random.seed(7)
smp = random.sample(eva, min(30, len(eva)))
with open(sys.argv[2] if len(sys.argv) > 2 else "/dev/null", "w", encoding="utf-8") as f:
    for r in smp:
        g = [k for k, v in groups.items() if r in v][0]
        f.write("%s | %s | %s | %s\n" % (g, r["date"], r["rating"], r["text"][:300].replace("\n", " ")))
