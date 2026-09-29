# -*- coding: utf-8 -*-
"""Flask WebUI 入口：ETF历史K线网格参数优化工具。"""
import os
from flask import Flask, render_template, request, jsonify

from data_fetcher import fetch_history
from grid_optimizer import analyze_volatility, optimize_periods

os.environ.pop("HTTP_PROXY", None)
os.environ.pop("HTTPS_PROXY", None)

app = Flask(__name__)


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

    # K线数据（转成前端数组）
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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
