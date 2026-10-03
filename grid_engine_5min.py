# -*- coding: utf-8 -*-
"""触网标记 + 反向确认成交 网格回测引擎（5分钟K线，事件驱动）。

规则（用户定义）：
- 网格间距 grid_pct（%），确认阈值 confirm_pct（%）
- 买入：价格跌破网格线(基价*(1-grid)) 仅标记；此后价格反弹回到 网格线*(1+confirm) 才下单买入
- 卖出：价格涨破卖出网格线(买入价*(1+grid)) 仅标记；此后价格回落 卖出网格线*(1-confirm) 才下单卖出
- 手续费：万1，单笔保底 0.1 元
"""
import pandas as pd


def _fee(trade_value: float, rate: float = 0.0001, min_fee: float = 0.1) -> float:
    return max(trade_value * rate, min_fee)


def backtest_5min(df: pd.DataFrame, base: float, grid_pct: float, confirm_pct: float,
                  order_amount: float = 10000.0, init_cash: float = 100000.0,
                  max_pos: int = 6) -> dict:
    g = grid_pct / 100.0
    c = confirm_pct / 100.0

    cash = float(init_cash)
    positions = []          # {"buy", "grid", "confirm", "shares", "buy_fee", "armed": 是否已触卖网标记}
    pending_buy = None      # 已跌破未反弹确认的买入网格线
    logs = []
    equity = []
    times = []
    buy_points = []
    sell_points = []
    realized = 0.0
    peak_pos = 0

    bars = df.sort_values("time").reset_index(drop=True)
    for idx, r in bars.iterrows():
        t = str(r["time"])
        hi, lo, cl = float(r["high"]), float(r["low"]), float(r["close"])

        # ===== 卖出：先检查每笔持仓 =====
        keep = []
        for pos in positions:
            sg, sc = pos["grid"], pos["confirm"]
            if hi >= sg:                    # 触达卖出网格线 → 标记
                pos["armed"] = True
            if pos["armed"] and lo <= sc:   # 已标记且回落确认 → 成交
                sell_price = sc
                gross = pos["shares"] * sell_price
                fee = _fee(gross)
                cash += gross - fee
                realized += (sell_price - pos["buy"]) * pos["shares"] - fee - pos.get("buy_fee", 0)
                sell_points.append([t, sell_price])
                logs.append({"t": t, "act": "卖出", "price": round(sell_price, 4),
                             "shares": round(pos["shares"], 2), "fee": round(fee, 2),
                             "cash": round(cash, 2)})
                continue
            keep.append(pos)
        positions = keep

        # ===== 买入 =====
        if len(positions) < max_pos:
            if pending_buy is not None:
                gline, confirm_price = pending_buy
                if hi >= confirm_price:          # 反弹确认 → 买入
                    buy_amt = order_amount
                    buy_fee = _fee(buy_amt)
                    shares = (buy_amt - buy_fee) / confirm_price
                    cash -= buy_amt
                    positions.append({
                        "buy": confirm_price,
                        "grid": confirm_price * (1 + g),
                        "confirm": confirm_price * (1 + g) * (1 - c),
                        "shares": shares,
                        "buy_fee": buy_fee,
                        "armed": False,
                    })
                    buy_points.append([t, confirm_price])
                    logs.append({"t": t, "act": "买入", "price": round(confirm_price, 4),
                                 "shares": round(shares, 2), "fee": round(buy_fee, 2),
                                 "cash": round(cash, 2)})
                    pending_buy = None
            if pending_buy is None and len(positions) < max_pos:
                ref = base if len(positions) == 0 else positions[-1]["buy"]
                gline = ref * (1 - g)
                confirm_price = gline * (1 + c)
                if lo <= gline:
                    if hi >= confirm_price:      # 同bar跌破又反弹确认 → 直接买入
                        buy_amt = order_amount
                        buy_fee = _fee(buy_amt)
                        shares = (buy_amt - buy_fee) / confirm_price
                        cash -= buy_amt
                        positions.append({
                            "buy": confirm_price,
                            "grid": confirm_price * (1 + g),
                            "confirm": confirm_price * (1 + g) * (1 - c),
                            "shares": shares,
                            "buy_fee": buy_fee,
                            "armed": False,
                        })
                        buy_points.append([t, confirm_price])
                        logs.append({"t": t, "act": "买入", "price": round(confirm_price, 4),
                                     "shares": round(shares, 2), "fee": round(buy_fee, 2),
                                     "cash": round(cash, 2)})
                    else:
                        pending_buy = (gline, confirm_price)

        peak_pos = max(peak_pos, len(positions))
        mv = sum(p["shares"] * cl for p in positions)
        equity.append(cash + mv)
        times.append(t)

    last_close = float(bars["close"].iloc[-1])
    total_shares = sum(p["shares"] for p in positions)
    unrealized = 0.0
    for p in positions:
        cost = p["buy"] * p["shares"] + p.get("buy_fee", 0)
        unrealized += p["shares"] * last_close - cost
    final_asset = equity[-1] if equity else cash
    total_pnl = final_asset - init_cash
    ret = total_pnl / init_cash * 100

    return {
        "base": round(base, 4),
        "grid_pct": round(grid_pct, 3),
        "confirm_pct": round(confirm_pct, 3),
        "init_cash": init_cash,
        "final_asset": round(final_asset, 2),
        "total_pnl": round(total_pnl, 2),
        "ret_rate": round(ret, 4),
        "realized": round(realized, 2),
        "unrealized": round(unrealized, 2),
        "buys": len(buy_points),
        "sells": len(sell_points),
        "max_position": peak_pos,
        "end_shares": round(total_shares, 2),
        "remaining_cash": round(cash, 2),
        "last_close": round(last_close, 4),
        "n_bars": len(bars),
        "equity": equity,
        "times": times,
        "logs": logs,
        "buy_points": buy_points,
        "sell_points": sell_points,
    }
