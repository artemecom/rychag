# Доля плохих отзывов (оценка 1-2) до и после перелома середины 2025: вклад тем и проверка на срезе без связи с предполагаемой причиной.
# Счёт по словарю слов на ВСЕХ отзывах выгрузки RuStore. Темы взаимоисключающие, берётся первая подходящая по порядку.
# Запуск: python3 prosadka_2025.py <csv> [<файл выборки для проверки точности>]
import csv
import re
import sys
import random
import collections

with open(sys.argv[1], encoding="utf-8", newline="") as f:
    rows = list(csv.DictReader(f))

# Периоды выбраны до расчёта по помесячной доле плохих и объёму отзывов: перелом июль 2025 (94,0% против 87,6% в июне, объём 449 против 275).
BEFORE = ("2025-01", "2025-06")
AFTER = ("2025-07", "2025-12")

THEMES = [
    # «оператор связи» (сам МегаФон) в тему не входит, только оператор как человек в чате или на линии
    ("поддержка и бот: не дозвониться, не связаться с оператором", re.compile(r"поддержк|оператор(?!\w*\s+(связи|сотов|мобильн))|робот|\bбот(а|у|ом|е|ы)?\b|\bчат(е|а|у|ом)?\b|помощник|ассистент|связаться|дозвониться|дозвон\w+ до (оператор|поддерж)|нейросет|консультант|горяч\w+ лини|\bева\b|евой|евы", re.I)),
    ("деньги: списания, платные услуги, тарифы, баланс", re.compile(r"списыв|списал|деньги|денег|платн|подписк|тариф|цен[аыуе]|стоимост|баланс|оплат|рубл|\bруб\b|пополн", re.I)),
    ("приложение: не открывается, вылеты, вход, кабинет, обновление", re.compile(r"открыв|вылет|зависа|грузит|обновл|зайти|заход|вход|логин|парол|кабинет|экран|тормоз|глючит|баг|интерфейс|приложен", re.I)),
    ("сеть: интернет, скорость, покрытие, качество связи", re.compile(r"интернет|скорост|покрыт|\bсеть|сети\b|ловит|сигнал|вышк|lte|4g|5g|связь|связи|качеств|обрыв", re.I)),
]
OTHER = "прочее"


def theme(text):
    for name, rx in THEMES:
        if rx.search(text):
            return name
    return OTHER


def period(d):
    m = d[:7]
    if BEFORE[0] <= m <= BEFORE[1]:
        return 0
    if AFTER[0] <= m <= AFTER[1]:
        return 1
    return None


for r in rows:
    r["theme"] = theme(r["text"])
    r["bad"] = int(r["rating"]) <= 2
    r["per"] = period(r["date"])

total = len(rows)
print("Всего отзывов: %d, период данных %s - %s" % (total, min(r["date"] for r in rows), max(r["date"] for r in rows)))
print("До: %s - %s; после: %s - %s (границы выбраны заранее по перелому июль 2025)" % (BEFORE[0], BEFORE[1], AFTER[0], AFTER[1]))

A = [r for r in rows if r["per"] == 0]
B = [r for r in rows if r["per"] == 1]
n0, n1 = len(A), len(B)
B0 = sum(r["bad"] for r in A) / n0
B1 = sum(r["bad"] for r in B) / n1
print("Отзывов до: %d, после: %d" % (n0, n1))
print("Доля плохих (1-2) до: %.2f%%, после: %.2f%%, изменение: %+.2f п.п." % (100 * B0, 100 * B1, 100 * (B1 - B0)))

names = [n for n, _ in THEMES] + [OTHER]
print()
print("Раздел 1. Вклад тем в изменение доли плохих отзывов (п.п.; сумма вкладов = изменение).")
print("Вклад темы = сдвиг состава + сдвиг доли плохих внутри темы.")
print("Состав: (доля темы после - доля до) * (плохих в теме до - плохих во всём потоке до). Внутри: доля темы после * (плохих в теме после - до).")
sum_c = sum_mix = sum_rate = 0.0
for n in names:
    a = [r for r in A if r["theme"] == n]
    b = [r for r in B if r["theme"] == n]
    w0, w1 = len(a) / n0, len(b) / n1
    b0 = sum(r["bad"] for r in a) / len(a) if a else 0.0
    b1 = sum(r["bad"] for r in b) / len(b) if b else 0.0
    mix = (w1 - w0) * (b0 - B0)
    rate = w1 * (b1 - b0)
    contrib = mix + rate
    sum_c += contrib
    sum_mix += mix
    sum_rate += rate
    print("%s: отзывов до %d (%.1f%%), после %d (%.1f%%); плохих внутри темы до %.1f%%, после %.1f%%; вклад %+.2f п.п. (состав %+.2f, доля внутри %+.2f)" % (
        n, len(a), 100 * w0, len(b), 100 * w1, 100 * b0, 100 * b1, 100 * contrib, 100 * mix, 100 * rate))
print("Сумма вкладов: %+.2f п.п. (должна совпасть с изменением %+.2f); состав %+.2f, доля внутри %+.2f" % (100 * sum_c, 100 * (B1 - B0), 100 * sum_mix, 100 * sum_rate))

print()
print("Раздел 2. Проверка на срезе, которого предполагаемая причина (поддержка и бот) касаться не должна.")
print("Срез: отзывы про сеть и про сбои приложения, в которых нет слов про поддержку и деньги (так задан порядок тем).")
ctrl_names = [THEMES[2][0], THEMES[3][0]]
for n in ctrl_names:
    a = [r for r in A if r["theme"] == n]
    b = [r for r in B if r["theme"] == n]
    b0 = sum(r["bad"] for r in a) / len(a)
    b1 = sum(r["bad"] for r in b) / len(b)
    print("%s: до %d отзывов, плохих %.1f%%; после %d отзывов, плохих %.1f%%; изменение %+.1f п.п." % (n, len(a), 100 * b0, len(b), 100 * b1, 100 * (b1 - b0)))
a = [r for r in A if r["theme"] in ctrl_names]
b = [r for r in B if r["theme"] in ctrl_names]
c0 = sum(r["bad"] for r in a) / len(a)
c1 = sum(r["bad"] for r in b) / len(b)
print("Оба среза вместе: до %d, плохих %.1f%%; после %d, плохих %.1f%%; изменение %+.1f п.п." % (len(a), 100 * c0, len(b), 100 * c1, 100 * (c1 - c0)))
print("Доля срезов в потоке отзывов: до %.1f%%, после %.1f%%" % (100 * len(a) / n0, 100 * len(b) / n1))
# разница изменений: поддержка против контрольного среза
s = THEMES[0][0]
sa = [r for r in A if r["theme"] == s]
sb = [r for r in B if r["theme"] == s]
s0 = sum(r["bad"] for r in sa) / len(sa)
s1 = sum(r["bad"] for r in sb) / len(sb)
print("Для сравнения, тема поддержки: до %.1f%%, после %.1f%%, изменение %+.1f п.п." % (100 * s0, 100 * s1, 100 * (s1 - s0)))
# грубая неопределённость: 95% интервал разности долей в контрольном срезе (нормальное приближение)
import math
se = math.sqrt(c0 * (1 - c0) / len(a) + c1 * (1 - c1) / len(b))
print("Контрольный срез: изменение %+.1f п.п., 95%% интервал примерно от %+.1f до %+.1f п.п." % (100 * (c1 - c0), 100 * (c1 - c0 - 1.96 * se), 100 * (c1 - c0 + 1.96 * se)))

print()
print("Доля отзывов с темой поддержки в потоке по полугодиям:")
by = collections.defaultdict(lambda: [0, 0])
for r in rows:
    h = r["date"][:4] + ("H1" if int(r["date"][5:7]) <= 6 else "H2")
    by[h][0] += 1
    by[h][1] += r["theme"] == s
for h in sorted(by):
    if h >= "2024":
        print("  %s: %d отзывов, из них про поддержку %.1f%%" % (h, by[h][0], 100 * by[h][1] / by[h][0]))

# выборка для проверки точности словаря: 50 случайных отзывов обоих периодов, без метки темы (метку ставит второй читатель отдельно)
if len(sys.argv) > 2:
    random.seed(int(sys.argv[3]) if len(sys.argv) > 3 else 11)
    pool = A + B
    smp = random.sample(pool, 50)
    with open(sys.argv[2], "w", encoding="utf-8") as f:
        for i, r in enumerate(smp, 1):
            f.write("%d | %s\n" % (i, r["text"][:350].replace("\n", " ")))
    with open(sys.argv[2] + ".key", "w", encoding="utf-8") as f:
        for i, r in enumerate(smp, 1):
            f.write("%d | %s\n" % (i, r["theme"]))
