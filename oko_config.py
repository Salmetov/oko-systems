"""Environment-derived configuration for OKO.

A single source of truth for runtime settings read from environment variables (with sane
defaults). Pure — depends only on the standard library.
"""
import os
from pathlib import Path


PORT = int(os.getenv('CALLBACK_PORT', '18080'))
HOST = os.getenv('CALLBACK_HOST', '127.0.0.1')
MT_CLIENT_ID = os.getenv('BITRIX_MT_CLIENT_ID') or os.getenv('BITRIX_CLIENT_ID', '')
MT_CLIENT_SECRET = os.getenv('BITRIX_MT_CLIENT_SECRET') or os.getenv('BITRIX_CLIENT_SECRET', '')
MT_REDIRECT_URI = os.getenv('BITRIX_MT_REDIRECT_URI') or os.getenv('BITRIX_REDIRECT_URI', 'https://ai.salmetov.fun/bitrix/oauth/callback')
SCHEMA_PATH = Path(os.getenv('SCHEMA_PATH', '/root/okosystems/schema.sql'))
AUTO_REFRESH_BUFFER_SEC = int(os.getenv('AUTO_REFRESH_BUFFER_SEC', '300'))
ADMIN_TOKEN = os.getenv('OAUTH_ADMIN_TOKEN', '')
UI_SESSION_COOKIE = os.getenv('UI_SESSION_COOKIE', 'rop_session')
UI_SESSION_MAX_AGE_SEC = int(os.getenv('UI_SESSION_MAX_AGE_SEC', '43200'))
UI_PRODUCT_NAME = os.getenv('UI_PRODUCT_NAME', 'Oko Systems')
BITRIX_MARKET_INSTALL_URL = os.getenv('BITRIX_MARKET_INSTALL_URL', 'https://www.bitrix24.kz/register/reg.php?addmodule=oko.app')
BITRIX_APP_CODE = os.getenv('BITRIX_APP_CODE', 'oko.app').strip() or 'oko.app'

DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://localhost:5432/oko')
APP_BASE_URL = os.getenv('APP_BASE_URL', 'https://ai.salmetov.fun')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
DEMO_NOTIFY_CHAT_ID = os.getenv('DEMO_NOTIFY_CHAT_ID', '')
SONIOX_API_KEY = os.getenv('SONIOX_API_KEY', '')
SONIOX_API_BASE = os.getenv('SONIOX_API_BASE', 'https://api.soniox.com/v1')
SONIOX_MODEL = os.getenv('SONIOX_MODEL', 'stt-async-v4')
SONIOX_LANGUAGE_HINTS = [s.strip() for s in os.getenv('SONIOX_LANGUAGE_HINTS', 'ru,kk').split(',') if s.strip()]
SONIOX_POLL_INTERVAL_SEC = float(os.getenv('SONIOX_POLL_INTERVAL_SEC', '3'))
SONIOX_TIMEOUT_SEC = int(os.getenv('SONIOX_TIMEOUT_SEC', '600'))
# Active provider used when WRITING new transcriptions. Reads are provider-agnostic so historical
# transcriptions from previous providers (e.g. ElevenLabs) remain visible after switching.
ACTIVE_TRANSCRIBE_PROVIDER = (os.getenv('TRANSCRIBE_PROVIDER') or 'soniox').strip().lower()
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY', '')
ANTHROPIC_MODEL = os.getenv('ANTHROPIC_MODEL', 'claude-sonnet-4-6')
# Per-task models. QA scoring is fast & structured → Haiku is plenty. Development plans need
# longer-form reasoning, so Sonnet stays as the default there.
ANTHROPIC_MODEL_QA = os.getenv('ANTHROPIC_MODEL_QA', 'claude-haiku-4-5')
ANTHROPIC_MODEL_PLAN = os.getenv('ANTHROPIC_MODEL_PLAN', 'claude-sonnet-4-6')
ANTHROPIC_ENDPOINT = os.getenv('ANTHROPIC_ENDPOINT', 'https://api.anthropic.com/v1/messages')
ANTHROPIC_MAX_TOKENS = int(os.getenv('ANTHROPIC_MAX_TOKENS', '16000'))
ANTHROPIC_TIMEOUT_SEC = int(os.getenv('ANTHROPIC_TIMEOUT_SEC', '120'))
ANTHROPIC_CONNECT_TIMEOUT_SEC = int(os.getenv('ANTHROPIC_CONNECT_TIMEOUT_SEC', '15'))
OPERATOR_PROGRESS_VALID_FROM_UTC = os.getenv('OPERATOR_PROGRESS_VALID_FROM_UTC', '2026-03-14T00:00:00+00:00')

EXPORT_POLL_INTERVAL_SEC = int(os.getenv('EXPORT_POLL_INTERVAL_SEC', '5'))
EXPORT_AUDIO_WAIT_TIMEOUT_SEC = int(os.getenv('EXPORT_AUDIO_WAIT_TIMEOUT_SEC', '1800'))
EXPORT_WORKER_INTERVAL_SEC = int(os.getenv('EXPORT_WORKER_INTERVAL_SEC', '2'))
QA_WORKER_INTERVAL_SEC = int(os.getenv('QA_WORKER_INTERVAL_SEC', '2'))
FIXED_STANDARD_CSV_PATH = Path(os.getenv('FIXED_STANDARD_CSV_PATH', '/root/Стандарты MDS ОП_КЦ для агента - Стандарт касаний по тел.csv'))
REPORT_PUBLIC_BASE_URL = os.getenv('REPORT_PUBLIC_BASE_URL', 'https://ai.salmetov.fun')
QA_SYSTEM_PROMPT_PATH = Path(os.getenv('QA_SYSTEM_PROMPT_PATH', '/root/okosystems/prompts/qa_system_prompt.md'))
QA_USER_PROMPT_PATH = Path(os.getenv('QA_USER_PROMPT_PATH', '/root/okosystems/prompts/qa_user_prompt.md'))
UI_DASH_DIST_PATH = Path(os.getenv('UI_DASH_DIST_PATH', '/root/okosystems/ui-dashboard/dist'))
APP_SESSION_COOKIE = os.getenv('APP_SESSION_COOKIE', os.getenv('TG_SESSION_COOKIE', 'app_session'))
APP_SESSION_MAX_AGE_SEC = int(os.getenv('APP_SESSION_MAX_AGE_SEC', os.getenv('TG_SESSION_MAX_AGE_SEC', str(30 * 24 * 3600))))
PASSWORD_RESET_TTL_SEC = int(os.getenv('PASSWORD_RESET_TTL_SEC', '3600'))
AUTH_EMAIL_CODE_TTL_SEC = int(os.getenv('AUTH_EMAIL_CODE_TTL_SEC', '900'))
MAILTRAP_API_TOKEN = os.getenv('MAILTRAP_API_TOKEN', '')
MAILTRAP_API_BASE_URL = os.getenv('MAILTRAP_API_BASE_URL', 'https://send.api.mailtrap.io').rstrip('/')
MAILTRAP_FROM_EMAIL = os.getenv('MAILTRAP_FROM_EMAIL', 'hello@ai.salmetov.fun').strip()
MAILTRAP_FROM_NAME = os.getenv('MAILTRAP_FROM_NAME', UI_PRODUCT_NAME).strip() or UI_PRODUCT_NAME
COOKIE_SECURE_ATTR = '; Secure' if APP_BASE_URL.startswith('https://') else ''
COOKIE_SAMESITE_ATTR = os.getenv('COOKIE_SAMESITE_ATTR', 'None' if COOKIE_SECURE_ATTR else 'Lax').strip() or ('None' if COOKIE_SECURE_ATTR else 'Lax')
COOKIE_SAMESITE_ATTR = COOKIE_SAMESITE_ATTR.title()
COOKIE_SESSION_ATTR = f"; SameSite={COOKIE_SAMESITE_ATTR}{COOKIE_SECURE_ATTR}"

__all__ = [
    'PORT',
    'HOST',
    'MT_CLIENT_ID',
    'MT_CLIENT_SECRET',
    'MT_REDIRECT_URI',
    'SCHEMA_PATH',
    'AUTO_REFRESH_BUFFER_SEC',
    'ADMIN_TOKEN',
    'UI_SESSION_COOKIE',
    'UI_SESSION_MAX_AGE_SEC',
    'UI_PRODUCT_NAME',
    'BITRIX_MARKET_INSTALL_URL',
    'BITRIX_APP_CODE',
    'DATABASE_URL',
    'APP_BASE_URL',
    'TELEGRAM_BOT_TOKEN',
    'DEMO_NOTIFY_CHAT_ID',
    'SONIOX_API_KEY',
    'SONIOX_API_BASE',
    'SONIOX_MODEL',
    'SONIOX_LANGUAGE_HINTS',
    'SONIOX_POLL_INTERVAL_SEC',
    'SONIOX_TIMEOUT_SEC',
    'ACTIVE_TRANSCRIBE_PROVIDER',
    'ANTHROPIC_API_KEY',
    'ANTHROPIC_MODEL',
    'ANTHROPIC_MODEL_QA',
    'ANTHROPIC_MODEL_PLAN',
    'ANTHROPIC_ENDPOINT',
    'ANTHROPIC_MAX_TOKENS',
    'ANTHROPIC_TIMEOUT_SEC',
    'ANTHROPIC_CONNECT_TIMEOUT_SEC',
    'OPERATOR_PROGRESS_VALID_FROM_UTC',
    'EXPORT_POLL_INTERVAL_SEC',
    'EXPORT_AUDIO_WAIT_TIMEOUT_SEC',
    'EXPORT_WORKER_INTERVAL_SEC',
    'QA_WORKER_INTERVAL_SEC',
    'FIXED_STANDARD_CSV_PATH',
    'REPORT_PUBLIC_BASE_URL',
    'QA_SYSTEM_PROMPT_PATH',
    'QA_USER_PROMPT_PATH',
    'UI_DASH_DIST_PATH',
    'APP_SESSION_COOKIE',
    'APP_SESSION_MAX_AGE_SEC',
    'PASSWORD_RESET_TTL_SEC',
    'AUTH_EMAIL_CODE_TTL_SEC',
    'MAILTRAP_API_TOKEN',
    'MAILTRAP_API_BASE_URL',
    'MAILTRAP_FROM_EMAIL',
    'MAILTRAP_FROM_NAME',
    'COOKIE_SECURE_ATTR',
    'COOKIE_SAMESITE_ATTR',
    'COOKIE_SESSION_ATTR',
]
