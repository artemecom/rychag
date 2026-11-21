# -*- coding: utf-8 -*-
"""Готовые расчёты: арифметику ведёт программа, а не модель.

Каждый расчёт получает параметры из файла JSON в папке задачи и возвращает строки текста. Текст сохраняется как источник
вида «расчёт», числа из него цитируются в реестр (claim add --type calc). При verify расчёт выполняется заново
и сверяется с сохранённым выводом. Только стандартная библиотека: math, fractions, statistics.NormalDist.

Доли в параметрах задаются в процентах (12 значит 12 %), как их потом пишут в тексте.
Ключи, которые начинаются с «_», программа не читает: это пояснения для человека.
"""
import math
from fractions import Fraction
from statistics import NormalDist

from .common import Fail, canon_number

VARIANTS = ("слабый", "основной", "сильный")


# ---------------------------------------------------------------- запись чисел

def fmt(x, digits=1):
    """Число для текста: разряды через пробел, дробная часть через запятую, отрицательное со словом «минус»."""
    x = float(x)
    if x != x or x in (float("inf"), float("-inf")):
        raise Fail("В расчёте получилось не число. Проверьте параметры: нет ли деления на ноль.")
    r = round(x, digits)
    if abs(r - round(r)) < 10 ** -(digits + 2):
        r = int(round(r))
    sign = "минус " if r < 0 else ""
    r = abs(r)
    if isinstance(r, int):
        whole, frac = r, ""
    else:
        whole = int(math.floor(r))
        frac = ("%.*f" % (digits, r - whole))[2:].rstrip("0")
    s = "{:,}".format(whole).replace(",", " ")
    return sign + s + ("," + frac if frac else "")


def pct(share, digits=1):
    """Доля (0..1) как проценты."""
    return fmt(share * 100, digits) + " %"


def _ceil(x):
    return int(math.ceil(x - 1e-9))


# ---------------------------------------------------------------- чтение параметров

def _num(p, key, default=None, low=None, high=None, where=""):
    v = p.get(key, default)
    if v is None:
        raise Fail("В параметрах%s нет поля «%s». Список полей: python3 tools/rychag.py calc list" % (where, key))
    if isinstance(v, bool):
        raise Fail("Поле «%s»%s должно быть числом." % (key, where))
    if isinstance(v, str):
        try:
            v = float(canon_number(v.strip()))
        except ValueError:
            raise Fail("Поле «%s»%s должно быть числом, получено «%s»." % (key, where, v))
    if not isinstance(v, (int, float)):
        raise Fail("Поле «%s»%s должно быть числом." % (key, where))
    if low is not None and v < low:
        raise Fail("Поле «%s»%s не может быть меньше %s (получено %s)." % (key, where, fmt(low), fmt(v, 4)))
    if high is not None and v > high:
        raise Fail("Поле «%s»%s не может быть больше %s (получено %s)." % (key, where, fmt(high), fmt(v, 4)))
    return v


def _list(p, key, where="", default=None):
    v = p.get(key, default)
    if not isinstance(v, list) or not v:
        raise Fail("Поле «%s»%s должно быть непустым списком." % (key, where))
    return v


def _nums(p, key, where="", default=None, n=None):
    v = _list(p, key, where, default)
    out = [_num({"x": x}, "x", where=" (список «%s»%s)" % (key, where)) for x in v]
    if n is not None and len(out) != n:
        raise Fail("В списке «%s»%s должно быть %d чисел, получено %d." % (key, where, n, len(out)))
    return out


def _text(p, key, default):
    v = p.get(key, default)
    return str(v).strip() if v is not None and str(v).strip() else default


def param_numbers(params, skip=("месяц", "стороны", "групп", "месяцев_в_периоде", "срок_кварталов")):
    """Все числа параметров в каноническом виде (для сверки с записями реестра). Служебные поля не считаются."""
    found = set()

    def walk(v, key=""):
        if isinstance(v, dict):
            for k, x in v.items():
                if not str(k).startswith("_"):
                    walk(x, str(k))
        elif isinstance(v, list):
            for x in v:
                walk(x, key)
        elif isinstance(v, bool) or key in skip:
            return
        elif isinstance(v, (int, float)):
            found.add(canon_number(repr(v) if isinstance(v, int) else ("%.10f" % v).rstrip("0").rstrip(".")))
        elif isinstance(v, str):
            try:
                float(canon_number(v.strip()))
            except ValueError:
                return
            found.add(canon_number(v.strip()))

    walk(params)
    return found


# ---------------------------------------------------------------- 1. сведение числа подключённых

def calc_balance(p):
    unit = _text(p, "единица", "единиц")
    start = _num(p, "на_начало", low=0)
    new = _num(p, "новые", low=0)
    gone = _num(p, "выбывшие", low=0)
    end = start + new - gone
    if end < 0:
        raise Fail("Выбывших больше, чем было на начало вместе с новыми: на конец периода получается меньше нуля.")
    out = ["Сведение числа подключённых. Единица счёта: %s." % unit,
           "На конец периода: на начало %s плюс новые %s минус выбывшие %s равно %s." % (fmt(start), fmt(new), fmt(gone), fmt(end))]
    net = end - start
    out.append("Чистый прирост за период: %s." % fmt(net) if net >= 0 else "Чистая убыль за период: %s." % fmt(-net))
    goal = p.get("цель")
    base = p.get("без_изменений")
    if goal is not None:
        goal = _num(p, "цель", low=0)
        out.append("Цель на конец периода %s: от начала периода нужен чистый прирост %s." % (fmt(goal), fmt(goal - start)))
        if end >= goal:
            out.append("План %s против цели %s: цель выполнена, запас %s." % (fmt(end), fmt(goal), fmt(end - goal)))
        else:
            out.append("План %s против цели %s: не хватает %s." % (fmt(end), fmt(goal), fmt(goal - end)))
        out.append("Чтобы выйти на цель при %s выбывших, новых подключений нужно %s." % (fmt(gone), fmt(goal - start + gone)))
    if base is not None:
        base = _num(p, "без_изменений", low=0)
        diff = end - base
        if diff >= 0:
            out.append("Прогноз без изменений на конец периода: %s. План выше него на %s: только эту разницу можно относить "
                       "к изменениям, остальные подключения случились бы и так." % (fmt(base), fmt(diff)))
        else:
            out.append("Прогноз без изменений на конец периода: %s. План ниже него на %s." % (fmt(base), fmt(-diff)))
        if goal is not None:
            gap = goal - base
            out.append("Разрыв между прогнозом без изменений %s и целью %s составляет %s." % (fmt(base), fmt(goal), fmt(gap)))
            if gap > 0:
                out.append("План закрывает из этого разрыва %s, это %s." % (fmt(diff), pct(diff / gap)))
    return out


# ---------------------------------------------------------------- 2. воронка

def calc_funnel(p):
    unit = _text(p, "единица", "клиентов")
    steps = [str(s).strip() for s in _list(p, "шаги")]
    chans = _list(p, "каналы")
    names = []
    seen = {}
    rates = {}
    for i, ch in enumerate(chans, 1):
        if not isinstance(ch, dict):
            raise Fail("Каждый канал в списке «каналы» это объект с полями «название», «увидели», «доли_процентов».")
        w = " (канал %d)" % i
        name = _text(ch, "название", "")
        if not name:
            raise Fail("У канала %d нет поля «название»." % i)
        if name in seen:
            raise Fail("Канал «%s» указан дважды." % name)
        names.append(name)
        seen[name] = _num(ch, "увидели", low=0, where=w)
        rates[name] = [x / 100.0 for x in _nums(ch, "доли_процентов", where=w, n=len(steps))]
        if any(not 0 <= x <= 1 for x in rates[name]):
            raise Fail("Доли по шагам%s задаются в процентах от 0 до 100." % w)
    out = ["Воронка. Единица счёта: %s. Первый столбец: сколько разных подходящих клиентов увидели предложение." % unit]
    adjusted = dict(seen)
    overlaps = p.get("пересечения") or []
    order = p.get("правило_отнесения") or []
    if overlaps:
        if not isinstance(order, list) or not order:
            raise Fail("Есть пересечения каналов, но нет поля «правило_отнесения»: списка каналов по старшинству. "
                       "Клиента, который видел предложение в нескольких каналах, относим к тому, что раньше в списке.")
        for n in order:
            if n not in seen:
                raise Fail("В «правило_отнесения» назван канал «%s», которого нет в списке каналов." % n)
        out.append("Правило отнесения: клиента, который видел предложение в нескольких каналах, считаем один раз, "
                   "в том канале, который раньше в списке: %s." % ", ".join(order))
        for ov in overlaps:
            pair = ov.get("каналы") if isinstance(ov, dict) else None
            if not isinstance(pair, list) or len(pair) < 2 or any(c not in seen for c in pair):
                raise Fail("Пересечение задаётся так: {\"каналы\": [\"а\", \"б\"], \"число\": 100}, названия из списка каналов.")
            n = _num(ov, "число", low=0, where=" (пересечение %s)" % " и ".join(pair))
            ranked = [c for c in order if c in pair]
            if not ranked:
                raise Fail("Ни один из каналов пересечения (%s) не назван в «правило_отнесения»." % ", ".join(pair))
            winner = ranked[0]
            for c in pair:
                if c != winner:
                    adjusted[c] -= n
                    if adjusted[c] < 0:
                        raise Fail("Пересечение больше, чем увидели в канале «%s»." % c)
            out.append("Пересечение каналов %s: %s отнесены к каналу «%s» и вычтены из остальных." % (
                " и ".join("«%s»" % c for c in pair), fmt(n), winner))
    totals = [0.0] * (len(steps) + 1)
    result = {}
    for name in names:
        cur = adjusted[name]
        counts = [cur]
        for r in rates[name]:
            cur = cur * r
            counts.append(cur)
        result[name] = counts
        for i, c in enumerate(counts):
            totals[i] += c
        head = "увидели %s" % fmt(seen[name], 0)
        if adjusted[name] != seen[name]:
            head += ", после вычета пересечений %s" % fmt(adjusted[name], 0)
        parts = ["%s %s (%s от предыдущего шага)" % (steps[i], fmt(counts[i + 1], 0), pct(rates[name][i])) for i in range(len(steps))]
        share = pct(counts[-1] / counts[0]) if counts[0] else "0 %"
        out.append("Канал «%s»: %s; %s. Дошли до конца %s, это %s от увидевших." % (name, head, "; ".join(parts), fmt(counts[-1], 0), share))
    if len(names) > 1:
        out.append("Итого по всем каналам без двойного счёта: увидели %s; %s." % (
            fmt(totals[0], 0), "; ".join("%s %s" % (steps[i], fmt(totals[i + 1], 0)) for i in range(len(steps)))))
    if totals[0]:
        out.append("Всего дошли до конца %s из %s увидевших, это %s." % (fmt(totals[-1], 0), fmt(totals[0], 0), pct(totals[-1] / totals[0])))
        if len(steps) > 1 and totals[1]:
            out.append("От первого шага («%s», %s) до последнего дошли %s." % (steps[0], fmt(totals[1], 0), pct(totals[-1] / totals[1])))
    losses = [(totals[i] - totals[i + 1], i) for i in range(len(steps)) if totals[i] > 0]
    if losses:
        lost, i = max(losses)
        out.append("Больше всего людей останавливается на шаге «%s»: не проходят %s, это %s пришедших на этот шаг." % (
            steps[i], fmt(lost, 0), pct(lost / totals[i])))
    key_step = _text(p, "шаг_подключения", steps[-1])
    if key_step not in steps:
        raise Fail("Поле «шаг_подключения» должно совпадать с одним из шагов: %s." % ", ".join(steps))
    ki = steps.index(key_step) + 1
    gain_total, any_base = 0.0, False
    for ch in chans:
        name = ch["название"].strip()
        if ch.get("и_так_подключились") is None:
            continue
        any_base = True
        usual = _num(ch, "и_так_подключились", low=0, where=" (канал «%s»)" % name)
        got = result[name][ki]
        gain = got - usual
        gain_total += gain
        line = "Канал «%s»: на шаге «%s» %s, при обычном обслуживании было бы %s, прирост %s." % (name, key_step, fmt(got, 0), fmt(usual, 0), fmt(gain, 0))
        if ch.get("расходы") is not None:
            cost = _num(ch, "расходы", low=0, where=" (канал «%s»)" % name)
            if gain > 0:
                line += " Расходы %s: одно дополнительное подключение стоит %s." % (fmt(cost, 0), fmt(cost / gain, 0))
            else:
                line += " Расходы %s, а прироста нет: стоимость дополнительного подключения посчитать нельзя." % fmt(cost, 0)
        out.append(line)
    if any_base:
        out.append("Суммарный прирост против обычного обслуживания: %s. Только его можно относить к новому предложению." % fmt(gain_total, 0))
    return out


# ---------------------------------------------------------------- 3. доля активных

def _simple_fraction(a, b):
    if float(a).is_integer() and float(b).is_integer() and b:
        f = Fraction(int(a), int(b))
        if f.denominator <= 12 and 0 < f < 1:
            return " (%d из %d)" % (f.numerator, f.denominator)
    return ""


def calc_active(p):
    unit = _text(p, "единица", "единиц")
    bc = _num(p, "база_подключённые", low=1)
    ba = _num(p, "база_активные", low=0)
    pc = _num(p, "план_подключённые", low=1)
    pa = _num(p, "план_активные", low=0)
    if ba > bc or pa > pc:
        raise Fail("Активных не может быть больше, чем подключённых.")
    bs, ps = ba / bc, pa / pc
    growth = pa - ba
    by_count = (pc - bc) * bs
    by_share = pc * (ps - bs)
    out = ["Доля активных. Единица счёта: %s. База это прогноз без изменений, план это наш вариант." % unit,
           "База: активных %s из %s подключённых, это %s%s." % (fmt(ba), fmt(bc), pct(bs), _simple_fraction(ba, bc)),
           "План: активных %s из %s подключённых, это %s%s." % (fmt(pa), fmt(pc), pct(ps), _simple_fraction(pa, pc)),
           "Изменение числа активных: %s." % fmt(growth),
           "За счёт изменения числа подключённых при прежней доле: (%s минус %s) умножить на %s равно %s." % (fmt(pc), fmt(bc), pct(bs), fmt(by_count)),
           "За счёт изменения доли активных: %s умножить на (%s минус %s) равно %s." % (fmt(pc), pct(ps), pct(bs), fmt(by_share)),
           "Если доля останется прежней, при %s подключённых активных будет %s: до плана %s." % (
               fmt(pc), fmt(pc * bs), ("не хватит %s" % fmt(pa - pc * bs)) if pa > pc * bs + 1e-9 else "хватает")]
    return out


# ---------------------------------------------------------------- 4. граница решения

def calc_breakeven(p):
    unit = _text(p, "единица", "единиц")
    gap = _num(p, "разрыв", low=0)
    rate = _num(p, "ставка")
    if rate <= 0:
        raise Fail("Поле «ставка» должно быть больше нуля: это прибыль с одной единицы.")
    other = _num(p, "другие_вклады", default=0)
    variants = p.get("варианты")
    if not isinstance(variants, dict) or any(v not in variants for v in VARIANTS):
        raise Fail("Поле «варианты» это объект с тремя вариантами: слабый, основной, сильный. У каждого «единиц» и «прямые_расходы».")
    out = ["Граница решения. Единица: %s. Разрыв, который нужно закрыть: %s. Ставка за единицу: %s." % (unit, fmt(gap), fmt(rate)),
           "Формула: нужное число единиц равно (разрыв плюс новые прямые расходы минус другие вклады), делённое на ставку.",
           "Без новых прямых расходов и других вкладов: %s разделить на %s равно %s." % (fmt(gap), fmt(rate), fmt(gap / rate))]
    for name in VARIANTS:
        v = variants[name]
        if not isinstance(v, dict):
            raise Fail("Вариант «%s» это объект с полями «единиц» и «прямые_расходы»." % name)
        w = " (вариант «%s»)" % name
        units = _num(v, "единиц", low=0, where=w)
        cost = _num(v, "прямые_расходы", default=0, low=0, where=w)
        r = _num(v, "ставка", default=rate, where=w)
        if r <= 0:
            raise Fail("Ставка%s должна быть больше нуля." % w)
        oth = _num(v, "другие_вклады", default=other, where=w)
        need = (gap + cost - oth) / r
        contrib = units * r + oth - cost
        line = "Вариант «%s»: ожидаем %s, прямые расходы %s, ставка %s%s. Граница: нужно %s. Вклад после прямых расходов: %s." % (
            name, fmt(units), fmt(cost), fmt(r), ", другие вклады %s" % fmt(oth) if oth else "", fmt(max(need, 0)), fmt(contrib))
        if gap <= 0:
            line += " Разрыва нет."
        elif contrib >= gap:
            line += " Разрыв закрыт, запас %s." % fmt(contrib - gap)
        else:
            line += " Разрыв закрыт на %s, не хватает %s, это ещё %s единиц." % (pct(max(contrib, 0) / gap), fmt(gap - contrib), fmt((gap - contrib) / r))
        out.append(line)
    return out


# ---------------------------------------------------------------- 5. вклад удержания по месяцам запуска

def calc_retention(p):
    unit = _text(p, "единица", "номеров")
    rate = _num(p, "ставка", low=0)
    months = int(_num(p, "месяцев_в_периоде", default=12, low=1))
    out = ["Вклад удержания по месяцам запуска. Единица: %s. Месяцев в периоде: %s. Ставка за один дополнительный оплаченный месяц: %s." % (
        unit, fmt(months), fmt(rate)),
        "Правило: запуск в месяце с номером М оставляет в периоде не больше (%s минус М плюс один) месяцев на единицу. "
        "Запуск в последнем месяце даёт максимум один месяц." % fmt(months)]
    total, spill = 0.0, 0.0
    for i, row in enumerate(_list(p, "запуски"), 1):
        if not isinstance(row, dict):
            raise Fail("Каждый запуск это объект с полями «месяц», «число» и «доп_месяцев_на_единицу» либо двумя списками долей.")
        w = " (запуск %d)" % i
        m = int(_num(row, "месяц", low=1, high=months, where=w))
        n = _num(row, "число", low=0, where=w)
        room = months - m + 1
        if row.get("доп_месяцев_на_единицу") is not None:
            extra = _num(row, "доп_месяцев_на_единицу", low=0, where=w)
            inside = min(extra, room)
            outside = extra - inside
            how = "дополнительных оплаченных месяцев на единицу %s, в период попадает %s" % (fmt(extra, 2), fmt(inside, 2))
        else:
            new = _nums(row, "платят_новое_процентов", where=w)
            old = _nums(row, "платят_обычное_процентов", where=w, n=len(new))
            diffs = [(a - b) / 100.0 for a, b in zip(new, old)]
            inside = sum(diffs[:room])
            outside = sum(diffs[room:])
            how = "разница долей платящих по месяцам, начиная с месяца запуска, внутри периода даёт дополнительных оплаченных месяцев на единицу %s" % fmt(inside, 2)
        got = n * inside
        total += got
        spill += n * outside
        out.append("Запуск в месяце %d: %s %s; месяцев до конца периода: %d; %s; всего дополнительных оплаченных месяцев %s; вклад: %s умножить на %s равно %s." % (
            m, fmt(n), unit, room, how, fmt(got), fmt(got), fmt(rate), fmt(got * rate)))
    out.append("Итого в периоде: дополнительных оплаченных месяцев %s, вклад %s." % (fmt(total), fmt(total * rate)))
    if abs(spill) > 1e-9:
        out.append("За пределами периода остаётся дополнительных оплаченных месяцев %s (вклад %s): их относим к следующим годам, в этот расчёт они не входят." % (
            fmt(spill), fmt(spill * rate)))
    return out


# ---------------------------------------------------------------- 6. окупаемость по кварталам

def calc_payback(p):
    profit = _nums(p, "доп_прибыль_по_кварталам")
    n = len(profit)
    costs = _nums(p, "прямые_расходы_по_кварталам", default=[0] * n, n=n)
    invest = p.get("вложения_по_кварталам")
    if invest is not None:
        invest = _nums(p, "вложения_по_кварталам", n=n)
    horizon = int(_num(p, "срок_кварталов", default=n, low=1, high=n))
    out = ["Окупаемость по кварталам. Считаем накопленную дополнительную прибыль после новых прямых расходов и сравниваем "
           "с вложениями к тому же моменту. Деньги после конца периода в расчёт не входят: их относим к следующим годам."]
    cum, cum_inv, payback = 0.0, 0.0, None
    cums = []
    for q in range(n):
        net = profit[q] - costs[q]
        cum += net
        cums.append(cum)
        line = "Квартал %d: дополнительная прибыль %s, прямые расходы %s, после расходов %s; накоплено %s" % (
            q + 1, fmt(profit[q]), fmt(costs[q]), fmt(net), fmt(cum))
        if invest is not None:
            cum_inv += invest[q]
            if cum_inv <= 0:
                line += "; вложений к этому моменту нет"
            elif cum >= cum_inv:
                line += "; вложения накоплено %s: покрыты" % fmt(cum_inv)
                if payback is None:
                    payback = q + 1
            else:
                line += "; вложения накоплено %s: не покрыты, не хватает %s" % (fmt(cum_inv), fmt(cum_inv - cum))
                payback = None  # покрытие должно сохраняться: если следующий квартал снова ушёл в минус, срок считаем заново
        out.append(line + ".")
    if invest is not None:
        if payback is not None:
            out.append("Расчётный срок окупаемости: квартал %d. С этого квартала накопленная прибыль после прямых расходов не меньше вложений." % payback)
        else:
            out.append("За весь период (кварталов: %d) вложения не возвращаются: к концу периода не хватает %s." % (n, fmt(cum_inv - cum)))
    else:
        out.append("Вложения не заданы: срок окупаемости посчитать нельзя, ниже предельная сумма.")
    limit = cums[horizon - 1]
    if limit > 0:
        out.append("Предельная сумма вложений, которая вернётся за выбранный срок (кварталов: %d): %s. Всё, что дороже, за этот срок не окупится." % (horizon, fmt(limit)))
    else:
        out.append("Предельная сумма вложений за выбранный срок (кварталов: %d): ноль. Накопленная прибыль после прямых расходов не положительна (%s)." % (horizon, fmt(limit)))
    return out


# ---------------------------------------------------------------- 7. число участников проверки

def _z(prob):
    return NormalDist().inv_cdf(prob)


def group_size(p1, p2, alpha, power, sides):
    """Сколько нужно в каждой группе, чтобы различить доли p1 и p2 (нормальное приближение, раздельные дисперсии)."""
    za = _z(1 - alpha / sides)
    zb = _z(power)
    return (za + zb) ** 2 * (p1 * (1 - p1) + p2 * (1 - p2)) / (p1 - p2) ** 2


def smallest_visible(p1, n, alpha, power, sides, down=True):
    """Наименьшая разница долей, которую видно на n участниках в группе. Возвращает разницу (в долях) или None."""
    lo, hi = 1e-9, (p1 if down else 1 - p1) - 1e-9
    if hi <= lo:
        return None
    sign = -1 if down else 1
    if group_size(p1, p1 + sign * hi, alpha, power, sides) > n:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        if group_size(p1, p1 + sign * mid, alpha, power, sides) > n:
            lo = mid
        else:
            hi = mid
    return hi


def calc_sample(p):
    unit = _text(p, "единица", "участников")
    p1 = _num(p, "доля_обычная_процентов", low=0, high=100) / 100.0
    if not 0 < p1 < 1:
        raise Fail("Поле «доля_обычная_процентов» должно быть больше 0 и меньше 100.")
    alpha = _num(p, "риск_ошибки_процентов", default=5) / 100.0
    power = _num(p, "мощность_процентов", default=80) / 100.0
    sides = int(_num(p, "стороны", default=2))
    groups = int(_num(p, "групп", default=2, low=2))
    if not 0 < alpha < 0.5 or not 0.5 <= power < 1 or sides not in (1, 2):
        raise Fail("Риск ошибки задаётся от 0 до 50 процентов, мощность от 50 до 100, «стороны» равно 1 или 2.")
    side_ru = {1: "односторонняя", 2: "двусторонняя"}
    out = ["Число участников проверки для сравнения двух долей. Единица счёта: %s. Групп сравнения: %d." % (unit, groups),
           "Условия: риск принять случайность за улучшение %s (%s проверка), вероятность заметить настоящее улучшение %s." % (
               pct(alpha), side_ru[sides], pct(power)),
           "Способ: нормальное приближение для разницы двух долей. Число в группе равно квадрату суммы двух порогов нормального "
           "распределения, умноженному на сумму разбросов двух долей и делённому на квадрат разницы долей."]
    need = None
    down = _text(p, "направление", "снижение") != "рост"
    if p.get("доля_ожидаемая_процентов") is not None:
        p2 = _num(p, "доля_ожидаемая_процентов", low=0, high=100) / 100.0
        if not 0 < p2 < 1 or p2 == p1:
            raise Fail("Ожидаемая доля должна быть больше 0, меньше 100 и отличаться от обычной.")
        down = p2 < p1
        word = "снижение" if down else "рост"
        out.append("Обычная доля %s, ожидаемая %s. Разница в процентных пунктах: %s; относительно обычной доли это %s на %s. "
                   "Это две разные записи одного изменения, порог решения задавайте в одной из них заранее." % (
                       pct(p1), pct(p2), fmt(abs(p1 - p2) * 100, 2), word, pct(abs(p1 - p2) / p1)))
        need = _ceil(group_size(p1, p2, alpha, power, sides))
        out.append("Нужно в каждой группе: %s. Всего (групп: %d): %s." % (fmt(need), groups, fmt(need * groups)))
        other = 1 if sides == 2 else 2
        out.append("Для сравнения, %s проверка при тех же условиях: %s в каждой группе." % (
            side_ru[other], fmt(_ceil(group_size(p1, p2, alpha, power, other)))))
    elif p.get("участников_в_группе") is None:
        raise Fail("Нужно хотя бы одно из двух полей: «доля_ожидаемая_процентов» (сколько участников нужно) "
                   "или «участников_в_группе» (какое улучшение можно увидеть).")
    have = p.get("участников_в_группе")
    if have is not None:
        have = _num(p, "участников_в_группе", low=2)
        d = smallest_visible(p1, have, alpha, power, sides, down)
        if d is None:
            out.append("На %s в каждой группе при обычной доле %s проверка не увидит даже самого сильного изменения." % (fmt(have), pct(p1)))
        else:
            pp = math.ceil(d * 1000 - 1e-6) / 10.0
            edge = p1 * 100 - pp if down else p1 * 100 + pp
            out.append("Обратный расчёт: на %s в каждой группе видно изменение не меньше чем на %s (в процентных пунктах): с %s до %s %s. "
                       "Меньшее изменение такая проверка, скорее всего, не отличит от случайности." % (
                           fmt(have), fmt(pp), pct(p1), fmt(edge) + " %", "или ниже" if down else "или выше"))
    total = p.get("нужно_участников")
    if total is not None:
        total = _num(p, "нужно_участников", low=1)
    elif need is not None:
        total = need * groups
    elif have is not None:
        total = have * groups
    weeks_obs = _num(p, "наблюдение_недель", default=0, low=0)
    if total is not None and p.get("набор_недель") is not None:
        w = _num(p, "набор_недель", low=0.0001)
        out.append("Темп набора: чтобы набрать %s за срок набора (недель: %s), каждую неделю должно появляться в среднем %s впервые подходящих." % (
            fmt(total), fmt(w), fmt(total / w)))
        if weeks_obs:
            out.append("С наблюдением за последними участниками (недель: %s) результат будет после старта через недель: %s." % (fmt(weeks_obs), fmt(w + weeks_obs)))
    if total is not None and p.get("поток_в_неделю") is not None:
        flow = _num(p, "поток_в_неделю", low=0.0001)
        w = _ceil(total / flow)
        line = "Срок набора: при потоке %s впервые подходящих в неделю на набор %s нужно недель: %s" % (fmt(flow), fmt(total), fmt(w))
        if weeks_obs:
            line += "; с наблюдением за последними участниками (недель: %s) результат будет после старта через недель: %s" % (fmt(weeks_obs), fmt(w + weeks_obs))
        out.append(line + ".")
    return out


# ---------------------------------------------------------------- список расчётов

KINDS = {
    "сведение": {
        "func": calc_balance, "file": "svedenie",
        "what": "сведение числа подключённых: на начало плюс новые минус выбывшие равно на конец; разрыв с целью и с прогнозом без изменений",
        "fields": "единица, на_начало, новые, выбывшие; необязательно: цель, без_изменений",
        "template": {"_как_заполнять": "Замените числа своими. «без_изменений» это прогноз на конец периода при обычной работе.",
                     "единица": "семейных групп", "на_начало": 1000, "новые": 600, "выбывшие": 200, "цель": 1800, "без_изменений": 1200},
    },
    "воронка": {
        "func": calc_funnel, "file": "voronka",
        "what": "воронка по каналам без двойного счёта: сколько увидели, доли по шагам, сколько дошло, прирост против обычного обслуживания и цена дополнительного подключения",
        "fields": "единица, шаги (список названий), каналы (название, увидели, доли_процентов по шагам; необязательно: и_так_подключились, расходы); "
                  "необязательно: пересечения (каналы, число), правило_отнесения (список каналов по старшинству), шаг_подключения",
        "template": {"_как_заполнять": "Доли в процентах от предыдущего шага. Клиент из пересечения считается один раз, в канале, который раньше в «правило_отнесения».",
                     "единица": "домохозяйств", "шаги": ["создали группу", "приняли приглашение", "совершили первое действие"],
                     "каналы": [{"название": "приложение", "увидели": 20000, "доли_процентов": [10, 60, 50], "и_так_подключились": 300, "расходы": 0},
                                {"название": "поддержка", "увидели": 3000, "доли_процентов": [20, 70, 60], "и_так_подключились": 100, "расходы": 150000}],
                     "пересечения": [{"каналы": ["приложение", "поддержка"], "число": 500}],
                     "правило_отнесения": ["поддержка", "приложение"], "шаг_подключения": "приняли приглашение"},
    },
    "активность": {
        "func": calc_active, "file": "aktivnost",
        "what": "доля активных: сколько активных из подключённых и какая часть прироста от роста числа, а какая от роста доли",
        "fields": "единица, база_подключённые, база_активные, план_подключённые, план_активные",
        "template": {"_как_заполнять": "База это прогноз без изменений, план это ваш вариант на тот же момент.",
                     "единица": "семейных групп", "база_подключённые": 1200, "база_активные": 700, "план_подключённые": 1800, "план_активные": 1200},
    },
    "граница": {
        "func": calc_breakeven, "file": "granica",
        "what": "граница решения: сколько дополнительных оплаченных месяцев (или других единиц) нужно, чтобы закрыть разрыв прибыли при ставке и новых прямых расходах; три варианта",
        "fields": "единица, разрыв, ставка, варианты (слабый, основной, сильный: единиц, прямые_расходы; необязательно: ставка, другие_вклады); необязательно: другие_вклады",
        "template": {"_как_заполнять": "«единиц» это сколько вы ожидаете получить в каждом варианте, «прямые_расходы» это новые расходы на обслуживание.",
                     "единица": "дополнительных оплаченных месяцев", "разрыв": 1000000, "ставка": 400,
                     "варианты": {"слабый": {"единиц": 1500, "прямые_расходы": 200000}, "основной": {"единиц": 3000, "прямые_расходы": 200000},
                                  "сильный": {"единиц": 4500, "прямые_расходы": 250000}}},
    },
    "удержание": {
        "func": calc_retention, "file": "uderzhanie",
        "what": "вклад удержания по месяцам запуска: сколько единиц получили услугу в каком месяце и сколько дополнительных оплаченных месяцев попадает в период",
        "fields": "единица, ставка, запуски (месяц, число и либо доп_месяцев_на_единицу, либо платят_новое_процентов и платят_обычное_процентов "
                  "списками по месяцам, начиная с месяца запуска); необязательно: месяцев_в_периоде (по умолчанию 12)",
        "template": {"_как_заполнять": "Каждая строка: в каком месяце периода услуга стала доступна и скольким единицам. Лишние месяцы за концом периода программа отрежет сама.",
                     "единица": "номеров", "ставка": 400, "месяцев_в_периоде": 12,
                     "запуски": [{"месяц": 4, "число": 1000, "доп_месяцев_на_единицу": 2},
                                 {"месяц": 12, "число": 500, "платят_новое_процентов": [100, 95, 92], "платят_обычное_процентов": [97, 90, 85]}]},
    },
    "окупаемость": {
        "func": calc_payback, "file": "okupaemost",
        "what": "окупаемость по кварталам: накопленная дополнительная прибыль после прямых расходов против вложений, расчётный срок и предельная сумма вложений",
        "fields": "доп_прибыль_по_кварталам (список); необязательно: прямые_расходы_по_кварталам, вложения_по_кварталам, срок_кварталов",
        "template": {"_как_заполнять": "Пока стоимость разработки неизвестна, уберите «вложения_по_кварталам»: программа назовёт предельную сумму.",
                     "доп_прибыль_по_кварталам": [0, 200000, 600000, 900000], "прямые_расходы_по_кварталам": [50000, 100000, 100000, 100000],
                     "вложения_по_кварталам": [300000, 500000, 0, 0], "срок_кварталов": 4},
    },
    "выборка": {
        "func": calc_sample, "file": "vyborka",
        "what": "число участников проверки для сравнения двух долей, обратный расчёт (какое наименьшее улучшение видно на заданном числе) и темп набора",
        "fields": "доля_обычная_процентов и одно или оба: доля_ожидаемая_процентов, участников_в_группе; необязательно: риск_ошибки_процентов (5), "
                  "мощность_процентов (80), стороны (2), групп (2), направление (снижение или рост), нужно_участников, поток_в_неделю, набор_недель, наблюдение_недель, единица",
        "template": {"_как_заполнять": "Доли в процентах. «участников_в_группе» включает обратный расчёт. «поток_в_неделю» это впервые подходящие случаи, а не все подключённые.",
                     "единица": "семейных групп", "доля_обычная_процентов": 20, "доля_ожидаемая_процентов": 15, "риск_ошибки_процентов": 5,
                     "мощность_процентов": 80, "стороны": 2, "групп": 2, "участников_в_группе": 400, "поток_в_неделю": 150, "наблюдение_недель": 2},
    },
}


def compute(kind, params):
    """Строки вывода готового расчёта."""
    if kind not in KINDS:
        raise Fail("Готового расчёта «%s» нет. Есть: %s." % (kind, ", ".join(KINDS)))
    if not isinstance(params, dict):
        raise Fail("Файл параметров должен быть объектом JSON с полями расчёта.")
    try:
        lines = KINDS[kind]["func"](params)
    except (ZeroDivisionError, OverflowError):
        raise Fail("В расчёте «%s» получилось деление на ноль или слишком большое число. Проверьте параметры." % kind)
    return ["Готовый расчёт «%s»." % kind] + lines


def list_lines():
    out = ["Готовые расчёты (арифметику ведёт программа). Запуск: python3 tools/rychag.py calc ready <вид> --params analysis/<файл>.json --rests-on C001,C002",
           "Образец файла параметров: python3 tools/rychag.py calc template <вид>. Доли задаются в процентах."]
    for name, k in KINDS.items():
        out.append("%s: %s." % (name, k["what"]))
        out.append("  Поля: %s." % k["fields"])
    return out
