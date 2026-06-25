CREATE TABLE IF NOT EXISTS calls (
  id BIGSERIAL PRIMARY KEY,
  bitrix_activity_id BIGINT NOT NULL UNIQUE,
  bitrix_file_id BIGINT,
  owner_type_id INTEGER,
  owner_id BIGINT,
  deal_id BIGINT,
  contact_id BIGINT,
  responsible_id BIGINT,
  phone TEXT,
  direction TEXT,
  started_at TIMESTAMPTZ,
  ended_at TIMESTAMPTZ,
  duration_seconds INTEGER,
  audio_url TEXT,
  source_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS transcriptions (
  id BIGSERIAL PRIMARY KEY,
  call_id BIGINT NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
  provider TEXT NOT NULL,
  provider_job_id TEXT,
  status TEXT NOT NULL,
  language TEXT,
  transcript_text TEXT,
  confidence NUMERIC(5,4),
  segments_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  request_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  response_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  error_text TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  completed_at TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_transcriptions_provider_job
  ON transcriptions(provider, provider_job_id)
  WHERE provider_job_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS sync_log (
  id BIGSERIAL PRIMARY KEY,
  source TEXT NOT NULL,
  event_type TEXT NOT NULL,
  reference_id TEXT,
  payload JSONB NOT NULL,
  status TEXT NOT NULL,
  error_text TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_calls_bitrix_activity_id ON calls(bitrix_activity_id);
CREATE INDEX IF NOT EXISTS ix_transcriptions_call_id ON transcriptions(call_id);
CREATE INDEX IF NOT EXISTS ix_transcriptions_status ON transcriptions(status);
CREATE INDEX IF NOT EXISTS ix_sync_log_source_created_at ON sync_log(source, created_at DESC);

CREATE TABLE IF NOT EXISTS analysis_exports (
  id BIGSERIAL PRIMARY KEY,
  deal_id BIGINT,
  client_name TEXT,
  client_contact_id BIGINT,
  client_company_id BIGINT,
  responsible_id BIGINT,
  responsible_name TEXT,
  executor_position TEXT,
  source TEXT NOT NULL DEFAULT 'web',
  status TEXT NOT NULL DEFAULT 'received',
  error_summary TEXT,
  export_text TEXT,
  source_snapshot_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  selection_options_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_analysis_exports_deal_id ON analysis_exports(deal_id);
CREATE INDEX IF NOT EXISTS ix_analysis_exports_status ON analysis_exports(status);
ALTER TABLE analysis_exports ADD COLUMN IF NOT EXISTS executor_position TEXT;
ALTER TABLE analysis_exports ADD COLUMN IF NOT EXISTS status_message_id BIGINT;
ALTER TABLE analysis_exports ADD COLUMN IF NOT EXISTS processing_stage TEXT;
ALTER TABLE analysis_exports ADD COLUMN IF NOT EXISTS selected_operator_id BIGINT;
ALTER TABLE analysis_exports ADD COLUMN IF NOT EXISTS selected_operator_name TEXT;
ALTER TABLE analysis_exports ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'web';
ALTER TABLE analysis_exports ADD COLUMN IF NOT EXISTS selection_options_json JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE analysis_exports ADD COLUMN IF NOT EXISTS error_kind TEXT;
ALTER TABLE analysis_exports ADD COLUMN IF NOT EXISTS retry_after TIMESTAMPTZ;
ALTER TABLE analysis_exports ADD COLUMN IF NOT EXISTS retry_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE analysis_exports ADD COLUMN IF NOT EXISTS entity_type TEXT NOT NULL DEFAULT 'deal';
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'analysis_exports_entity_type_check') THEN
    ALTER TABLE analysis_exports ADD CONSTRAINT analysis_exports_entity_type_check CHECK (entity_type IN ('deal','lead'));
  END IF;
END $$;
CREATE INDEX IF NOT EXISTS ix_analysis_exports_retry ON analysis_exports(retry_after) WHERE retry_after IS NOT NULL;

-- Внутренний реестр сотрудников. Bitrix-id не identity, а просто внешняя ссылка.
-- Ключ дедупликации — (bitrix_account, bitrix_user_id, normalized_name): если админ
-- переименовал аккаунт в Bitrix (Фариза → Сара), нормализованное имя меняется и мы
-- создаём нового сотрудника, не сливая историю двух разных людей.
CREATE TABLE IF NOT EXISTS employees (
  id BIGSERIAL PRIMARY KEY,
  bitrix_account_id BIGINT REFERENCES user_bitrix_connections(id) ON DELETE SET NULL,
  bitrix_user_id BIGINT,
  name TEXT NOT NULL,
  normalized_name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  merged_into_id BIGINT REFERENCES employees(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_employees_resolver_key
  ON employees(bitrix_account_id, bitrix_user_id, normalized_name);
CREATE INDEX IF NOT EXISTS ix_employees_account_status
  ON employees(bitrix_account_id, status);
CREATE INDEX IF NOT EXISTS ix_employees_normalized_name
  ON employees(normalized_name);

ALTER TABLE analysis_exports ADD COLUMN IF NOT EXISTS employee_id BIGINT REFERENCES employees(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS ix_analysis_exports_employee_id ON analysis_exports(employee_id);

CREATE TABLE IF NOT EXISTS analysis_batches (
  id BIGSERIAL PRIMARY KEY,
  source_text TEXT,
  total_deals INTEGER NOT NULL DEFAULT 0,
  source TEXT NOT NULL DEFAULT 'web',
  status TEXT NOT NULL DEFAULT 'queued',
  auto_qa BOOLEAN NOT NULL DEFAULT TRUE,
  final_message_sent_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_analysis_batches_status ON analysis_batches(status);
ALTER TABLE analysis_batches ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'web';
ALTER TABLE analysis_exports
ADD COLUMN IF NOT EXISTS batch_id BIGINT REFERENCES analysis_batches(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS ix_analysis_exports_batch_id ON analysis_exports(batch_id);

CREATE TABLE IF NOT EXISTS deal_events (
  id BIGSERIAL PRIMARY KEY,
  deal_id BIGINT NOT NULL,
  event_at TIMESTAMPTZ,
  event_type TEXT NOT NULL,
  channel TEXT NOT NULL,
  actor_role TEXT,
  actor_name TEXT,
  actor_id BIGINT,
  text_content TEXT,
  source_type TEXT NOT NULL,
  source_id BIGINT,
  raw_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (deal_id, source_type, source_id)
);

CREATE INDEX IF NOT EXISTS ix_deal_events_deal_id_event_at ON deal_events(deal_id, event_at);
CREATE INDEX IF NOT EXISTS ix_deal_events_channel ON deal_events(channel);
ALTER TABLE deal_events ADD COLUMN IF NOT EXISTS entity_type TEXT NOT NULL DEFAULT 'deal';
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'deal_events_entity_type_check') THEN
    ALTER TABLE deal_events ADD CONSTRAINT deal_events_entity_type_check CHECK (entity_type IN ('deal','lead'));
  END IF;
END $$;
ALTER TABLE deal_events DROP CONSTRAINT IF EXISTS deal_events_deal_id_source_type_source_id_key;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'deal_events_entity_uniq') THEN
    ALTER TABLE deal_events ADD CONSTRAINT deal_events_entity_uniq UNIQUE (entity_type, deal_id, source_type, source_id);
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS event_media (
  id BIGSERIAL PRIMARY KEY,
  deal_event_id BIGINT NOT NULL REFERENCES deal_events(id) ON DELETE CASCADE,
  media_type TEXT NOT NULL,
  source_url TEXT,
  mime_type TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  error_text TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (deal_event_id, source_url)
);

CREATE INDEX IF NOT EXISTS ix_event_media_event_id ON event_media(deal_event_id);
CREATE INDEX IF NOT EXISTS ix_event_media_status ON event_media(status);

CREATE TABLE IF NOT EXISTS media_transcriptions (
  id BIGSERIAL PRIMARY KEY,
  event_media_id BIGINT NOT NULL REFERENCES event_media(id) ON DELETE CASCADE,
  provider TEXT NOT NULL,
  provider_job_id TEXT,
  status TEXT NOT NULL,
  transcript_text TEXT,
  request_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  response_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  error_text TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  completed_at TIMESTAMPTZ,
  UNIQUE (event_media_id, provider),
  UNIQUE (provider, provider_job_id)
);

CREATE INDEX IF NOT EXISTS ix_media_transcriptions_media_id ON media_transcriptions(event_media_id);
CREATE INDEX IF NOT EXISTS ix_media_transcriptions_status ON media_transcriptions(status);

CREATE TABLE IF NOT EXISTS qa_standard_versions (
  id BIGSERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  source_type TEXT NOT NULL DEFAULT 'csv',
  source_file_name TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  archived_at TIMESTAMPTZ
);
ALTER TABLE qa_standard_versions ADD COLUMN IF NOT EXISTS card_fields_json JSONB NOT NULL DEFAULT '[]'::jsonb;

CREATE TABLE IF NOT EXISTS qa_standard_blocks (
  id BIGSERIAL PRIMARY KEY,
  standard_version_id BIGINT NOT NULL REFERENCES qa_standard_versions(id) ON DELETE CASCADE,
  block_name TEXT NOT NULL,
  block_weight_percent NUMERIC(6,2) NOT NULL CHECK (block_weight_percent >= 0 AND block_weight_percent <= 100),
  sort_order INTEGER NOT NULL,
  UNIQUE (standard_version_id, block_name)
);

CREATE INDEX IF NOT EXISTS ix_qa_standard_blocks_version
ON qa_standard_blocks(standard_version_id);

CREATE TABLE IF NOT EXISTS qa_standard_modules (
  id BIGSERIAL PRIMARY KEY,
  standard_version_id BIGINT NOT NULL REFERENCES qa_standard_versions(id) ON DELETE CASCADE,
  block_id BIGINT NOT NULL REFERENCES qa_standard_blocks(id) ON DELETE CASCADE,
  module_name TEXT NOT NULL,
  module_details TEXT,
  module_weight_percent NUMERIC(6,2) NOT NULL CHECK (module_weight_percent >= 0 AND module_weight_percent <= 100),
  scoring_rules TEXT,
  is_scored BOOLEAN NOT NULL DEFAULT TRUE,
  sort_order INTEGER NOT NULL,
  UNIQUE (standard_version_id, block_id, sort_order)
);

CREATE INDEX IF NOT EXISTS ix_qa_standard_modules_version
ON qa_standard_modules(standard_version_id);

CREATE TABLE IF NOT EXISTS qa_analysis_runs (
  id BIGSERIAL PRIMARY KEY,
  export_id BIGINT NOT NULL REFERENCES analysis_exports(id) ON DELETE CASCADE,
  standard_version_id BIGINT NOT NULL REFERENCES qa_standard_versions(id),
  run_version INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued',
  claude_model TEXT NOT NULL DEFAULT 'sonnet',
  schema_version TEXT NOT NULL DEFAULT 'qa_call_analysis_v1',
  request_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  response_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  error_text TEXT,
  started_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (export_id, run_version)
);

CREATE INDEX IF NOT EXISTS ix_qa_analysis_runs_export_status
ON qa_analysis_runs(export_id, status);

CREATE TABLE IF NOT EXISTS qa_analysis_module_scores (
  id BIGSERIAL PRIMARY KEY,
  run_id BIGINT NOT NULL REFERENCES qa_analysis_runs(id) ON DELETE CASCADE,
  standard_module_id BIGINT NOT NULL REFERENCES qa_standard_modules(id),
  block_name TEXT NOT NULL,
  module_name TEXT NOT NULL,
  module_weight_percent NUMERIC(6,2) NOT NULL,
  raw_coef NUMERIC(3,2) NOT NULL CHECK (raw_coef IN (0, 0.5, 1)),
  weighted_points NUMERIC(6,2) NOT NULL CHECK (weighted_points >= 0 AND weighted_points <= 100),
  comment TEXT,
  evidence_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (run_id, standard_module_id)
);

CREATE INDEX IF NOT EXISTS ix_qa_analysis_module_scores_run
ON qa_analysis_module_scores(run_id);

CREATE TABLE IF NOT EXISTS qa_analysis_summary (
  run_id BIGINT PRIMARY KEY REFERENCES qa_analysis_runs(id) ON DELETE CASCADE,
  overall_score_0_100 NUMERIC(6,2) NOT NULL CHECK (overall_score_0_100 >= 0 AND overall_score_0_100 <= 100),
  final_summary TEXT NOT NULL,
  final_summary_kk TEXT,
  sum_weighted_points NUMERIC(6,2) NOT NULL,
  rounded_overall_score_0_100 NUMERIC(6,2) NOT NULL,
  formula TEXT NOT NULL DEFAULT 'overall_score_0_100 = round(sum(weighted_points), 2)',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS qa_analysis_touches (
  run_id BIGINT PRIMARY KEY REFERENCES qa_analysis_runs(id) ON DELETE CASCADE,
  touches_count INTEGER NOT NULL DEFAULT 0 CHECK (touches_count >= 0),
  items_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS qa_analysis_recommendations (
  id BIGSERIAL PRIMARY KEY,
  run_id BIGINT NOT NULL REFERENCES qa_analysis_runs(id) ON DELETE CASCADE,
  sort_order INTEGER NOT NULL,
  recommendation_text TEXT NOT NULL,
  recommendation_text_kk TEXT,
  UNIQUE (run_id, sort_order)
);

CREATE INDEX IF NOT EXISTS ix_qa_analysis_recommendations_run
ON qa_analysis_recommendations(run_id);

CREATE TABLE IF NOT EXISTS qa_report_links (
  id BIGSERIAL PRIMARY KEY,
  run_id BIGINT NOT NULL UNIQUE REFERENCES qa_analysis_runs(id) ON DELETE CASCADE,
  export_id BIGINT NOT NULL REFERENCES analysis_exports(id) ON DELETE CASCADE,
  public_id TEXT NOT NULL UNIQUE,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_qa_report_links_export
ON qa_report_links(export_id);

CREATE TABLE IF NOT EXISTS qa_call_texts (
  id BIGSERIAL PRIMARY KEY,
  export_id BIGINT NOT NULL UNIQUE REFERENCES analysis_exports(id) ON DELETE CASCADE,
  deal_id BIGINT,
  title TEXT NOT NULL,
  text_content TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'analysis_export',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_qa_call_texts_deal_id
ON qa_call_texts(deal_id);

-- ============================================================
-- User-oriented access tables
-- ============================================================
-- Основной вход: passwordless через email code.
-- Поля/таблицы password_hash и password_reset_tokens оставлены как совместимый технический хвост,
-- но не являются основным продуктовым сценарием.

CREATE TABLE IF NOT EXISTS users (
  id BIGSERIAL PRIMARY KEY,
  login TEXT,
  email TEXT,
  password_hash TEXT,
  first_name TEXT,
  last_name TEXT,
  username TEXT,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE users ADD COLUMN IF NOT EXISTS login TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS email TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS default_standard_id BIGINT
  REFERENCES qa_standard_versions(id) ON DELETE SET NULL;

CREATE TABLE IF NOT EXISTS user_bitrix_connections (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  member_id TEXT UNIQUE,
  bitrix_domain TEXT,
  title TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  is_primary BOOLEAN NOT NULL DEFAULT TRUE,
  bitrix_access_token TEXT,
  bitrix_refresh_token TEXT,
  bitrix_expires_at TIMESTAMPTZ,
  bitrix_scope TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_user_bitrix_connections_primary
ON user_bitrix_connections(user_id)
WHERE is_primary = TRUE;

CREATE INDEX IF NOT EXISTS ix_user_bitrix_connections_user ON user_bitrix_connections(user_id);

CREATE TABLE IF NOT EXISTS bitrix_connect_tokens (
  id BIGSERIAL PRIMARY KEY,
  token TEXT NOT NULL UNIQUE DEFAULT gen_random_uuid()::text,
  user_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
  expires_at TIMESTAMPTZ NOT NULL,
  used_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS bitrix_install_events (
  id BIGSERIAL PRIMARY KEY,
  token TEXT NOT NULL UNIQUE DEFAULT gen_random_uuid()::text,
  member_id TEXT,
  domain TEXT,
  access_token TEXT NOT NULL,
  refresh_token TEXT,
  expires_at TIMESTAMPTZ,
  scope TEXT,
  used_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sessions (
  id BIGSERIAL PRIMARY KEY,
  session_token TEXT NOT NULL UNIQUE,
  user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  expires_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS password_reset_tokens (
  id BIGSERIAL PRIMARY KEY,
  token TEXT NOT NULL UNIQUE,
  user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  expires_at TIMESTAMPTZ NOT NULL,
  used_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS auth_email_codes (
  id BIGSERIAL PRIMARY KEY,
  token TEXT NOT NULL UNIQUE,
  user_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
  email TEXT NOT NULL,
  first_name TEXT,
  purpose TEXT NOT NULL,
  code_hash TEXT NOT NULL,
  install_token TEXT,
  next_path TEXT,
  expires_at TIMESTAMPTZ NOT NULL,
  used_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_users_login ON users(login) WHERE login IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_users_email ON users(email) WHERE email IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_bitrix_connect_tokens_token ON bitrix_connect_tokens(token);
CREATE INDEX IF NOT EXISTS ix_bitrix_install_events_token ON bitrix_install_events(token);
CREATE INDEX IF NOT EXISTS ix_sessions_token ON sessions(session_token);
CREATE INDEX IF NOT EXISTS ix_sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS ix_password_reset_tokens_token ON password_reset_tokens(token);
CREATE INDEX IF NOT EXISTS ix_password_reset_tokens_user ON password_reset_tokens(user_id);
CREATE INDEX IF NOT EXISTS ix_auth_email_codes_token ON auth_email_codes(token);
CREATE INDEX IF NOT EXISTS ix_auth_email_codes_email ON auth_email_codes(email);

ALTER TABLE analysis_exports ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE analysis_exports ADD COLUMN IF NOT EXISTS bitrix_connection_id BIGINT REFERENCES user_bitrix_connections(id) ON DELETE SET NULL;
ALTER TABLE analysis_batches ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE analysis_batches ADD COLUMN IF NOT EXISTS bitrix_connection_id BIGINT REFERENCES user_bitrix_connections(id) ON DELETE SET NULL;

-- ============================================================
-- Operator development plans
-- ============================================================

CREATE TABLE IF NOT EXISTS employee_development_plans (
  id BIGSERIAL PRIMARY KEY,
  employee_id BIGINT REFERENCES employees(id) ON DELETE SET NULL,
  user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
  bitrix_connection_id BIGINT REFERENCES user_bitrix_connections(id) ON DELETE SET NULL,
  run_ids_json JSONB NOT NULL DEFAULT '[]',
  problem_modules_json JSONB NOT NULL DEFAULT '[]',
  tasks_json JSONB NOT NULL DEFAULT '[]',
  claude_request_json JSONB NOT NULL DEFAULT '{}',
  claude_response_json JSONB NOT NULL DEFAULT '{}',
  bitrix_task_ids_json JSONB NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'draft',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_employee_dev_plans_employee ON employee_development_plans(employee_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_employee_dev_plans_user ON employee_development_plans(user_id);

-- ============================================================
-- Employee plan cycles (auto-triggered analysis cycles)
-- ============================================================

CREATE TABLE IF NOT EXISTS employee_plan_cycles (
  id BIGSERIAL PRIMARY KEY,
  employee_id BIGINT REFERENCES employees(id) ON DELETE SET NULL,
  user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
  status TEXT NOT NULL DEFAULT 'plan_generating',
  base_run_ids_json JSONB NOT NULL DEFAULT '[]',
  check_run_ids_json JSONB NOT NULL DEFAULT '[]',
  plan_id BIGINT REFERENCES employee_development_plans(id) ON DELETE SET NULL,
  report_json JSONB,
  error_text TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_employee_plan_cycles_employee ON employee_plan_cycles(employee_id, user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_employee_plan_cycles_status ON employee_plan_cycles(status);

-- ============================================================
-- User notifications
-- ============================================================

CREATE TABLE IF NOT EXISTS user_notifications (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  type TEXT NOT NULL,
  payload_json JSONB NOT NULL DEFAULT '{}',
  read_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_user_notifications_user ON user_notifications(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_user_notifications_unread ON user_notifications(user_id) WHERE read_at IS NULL;
