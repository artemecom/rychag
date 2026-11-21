"""Версия 5: к модели 3 добавлен третий ход, удержание групп (сообщение организатору неактивной группы).
Причины ухода групп неизвестны: все числа удержания допущения с диапазоном. Строки «Р:» идут в реестр. Деньги в рублях, суммы считаются из округлённых слагаемых."""
import os, io, json, math, contextlib, importlib.util
D = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("m3", os.path.join(D, "model3.py"))
m3 = importlib.util.module_from_spec(spec)
with contextlib.redirect_stdout(io.StringIO()):
    spec.loader.exec_module(m3)
RATE, PM = 500, 300000
def f(x, d=0):
    return f"{round(x, d):,.{d}f}".replace(",", " ").replace(".", ",")
def R(x): return int(round(x))
def z2(p1, p2, z=1.644854 + 0.841621):
    return z * z * (p1 * (1 - p1) + p2 * (1 - p2)) / (p1 - p2) ** 2

RT = {  # удержание групп: допущения по сценариям
 "основной": dict(sh=.70, cut=.05, pers=.50, upl=8, sms=.50),
 "слабый":   dict(sh=.50, cut=.00, pers=.25, upl=4, sms=.70),
 "сильный":  dict(sh=.90, cut=.10, pers=.75, upl=12, sms=.30),
}
N_IN = 6500 * (1 - 5000 / 8000)  # неактивных групп в месяц: 37,5 % подключённых
OUT = {}
for sc in m3.SC:
    p = m3.SC[sc]; q = RT[sc]; r = m3.res[sc]
    e_in = m3.EXITS * q["sh"] / 52           # уходов неактивных групп в неделю
    avoided = mon = 0.0; cost = c_q = [0.0] * 4
    cost = 0.0; cq = [0.0] * 4; mq = [0.0] * 4
    surv = 0.0
    for w in range(5, 53):
        tr = .5 if w <= 13 else .85
        a = e_in * tr * q["cut"]
        avoided += a
        rem = (52 - w) / 4.333
        mon += a * p["nums"] * m3.months(rem, 1.0)
        surv += a * (1 - m3.Q) ** (rem / 12)
        c1 = N_IN / 4.333 * tr * q["sms"] * 2
        cost += c1; cq[min(3, (w - 1) // 13)] += c1
        for k in range(4):
            t1 = max(0.0, (13 * (k + 1) - w) / 4.333); t0 = max(0.0, (13 * k - w) / 4.333)
            mq[k] += a * p["nums"] * (m3.months(t1, 1.0) - m3.months(t0, 1.0))
    act = N_IN * .85 * q["upl"] / 100 * q["pers"]
    p3 = R(mon * RATE) - R(cost)
    OUT[sc] = dict(avoided=avoided, mon=mon, cost=cost, p3=p3, surv=surv, act=act, cq=cq, mq=mq, e_in=e_in)
    p1, p2 = R(r["p1"]), R(r["p2"])
    tot = p1 + p2 + p3
    end = r["end"] + surv; actt = r["act"] + act
    OUT[sc].update(p1=p1, p2=p2, tot=tot, end=end, actt=actt)
    print(f"Р: {sc} сценарий, третий ход (удержание групп): предотвращено уходов {f(avoided)}, остаётся к концу года {f(surv)}; оплаченных месяцев {f(mon)}; расходы на СМС {f(cost)} рублей; итог за год {f(p3)} рублей; активных групп добавляется {f(act)}.")
    print(f"Р: {sc} сценарий, итоги года с тремя ходами: подключённых групп {f(end)}, активных групп {f(actt)}, прибыль {f(279 + tot / 1e6, 2)} миллиона рублей при цели 285; итог за год {f(p1)} плюс {f(p2)} плюс {f(p3)} равно {f(tot)} рублей.")
b = OUT["основной"]; w_ = OUT["слабый"]; s_ = OUT["сильный"]
# безубыточность удержания и размер проверки
val = b["mon"] / b["avoided"] * RATE if b["avoided"] else 0
be = b["cost"] / val / (m3.EXITS * .70 * .5 * .85 / 1) if val else 0
print(f"Р: Удержание окупается при снижении уходов неактивных групп от {f(be * 100 * 1, 1)} % (расходы {f(b['cost'])} рублей, один сохранённый платящий набор номеров группы приносит в год в среднем {f(val)} рублей).")
n_prox = math.ceil(z2(.10, .18))
n_arm = N_IN / 2
p0 = m3.EXITS * .70 / N_IN / 4   # уход за квартал среди неактивных
lo, hi = 0.0005, p0
for _ in range(60):
    mid = (lo + hi) / 2
    if z2(p0, p0 - mid) > n_arm: lo = mid
    else: hi = mid
print(f"Р: Проверка удержания: неактивных групп {f(N_IN)} в месяц, по {f(n_arm)} в варианте; сообщение должно дать разницу 10 % и 18 % активных за 14 дней, для этого достаточно {f(n_prox)} групп в варианте; уход за квартал среди неактивных {f(p0 * 100, 1)} %, различим только спад не меньше {f(hi * 100, 1)} процентного пункта, это {f(hi / p0 * 100)} % от ухода, ожидание 5 % не различимо.")
print(f"Р: Уходы групп 2 100 в год: на неактивные приходится 70 % (допущение), то есть {f(m3.EXITS * .70)} групп; снижение этих уходов на 5 % за полный год сохраняет {f(m3.EXITS * .70 * .05)} групп, на 10 % {f(m3.EXITS * .70 * .10)} групп.")
# просьба
pe = m3.people
fixed = lambda s: R(m3.res[s]["cost"]) + R(m3.res[s]["d2"]) + R(OUT[s]["cost"])
r = m3.res["основной"]
rq13 = sum(b["cq"][:1]) * 9 / 13  # недели 5-13 из первого квартала
ret13 = R(rq13)
ret26 = R(b["cost"] * 0)  # заполнится ниже точнее
c13 = c26 = 0.0
for w in range(5, 53):
    tr = .5 if w <= 13 else .85
    c1 = N_IN / 4.333 * tr * RT["основной"]["sms"] * 2
    if w <= 13: c13 += c1
    elif w <= 26: c26 += c1
c13, c26 = R(c13), R(c26)
c52 = R(b["cost"]) - c13 - c26
t1 = R(2.5 * PM) + R(r["test_cost"]) + c13
t2 = R(3 * PM) + R(r["expo_q2"]) + R(r["d2"] / 2) + c26
t3 = R(3 * PM) + (R(r["cost"]) - R(r["cost_to26"])) + R(r["d2"]) - R(r["d2"] / 2) + c52
tot = t1 + t2 + t3
print(f"Р: Просьба по частям при 300 000 рублей за человеко-месяц: сейчас {f(t1)} рублей, на неделе 13 ещё {f(t2)} рублей, на неделе 26 ещё {f(t3)} рублей, всего {f(tot)} рублей.")
fx = R(r["cost"]) + R(r["d2"]) + R(b["cost"])
for pm in (200000, 300000, 450000):
    print(f"Р: Всего на год при {f(pm)} рублей за человеко-месяц: {f(R(8.5 * pm) + fx)} рублей; сейчас {f(R(2.5 * pm) + R(r['test_cost']) + c13)} рублей.")
ws = m3.res["слабый"]
c13w = c26w = 0.0
for w in range(5, 53):
    tr = .5 if w <= 13 else .85
    c1 = N_IN / 4.333 * tr * RT["слабый"]["sms"] * 2
    if w <= 13: c13w += c1
    elif w <= 26: c26w += c1
loss13 = R(2.5 * 450000) + R(ws["test_cost"]) + R(c13w)
loss26 = R(5.5 * 450000) + R(ws["cost_to26"]) + R(ws["d2"] / 2) + R(c13w) + R(c26w)
print(f"Р: Наибольшая потеря при остановке на неделе 13 {f(loss13)} рублей, на неделе 26 {f(loss26)} рублей (слабый сценарий, 450 000 рублей за человеко-месяц); в основном сценарии и при 300 000 рублей сейчас {f(t1)} рублей, к неделе 26 {f(t1 + t2)} рублей.")
# вклад в цели
conn = b["end"]; actt = b["actt"]
print(f"Р: Вклад в цели, подключённые группы: разрыв 4 000; первый ход {f(r['sur'])}, второй {f(r['prevented'])}, третий {f(b['surv'])}; остаток {f(12000 - conn)}.")
print(f"Р: Вклад в цели, активные группы: разрыв 3 000; первый ход {f(r['sur'] * r['p']['actnew'])}, второй {f(r['act'] - 5000 - r['sur'] * r['p']['actnew'])}, третий {f(b['act'])}; итог {f(actt)}, доля активных {f(actt / conn * 100, 1)} %; остаток {f(8000 - actt)}.")
print(f"Р: Вклад в цели, прибыль: разрыв 6 000 000 рублей; первый ход {f(b['p1'])}, второй {f(b['p2'])}, третий {f(b['p3'])}; сумма {f(b['tot'])}; остаток {f(6000000 - b['tot'])} рублей.")
# следующие годы
fresh = max(0.0, r["pool"] - r["exposed"])
a_aud = 770 * 52
y2_app = min(fresh, a_aud) * .05; y2_ss = 460
y2_cost = R(min(fresh, a_aud) * (20 + .075 * 300)) + 800000 + 150000 + R(N_IN / 4.333 * 52 * .85 * .5 * 2 / 1.0)
y2_ret = m3.EXITS * .70 * .85 * .05 * 52 / 52
mo_c = r["sur"] * r["nn"] * sum(.98 ** t for t in range(12)) * .85
mo_n = (y2_app + y2_ss) * r["nn"] * m3.months(6, .70)
mo_r_carry = b["surv"] * 3 * sum(.98 ** t for t in range(12)) * .85
mo_r_new = y2_ret * 3 * sum(.98 ** t for t in range(6))
p_y2 = R((mo_c + mo_n + mo_r_carry + mo_r_new) * RATE) - y2_cost
end2 = m3.NOCHANGE + r["sur"] * (1 - m3.Q) + (y2_app + y2_ss) * .85 + b["surv"] * (1 - m3.Q) + y2_ret * .85 + r["prevented"]
end3 = m3.NOCHANGE + r["sur"] * (1 - m3.Q) ** 2 + (y2_app + y2_ss) * .85 * (1 - m3.Q) + b["surv"] * (1 - m3.Q) ** 2 + y2_ret * .85 * (1 - m3.Q) + (770 * 52 * .017 + 460) * .85 + y2_ret * .85
print(f"Р: Следующие годы: подключённых групп к концу первого года {f(conn)}, второго {f(end2)}, третьего {f(end3)}; прибыль второго года {f(p_y2)} рублей после расходов {f(y2_cost)} рублей; цель 285 во втором году {'достигается' if p_y2 >= 6000000 else 'не достигается'}.")
# ряд по кварталам в рублях
def series(sc):
    p = m3.SC[sc]; nn = p["P"] * p["s"]; pr = [0.0] * 8; co = [0.0] * 8
    def cohort(incr, wj, rb):
        for q in range(4):
            t1 = max(0.0, (13 * (q + 1) - wj) / 4.333); t0 = max(0.0, (13 * q - wj) / 4.333)
            pr[q] += incr * nn * (m3.months(t1, rb) - m3.months(t0, rb)) * RATE
    cohort(1500 * p["dA"] / 100, 10, 1.0); cohort(1500 * p["dB"] / 100, 10, p["rb"])
    co[0] += 1500 * p["expc"] * 2 + 1500 * (p["p0"] + p["dB"]) / 100 * p["bonus"]
    for w in range(11, 51):
        n = p["aud"] * .5 if w <= 26 else (p["aud"] * .85 if p["go"] else 0.0)
        if n <= 0: continue
        cohort(n * p["dB"] / 100, w + 2, p["rb"])
        co[min(3, (w - 1) // 13)] += n * p["expc"] + n * (p["p0"] + p["dB"]) / 100 * p["bonus"]
    share = p["compat"] * p["consent"]
    treated = m3.res[sc]["treated"]
    ro, rn = .98, .98 + p["churn_d"] / 100
    d = [rn ** t - ro ** t for t in range(6)]
    pr[2] += treated * sum(d[:3]) * RATE; pr[3] += treated * sum(d[3:]) * RATE
    co[1] += p["dir2"] / 6; co[2] += p["dir2"] / 6
    for k in range(4):
        pr[k] += OUT[sc]["mq"][k] * RATE; co[k] += OUT[sc]["cq"][k]
    rr = m3.res[sc]
    if p["go"]:
        fr = max(0.0, rr["pool"] - rr["exposed"]); app = min(fr, 770 * 52); yn = app * .05 + 460
        yc = app * (20 + .075 * 300) + 800000 + 150000 + 30000
        mc = rr["sur"] * nn * sum(.98 ** t for t in range(12)) * .85
        mn = yn * nn * m3.months(6, .70)
        mrc = OUT[sc]["surv"] * 3 * sum(.98 ** t for t in range(12)) * .85
        mrn = (m3.EXITS * RT[sc]["sh"] * .85 * RT[sc]["cut"]) * 3 * sum(.98 ** t for t in range(6))
        wts = [1, 3, 5, 7]
        for k in range(4):
            pr[4 + k] = (mc / 4 + mn * wts[k] / 16 + mrc / 4 + mrn * wts[k] / 16) * RATE; co[4 + k] = yc / 4
    else:
        for k in range(4):
            pr[4 + k] = (rr["sur"] * nn * 3 * .5 + OUT[sc]["surv"] * 3 * 3 / 4) * RATE; co[4 + k] = OUT[sc]["cost"] / 4
    return [R(x) for x in pr], [R(x) for x in co]
for sc, name in (("основной", "kv5_osnovnoi.json"), ("слабый", "kv5_slabyi.json")):
    pr, co = series(sc)
    inv = [R(2.5 * PM), R(3.5 * PM), R(1.5 * PM), R(1.5 * PM)] + [R(1.5 * PM)] * 4 if sc == "основной" else [R(2.5 * PM), R(3.5 * PM), 0, 0, 0, 0, 0, 0]
    json.dump({"единица": "руб.", "срок_кварталов": 8, "доп_прибыль_по_кварталам": pr, "прямые_расходы_по_кварталам": co, "вложения_по_кварталам": inv},
              open(os.path.join(D, name), "w"), ensure_ascii=False, indent=1)
