# -*- coding: utf-8 -*-
"""5分钟K线数据获取模块（腾讯 ifzq 行情接口，带重试与缓存）。"""
import os
import time
import requests
import pandas as pd

# 关闭代理干扰（本环境代理无法访问行情接口）
for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
    os.environ.pop(k, None)

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
M5_URL = "https://ifzq.gtimg.cn/appstock/app/kline/mkline"


def _exchange_prefix(symbol: str) -> str:
    s = str(symbol).strip()
    if s.startswith(("5", "6", "9", "110", "113", "118", "500", "51", "55", "56", "58", "60", "68")):
        return "sh" + s
    return "sz" + s


def fetch_5min(symbol: str, count: int = 400) -> pd.DataFrame:
    """下载5分钟K线，返回 DataFrame: time, open, close, high, low, volume, amount.

    腾讯5分钟接口返回 bar 形如 [时间, 开, 收, 高, 低, 量, {}, 额]
    """
    code = _exchange_prefix(symbol)
    last_err = None
    for attempt in range(4):
        try:
            params = {"param": f"{code},m5,,{count}"}
            resp = requests.get(M5_URL, params=params, timeout=20, headers=UA)
            resp.raise_for_status()
            data = resp.json().get("data", {})
            if code not in data:
                raise ValueError(f"接口未返回 {symbol} 的5分钟数据，请检查代码")
            node = data[code]
            key = next((k for k in node.keys() if "m5" in k), None)
            if not key:
                raise ValueError("接口未返回 m5 字段")
            bars = node[key]
            if not bars:
                raise ValueError("5分钟K线为空")
            df = pd.DataFrame(bars)
            # 腾讯5分钟列序固定
            df = df.iloc[:, :8]
            df.columns = ["time", "open", "close", "high", "low", "volume", "_e", "amount"]
            df["time"] = pd.to_datetime(df["time"], format="%Y%m%d%H%M")
            for c in ["open", "close", "high", "low", "volume"]:
                df[c] = pd.to_numeric(df[c], errors="coerce")
            df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0)
            df = df.dropna(subset=["close"]).reset_index(drop=True)
            df = df.sort_values("time").reset_index(drop=True)
            if len(df) == 0:
                raise ValueError("解析后无有效5分钟K线")
            return df[["time", "open", "close", "high", "low", "volume", "amount"]]
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(0.8 * (attempt + 1))
    raise RuntimeError(f"腾讯5分钟接口 {symbol} 获取失败：{last_err}")
