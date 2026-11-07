import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_env_file() -> None:
    """本地开发从 .env 读取（服务器部署由 docker --env-file 注入）。"""
    for name in (".env", ".env.dev"):
        path = ROOT / name
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    os.environ.setdefault(key.strip(), value.strip())
            break


_load_env_file()


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


def _flag(key: str, default: str = "true") -> bool:
    return _env(key, default).lower() == "true"


# 数据与缓存
DATABASE_URL = _env("DATABASE_URL", "mysql+aiomysql://zhiyin:password@127.0.0.1:3307/zhiyin_test_db")
REDIS_URL = _env("REDIS_URL", "redis://127.0.0.1:6379/3")

# 扶摇金融数据 API（个股与标的事实面）
FUYAO_API_KEY = _env("FUYAO_API_KEY")
FUYAO_BASE_URL = _env("FUYAO_BASE_URL", "https://fuyao.aicubes.cn")

# 研究模型与判分模型（OpenAI 兼容接入，模型可替换）
LLM_API_KEY = _env("LLM_API_KEY")
LLM_BASE_URL = _env("LLM_BASE_URL", "https://api.deepseek.com")
LLM_MODEL = _env("LLM_MODEL", "deepseek-flash")
JUDGE_MODEL = _env("JUDGE_MODEL", "deepseek-v4-pro")

# iFinD MCP（市场环境与归因面，可选）
IFIND_MCP_URL = _env("IFIND_MCP_URL")
IFIND_API_KEY = _env("IFIND_API_KEY")

# 机制开关：线上降级与评测消融共用
LEXICON_ENABLED = _flag("LEXICON_ENABLED")
PROFILE_ENABLED = _flag("PROFILE_ENABLED")
LLM_ENABLED = _flag("LLM_ENABLED")
SCHEDULER_ENABLED = _flag("SCHEDULER_ENABLED")

# 交互与执行约束（与 PRD 1.8/2.12 一致）
SESSION_TTL_DAYS = 7
CLARIFY_MAX_ROUNDS = 2
MAX_INPUT_CHARS = 1000
MAX_CONCURRENT_TASKS = 8
DAILY_RESEARCH_QUOTA = 30
DAILY_CHECK_QUOTA = 50
FUYAO_CACHE_TTL = 60  # 秒，同标的行情快照短缓存
