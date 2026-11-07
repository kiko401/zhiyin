-- 知音 Zhiyin 建库建表脚本（共用 MySQL 实例，一次性执行）
-- 用法：mysql -h 127.0.0.1 -P 3307 -u root -p < scripts/init_db.sql
-- 说明：重复执行安全（IF NOT EXISTS）；表清单与 PRD 11.2 逐一对齐，共二十一表

CREATE DATABASE IF NOT EXISTS zhiyin_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS zhiyin_test_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE USER IF NOT EXISTS 'zhiyin'@'%' IDENTIFIED BY 'change_me_in_deploy';
ALTER USER 'zhiyin'@'%' IDENTIFIED BY 'change_me_in_deploy';
GRANT ALL PRIVILEGES ON zhiyin_db.* TO 'zhiyin'@'%';
GRANT ALL PRIVILEGES ON zhiyin_test_db.* TO 'zhiyin'@'%';
FLUSH PRIVILEGES;

USE zhiyin_db;

-- ============ 核心链路（12 表）============

CREATE TABLE IF NOT EXISTS user (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  username VARCHAR(32) NOT NULL UNIQUE,
  password_hash VARCHAR(128) NOT NULL,
  status TINYINT NOT NULL DEFAULT 1 COMMENT '1正常 0禁用',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB COMMENT='账号（委托关系的跨会话载体）';

CREATE TABLE IF NOT EXISTS session (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  session_uid CHAR(36) NOT NULL UNIQUE COMMENT '对外会话ID',
  user_id BIGINT NOT NULL,
  state VARCHAR(16) NOT NULL DEFAULT 'IDLE' COMMENT 'IDLE/DECIDE/BOUNDARY/CLARIFY/MEM_NOTE/SPEC_REVIEW/EXECUTING/ANSWERED/EXPIRED',
  last_active_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_session_user (user_id),
  INDEX idx_session_active (last_active_at)
) ENGINE=InnoDB COMMENT='会话与状态机当前态';

CREATE TABLE IF NOT EXISTS message (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  session_id BIGINT NOT NULL,
  role VARCHAR(8) NOT NULL COMMENT 'user/system',
  card_type VARCHAR(16) NULL COMMENT 'lexicon/clarify/boundary/memory_note/spec/delegate/work/answer/briefing/system_banner',
  content JSON NOT NULL,
  task_uid CHAR(36) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_message_session (session_id, id)
) ENGINE=InnoDB COMMENT='消息流';

CREATE TABLE IF NOT EXISTS clarification (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  session_id BIGINT NOT NULL,
  round_no TINYINT NOT NULL DEFAULT 1 COMMENT '第n/2轮',
  question TEXT NOT NULL,
  options JSON NOT NULL,
  ambiguity_type VARCHAR(2) NULL COMMENT 'A1-A6',
  skippable TINYINT NOT NULL DEFAULT 1,
  status VARCHAR(16) NOT NULL DEFAULT 'open' COMMENT 'open/closed/expired',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_clarify_session (session_id)
) ENGINE=InnoDB COMMENT='澄清卡实例';

CREATE TABLE IF NOT EXISTS clarification_choice (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  clarification_id BIGINT NOT NULL,
  choice VARCHAR(255) NOT NULL,
  is_skip TINYINT NOT NULL DEFAULT 0,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_choice_clarify (clarification_id)
) ENGINE=InnoDB COMMENT='澄清选择（数据飞轮）';

CREATE TABLE IF NOT EXISTS research_spec (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  spec_uid CHAR(36) NOT NULL UNIQUE,
  user_id BIGINT NOT NULL,
  session_id BIGINT NULL,
  version INT NOT NULL DEFAULT 1,
  task_type VARCHAR(24) NOT NULL,
  spec JSON NOT NULL,
  status VARCHAR(16) NOT NULL DEFAULT 'draft' COMMENT 'draft/confirmed/cancelled',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_spec_user (user_id),
  INDEX idx_spec_session (session_id)
) ENGINE=InnoDB COMMENT='研究规格（版本化可审计，含委托trigger）';

CREATE TABLE IF NOT EXISTS research_task (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  task_uid CHAR(36) NOT NULL UNIQUE,
  user_id BIGINT NOT NULL,
  session_id BIGINT NULL,
  standing_task_id BIGINT NULL COMMENT '持续任务触发的检查实例回链',
  spec_id BIGINT NOT NULL,
  spec_version INT NOT NULL,
  task_type VARCHAR(24) NOT NULL,
  state VARCHAR(16) NOT NULL DEFAULT 'QUEUED' COMMENT 'QUEUED/PLANNING/FETCHING/VERIFYING/ASSEMBLING/DELIVERED/FAILED/DEGRADED',
  blueprint VARCHAR(128) NULL,
  idempotency_key VARCHAR(128) NULL,
  queued_position TINYINT NULL,
  error_note VARCHAR(255) NULL,
  started_at DATETIME NULL,
  finished_at DATETIME NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_task_idem (idempotency_key),
  INDEX idx_task_user (user_id),
  INDEX idx_task_state (state),
  INDEX idx_task_standing (standing_task_id)
) ENGINE=InnoDB COMMENT='研究任务实例（状态机/蓝图选择/幂等键）';

CREATE TABLE IF NOT EXISTS task_event (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  task_id BIGINT NOT NULL,
  event_type VARCHAR(24) NOT NULL COMMENT 'plan_complete/stage_start/stage_end/tool_call_begin/tool_call_end/evidence_appended/llm_call/verify_pass/verify_fail/deliver',
  stage VARCHAR(16) NULL,
  payload JSON NULL,
  elapsed_ms INT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_event_task (task_id, id)
) ENGINE=InnoDB COMMENT='任务阶段事件（事件溯源，工作卡/任务中心/日志的渲染源）';

CREATE TABLE IF NOT EXISTS tool_call (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  task_id BIGINT NOT NULL,
  tool_name VARCHAR(32) NOT NULL,
  source VARCHAR(8) NOT NULL COMMENT 'fuyao/ifind/dossier',
  input_digest VARCHAR(255) NULL,
  output_count INT NULL,
  status VARCHAR(16) NOT NULL COMMENT 'ok/empty/error',
  latency_ms INT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_toolcall_task (task_id)
) ENGINE=InnoDB COMMENT='工具调用留痕';

CREATE TABLE IF NOT EXISTS evidence_item (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  task_id BIGINT NOT NULL,
  layer VARCHAR(8) NOT NULL COMMENT 'fact/env/cause',
  source VARCHAR(32) NOT NULL,
  as_of VARCHAR(32) NOT NULL,
  unit VARCHAR(32) NULL,
  caliber VARCHAR(128) NULL,
  payload JSON NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_evidence_task (task_id)
) ENGINE=InnoDB COMMENT='证据条目（来源/时点/单位/口径）';

CREATE TABLE IF NOT EXISTS answer (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  task_id BIGINT NOT NULL,
  answer_uid CHAR(36) NOT NULL UNIQUE,
  content JSON NOT NULL COMMENT '四段式或直答的结构化内容，含引用角标',
  confidence VARCHAR(8) NOT NULL COMMENT 'high/mid/low',
  feedback VARCHAR(8) NULL COMMENT 'useful/improve',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_answer_task (task_id)
) ENGINE=InnoDB COMMENT='回答与反馈';

CREATE TABLE IF NOT EXISTS ai_usage_log (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  task_id BIGINT NULL,
  purpose VARCHAR(32) NOT NULL COMMENT 'intent/clarify/answer/briefing/judge',
  model VARCHAR(32) NOT NULL,
  prompt_tokens INT NULL,
  completion_tokens INT NULL,
  latency_ms INT NULL,
  status VARCHAR(16) NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_usage_task (task_id),
  INDEX idx_usage_purpose (purpose)
) ENGINE=InnoDB COMMENT='模型调用记录';

-- ============ 持续任务层（3 表）============

CREATE TABLE IF NOT EXISTS standing_task (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  standing_uid CHAR(36) NOT NULL UNIQUE,
  user_id BIGINT NOT NULL,
  task_type VARCHAR(16) NOT NULL COMMENT 'watch/routine',
  name VARCHAR(64) NOT NULL,
  ticker VARCHAR(16) NULL,
  trigger_config JSON NOT NULL COMMENT '盯什么（范围+词表/阈值）、何时查、什么算动静、怎么通知',
  freq_cap TINYINT NOT NULL DEFAULT 1 COMMENT '每日每标的简报上限（1-3）',
  status VARCHAR(16) NOT NULL DEFAULT 'active' COMMENT 'active/paused/pending_manual/deleted',
  last_check_at DATETIME NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_standing_user (user_id),
  INDEX idx_standing_status (status)
) ENGINE=InnoDB COMMENT='持续任务定义（盯盘/例行）';

CREATE TABLE IF NOT EXISTS briefing (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  briefing_uid CHAR(36) NOT NULL UNIQUE,
  standing_task_id BIGINT NOT NULL,
  task_id BIGINT NOT NULL,
  headline VARCHAR(64) NULL,
  fact_text VARCHAR(255) NOT NULL COMMENT '事实段≤120字，数字带角标',
  impact_text VARCHAR(128) NULL COMMENT '中性影响一句话',
  evidence JSON NULL COMMENT '角标回链的引用四要素',
  status VARCHAR(16) NOT NULL DEFAULT 'published' COMMENT 'published/recalled',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_briefing_standing (standing_task_id),
  INDEX idx_briefing_time (created_at)
) ENGINE=InnoDB COMMENT='简报产出（四件套）';

CREATE TABLE IF NOT EXISTS briefing_feedback (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  briefing_id BIGINT NOT NULL,
  user_id BIGINT NOT NULL,
  feedback VARCHAR(12) NOT NULL COMMENT 'useful/not_important',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_feedback_briefing (briefing_id)
) ENGINE=InnoDB COMMENT='简报反馈（降噪闭环入口）';

-- ============ 资产层（4 表）============

CREATE TABLE IF NOT EXISTS lexicon_term (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  term VARCHAR(32) NOT NULL,
  layer VARCHAR(2) NOT NULL COMMENT 'L1/L2/L3',
  canonical VARCHAR(128) NOT NULL,
  definition VARCHAR(255) NULL,
  caliber_note VARCHAR(128) NULL,
  risk_flag TINYINT NOT NULL DEFAULT 0,
  confidence DECIMAL(3,2) NOT NULL,
  source VARCHAR(32) NULL,
  reviewer VARCHAR(16) NULL,
  owner_id BIGINT NULL COMMENT 'L3词条归属用户，全局词条为NULL',
  governance VARCHAR(16) NOT NULL DEFAULT 'published' COMMENT 'candidate/published/deprecated',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_lexicon_term (term, layer, owner_id),
  INDEX idx_lexicon_layer (layer, governance)
) ENGINE=InnoDB COMMENT='词典词条（三层，置信度与治理状态）';

CREATE TABLE IF NOT EXISTS lexicon_hit (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  user_id BIGINT NOT NULL,
  term VARCHAR(32) NOT NULL,
  resolved_to VARCHAR(128) NOT NULL,
  overridden TINYINT NOT NULL DEFAULT 0 COMMENT '用户改回=1，进词条修正池',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_hit_user (user_id)
) ENGINE=InnoDB COMMENT='消解与用户改回留痕';

CREATE TABLE IF NOT EXISTS profile_field (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  user_id BIGINT NOT NULL,
  field_key VARCHAR(24) NOT NULL COMMENT 'time_horizon/risk_context/unit_pref/watch_list/knowledge_level',
  value JSON NULL,
  value_source VARCHAR(16) NULL COMMENT 'clarified/declared/inferred_pending',
  auth_state VARCHAR(12) NOT NULL DEFAULT 'session_only' COMMENT 'granted/session_only/denied',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_profile_field (user_id, field_key)
) ENGINE=InnoDB COMMENT='画像字段与三态授权';

CREATE TABLE IF NOT EXISTS profile_hit (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  user_id BIGINT NOT NULL,
  field_key VARCHAR(24) NOT NULL,
  purpose VARCHAR(16) NOT NULL COMMENT 'free_clarify/personalize/glossary/prefill/briefing_tone',
  accepted TINYINT NULL,
  session_id BIGINT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_profilehit_user (user_id)
) ENGINE=InnoDB COMMENT='画像应用留痕（可回放）';

-- ============ 评测层（2 表）============

CREATE TABLE IF NOT EXISTS eval_batch (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  batch_uid CHAR(36) NOT NULL UNIQUE,
  config JSON NOT NULL COMMENT '双臂配置与消融开关覆盖项',
  status VARCHAR(16) NOT NULL DEFAULT 'running' COMMENT 'running/done/failed',
  result JSON NULL COMMENT '六指标对照、Wilcoxon与敏感性结论',
  started_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  finished_at DATETIME NULL
) ENGINE=InnoDB COMMENT='评测批次';

CREATE TABLE IF NOT EXISTS eval_item (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  batch_id BIGINT NOT NULL,
  gid VARCHAR(8) NOT NULL,
  baseline_answer JSON NULL,
  zhiyin_answer JSON NULL,
  baseline_score JSON NULL,
  zhiyin_score JSON NULL,
  diff_note VARCHAR(255) NULL,
  INDEX idx_evalitem_batch (batch_id, id)
) ENGINE=InnoDB COMMENT='逐题结果（两臂回答与判分明细）';
