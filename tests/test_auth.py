"""鉴权接口冒烟：注册 / 登录 / 登出全流程与错误码（TEST_PLAN API 契约组，P0）。

统一校验响应包络 {code, message, data}；业务错误码 40001。
"""
import uuid

import pytest

pytestmark = pytest.mark.smoke

PASSWORD = "smoke12345"


def _unique_username() -> str:
    return f"smoke_{uuid.uuid4().hex[:10]}"


def _assert_envelope(body: dict) -> None:
    assert set(body.keys()) == {"code", "message", "data"}, body


def test_register_login_logout_flow(client):
    """注册 → 登录 → 登出全流程，登出后会话失效。"""
    username = _unique_username()

    resp = client.post("/api/auth/register", json={"username": username, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    _assert_envelope(body)
    assert body["code"] == 0, body
    assert body["data"]["username"] == username
    assert isinstance(body["data"]["user_id"], int)

    resp = client.post("/api/auth/login", json={"username": username, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    _assert_envelope(body)
    assert body["code"] == 0, body
    assert body["data"]["username"] == username

    resp = client.post("/api/auth/logout")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    _assert_envelope(body)
    assert body["code"] == 0, body

    resp = client.get("/api/sessions")
    assert resp.status_code == 401, resp.text
    body = resp.json()
    _assert_envelope(body)
    assert body["code"] == 40402, body


def test_register_invalid_username(client):
    """用户名非法（少于 3 位 / 含非法字符 / 超长）→ 40001。"""
    for username in ("ab", "bad name!", "a" * 21):
        resp = client.post("/api/auth/register", json={"username": username, "password": PASSWORD})
        assert resp.status_code == 400, resp.text
        body = resp.json()
        _assert_envelope(body)
        assert body["code"] == 40001, body
        assert body["data"] is None


def test_register_short_password(client):
    """密码不足 8 位 → 40001。"""
    resp = client.post("/api/auth/register", json={"username": _unique_username(), "password": "1234567"})
    assert resp.status_code == 400, resp.text
    body = resp.json()
    _assert_envelope(body)
    assert body["code"] == 40001, body
    assert body["data"] is None


def test_login_wrong_password(client):
    """错误密码登录 → 40001。"""
    username = _unique_username()
    resp = client.post("/api/auth/register", json={"username": username, "password": PASSWORD})
    assert resp.status_code == 200, resp.text

    resp = client.post("/api/auth/login", json={"username": username, "password": "wrong_password"})
    assert resp.status_code == 400, resp.text
    body = resp.json()
    _assert_envelope(body)
    assert body["code"] == 40001, body
    assert body["data"] is None
