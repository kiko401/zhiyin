# 知音 Zhiyin 测试报告

| 项 | 内容 |
| --- | --- |
| 文档编号 | ZY-TEST-002 |
| 测试对象 | 知音 Zhiyin Web 原型（app.main:app，commit 4cc2bf4） |
| 报告日期 | 2026 年 11 月 7 日 |
| 执行人 | 孔宇凡 |
| 关联文档 | docs/TEST_PLAN.md（ZY-TEST-001）、PRD 第 8 章 |

## 1 概述

本轮执行 TEST_PLAN 中的冒烟集（smoke），覆盖三条线：鉴权接口契约（注册/登录/登出与 40001 错误码）、合规词表纯函数（R1 红线、R2 软风险）、主链路端到端（红线边界卡 → 两轮澄清 → 规格卡 → 确认建任务）。执行方式为 pytest 自动化，主链路用例真实调用研究模型与扶摇数据源。结果：17 例全部通过，未发现应用缺陷。

## 2 测试环境

| 项 | 值 |
| --- | --- |
| 被测版本 | commit 4cc2bf4 之上的当前工作区构建（含未提交改动；本轮未改动 app/ 代码） |
| 运行方式 | fastapi.testclient.TestClient 进程内调用，lifespan 触发词典 warmup |
| Python / 测试框架 | Python 3.11.9；pytest 8.3.4、pytest-timeout 2.4.0（本轮装入 venv） |
| 数据库 | MySQL 8，SSH 隧道 127.0.0.1:3307 / zhiyin_test_db |
| 缓存 | Redis，127.0.0.1:6379/3 |
| 外部依赖 | 扶摇 API、DeepSeek 研究模型（真实调用） |
| 测试环境变量 | REGISTER_DAILY_LIMIT 由 50 提升至 200（tests/conftest.py 于导入应用前设置，避免冒烟注册触发限流） |
| 测试账号 | 每次运行以 uuid 后缀注册新账号；历史账号 smoke_m2 / smoke_m3 未复用 |

## 3 测试范围

**包含**（对应 TEST_PLAN 第 2/5 章）：

- API 契约冒烟（P0 抽样）：注册/登录/登出正向流程、统一包络 `{code, message, data}`、错误码 40001（用户名非法、密码过短、错误密码）、未登录 401/40402。
- 合规（P0 抽样）：R1 红线样本 5 条零漏放、正常样本 5 条零误拦、R2 软风险命中与不命中（app/services/compliance.py 纯函数直测）。
- 主链路（P0 抽样）：红线题 → boundary 卡（BOUNDARY）；决策支持题 → clarify 卡（round==1，含 options）→ 选第一项 → 第二轮澄清 → 规格卡 → POST /api/spec/{uid}/confirm 返回 202 且 data.task_uid 存在。

**不包含**（归入 full 集或后续轮次）：

- 33 接口契约的其余接口（任务查询/事件/重试、规格查询、画像授权、历史会话等）。
- 故障注入（E 组）、委托任务全链路（T 组）、词典与画像（LX/PF 组）、边界值（截断/排队/过期）。
- 性能压测、多浏览器兼容、移动端（TEST_PLAN 第 2 章既定不含）。
- 注册限流（42901）与登录失败锁定（42901）：冒烟环境已放宽限流，逻辑未验证。

## 4 用例统计

| 文件 | 用例数 | 通过 | 失败 | 跳过 |
| --- | --- | --- | --- | --- |
| tests/test_auth.py | 4 | 4 | 0 | 0 |
| tests/test_compliance.py（含参数化 10 例） | 12 | 12 | 0 | 0 |
| tests/test_chat_flow.py（slow，真实模型调用） | 1 | 1 | 0 | 0 |
| 合计 | 17 | 17 | 0 | 0 |

执行命令：`python -m pytest tests/ -m smoke -v --timeout=300`；耗时 25.93 秒（其中主链路用例含 3 次真实模型调用，单步 3–10 秒）。

## 5 结果摘录

冒烟集判定：

```
======================= 17 passed, 1 warning in 25.93s ========================
```

主链路关键断言输出（每步为实测包络 data 摘录）：

```
boundary : state=BOUNDARY    card=boundary
clarify-1: state=CLARIFY     ambiguity=A4 round=1 options=['短线（数日）', '波段（数周）', '中长线（数月以上）']
clarify-2: state=CLARIFY     ambiguity=A5 round=2 options=['被套中', '浮盈中', '空仓观察']
spec     : state=SPEC_REVIEW card=spec task_type=decision_support fields=['ticker', 'risk_context', 'time_horizon']
confirm  : http=202 code=0 task_uid=a7249567... state=QUEUED
```

错误码断言摘录：用户名非法 / 密码过短 / 错误密码均返回 HTTP 400 且 `{code: 40001, data: None}`；登出后访问受保护接口返回 HTTP 401 且 `{code: 40402}`。

## 6 缺陷记录

本轮冒烟未发现应用缺陷，无待登记项。

## 7 覆盖分析

接口覆盖（本轮冒烟涉及 7 个接口路径）：

| 接口 | 覆盖情形 |
| --- | --- |
| POST /api/auth/register | 正向；用户名非法 40001；密码过短 40001 |
| POST /api/auth/login | 正向；错误密码 40001 |
| POST /api/auth/logout | 正向；登出后会话失效（GET /api/sessions → 401/40402） |
| POST /api/chat | 红线 boundary（D1，命中词表不消耗澄清轮次）；决策支持 clarify |
| POST /api/clarify/{id}/choice | 第 1→2 轮澄清（A4/A5），第 2 轮后收敛为规格卡 |
| POST /api/spec/{uid}/confirm | 202 受理，data.task_uid 非空，任务初始态 QUEUED |
| GET /api/sessions | 仅覆盖未登录鉴权分支 |

模块覆盖：app/services/compliance.py 的 scan_redline / scan_soft_risk 以固定样本集全量直测。

未覆盖（后续轮次补充）：GET /api/spec/{uid}、GET /api/task/{task_uid}、GET /api/task/{task_uid}/events、POST /api/task/{task_uid}/retry、GET /api/tasks、POST /api/clarify/{id}/memory、GET /api/session/{session_uid}/history；A1 多候选/自由输入澄清分支、fact_query 直答路径（direct → EXECUTING）、委托（delegate）路径；42901 限流与登录锁定；澄清 2 轮上限的负向用例。

## 8 结论

对照 TEST_PLAN 第 6 章准出标准："P0 用例 100% 通过"。本轮冒烟子集（17 例，均属 P0 范围）通过率 100%，无阻塞与严重缺陷，冒烟准入结论为通过。全量 P0（33 接口契约、8 主链路、6 故障注入、5 合规、5 任务链路）须待 full 集执行后方可出具最终准出结论。

## 9 遗留风险

- 主链路用例依赖真实外部服务（研究模型、扶摇 API、SSH 隧道测试库），存在网络波动与限流导致的偶发失败可能；澄清分支走向亦依赖模型分类输出（本轮稳定收敛于 A4→A5→规格卡）。
- 规格确认后的任务为后台异步执行（202 受理即返回），本轮仅断言受理与初始状态，任务执行过程与交付物契约未覆盖。
- 测试环境将 REGISTER_DAILY_LIMIT 提升至 200，注册限流分支（>50 报 42901）未在本轮验证。
- 会话 TTL（7 天）、输入截断（1000 字）、并发排队（Semaphore(8)）等边界值未覆盖。
