"""Pure, dependency-free helpers extracted from app.py.

These functions depend only on the standard library — never on application config or runtime
state — so they live in their own module to keep app.py focused and to make them trivially
importable and testable in isolation.
"""
import hashlib
import re
import time
from datetime import datetime
from pathlib import Path


def guess_content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == '.html':
        return 'text/html; charset=utf-8'
    if suffix == '.js':
        return 'application/javascript; charset=utf-8'
    if suffix == '.css':
        return 'text/css; charset=utf-8'
    if suffix == '.json':
        return 'application/json; charset=utf-8'
    if suffix == '.svg':
        return 'image/svg+xml'
    if suffix == '.png':
        return 'image/png'
    if suffix in ('.jpg', '.jpeg'):
        return 'image/jpeg'
    if suffix == '.ico':
        return 'image/x-icon'
    if suffix == '.woff2':
        return 'font/woff2'
    return 'application/octet-stream'


def now_ts() -> int:
    return int(time.time())


def parse_iso_datetime(value: str, fallback: datetime | None = None) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except Exception:
        return fallback


def is_placeholder_text(value) -> bool:
    txt = str(value or '').strip().casefold()
    return txt in {'', '<не доступно>', '<нет>', '—', 'none', 'null'}


def normalize_module_title(title: str) -> str:
    raw = str(title or '')
    cleaned = raw.replace('* (см. под чек-листом)', '').strip()
    cleaned = re.sub(r'\s{2,}', ' ', cleaned)
    return cleaned or raw.strip() or '<не доступно>'


def module_anchor_id(title: str) -> str:
    normalized = normalize_module_title(title)
    digest = hashlib.md5(normalized.encode('utf-8')).hexdigest()[:12]
    return f"mod-{digest}"
