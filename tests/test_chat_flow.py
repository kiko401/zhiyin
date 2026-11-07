"""主链路冒烟：红线边界 → 澄清 → 规格 → 确认建任务（TEST_PLAN F 主链路抽样，P0）。

真实调用研究模型与扶摇数据源，单步 3-10 秒；执行时整体超时放宽（--timeout=300）。
"""
import uuid

import pytest

pytestmark = [pytest.mark.smoke, pytest.mark.slow]

PASSWORD = "smoke12345"


def _register(client) -> int:
    username = f"smoke_{uuid.uuid4().hex[:10]}"
    resp = client.post("/api/auth/register", json={"username": username, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body.keys()) == {"code", "message", "data"}
    assert body["code"] == 0, body
    return body["data"]["user_id"]


def _chat(client, text: str) -> dict:
    resp = client.post("/api/chat", json={"text": text})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body.keys()) == {"code", "message", "data"}
    assert body["code"] == 0, body
    return body["data"]


def _choose(client, clarify_id: int, choice: str) -> dict:
    resp = client.post(f"/api/clarify/{clarify_id}/choice", json={"choice": choice})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body.keys()) == {"code", "message", "data"}
    assert body["code"] == 0, body
    return body["data"]


def test_chat_boundary_then_clarify_then_spec_confirm(client):
    _register(client)

    # 1) 红线题 → boundary 卡，状态 BOUNDARY（D1 硬红线，不消耗澄清轮次）
    data = _chat(client, "明天哪只股票能涨停")
    cards = data["cards"]
    assert cards and cards[-1]["card_type"] == "boundary", cards
    assert data["state"] == "BOUNDARY"
    assert "无法回答" in cards[-1]["text"]

    # 2) 决策支持题 → clarify 卡，含 options 且 round == 1
    data = _chat(client, "新易盛还能拿吗")
    cards = data["cards"]
    clarify = next(c for c in cards if c["card_type"] == "clarify")
    assert clarify["options"], clarify
    assert clarify["round"] == 1, clarify
    assert data["state"] == "CLARIFY"

    # 3) 选第一项 → 第二轮澄清或规格卡
    data = _choose(client, clarify["clarify_id"], clarify["options"][0])
    last = data["cards"][-1]

    # 4) 若仍为澄清卡（第二轮），继续选第一项直至规格卡（澄清轮次上限 2）
    hop = 0
    while last["card_type"] == "clarify" and hop < 2:
        assert last["round"] == 2 + hop, last
        data = _choose(client, last["clarify_id"], last["options"][0])
        last = data["cards"][-1]
        hop += 1

    assert last["card_type"] == "spec", last
    spec_uid = last["spec_uid"]
    assert spec_uid

    # 5) 规格确认 → 202，data.task_uid 存在
    resp = client.post(f"/api/spec/{spec_uid}/confirm", json={})
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert set(body.keys()) == {"code", "message", "data"}, body
    assert body["code"] == 0, body
    assert body["data"]["task_uid"], body
