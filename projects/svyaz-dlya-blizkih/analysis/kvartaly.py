"""Ряд по кварталам для окупаемости, основной и слабый ход, тысячи рублей. Пишет файлы параметров рядом."""
import json, os
D = os.path.dirname(os.path.abspath(__file__))
RATE = 500
def q_of_week(w): return min(3, (w - 1) // 13)

def build(sc):
    if sc == "основной":
        aud, p0, dA, dB, expc, bonus, nu, nums, scale = 770, 2.5, 1.7, 5.0, 20, 300, .30, 3, True
        churn_d, nums2, share, treated_nums, direct2 = .15, 3, .48, 5772, 150000
    else:
        aud, p0, dA, dB, expc, bonus, nu, nums, scale = 400, 1.5, .5, 2.0, 40, 600, .10, 2, False
        churn_d, nums2, share, treated_nums, direct2 = .02, 2, .24, 1744, 240000
    prof = [0.0] * 8; costs = [0.0] * 8
    # проверка хода 1: показ недели 5-10, подключения около недели 8
    inc_t = 1500 * (dA + dB) / 100
    tc = 1500 * expc * 2 + bonus * 1500 * (2 * p0 + dA + dB) / 100
    costs[0] += tc
    prof[0] += inc_t * nu * nums * (min(13, 52 - 8) - 8) / 4.333 * RATE if False else 0
    # месяцы по кварталам: подключение недели 8, платит с недели 8 до конца года
    def add_months(week_join, groups):
        for q in range(4):
            start, end = q * 13 + 1, q * 13 + 13
            weeks = max(0, min(end, 52) - max(start, week_join + 1) + 1)
            prof[q] += groups * nu * nums * weeks / 4.333 * RATE
    add_months(10, inc_t)
    inc = 0.0
    if scale:
        for w in range(14, 51):
            ic = aud * dB / 100
            add_months(w + 2, ic)
            costs[q_of_week(w)] += aud * expc + aud * (p0 + dB) / 100 * bonus
            inc += ic
    # ход 2: удержание с седьмого месяца на половине охвата
    ro, rn = .98, .98 + churn_d / 100
    d = [rn ** t - ro ** t for t in range(6)]
    prof[2] += treated_nums * sum(d[:3]) * RATE
    prof[3] += treated_nums * sum(d[3:]) * RATE
    costs[2] += direct2 / 2; costs[3] += direct2 / 2
    # второй год
    carry = (inc + inc_t) * nu * nums * 12 * RATE / 4
    pool_left = 53500 - 3000 - 28490 if scale else 0
    y2_inc = min(pool_left, aud * 52) * dB / 100 if scale else 0
    new_w = [.5, 1.5, 2.5, 3.5]
    N2 = 8000 * share * nums2
    m2_total = N2 * sum(rn ** t - ro ** t for t in range(12)) * RATE
    wts = [3, 12, 21, 30]
    y2_cost = min(pool_left, aud * 52) * (expc + (p0 + dB) / 100 * bonus) if scale else 0
    for q in range(4):
        prof[4 + q] = carry + y2_inc * nu * nums * 12 * RATE * new_w[q] / 16 + m2_total * wts[q] / 66
        costs[4 + q] = y2_cost / 4 + direct2 / 4
    return [round(x / 1000) for x in prof], [round(x / 1000) for x in costs]

for sc, name in (("основной", "kv2_osnovnoi.json"), ("слабый", "kv2_slabyi.json")):
    p, c = build(sc)
    inv = [750, 1950, 450, 450, 450, 450, 450, 450]
    json.dump({"единица": "тыс. руб.", "срок_кварталов": 8, "доп_прибыль_по_кварталам": p, "прямые_расходы_по_кварталам": c, "вложения_по_кварталам": inv},
              open(os.path.join(D, name), "w"), ensure_ascii=False, indent=1)
    print(sc, p, c)
