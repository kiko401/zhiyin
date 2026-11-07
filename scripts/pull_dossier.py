#!/usr/bin/env python3
"""拉取五家公司研究底稿并冻结为 data/dossier/*.json。

数据以扶摇 REST 接口返回为准（X-api-key 认证），冻结时点写入 frozen_at；
运行时链路以实时接口为主，本底稿在接口失败时兜底并显式标注数据时点。
"""
import json
import os
import time
import urllib.request
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = "https://fuyao.aicubes.cn"
ROOT = Path(__file__).resolve().parents[1]

COMPANIES = [
    ("300502.SZ", "新易盛"),
    ("300308.SZ", "中际旭创"),
    ("300394.SZ", "天孚通信"),
    ("600519.SH", "贵州茅台"),
    ("300750.SZ", "宁德时代"),
]


def load_env(path: Path) -> dict:
    env = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            env[k] = v
    return env


ENV = load_env(ROOT / ".env.dev")
KEY = os.environ.get("FUYAO_API_KEY") or ENV.get("FUYAO_API_KEY")

TZ = timezone(timedelta(hours=8))


def get(path: str, **params):
    qs = urllib.parse.urlencode(params)
    req = urllib.request.Request(f"{BASE}{path}?{qs}", headers={"X-api-key": KEY})
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            if body.get("code") == 0:
                return body["data"]
            last = RuntimeError(f"{path} code={body.get('code')} {body.get('message')}")
            if body.get("code") not in (4001, 5001, 5002, 5003):
                break  # 调用方可修复错误，不重试
        except Exception as e:  # 网络类错误退避重试
            last = e
        time.sleep(2 * (attempt + 1))
    raise last


def fmt_ms(v):
    return datetime.fromtimestamp(v / 1000, tz=TZ).strftime("%Y-%m-%d") if v else None


def yoy(items, field):
    # 季度序列第 5 项即上年同期；缺值或基数为 0 时不给同比
    if len(items) >= 5 and items[0].get(field) is not None and items[4].get(field) not in (None, 0):
        return round((items[0][field] / items[4][field] - 1) * 100, 2)
    return None


def main():
    out_dir = ROOT / "data" / "dossier"
    out_dir.mkdir(parents=True, exist_ok=True)
    codes = [c for c, _ in COMPANIES]
    joined = ",".join(codes)
    now = datetime.now(TZ)

    # 标的检索：校验代码、取上市日期（同时验证检索接口契约）
    search = {}
    for code, cname in COMPANIES:
        d = get("/api/meta/tickers/search", q=code, limit=1)
        hit = (d.get("item") or [{}])[0]
        search[code] = {"name": hit.get("name") or cname, "list_date": hit.get("list_date")}
        time.sleep(0.3)

    snap = get("/api/a-share/prices/snapshot", thscodes=joined)
    snap_by = {i["thscode"]: i for i in snap.get("item", [])}

    val = get("/api/a-share/valuations/snapshot", thscodes=joined)
    val_by = {i["thscode"]: i for i in val.get("item", [])}

    summary = {}
    for code, cname in COMPANIES:
        end = now
        start = now - timedelta(days=100)  # 约 68 个交易日，截取最近 60 根
        k = get("/api/a-share/prices/historical", thscode=code, interval="1d",
                start=int(start.timestamp() * 1000), end=int(end.timestamp() * 1000),
                adjust="forward")
        bars = [{
            "date": fmt_ms(b["date_ms"]), "open": b["open_price"], "close": b["close_price"],
            "high": b["high_price"], "low": b["low_price"], "volume": b["volume"],
            "turnover": b["turnover"],
        } for b in k.get("item", [])][-60:]

        fin = get("/api/a-share/financials/income-statements", thscode=code,
                  period="quarterly", limit=8)
        fin_items = fin.get("item", [])
        latest = fin_items[0] if fin_items else {}

        s = snap_by.get(code, {})
        v = val_by.get(code, {})
        dossier = {
            "ticker": code.split(".")[0],
            "thscode": code,
            "name": search[code]["name"],
            "list_date": search[code]["list_date"],
            "frozen_at": now.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
            "source": "扶摇API（REST）",
            "sections": {
                "snapshot": {
                    "last_price": s.get("last_price"),
                    "price_change_pct": s.get("price_change_ratio_pct"),
                    "open": s.get("open_price"), "high": s.get("high_price"),
                    "low": s.get("low_price"), "prev_close": s.get("prev_price"),
                    "volume": s.get("volume"), "turnover": s.get("turnover"),
                    "as_of": fmt_ms(snap.get("timestamp")),
                    "unit": "元（CNY）",
                    "caliber": "行情快照，按请求时点返回当日盘中/收盘口径",
                },
                "kline": {
                    "window": "近 60 交易日", "adjust": "forward", "unit": "元（CNY），成交量单位为股",
                    "caliber": "日线前复权", "bars": bars,
                },
                "valuation": {
                    "pe_ttm": v.get("pe_ttm"), "pe_mrq": v.get("pe_mrq"),
                    "pb_mrq": v.get("pb_mrq"), "ps_ttm": v.get("ps_ttm"),
                    "pcf_ttm": v.get("pcf_ttm"),
                    "as_of": fmt_ms(val.get("timestamp")),
                    "unit": "倍",
                    "caliber": "口径见字段名（TTM/MRQ），负值或空值原样保留",
                },
                "financials": {
                    "period": "quarterly", "unit": "元（CNY）",
                    "caliber": "整体合并报表，报告期降序",
                    "latest": {
                        "fiscal_period": f"{latest.get('fiscal_year')}{latest.get('fiscal_period')}" if latest else None,
                        "period_end": fmt_ms(latest.get("period_end_ms")),
                        "report_date": fmt_ms(latest.get("report_date_ms")),
                        "operating_income": latest.get("operating_income"),
                        "operating_income_yoy_pct": yoy(fin_items, "operating_income"),
                        "parent_net_profit": latest.get("parent_holder_net_profit"),
                        "parent_net_profit_yoy_pct": yoy(fin_items, "parent_holder_net_profit"),
                        "basic_eps": latest.get("basic_eps"),
                    },
                    "items": [{
                        "fiscal_period": f"{i.get('fiscal_year')}{i.get('fiscal_period')}",
                        "period_end": fmt_ms(i.get("period_end_ms")),
                        "operating_income": i.get("operating_income"),
                        "parent_holder_net_profit": i.get("parent_holder_net_profit"),
                    } for i in fin_items],
                },
            },
            "caliber_note": "全部数据为冻结时点的扶摇接口返回；运行时以实时接口为准，接口失败时本底稿兜底并显式标注数据时点",
            "disclaimer": "仅供参考，不构成投资建议",
        }
        path = out_dir / f"{code}.json"
        path.write_text(json.dumps(dossier, ensure_ascii=False, indent=2), encoding="utf-8")
        fl = dossier["sections"]["financials"]["latest"]
        summary[code] = {
            "file": path.name, "kline_bars": len(bars), "quarters": len(fin_items),
            "last_price": s.get("last_price"), "pe_ttm": v.get("pe_ttm"),
            "latest_quarter": fl["fiscal_period"], "rev_yoy_pct": fl["operating_income_yoy_pct"],
        }
        time.sleep(0.4)

    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
