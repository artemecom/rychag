"""Ряд по кварталам для окупаемости (тысячи рублей), основной и слабый сценарий, версия 4. Пишет kv3_*.json рядом."""
import json, os, io, contextlib, importlib.util
D = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("m3", os.path.join(D, "model3.py"))
m3 = importlib.util.module_from_spec(spec)
with contextlib.redirect_stdout(io.StringIO()):
    spec.loader.exec_module(m3)
RATE = 500

def series(sc):
    p = m3.SC[sc]; nn = p["P"] * p["s"]
    prof = [0.0] * 8; cost = [0.0] * 8
    def cohort(incr, wj, rb):
        for q in range(4):
            t1 = max(0.0, (13 * (q + 1) - wj) / 4.333); t0 = max(0.0, (13 * q - wj) / 4.333)
            prof[q] += incr * nn * (m3.months(t1, rb) - m3.months(t0, rb)) * RATE
    cohort(1500 * p["dA"] / 100, 10, 1.0); cohort(1500 * p["dB"] / 100, 10, p["rb"])
    cost[0] += 1500 * p["expc"] * 2 + 1500 * (p["p0"] + p["dB"]) / 100 * p["bonus"]
    tot_incr = 1500 * (p["dA"] + p["dB"]) / 100
    for w in range(11, 51):
        n = p["aud"] * .5 if w <= 26 else (p["aud"] * .85 if p["go"] else 0.0)
        if n <= 0: continue
        ic = n * p["dB"] / 100; tot_incr += ic
        cohort(ic, w + 2, p["rb"])
        cost[min(3, (w - 1) // 13)] += n * p["expc"] + n * (p["p0"] + p["dB"]) / 100 * p["bonus"]
    # второй ход
    share = p["compat"] * p["consent"]
    treated = (6500 + 1000) * share * p["nums"] / 3 / 2
    ro, rn = .98, .98 + p["churn_d"] / 100
    d = [rn ** t - ro ** t for t in range(6)]
    prof[2] += treated * sum(d[:3]) * RATE; prof[3] += treated * sum(d[3:]) * RATE
    cost[1] += p["dir2"] / 6; cost[2] += p["dir2"] / 6
    # второй год
    r = m3.res[sc]
    if p["go"]:
        fresh = max(0.0, r["pool"] - r["exposed"]); app = min(fresh, 770 * 52); y2_new = app * .05 + 460
        y2_cost = app * (20 + .075 * 300) + 800000 + 150000
        mo_c = r["sur"] * nn * sum(.98 ** t for t in range(12)) * .85
        mo_n = y2_new * nn * m3.months(6, .70)
        w_ = [1, 3, 5, 7]
        for q in range(4):
            prof[4 + q] = (mo_c / 4 + mo_n * w_[q] / 16) * RATE
            cost[4 + q] = y2_cost / 4
    else:
        for q in range(4):
            prof[4 + q] = r["sur"] * nn * 3 * RATE * .5
    return [round(x / 1000) for x in prof], [round(x / 1000) for x in cost]

for sc, name in (("основной", "kv3_osnovnoi.json"), ("слабый", "kv3_slabyi.json")):
    pr, co = series(sc)
    inv = [750, 900, 450, 450, 450, 450, 450, 450] if sc == "основной" else [750, 900, 0, 0, 0, 0, 0, 0]
    json.dump({"единица": "тыс. руб.", "срок_кварталов": 8, "доп_прибыль_по_кварталам": pr, "прямые_расходы_по_кварталам": co, "вложения_по_кварталам": inv},
              open(os.path.join(D, name), "w"), ensure_ascii=False, indent=1)
    print(sc, pr, co)
