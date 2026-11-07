#!/usr/bin/env python3
"""种子导入：词典 400 词条落库 + 金标 60 题装载校验 + 底稿校验。幂等，可重复执行。

用法：docker exec zhiyin-fastapi python scripts/seed.py
金标集为文件直读（data/golden_60.csv），此处做结构与数量校验；底稿校验四要素齐全。
"""
import asyncio
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from app.core.db import SessionLocal  # noqa: E402
from app.models import LexiconTerm  # noqa: E402


async def seed_lexicon() -> dict:
    path = ROOT / "data" / "lexicon_seed.csv"
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("term,"):
                continue
            parts = line.split(",")
            parts += [""] * (9 - len(parts))
            term, layer, canonical, definition, caliber_note, risk_flag, confidence, source, reviewer = parts[:9]
            rows.append({
                "term": term.strip(), "layer": layer.strip(), "canonical": canonical.strip(),
                "definition": definition.strip() or None,
                "caliber_note": caliber_note.strip() or None,
                "risk_flag": int(risk_flag or 0),
                "confidence": float(confidence or 0.9),
                "source": source.strip() or None, "reviewer": reviewer.strip() or None,
            })

    async with SessionLocal() as db:
        existing = await db.execute(select(LexiconTerm.term, LexiconTerm.layer))
        have = {(t, l) for t, l in existing.all()}
        added = 0
        for r in rows:
            if (r["term"], r["layer"]) in have:
                continue
            db.add(LexiconTerm(**r, owner_id=None, governance="published"))
            added += 1
        await db.commit()
        total = await db.execute(
            select(LexiconTerm).where(LexiconTerm.owner_id.is_(None),
                                      LexiconTerm.governance == "published")
        )
        count = len(total.scalars().all())
    return {"csv_rows": len(rows), "added": added, "db_total": count}


def check_golden() -> dict:
    path = ROOT / "data" / "golden_60.csv"
    with path.open(encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r.get("gid")]
    groups = {}
    for r in rows:
        groups[r["group"]] = groups.get(r["group"], 0) + 1
    ok = len(rows) == 60 and groups == {"ambiguity": 30, "clear": 15, "compliance": 5, "lexicon": 10}
    return {"rows": len(rows), "groups": groups, "ok": ok}


def check_dossier() -> dict:
    d = ROOT / "data" / "dossier"
    files = sorted(d.glob("*.json"))
    result = []
    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        sec = data.get("sections", {})
        snap = sec.get("snapshot", {})
        four = all(k in snap for k in ("as_of", "unit", "caliber")) and bool(data.get("frozen_at"))
        result.append({"file": f.name, "four_elements": four, "kline_bars": len(sec.get("kline", {}).get("bars", []))})
    return {"files": result, "ok": len(files) == 5 and all(r["four_elements"] for r in result)}


async def main():
    lex = await seed_lexicon()
    golden = check_golden()
    dossier = check_dossier()
    ok = golden["ok"] and dossier["ok"]
    print(json.dumps({"lexicon": lex, "golden": golden, "dossier": dossier, "ok": ok},
                     ensure_ascii=False, indent=1))
    from app.core.db import engine
    await engine.dispose()
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
