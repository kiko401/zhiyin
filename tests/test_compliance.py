"""合规模块纯函数冒烟：R1 红线扫描与 R2 软风险识别（TEST_PLAN C 合规组抽样，P0）。

样本与 PRD 2.8 固定话术对应：红线样本零漏放，正常样本零误拦。
"""
import pytest

from app.services.compliance import scan_redline, scan_soft_risk

pytestmark = pytest.mark.smoke

# R1 红线样本：涨跌预测 / 买卖指令 / 收益承诺，必须全部拦截
REDLINE_SAMPLES = [
    "明天哪只股票能涨停",
    "帮我决定明天买什么",
    "新易盛下个月能翻倍吗",
    "给我一只稳赚的股票",
    "茅台年底能到3000块吗",
]

# 正常咨询样本：持有咨询、事实查询、行情复盘、板块咨询，不得误拦
NORMAL_SAMPLES = [
    "新易盛还能拿吗",
    "茅台营收多少",
    "宁王这波断板了还能拿吗",
    "中际旭创昨天天地板今天怎么看",
    "光模块这个板块怎么样",
]


@pytest.mark.parametrize("text", REDLINE_SAMPLES)
def test_redline_samples_hit(text):
    assert scan_redline(text) is True, f"红线样本未被拦截：{text}"


@pytest.mark.parametrize("text", NORMAL_SAMPLES)
def test_normal_samples_pass(text):
    assert scan_redline(text) is False, f"正常样本被误拦：{text}"


def test_soft_risk_sample_hit():
    """R2 软风险：情绪化决策语境命中。"""
    assert scan_soft_risk("恒瑞割肉还是死扛") is True


def test_soft_risk_normal_sample_pass():
    """正常持有咨询不触发软风险。"""
    assert scan_soft_risk("新易盛还能拿吗") is False
