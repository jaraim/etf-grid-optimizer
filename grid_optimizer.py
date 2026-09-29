# -*- coding: utf-8 -*-
"""核心分析模块：涨跌幅/振幅分析 + 短/中/长网格参数优化 + 网格回测。"""
import numpy as np
import pandas as pd

COMMISSION_RATE = 0.0005  # 单边手续费约0.05%（ETF无印花税）
ORDER_AMOUNT = 10000      # 每笔买入金额（元），用于回测
MAX_POSITION = 10         # 最大持仓份数（风控）


# ========================= 涨跌幅 / 振幅分析 =========================
def analyze_volatility(df: pd.DataFrame) -> dict:
    """计算每日涨跌幅、振幅，并输出百分位分布。"""
    d = df.copy().sort_values("date").reset_index(drop=True)
    d["prev_close"] = d["close"].shift(1)
    d["ret"] = d["close"] / d["prev_close"] - 1.0
    d["amplitude"] = d["high"] / d["low"] - 1.0
    d = d.dropna(subset=["ret"])

    abs_ret = d["ret"].abs().dropna()
    amp = d["amplitude"].dropna()

    percs = [5, 10, 20, 25, 30, 40, 50, 60, 70, 75, 80, 85, 90, 95]
    return {
        "n": len(d),
        "date_start": str(d["date"].iloc[0].date()),
        "date_end": str(d["date"].iloc[-1].date()),
        "abs_ret_percentiles": {str(p): round(float(abs_ret.quantile(p / 100)) * 100, 4) for p in percs},
        "amp_percentiles": {str(p): round(float(amp.quantile(p / 100)) * 100, 4) for p in percs},
        "avg_abs_ret": round(float(abs_ret.mean()) * 100, 4),
        "avg_amplitude": round(float(amp.mean()) * 100, 4),
        "max_up": round(float(d["ret"].max()) * 100, 4),
        "max_down": round(float(d["ret"].min()) * 100, 4),
        "last_close": float(d["close"].iloc[-1]),
    }


# ========================= 网格回测（事件驱动） =========================
def backtest_grid(df: pd.DataFrame, base: float, grid_pct: float,
                  confirm_pct: float, layers: int = 5,
                  order_amount: float = ORDER_AMOUNT,
                  max_pos: int = MAX_POSITION) -> dict:
    """真实网格回测（每笔独立配对）。

    买入档: base*(1-grid_pct)^(i+1)，当日 low<=档位价 且 close>=档位价*(1+confirm) → 买入该档
    卖出目标: 每笔买入价*(1+grid_pct)，当日 high>=卖出目标 且 close<=卖出目标*(1-confirm) → 平仓该笔
    """
    t = grid_pct / 100.0
    c = confirm_pct / 100.0
    fee = COMMISSION_RATE
    buy_levels = [base * (1 - t) ** (i + 1) for i in range(layers)]

    open_orders = []      # 每笔: {"buy": 买入价, "shares": 份额}
    realized = 0.0        # 已实现盈亏（元）
    buys = sells = 0
    peak_pos = 0

    rows = df.sort_values("date").reset_index(drop=True)
    for _, r in rows.iterrows():
        low, high, close = r["low"], r["high"], r["close"]

        # --- 买入检测（单日最多加1份，从最低档向上找，避免同一天重复加仓）---
        if len(open_orders) < max_pos:
            for lv in reversed(buy_levels):
                if low <= lv and close >= lv * (1 + c):
                    buy_price = lv * (1 + c)
                    shares = order_amount / buy_price
                    open_orders.append({"buy": buy_price, "shares": shares})
                    buys += 1
                    break

        # --- 卖出检测（每笔独立止盈）---
        remaining = []
        for od in open_orders:
            sell_target = od["buy"] * (1 + t)
            if high >= sell_target and close <= sell_target * (1 - c):
                sell_price = sell_target * (1 - c)
                gross = (sell_price - od["buy"]) * od["shares"]
                fee_cost = od["buy"] * od["shares"] * fee + sell_price * od["shares"] * fee
                realized += gross - fee_cost
                sells += 1
            else:
                remaining.append(od)
        open_orders = remaining
        peak_pos = max(peak_pos, len(open_orders))

    last_close = rows["close"].iloc[-1]
    total_shares = sum(od["shares"] for od in open_orders)
    cost_sum = sum(od["buy"] * od["shares"] for od in open_orders)
    unrealized = (last_close * total_shares - cost_sum) - cost_sum * fee
    total_pnl = realized + unrealized
    invested = buys * order_amount
    ret_rate = total_pnl / invested if invested > 0 else 0.0

    return {
        "base": round(base, 4),
        "grid_pct": round(grid_pct, 3),
        "confirm_pct": round(confirm_pct, 3),
        "layers": layers,
        "buys": buys,
        "sells": sells,
        "trades": buys + sells,
        "max_position": peak_pos,
        "invested": round(invested, 2),
        "realized": round(realized, 2),
        "unrealized": round(unrealized, 2),
        "total_pnl": round(total_pnl, 2),
        "ret_rate": round(ret_rate * 100, 4),
        "last_close": round(last_close, 4),
    }


# ========================= 短/中/长参数优化 =========================
# 各周期：网格间距基准取 |日涨跌幅| 的百分位区间；确认阈值取间距的比例区间
PERIOD_CONFIG = {
    "短线": {"pct_range": (45, 60), "confirm_range": (0.10, 0.25)},
    "中线": {"pct_range": (60, 75), "confirm_range": (0.10, 0.20)},
    "长线": {"pct_range": (75, 88), "confirm_range": (0.08, 0.15)},
}
# 各周期基价用不同窗口的均线作为中枢
PERIOD_MA = {"短线": 20, "中线": 60, "长线": 120}


def _candidate_values(p_low: int, p_high: int, abs_ret_pct: dict) -> list:
    """在百分位区间内生成候选网格间距值。abs_ret_pct 键为字符串百分位。"""
    pcts = sorted(set(list(range(p_low, p_high + 1, 5)) + [p_high]))
    vals = [abs_ret_pct.get(str(p)) for p in pcts]
    vals = [v for v in vals if v]
    # 保证候选不为空，且间距不过小（低于0.5%易被手续费吃光）
    vals = [max(v, 0.5) for v in vals]
    return vals or [2.0]


def optimize_periods(df: pd.DataFrame, ma_ratio: float = 1.0,
                     layers: int = 5) -> list:
    """对短/中/长三个周期分别搜索最优网格参数。

    返回 list[dict]，每项含: period, base, grid_pct, confirm_pct, backtest
    """
    d = df.sort_values("date").reset_index(drop=True)
    vol = analyze_volatility(d)
    abs_ret_pct = vol["abs_ret_percentiles"]  # 键为字符串百分位

    results = []
    for period, cfg in PERIOD_CONFIG.items():
        p_low, p_high = cfg["pct_range"]
        grid_cands = _candidate_values(p_low, p_high, abs_ret_pct)
        c_lo, c_hi = cfg["confirm_range"]

        # 基价 = 周期对应均线
        win = PERIOD_MA[period]
        if len(d) >= win:
            base = float(d["close"].iloc[-win:].mean())
        else:
            base = float(d["close"].iloc[-1])
        base = base * ma_ratio

        best = None
        for g in grid_cands:
            conf_cands = {round(g * x, 4) for x in np.arange(c_lo, c_hi + 1e-6, 0.025)}
            conf_cands.add(round(g / 7.0, 4))  # 经验比例 1/7
            conf_cands = sorted(v for v in conf_cands if v > 0.1)
            for cf in conf_cands:
                bt = backtest_grid(d, base, g, cf, layers=layers)
                # 得分：收益优先，惩罚无交易/深套
                score = bt["ret_rate"]
                if bt["trades"] < 3:
                    score -= 100  # 交易太少，参数无意义
                # 惩罚期末深套（浮动亏损占投入比例过大）
                if bt["invested"] > 0 and bt["unrealized"] < 0:
                    deep = -bt["unrealized"] / bt["invested"]
                    score -= deep * 20
                if best is None or score > best["score"]:
                    best = {"score": score, "grid_pct": g, "confirm_pct": cf,
                            "backtest": bt}
        if best is None:
            best = {"score": -999, "grid_pct": grid_cands[0],
                    "confirm_pct": 0.15, "backtest": backtest_grid(d, base, grid_cands[0], 0.15, layers)}
        results.append({
            "period": period,
            "base": round(base, 4),
            "grid_pct": round(best["grid_pct"], 3),
            "confirm_pct": round(best["confirm_pct"], 3),
            "score": round(best["score"], 4),
            "backtest": best["backtest"],
        })
    return results
