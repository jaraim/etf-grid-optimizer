# -*- coding: utf-8 -*-
"""数据获取模块：下载ETF历史K线（腾讯行情为主源，akshare 为备用源）。"""
import os
import json
import datetime

import requests
import pandas as pd

# 关闭代理干扰（本环境代理无法访问行情接口）
os.environ.pop("HTTP_PROXY", None)
os.environ.pop("HTTPS_PROXY", None)
os.environ.pop("http_proxy", None)
os.environ.pop("https_proxy", None)

TENCENT_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def _exchange_prefix(symbol: str) -> str:
    """根据代码判断交易所前缀。"""
    s = str(symbol).strip()
    if s.startswith(("5", "6", "9", "110", "113", "118", "500", "51", "55", "56", "58", "60", "68")):
        return "sh" + s
    return "sz" + s


def fetch_tencent(symbol: str, count: int = 2000, adjust: str = "qfq") -> pd.DataFrame:
    """从腾讯接口下载日K线，返回 DataFrame。

    返回列: date, open, close, high, low, volume, amount
    自动重试2次，兼容复权/不复权两种返回。
    """
    code = _exchange_prefix(symbol)
    last_err = None
    for attempt in range(3):
        try:
            params = {"param": f"{code},day,,,{count},{adjust}"}
            resp = requests.get(TENCENT_URL, params=params, timeout=20, headers=UA)
            resp.raise_for_status()
            data = resp.json().get("data", {})
            if code not in data:
                raise ValueError(f"接口未返回 {symbol} 的数据，请检查代码是否正确")
            node = data[code]
            bars = node.get("qfqday") or node.get("day") or []
            if not bars:
                raise ValueError("接口返回空K线")
            df = pd.DataFrame(bars)
            # 腾讯返回列序固定：日期,开,收,高,低,成交量[,成交额]
            cols = ["date", "open", "close", "high", "low", "volume"] + (
                ["amount"] if len(df.columns) > 6 else [])
            df.columns = cols
            df = df.copy()
            df["date"] = pd.to_datetime(df["date"])
            for c in ["open", "close", "high", "low"]:
                df[c] = pd.to_numeric(df[c], errors="coerce")
            df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0)
            if "amount" in df.columns:
                df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0)
            df = df.dropna(subset=["close"]).reset_index(drop=True)
            if len(df) == 0:
                raise ValueError("解析后无有效K线")
            return df
        except Exception as e:  # noqa: BLE001
            last_err = e
            continue
    raise RuntimeError(f"腾讯接口 {symbol} 获取失败：{last_err}")


def fetch_akshare(symbol: str, start_date: str, end_date: str, adjust: str = "qfq") -> pd.DataFrame:
    """备用源：akshare 东财接口。"""
    import akshare as ak
    raw = ak.fund_etf_hist_em(
        symbol=symbol, period="daily",
        start_date=start_date, end_date=end_date, adjust=adjust,
    )
    df = raw.rename(columns={
        "日期": "date", "开盘": "open", "收盘": "close",
        "最高": "high", "最低": "low", "成交量": "volume", "成交额": "amount",
    })
    df["date"] = pd.to_datetime(df["date"])
    return df[["date", "open", "close", "high", "low", "volume", "amount"]].reset_index(drop=True)


def fetch_history(symbol: str, start_date: str = None, end_date: str = None,
                  source: str = "auto", count: int = 2000) -> pd.DataFrame:
    """下载历史K线，支持日期过滤。

    参数:
        symbol: ETF代码，如 513310 / 513180
        start_date: 'YYYYMMDD' 或 None（默认取最早）
        end_date:   'YYYYMMDD' 或 None（默认取最新）
        source: auto / tencent / akshare
    """
    errors = []
    order = ["tencent", "akshare"] if source == "auto" else [source]
    for s in order:
        try:
            if s == "tencent":
                df = fetch_tencent(symbol, count=count)
            else:
                ed = end_date or datetime.datetime.now().strftime("%Y%m%d")
                sd = start_date or "20000101"
                df = fetch_akshare(symbol, sd, ed)
            if start_date:
                df = df[df["date"] >= pd.to_datetime(start_date)]
            if end_date:
                df = df[df["date"] <= pd.to_datetime(end_date)]
            df = df.sort_values("date").reset_index(drop=True)
            if len(df) == 0:
                raise ValueError("日期范围内无数据")
            return df
        except Exception as e:  # noqa: BLE001
            errors.append(f"{s}: {e}")
            continue
    raise RuntimeError("数据获取失败，已尝试的源：" + " | ".join(errors))
