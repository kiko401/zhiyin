"""预置研究底稿：接口失败时的兜底证据层（时点冻结、显式标注）。"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DIR = ROOT / "data" / "dossier"

_cache: dict[str, dict] = {}

TOOL_SECTION = {"snapshot": "snapshot", "kline": "kline", "valuation": "valuation", "financials": "financials"}


def _load(thscode: str) -> dict | None:
    if thscode in _cache:
        return _cache[thscode]
    path = DIR / f"{thscode}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    _cache[thscode] = data
    return data


def _is_stale(frozen_at: str) -> bool:
    try:
        t = datetime.fromisoformat(frozen_at)
    except ValueError:
        return True
    return datetime.now(timezone.utc) - t > timedelta(days=90)


def fallback(thscode: str, tool: str) -> dict | None:
    """返回某工具对应的底稿证据（带冻结时点与"数据较旧"标注），无底稿返回 None。"""
    data = _load(thscode)
    if not data:
        return None
    section = TOOL_SECTION.get(tool)
    if not section:
        return None
    sec = data.get("sections", {}).get(section)
    if not sec:
        return None
    stale = _is_stale(data.get("frozen_at", ""))
    note = "底稿兜底（接口失败），冻结时点 " + data.get("frozen_at", "")
    if stale:
        note += "，数据较旧"
    out = dict(sec)
    out["as_of"] = sec.get("as_of") or data.get("frozen_at", "")[:10]
    out["caliber"] = (sec.get("caliber", "") + "；" + note).strip("；")
    out["__from_dossier__"] = True
    return out
