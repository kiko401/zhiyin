"""冒烟测试夹具与全局配置。

环境变量须在导入应用前固定：app.core.config 于模块导入时读取环境变量
（.env.dev 经 setdefault 载入，不会覆盖此处已设置的取值）。
"""
import os

os.environ["REGISTER_DAILY_LIMIT"] = "200"

import pytest
from fastapi.testclient import TestClient

from app.main import app


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: 慢速用例（真实调用研究模型，单步 3-10 秒）")


@pytest.fixture(scope="session")
def client():
    """应用级测试客户端；上下文管理器触发 lifespan（词典 warmup）。"""
    with TestClient(app) as c:
        yield c
