"""三层词典加载与文本消解（D3 静默消解 / D4 规格确认式）。"""
import csv
import re

from sqlalchemy import select

from app.core import config
from app.core.db import SessionLocal
from app.models import LexiconTerm

# 模块级缓存：全局词条（L1/L2）仅加载一次
_TERMS: list[dict] | None = None

# “名称（代码）”形态：括号内须为证券代码（字母数字点号），以区别于公式与注释性括注
_CODE_CANONICAL = re.compile(r"^(?P<name>[^（()]+)（(?P<code>[0-9A-Za-z.]{6,})）$")

_SILENT_THRESHOLD = 0.90  # 达到阈值静默消解，其余进入规格确认


def _to_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _row_dict(row: LexiconTerm) -> dict:
    return {
        "term": row.term,
        "layer": row.layer,
        "canonical": row.canonical,
        "confidence": _to_float(row.confidence),
        "risk_flag": bool(row.risk_flag),
    }


def _select_global():
    return select(LexiconTerm).where(
        LexiconTerm.layer.in_(("L1", "L2")),
        LexiconTerm.governance == "published",
        LexiconTerm.owner_id.is_(None),
    )


async def _seed_from_csv(session) -> None:
    """全局词条为空时回源种子文件，按 term+layer 去重后批量插入。"""
    path = config.ROOT / "data" / "lexicon_seed.csv"
    if not path.exists():
        return
    pairs = set(
        (t, l)
        for t, l in (await session.execute(select(LexiconTerm.term, LexiconTerm.layer))).all()
    )
    rows: list[LexiconTerm] = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for item in csv.DictReader(f):
            term = (item.get("term") or "").strip()
            if not term or term.startswith("#"):  # 跳过注释行
                continue
            layer = (item.get("layer") or "").strip()
            if (term, layer) in pairs:
                continue
            pairs.add((term, layer))
            rows.append(
                LexiconTerm(
                    term=term,
                    layer=layer,
                    canonical=(item.get("canonical") or "").strip(),
                    definition=(item.get("definition") or "").strip() or None,
                    caliber_note=(item.get("caliber_note") or "").strip() or None,
                    risk_flag=(item.get("risk_flag") or "0").strip() in ("1", "true"),
                    confidence=_to_float(item.get("confidence")),
                    source=(item.get("source") or "").strip() or None,
                    reviewer=(item.get("reviewer") or "").strip() or None,
                    owner_id=None,
                    governance="published",
                )
            )
    if rows:
        session.add_all(rows)
        await session.commit()


async def warmup() -> None:
    """启动时加载全局词条；DB 为空则先从种子文件导入。"""
    global _TERMS
    async with SessionLocal() as session:
        rows = (await session.execute(_select_global())).scalars().all()
        if not rows:
            await _seed_from_csv(session)
            rows = (await session.execute(_select_global())).scalars().all()
    _TERMS = [_row_dict(r) for r in rows]


def _display(canonical: str) -> str:
    """“名称（代码）”在替换文本中只保留名称部分。"""
    matched = _CODE_CANONICAL.match(canonical)
    return matched.group("name") if matched else canonical


def _match(text: str, terms: list[dict]) -> list[tuple[int, int, dict]]:
    """最长匹配优先，命中区间互不重叠，同一 term 只消解一次。"""
    lower = text.lower()  # 英文词条不区分大小写
    occupied: list[tuple[int, int]] = []
    seen: set[str] = set()
    hits: list[tuple[int, int, dict]] = []
    for row in sorted(terms, key=lambda r: (-len(r["term"]), r["term"])):
        term = row["term"]
        if not term or term in seen:
            continue
        start = lower.find(term.lower()) if term.isascii() else text.find(term)
        if start < 0:
            continue
        end = start + len(term)
        if any(s < end and start < e for s, e in occupied):
            continue
        seen.add(term)
        occupied.append((start, end))
        hits.append((start, end, row))
    hits.sort(key=lambda h: h[0])
    return hits


async def _load_personal(user_id: int) -> list[dict]:
    async with SessionLocal() as session:
        rows = (
            await session.execute(select(LexiconTerm).where(LexiconTerm.owner_id == user_id))
        ).scalars().all()
    return [_row_dict(r) for r in rows]


async def resolve(text: str, user_id: int | None) -> dict:
    """对文本做 L1/L2 全局与 L3 个人词条消解。"""
    if _TERMS is None:
        await warmup()
    terms = list(_TERMS or [])
    if user_id is not None:
        personal = await _load_personal(user_id)
        personal_terms = {p["term"] for p in personal}
        # 同名时个人词条优先于全局词条
        terms = [t for t in terms if t["term"] not in personal_terms] + personal

    hits = _match(text, terms)
    replaced = text
    for start, end, row in sorted(hits, key=lambda h: -h[0]):  # 从右往左替换避免位移
        replaced = replaced[:start] + _display(row["canonical"]) + replaced[end:]

    notes = []
    mapping: dict[str, str] = {}
    for _, _, row in hits:
        confidence = row["confidence"]
        notes.append(
            {
                "term": row["term"],
                "canonical": row["canonical"],
                "layer": row["layer"],
                "confidence": confidence,
                "risk_flag": row["risk_flag"],
                "silent": confidence >= _SILENT_THRESHOLD,
            }
        )
        mapping[row["term"]] = row["canonical"]
    return {"replaced_text": replaced, "notes": notes, "map": mapping}
