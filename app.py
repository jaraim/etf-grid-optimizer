# -*- coding: utf-8 -*-
"""Flask WebUI 入口：ETF网格交易工具（两个功能页面）。
- /            : 日K 短/中/长网格参数自动优化
- /backtest5   : 5分钟K线 触网标记+反向确认成交 回测
"""
import os
from flask import Flask, render_template, request, jsonify

from data_fetcher import fetch_history
from grid_optimizer import analyze_volatility, optimize_periods
from data_fetcher_min import fetch_5min
from grid_engine_5min import backtest_5min

for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
    os.environ.pop(k, None)

app = Flask(__name__)


# ========================= 首页：日K 参数优化 =========================
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/analyze")
def api_analyze():
    symbol = (request.args.get("symbol") or "513310").strip()
    start = request.args.get("start") or None
    end = request.args.get("end") or None
    try:
        ma_ratio = float(request.args.get("ma_ratio", "1"))
        layers = int(request.args.get("layers", "5"))
    except ValueError:
        return jsonify({"ok": False, "error": "ma_ratio/layers 必须是数字"}), 400

    try:
        df = fetch_history(symbol, start_date=start, end_date=end)
    except RuntimeError as e:
        return jsonify({"ok": False, "error": str(e)}), 502

    vol = analyze_volatility(df)
    periods = optimize_periods(df, ma_ratio=ma_ratio, layers=layers)

    d = df.sort_values("date").reset_index(drop=True)
    klines = [
        {
            "date": str(r["date"].date()),
            "open": float(r["open"]), "close": float(r["close"]),
            "high": float(r["high"]), "low": float(r["low"]),
            "volume": float(r["volume"]),
        }
        for r in d.to_dict("records")
    ]

    return jsonify({
        "ok": True,
        "symbol": symbol,
        "volatility": vol,
        "periods": periods,
        "klines": klines,
    })


# ========================= 5分钟K线 回测 =========================
@app.route("/backtest5")
def backtest5():
    return render_template("index_5min.html")


@app.route("/api/backtest5")
def api_backtest5():
    try:
        symbol = (request.args.get("symbol") or "513180").strip()
        base = float(request.args.get("base", "0.534"))
        grid_pct = float(request.args.get("grid", "1.0"))
        confirm_pct = float(request.args.get("confirm", "0.362"))
        order_amount = float(request.args.get("amount", "10000"))
        init_cash = float(request.args.get("cash", "100000"))
        max_pos = int(request.args.get("max_pos", "6"))
        count = int(request.args.get("count", "400"))
    except ValueError as e:
        return jsonify({"ok": False, "error": f"参数错误：{e}"}), 400

    try:
        df = fetch_5min(symbol, count=count)
    except RuntimeError as e:
        return jsonify({"ok": False, "error": str(e)}), 502

    r = backtest_5min(df, base=base, grid_pct=grid_pct, confirm_pct=confirm_pct,
                      order_amount=order_amount, init_cash=init_cash, max_pos=max_pos)

    klines = [
        {"time": str(t), "open": float(o), "close": float(cl),
         "high": float(h), "low": float(l), "volume": float(v)}
        for t, o, cl, h, l, v in zip(df["time"], df["open"], df["close"],
                                     df["high"], df["low"], df["volume"])
    ]
    price_range = {
        "min": float(df["low"].min()),
        "max": float(df["high"].max()),
        "last": float(df["close"].iloc[-1]),
    }
    return jsonify({"ok": True, "symbol": symbol, **r,
                    "klines": klines, "price_range": price_range})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
