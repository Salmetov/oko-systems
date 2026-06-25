#!/usr/bin/env python3
import csv
import hmac
import hashlib
import json
import os
import re
import secrets
import signal
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from html import escape as html_escape, unescape
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlencode, urlparse
from urllib.request import Request, urlopen

import psycopg2
import psycopg2.extras
import psycopg2.pool
import requests
import socket
from requests.adapters import HTTPAdapter


# Shared resilient HTTP client (pooled requests.Session + TCP_USER_TIMEOUT) lives in oko_http.py.
from oko_http import HTTP_SESSION

# Configuration (env-derived settings) now lives in oko_config.py.
from oko_config import *  # noqa: F401,F403 -- flat re-export preserves existing references


EXPORT_WORKER_LOCK = threading.Lock()
EXPORT_WORKER_STARTED = False
QA_WORKER_LOCK = threading.Lock()
QA_WORKER_STARTED = False
TOKEN_REFRESH_LOCK = threading.Lock()
TOKEN_REFRESH_STARTED = False
USER_PROFILE_CACHE = {}

DEAL_LINK_RE = re.compile(r'/crm/deal/details/(\d+)', re.IGNORECASE)
LEAD_LINK_RE = re.compile(r'/crm/lead/details/(\d+)', re.IGNORECASE)
BITRIX_OWNER_TYPE_BY_ENTITY = {'deal': 2, 'lead': 1}
BITRIX_GET_METHOD_BY_ENTITY = {'deal': 'crm.deal.get', 'lead': 'crm.lead.get'}
ENTITY_URL_PATH_BY_TYPE = {'deal': 'deal', 'lead': 'lead'}
URL_RE = re.compile(r'https?://[^\s\]"]+', re.IGNORECASE)
BBCODE_URL_RE = re.compile(r'\[url=([^\]]+)\]', re.IGNORECASE)
REPORT_LINK_RE = re.compile(r'^/r/([A-Za-z0-9_-]+)$')
REPORT_TXT_LINK_RE = re.compile(r'^/r/([A-Za-z0-9_-]+)/txt$')
REPORT_PDF_LINK_RE = re.compile(r'^/r/([A-Za-z0-9_-]+)\.pdf$')
REPORT_PRETTY_RE = re.compile(r'^/id/([A-Za-z0-9_-]+)$')
REPORT_PRETTY_TIMELINE_RE = re.compile(r'^/id/([A-Za-z0-9_-]+)/timeline$')
OPERATOR_REPORT_RE = re.compile(r'^/operator/(\d+)/report/([A-Za-z0-9_-]+)$')
OPERATOR_REPORT_TIMELINE_RE = re.compile(r'^/operator/(\d+)/report/([A-Za-z0-9_-]+)/timeline$')
REPORT_API_RE = re.compile(r'^/api/report/([A-Za-z0-9_-]+)$')
CHRONOLOGY_API_RE = re.compile(r'^/api/chronology/([A-Za-z0-9_-]+)$')
OPERATOR_DASH_RE = re.compile(r'^/operator/(\d+)$')
EMPLOYEE_API_RE = re.compile(r'^/api/employee/(\d+)$')
EMPLOYEE_ARCHIVE_API_RE = re.compile(r'^/api/employee/(\d+)/archive$')
EMPLOYEE_UNARCHIVE_API_RE = re.compile(r'^/api/employee/(\d+)/unarchive$')
EMPLOYEE_PLAN_API_RE = re.compile(r'^/api/employee/(\d+)/plan$')
EMPLOYEE_PLAN_GENERATE_RE = re.compile(r'^/api/employee/(\d+)/plan/generate$')
EMPLOYEE_PLAN_SEND_BITRIX_RE = re.compile(r'^/api/employee/(\d+)/plan/(\d+)/send-bitrix$')
NOTIFICATIONS_API_RE = re.compile(r'^/api/notifications$')
NOTIFICATION_READ_RE = re.compile(r'^/api/notifications/(\d+)/read$')
EMPLOYEE_CYCLES_API_RE = re.compile(r'^/api/employee/(\d+)/cycles$')
ME_API_RE = re.compile(r'^/api/me$')
EMPLOYEES_API_RE = re.compile(r'^/api/employees$')
ANALYSES_API_RE = re.compile(r'^/api/analyses$')
STANDARDS_API_RE = re.compile(r'^/api/standards$')
STANDARD_API_RE = re.compile(r'^/api/standards/(\d+)$')
STANDARD_RENAME_API_RE = re.compile(r'^/api/standards/(\d+)/rename$')
STANDARD_SET_DEFAULT_API_RE = re.compile(r'^/api/standards/(\d+)/set-default$')
STANDARD_CARD_FIELDS_API_RE = re.compile(r'^/api/standards/(\d+)/card-fields$')
STANDARD_BITRIX_FIELDS_API_RE = re.compile(r'^/api/standards/(\d+)/bitrix-fields$')
ANALYSES_RETRY_RE = re.compile(r'^/api/analyses/(\d+)/retry$')
EMPLOYEE_DELETE_RE = re.compile(r'^/employees/(\d+)/delete$')
PUBLIC_CONNECT_TOKEN_RE = re.compile(r'^/connect/bitrix/([A-Za-z0-9_-]{16,})$')
SYSTEM_PROMPT_CACHE = None
USER_PROMPT_TEMPLATE_CACHE = None
SPEAKER_DIGIT_RE = re.compile(r'(\d+)')
TG_SESSION_COOKIE = APP_SESSION_COOKIE
TG_SESSION_MAX_AGE_SEC = APP_SESSION_MAX_AGE_SEC


# Pure stdlib-only helpers now live in oko_utils.py (extracted to keep app.py focused).
from oko_utils import (
    guess_content_type,
    now_ts,
    parse_iso_datetime,
    is_placeholder_text,
    normalize_module_title,
    module_anchor_id,
)


# Internationalization (RU/KK): translation tables + helpers now live in oko_i18n.py.
from oko_i18n import (
    SUPPORTED_UI_LANGS,
    UI_TEXT,
    BLOCK_TRANSLATIONS_KK,
    BLOCK_SHORT_NAMES_RU,
    MODULE_SHORT_NAMES_RU,
    MODULE_TRANSLATIONS_KK,
    detect_ui_lang,
    t,
    translate_block_name,
    translate_module_name,
)


def report_path(public_id: str, operator_id: int | None = None) -> str:
    oid = safe_int(operator_id)
    if oid:
        return f"/operator/{oid}/report/{public_id}"
    return f"/id/{public_id}"


def chronology_path(public_id: str, operator_id: int | None = None) -> str:
    oid = safe_int(operator_id)
    if oid:
        return f"/operator/{oid}/report/{public_id}/timeline"
    return f"/id/{public_id}/timeline"
def lang_query_href(path: str, params: dict | None, lang: str) -> str:
    qp = {}
    for key, values in (params or {}).items():
        if key == 'lang':
            continue
        qp[key] = list(values) if isinstance(values, list) else [values]
    qp['lang'] = [lang]
    query = urlencode(qp, doseq=True)
    return f"{path}?{query}" if query else path


def add_lang_to_href(href: str, lang: str) -> str:
    if not href:
        return href
    parsed = urlparse(href)
    params = parse_qs(parsed.query)
    params['lang'] = [lang]
    query = urlencode(params, doseq=True)
    path = parsed.path or ''
    fragment = f"#{parsed.fragment}" if parsed.fragment else ''
    if query:
        return f"{path}?{query}{fragment}"
    return f"{path}{fragment}"


def add_query_to_href(href: str, **extra_params) -> str:
    if not href:
        return href
    parsed = urlparse(href)
    params = parse_qs(parsed.query)
    for key, value in extra_params.items():
        if value is None:
            continue
        params[str(key)] = [str(value)]
    query = urlencode(params, doseq=True)
    path = parsed.path or ''
    fragment = f"#{parsed.fragment}" if parsed.fragment else ''
    if query:
        return f"{path}?{query}{fragment}"
    return f"{path}{fragment}"


def parse_body_form(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get('Content-Length', '0'))
    if length <= 0:
        return {}
    raw = handler.rfile.read(length).decode('utf-8', errors='ignore')
    parsed = parse_qs(raw, keep_blank_values=True)
    out = {}
    for key, values in parsed.items():
        out[str(key)] = values[0] if isinstance(values, list) and values else ''
    return out


def status_label(lang: str, status: str | None) -> str:
    key = f"status_{str(status or '').strip().lower()}"
    return t(lang, key)


def _session_secret() -> str:
    return ADMIN_TOKEN or 'local-dev-secret'
def is_valid_ui_session_value(value: str) -> bool:
    raw = str(value or '').strip()
    if not raw:
        return False
    parts = raw.split('.')
    if len(parts) != 3:
        return False
    issued_at, nonce, signature = parts
    if not issued_at.isdigit() or not nonce or not signature:
        return False
    payload = f"{issued_at}.{nonce}"
    expected = hmac.new(_session_secret().encode('utf-8'), payload.encode('utf-8'), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return False
    age = now_ts() - int(issued_at)
    if age < 0 or age > UI_SESSION_MAX_AGE_SEC:
        return False
    return True


def get_cookie_value(handler: BaseHTTPRequestHandler, name: str) -> str:
    cookie_header = handler.headers.get('Cookie', '')
    if not cookie_header:
        return ''
    jar = SimpleCookie()
    try:
        jar.load(cookie_header)
    except Exception:
        return ''
    morsel = jar.get(name)
    return morsel.value if morsel else ''


def normalize_bitrix_domain(value: str) -> str:
    raw = str(value or '').strip()
    if not raw:
        return ''
    parsed = urlparse(raw if '://' in raw else f'https://{raw}')
    host = str(parsed.netloc or parsed.path or '').strip().casefold()
    host = host.split(':', 1)[0].strip('.')
    if not host or '.' not in host:
        return ''
    return host
def render_lang_switch(path: str, params: dict | None, lang: str) -> str:
    ru_href = lang_query_href(path, params, 'ru')
    kk_href = lang_query_href(path, params, 'kk')
    return (
        "<div class='lang-switch'>"
        f"<a class='lang-btn {'active' if lang == 'ru' else ''}' href='{html_escape(ru_href)}'>{html_escape(t(lang, 'lang_ru'))}</a>"
        f"<a class='lang-btn {'active' if lang == 'kk' else ''}' href='{html_escape(kk_href)}'>{html_escape(t(lang, 'lang_kk'))}</a>"
        "</div>"
    )


def render_dashboard_base_styles() -> str:
    return """
@import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800;900&display=swap');
:root{
  --bg:#F3F4F8;
  --bg-soft:#EAECF2;
  --surface:#FFFFFF;
  --surface-strong:#FFFFFF;
  --surface-muted:#F9FAFB;
  --border:#E5E7EB;
  --border-strong:#D1D5DB;
  --ink:#0C0C14;
  --ink-soft:#6B7280;
  --ink-faint:#9CA3AF;
  --accent:#5B6AF9;
  --accent-soft:#EEF0FE;
  --good:#2f8a57;
  --good-soft:#edf8f1;
  --warn:#9b6a19;
  --warn-soft:#fff7ea;
  --bad:#b3473f;
  --bad-soft:#fff1ef;
  --shadow:0 20px 56px rgba(12,12,20,.07);
  --shadow-soft:0 4px 16px rgba(12,12,20,.05);
  --radius-xl:18px;
  --radius-lg:18px;
  --radius-md:14px;
  --space-1:4px;
  --space-2:8px;
  --space-3:12px;
  --space-4:16px;
  --space-5:20px;
  --space-6:24px;
}
*{box-sizing:border-box}
html{color-scheme:light}
body{
  margin:0;
  min-height:100vh;
  color:var(--ink);
  font-family:"Manrope",ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  background:var(--bg);
}
.wrap{max-width:1240px;margin:0 auto;padding:24px 24px 40px}
.page{display:grid;grid-template-columns:minmax(0,1fr);gap:20px}
.page > *, .page-top > *, .two-col > *, .metrics-grid > *, .insight-grid > *, .stack > *{min-width:0;max-width:100%}
.panel{
  background:var(--surface);
  backdrop-filter:blur(14px);
  border:1px solid rgba(223,217,207,.96);
  border-radius:var(--radius-xl);
  box-shadow:var(--shadow-soft);
  min-width:0;
}
.header-card{padding:22px 22px 20px;box-shadow:var(--shadow)}
.panel-pad{padding:20px}
.page-top{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:16px;align-items:start}
.page-head{min-width:0}
.eyebrow{
  margin:0 0 8px;
  font-size:12px;
  line-height:1.2;
  font-weight:800;
  letter-spacing:.12em;
  text-transform:uppercase;
  color:var(--ink-faint);
}
.page-title{
  margin:0;
  font-size:clamp(32px,4vw,40px);
  line-height:1.02;
  letter-spacing:-.04em;
  color:var(--ink);
}
.page-subtitle{
  margin:10px 0 0;
  max-width:720px;
  color:var(--ink-soft);
  font-size:15px;
  line-height:1.55;
}
.header-meta,.top-actions,.chip-row{display:flex;gap:10px;flex-wrap:wrap}
.header-meta{margin-top:16px}
.top-actions{margin-top:18px}
.chip{
  display:inline-flex;
  align-items:center;
  gap:8px;
  min-height:36px;
  padding:0 12px;
  border-radius:999px;
  border:1px solid var(--border);
  background:rgba(255,255,255,.86);
  font-size:13px;
  font-weight:700;
  color:var(--ink-soft);
  box-shadow:inset 0 1px 0 rgba(255,255,255,.72);
}
.action-link{
  display:inline-flex;
  align-items:center;
  justify-content:center;
  gap:8px;
  min-height:40px;
  padding:0 16px;
  border-radius:11px;
  border:1px solid var(--border);
  background:#fff;
  color:var(--ink);
  text-decoration:none;
  font-size:14px;
  font-weight:700;
  letter-spacing:-.01em;
  appearance:none;
  cursor:pointer;
  transition:transform .15s ease, box-shadow .15s ease, border-color .15s ease, background .15s ease;
}
.action-link:hover{transform:translateY(-1px);box-shadow:var(--shadow-soft);border-color:var(--border-strong)}
.action-link.primary{background:#5B6AF9;border-color:#5B6AF9;color:#fff}
.action-link.primary:hover{background:#7B87FF;border-color:#7B87FF}
.action-link.secondary{background:var(--surface-muted);border-color:var(--border)}
.action-link.danger{background:var(--bad-soft);border-color:#f0d2ce;color:var(--bad)}
.action-inline{display:flex;gap:8px;flex-wrap:wrap}
.back-link{
  display:inline-flex;
  align-items:center;
  gap:8px;
  text-decoration:none;
  color:var(--ink-faint);
  font-size:13px;
  font-weight:700;
}
.back-link:hover{color:var(--ink)}
.lang-switch{
  display:inline-flex;
  align-self:flex-start;
  gap:3px;
  align-items:center;
  flex-wrap:nowrap;
  padding:3px;
  border-radius:10px;
  background:rgba(255,255,255,.06);
  border:1px solid rgba(255,255,255,.09);
  margin-bottom:18px;
}
.lang-btn{
  display:inline-flex;
  align-items:center;
  justify-content:center;
  min-width:44px;
  min-height:28px;
  padding:0 10px;
  border-radius:7px;
  text-decoration:none;
  font-size:11px;
  font-weight:800;
  letter-spacing:.04em;
  color:rgba(255,255,255,.4);
  transition:background .15s,color .15s;
}
.lang-btn.active{background:#5B6AF9;color:#fff}
.kpi-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px}
.kpi{
  position:relative;
  overflow:hidden;
  padding:18px 18px 16px;
}
.kpi::after{
  content:'';
  position:absolute;
  inset:auto 0 0 0;
  height:3px;
  background:linear-gradient(90deg, rgba(79,90,104,.44), rgba(79,90,104,0));
  opacity:.22;
}
.kpi.good::after{background:linear-gradient(90deg, rgba(47,138,87,.90), rgba(47,138,87,0));opacity:.28}
.kpi.mid::after,.kpi.warn::after{background:linear-gradient(90deg, rgba(155,106,25,.90), rgba(155,106,25,0));opacity:.28}
.kpi.bad::after{background:linear-gradient(90deg, rgba(179,71,63,.90), rgba(179,71,63,0));opacity:.28}
.kpi-label{
  margin:0 0 10px;
  font-size:12px;
  font-weight:800;
  line-height:1.35;
  letter-spacing:.08em;
  color:var(--ink-faint);
  text-transform:uppercase;
}
.kpi-value{
  margin:0;
  font-size:clamp(34px,3vw,40px);
  line-height:.95;
  font-weight:900;
  letter-spacing:-.05em;
  color:var(--ink);
}
.kpi-note{margin:10px 0 0;color:var(--ink-soft);font-size:13px;line-height:1.45}
.kpi-subvalue{margin-top:8px;font-size:14px;font-weight:700;color:var(--ink-soft)}
.panel-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;margin-bottom:16px}
.panel-title{margin:0;font-size:24px;line-height:1.1;letter-spacing:-.03em;color:var(--ink)}
.panel-subtitle{margin:6px 0 0;color:var(--ink-soft);font-size:14px;line-height:1.5}
.two-col{display:grid;grid-template-columns:minmax(0,1.55fr) minmax(320px,1fr);gap:18px;align-items:start}
.stack{display:grid;gap:18px}
.table-wrap,.hscroll{overflow:auto}
table{width:100%;border-collapse:separate;border-spacing:0}
th,td{padding:14px 12px;border-bottom:1px solid #ebe6de;text-align:left;vertical-align:top}
th{
  font-size:12px;
  font-weight:800;
  letter-spacing:.10em;
  text-transform:uppercase;
  color:var(--ink-faint);
  background:rgba(247,244,239,.92);
}
td{font-size:14px;line-height:1.5;color:var(--ink-soft)}
tbody tr:hover td{background:rgba(247,244,239,.82)}
.sub{font-size:12px;color:var(--ink-faint);margin-top:4px;line-height:1.35}
.score-pill{
  display:inline-flex;
  align-items:center;
  justify-content:center;
  min-width:76px;
  min-height:32px;
  padding:0 10px;
  border-radius:999px;
  border:1px solid var(--border);
  background:#fff;
  color:var(--ink-soft);
  font-size:12px;
  font-weight:900;
}
.score-pill.good{background:var(--good-soft);border-color:#cde7d7;color:var(--good)}
.score-pill.mid{background:var(--warn-soft);border-color:#f1dfbb;color:var(--warn)}
.score-pill.bad{background:var(--bad-soft);border-color:#f0d2ce;color:var(--bad)}
.badge{
  display:inline-flex;
  align-items:center;
  gap:6px;
  min-height:30px;
  padding:0 10px;
  border-radius:999px;
  border:1px solid var(--border);
  background:#fff;
  font-size:12px;
  font-weight:800;
  color:var(--ink-soft);
}
.badge.good{background:var(--good-soft);border-color:#cde7d7;color:var(--good)}
.badge.warn{background:var(--warn-soft);border-color:#f1dfbb;color:var(--warn)}
.badge.bad{background:var(--bad-soft);border-color:#f0d2ce;color:var(--bad)}
.clickable{
  cursor:pointer;
  transition:transform .18s ease, box-shadow .18s ease, border-color .18s ease;
}
.clickable:hover{transform:translateY(-2px);box-shadow:var(--shadow);border-color:var(--border-strong)}
.clickable:focus-visible{outline:2px solid rgba(79,90,104,.24);outline-offset:2px}
[data-reveal]{
  opacity:0;
  transform:translateY(14px);
  animation:pageReveal .55s cubic-bezier(.2,.7,.2,1) forwards;
  animation-delay:calc(var(--reveal, 0) * 70ms);
}
ul{margin:0;padding-left:18px}
li{margin:6px 0}
@keyframes pageReveal{to{opacity:1;transform:translateY(0)}}
@media (prefers-reduced-motion: reduce){
  [data-reveal]{opacity:1;transform:none;animation:none}
  .action-link,.clickable{transition:none}
}
@media (max-width: 1040px){
  .kpi-grid{grid-template-columns:repeat(2,minmax(0,1fr))}
  .two-col{grid-template-columns:1fr}
}
@media (max-width: 720px){
  .wrap{padding:16px 16px 28px}
  .header-card,.panel-pad,.kpi{padding:16px}
  .page-top{grid-template-columns:1fr;gap:12px}
  .page-title{font-size:32px}
  .page-subtitle{font-size:14px}
  .page-title,.page-subtitle,.panel-title{overflow-wrap:anywhere;word-break:break-word}
  .header-meta,.top-actions{gap:8px}
  .chip{width:100%;justify-content:flex-start;padding:8px 12px;min-height:40px;overflow-wrap:anywhere;word-break:break-word}
  .top-actions{display:grid;grid-template-columns:1fr;gap:8px}
  .action-link{width:100%}
  .lang-switch{justify-self:start}
  .kpi-grid{grid-template-columns:1fr}
  .panel-head{display:grid;grid-template-columns:1fr;gap:8px}
  .panel-title{font-size:21px}
  th,td{padding:10px;font-size:13px}
}
.shell{display:flex;min-height:100vh}
.shell-grid{display:flex;width:100%;align-items:stretch}
.sidebar{
  width:248px;
  flex-shrink:0;
  min-height:100vh;
  position:sticky;
  top:0;
  height:100vh;
  overflow-y:auto;
  padding:20px 16px 24px;
  background:#0C0C14;
  border-right:1px solid rgba(255,255,255,.07);
  display:flex;
  flex-direction:column;
}
.sidebar-brand{display:flex;align-items:center;gap:10px;padding:0 4px;margin-bottom:24px}
.sidebar-logo-icon{width:30px;height:30px;background:#5B6AF9;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:900;color:#fff;flex-shrink:0}
.sidebar-title{margin:0;font-size:15px;font-weight:800;line-height:1.1;letter-spacing:-.01em;color:#fff}
.sidebar-subtitle{margin:3px 0 0;font-size:11px;color:rgba(255,255,255,.35);line-height:1.3}
.sidebar-group{margin-top:22px}
.sidebar-group:first-of-type{margin-top:0}
.sidebar-label{margin:0 0 6px;padding:0 8px;font-size:10px;font-weight:900;letter-spacing:.14em;text-transform:uppercase;color:rgba(255,255,255,.28)}
.sidebar-nav{display:grid;gap:2px}
.sidebar-link{
  display:flex;align-items:center;justify-content:space-between;gap:10px;
  min-height:38px;padding:0 10px;border-radius:10px;
  color:rgba(255,255,255,.55);text-decoration:none;font-size:13px;font-weight:700;
  border:1px solid transparent;transition:background .15s,color .15s,border-color .15s;
}
.sidebar-link:hover{background:rgba(255,255,255,.07);color:rgba(255,255,255,.85)}
.sidebar-link.active{background:#5B6AF9;color:#fff;border-color:transparent}
.sidebar-link.minor{font-weight:600;font-size:12px;min-height:34px}
.sidebar-link.disabled{opacity:.28;cursor:default;pointer-events:none}
.sidebar-item-row{display:flex;align-items:center;gap:4px}
.sidebar-item-row .sidebar-link{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sidebar-delete-form{flex-shrink:0;margin:0}
.sidebar-delete-btn{display:flex;align-items:center;justify-content:center;width:26px;height:26px;border-radius:7px;border:1px solid transparent;background:transparent;color:rgba(255,255,255,.3);font-size:15px;line-height:1;cursor:pointer;transition:background .12s,color .12s,border-color .12s;padding:0}
.sidebar-delete-btn:hover{background:rgba(239,68,68,.15);border-color:rgba(239,68,68,.3);color:#f87171}
.sidebar-meta{margin-top:auto;padding-top:16px;border-top:1px solid rgba(255,255,255,.07)}
.sidebar-logout{
  display:inline-flex;align-items:center;justify-content:center;min-height:34px;padding:0 14px;
  border-radius:9px;border:1px solid rgba(255,255,255,.1);background:transparent;color:rgba(255,255,255,.45);
  font-family:inherit;font-size:12px;font-weight:700;cursor:pointer;transition:background .15s,color .15s,border-color .15s;
}
.sidebar-logout:hover{background:rgba(255,255,255,.08);color:rgba(255,255,255,.8);border-color:rgba(255,255,255,.2)}
.content-wrap{flex:1;min-width:0;overflow:auto}
.content-inner{padding:28px 28px 48px}
.auth-page{max-width:420px;margin:80px auto 0}
.auth-card{padding:24px}
.auth-form{display:grid;gap:12px;margin-top:18px}
.field-label{font-size:12px;font-weight:900;letter-spacing:.08em;text-transform:uppercase;color:var(--ink-faint)}
.field-input,.field-textarea,.field-select{
  width:100%;min-height:44px;padding:12px 14px;border-radius:14px;
  border:1px solid var(--border);background:#fff;color:var(--ink);font:inherit;
}
.field-textarea{min-height:120px;resize:vertical}
.form-error{padding:12px 14px;border-radius:14px;background:var(--bad-soft);border:1px solid #f0d2ce;color:var(--bad);font-size:14px;line-height:1.45}
.form-success{padding:12px 14px;border-radius:14px;background:var(--good-soft);border:1px solid #cde7d7;color:var(--good);font-size:14px;line-height:1.45}
.submit-btn{
  display:inline-flex;align-items:center;justify-content:center;min-height:44px;padding:0 16px;
  border:0;border-radius:12px;background:var(--ink);color:#fff;font:inherit;font-weight:800;cursor:pointer;
}
.submit-btn:hover{background:#2a313b}
.muted{color:var(--ink-soft)}
.dashboard-grid{display:grid;gap:18px}
.employee-table td strong{color:var(--ink)}
.employee-link{color:var(--ink);text-decoration:none}
.employee-link:hover{color:var(--ink);text-decoration:underline}
.split-two{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}
.status-list{display:grid;gap:10px}
.status-row{display:grid;grid-template-columns:minmax(0,1.1fr) minmax(0,.9fr) auto;gap:12px;align-items:start;padding:14px;border:1px solid var(--border);border-radius:16px;background:#fff}
.status-row.compact{grid-template-columns:minmax(0,1fr)}
.status-name{font-size:14px;font-weight:800;color:var(--ink);line-height:1.4}
.status-copy{font-size:13px;color:var(--ink-soft);line-height:1.5}
.pill{display:inline-flex;align-items:center;justify-content:center;min-height:30px;padding:0 10px;border-radius:999px;border:1px solid var(--border);background:#fff;color:var(--ink-soft);font-size:12px;font-weight:800}
.pill.good{background:var(--good-soft);border-color:#cde7d7;color:var(--good)}
.pill.warn{background:var(--warn-soft);border-color:#f1dfbb;color:var(--warn)}
.pill.bad{background:var(--bad-soft);border-color:#f0d2ce;color:var(--bad)}
.quick-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px}
.empty-note{padding:14px;border:1px dashed var(--border-strong);border-radius:16px;color:var(--ink-soft);background:rgba(255,255,255,.65)}
.modal-backdrop{
  position:fixed;
  inset:0;
  display:flex;
  align-items:center;
  justify-content:center;
  padding:16px;
  background:rgba(20,25,34,.34);
  backdrop-filter:blur(10px);
  opacity:0;
  pointer-events:none;
  transition:opacity .18s ease;
  z-index:60;
}
.modal-backdrop.open{opacity:1;pointer-events:auto}
.modal-card{
  width:min(100%, 460px);
  padding:22px;
  border-radius:18px;
  background:rgba(255,255,255,.96);
  border:1px solid rgba(223,217,207,.96);
  box-shadow:var(--shadow);
}
.modal-title{margin:0;font-size:24px;line-height:1.1;letter-spacing:-.03em;color:var(--ink)}
.modal-copy{margin:10px 0 0;color:var(--ink-soft);font-size:15px;line-height:1.55}
.modal-actions{display:flex;justify-content:flex-end;gap:10px;flex-wrap:wrap;margin-top:18px}
.modal-actions .action-link{min-width:120px}
body.modal-open{overflow:hidden}
@media (max-width: 1040px){
  .sidebar{display:none}
  .split-two,.quick-grid{grid-template-columns:1fr}
}
@media (max-width: 720px){
  .content-inner{padding:16px 16px 32px}
  .modal-actions{display:grid;grid-template-columns:1fr}
}
"""


def render_sidebar_html(lang: str, shell: dict | None) -> str:
    shell = shell or {}
    groups = shell.get('groups') if isinstance(shell.get('groups'), list) else []
    lang_switch = shell.get('lang_switch') or ''
    logout_html = shell.get('logout_html') or ''
    sections = []
    for group in groups:
        label = str(group.get('label') or '').strip()
        items = group.get('items') if isinstance(group.get('items'), list) else []
        item_html = []
        for item in items:
            if not isinstance(item, dict) or not str(item.get('label') or '').strip():
                continue
            label_text = html_escape(str(item.get('label') or ''))
            if item.get('disabled'):
                item_html.append(f"<span class='sidebar-link minor disabled'>{label_text}</span>")
                continue
            href = str(item.get('href') or '').strip() or '#'
            cls = ['sidebar-link']
            if item.get('active'):
                cls.append('active')
            if item.get('minor'):
                cls.append('minor')
            delete_href = str(item.get('delete_href') or '').strip()
            delete_id = item.get('delete_id')
            if delete_href and delete_id:
                confirm_msg = html_escape(t(lang, 'crm_disconnect_confirm'))
                item_html.append(
                    f"<div class='sidebar-item-row'>"
                    f"<a class='{' '.join(cls)}' href='{html_escape(href)}'>{label_text}</a>"
                    f"<form method='post' action='{html_escape(delete_href)}' class='sidebar-delete-form'"
                    f" data-confirm-message='{confirm_msg}'>"
                    f"<input type='hidden' name='connection_id' value='{int(delete_id)}'/>"
                    f"<button type='submit' class='sidebar-delete-btn' title='Удалить'>×</button>"
                    f"</form>"
                    f"</div>"
                )
            else:
                item_html.append(f"<a class='{' '.join(cls)}' href='{html_escape(href)}'>{label_text}</a>")
        if not item_html:
            continue
        sections.append(
            "<section class='sidebar-group'>"
            f"<p class='sidebar-label'>{html_escape(label)}</p>"
            f"<nav class='sidebar-nav'>{''.join(item_html)}</nav>"
            "</section>"
        )
    return (
        "<aside class='sidebar'>"
        "<div class='sidebar-brand'>"
        "<div class='sidebar-logo-icon'>О</div>"
        "<div>"
        f"<h2 class='sidebar-title'>{html_escape(t(lang, 'product_title'))}</h2>"
        f"<p class='sidebar-subtitle'>{html_escape(t(lang, 'rop_dashboard_subtitle'))}</p>"
        "</div>"
        "</div>"
        f"{lang_switch}"
        f"{''.join(sections)}"
        f"<div class='sidebar-meta'>{logout_html}</div>"
        "</aside>"
    )


def render_confirm_modal(lang: str) -> str:
    return (
        "<div class='modal-backdrop' id='confirm-modal' hidden>"
        "<div class='modal-card panel' role='dialog' aria-modal='true' aria-labelledby='confirm-modal-title'>"
        f"<h2 class='modal-title' id='confirm-modal-title'>{html_escape(t(lang, 'delete_employee'))}</h2>"
        "<p class='modal-copy' id='confirm-modal-copy'></p>"
        "<div class='modal-actions'>"
        f"<button type='button' class='action-link secondary' id='confirm-modal-cancel'>{html_escape(t(lang, 'cancel_action'))}</button>"
        f"<button type='button' class='action-link danger' id='confirm-modal-submit'>{html_escape(t(lang, 'confirm_action'))}</button>"
        "</div>"
        "</div>"
        "</div>"
    )


def render_frame_script() -> str:
    return """<script>
(function(){
  const modal = document.getElementById('confirm-modal');
  if (!modal) return;
  const copy = document.getElementById('confirm-modal-copy');
  const cancelBtn = document.getElementById('confirm-modal-cancel');
  const submitBtn = document.getElementById('confirm-modal-submit');
  let pendingForm = null;

  function closeModal() {
    modal.classList.remove('open');
    modal.hidden = true;
    document.body.classList.remove('modal-open');
    pendingForm = null;
  }

  function openModal(form) {
    pendingForm = form;
    copy.textContent = form.getAttribute('data-confirm-message') || '';
    modal.hidden = false;
    requestAnimationFrame(function(){ modal.classList.add('open'); });
    document.body.classList.add('modal-open');
  }

  document.addEventListener('submit', function(event){
    const form = event.target;
    if (!(form instanceof HTMLFormElement)) return;
    if (!form.hasAttribute('data-confirm-message')) return;
    if (form.dataset.confirmed === '1') {
      delete form.dataset.confirmed;
      return;
    }
    event.preventDefault();
    openModal(form);
  }, true);

  cancelBtn.addEventListener('click', closeModal);
  submitBtn.addEventListener('click', function(){
    if (!pendingForm) return;
    pendingForm.dataset.confirmed = '1';
    pendingForm.submit();
    closeModal();
  });

  modal.addEventListener('click', function(event){
    if (event.target === modal) closeModal();
  });

  document.addEventListener('keydown', function(event){
    if (event.key === 'Escape' && !modal.hidden) closeModal();
  });
})();
</script>"""


def render_page_frame(lang: str, title: str, body_html: str, extra_style: str = '', script: str = '', shell: dict | None = None) -> str:
    shell_html = ''
    if shell and shell.get('authenticated'):
        sidebar_html = render_sidebar_html(lang, shell)
        shell_html = f"<div class='shell'><div class='shell-grid'>{sidebar_html}<main class='content-wrap'><div class='content-inner'><div class='page'>{body_html}</div></div></main></div></div>"
    else:
        shell_html = f"<div class='wrap'><div class='page'>{body_html}</div></div>"
    return f"""<!doctype html>
<html lang="{html_escape(lang)}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html_escape(title)}</title>
<style>{render_dashboard_base_styles()}{extra_style}</style></head><body>
{shell_html}
{render_confirm_modal(lang)}
{render_frame_script()}
{script}
</body></html>"""


def render_logout_button(lang: str, current_path: str) -> str:
    return (
        "<form method='post' action='/logout' style='margin:0'>"
        f"<input type='hidden' name='next' value='{html_escape(current_path or '/')}'/>"
        f"<button type='submit' class='sidebar-logout'>{html_escape(t(lang, 'logout'))}</button>"
        "</form>"
    )


def format_sidebar_bitrix_label(lang: str, connection: dict, index: int) -> str:
    domain = str(connection.get('bitrix_domain') or '').strip()
    title = str(connection.get('title') or '').strip()
    if domain:
        return domain
    if title and title.casefold() != 'bitrix24':
        return title
    return t(lang, 'sidebar_bitrix_account_fallback').format(index=index)


def build_bitrix_accounts_group(lang: str, current_path: str, user_id: int | None) -> dict | None:
    uid = safe_int(user_id)
    if not uid:
        return None
    connections = get_user_bitrix_connections(uid)
    items = []
    for index, connection in enumerate(connections, start=1):
        label = format_sidebar_bitrix_label(lang, connection, index)
        connection_id = safe_int(connection.get('id'))
        if not connection_id:
            continue
        href = add_query_to_href(add_lang_to_href(f"/bitrix/switch/{connection_id}", lang), next=current_path or '/')
        items.append({
            'label': label,
            'href': href,
            'active': bool(connection.get('is_primary')),
            'minor': not bool(connection.get('is_primary')),
            'delete_href': f"/bitrix/disconnect",
            'delete_id': connection_id,
        })
    if not items:
        return None
    return {'label': t(lang, 'sidebar_bitrix_accounts'), 'items': items}


def build_sidebar_shell(lang: str, current_path: str, query_params: dict | None, groups: list[dict], user_id: int | None = None) -> dict:
    shell_groups = list(groups or [])
    bitrix_group = build_bitrix_accounts_group(lang, current_path, user_id)
    if bitrix_group:
        shell_groups.append(bitrix_group)
    return {
        'authenticated': True,
        'groups': shell_groups,
        'lang_switch': render_lang_switch(current_path or '/', query_params, lang),
        'logout_html': render_logout_button(lang, current_path or '/'),
    }


def build_detail_shell(lang: str, current_path: str, query_params: dict | None, active_key: str, context_items: list[dict], home_href: str = '/', analysis_href: str = '/', user_id: int | None = None) -> dict:
    home_items = [
        {'label': t(lang, 'nav_home'), 'href': add_lang_to_href(home_href, lang), 'active': active_key == 'home'},
    ]
    return build_sidebar_shell(lang, current_path, query_params, [
        {'label': t(lang, 'nav_home'), 'items': home_items},
    ], user_id=user_id)
def render_marketplace_app_page(lang: str, notice_text: str = '', error_text: str = '', values: dict | None = None) -> str:
    values = values or {}
    name_value = html_escape(str(values.get('name') or '').strip())
    email_value = html_escape(str(values.get('email') or '').strip())
    company_value = html_escape(str(values.get('company') or '').strip())
    message_value = html_escape(str(values.get('message') or '').strip())
    notice_html = f"<div class='form-success market-feedback' style='margin-bottom:16px'>{html_escape(notice_text)}</div>" if notice_text else ''
    error_html = f"<div class='form-error market-feedback' style='margin-bottom:16px'>{html_escape(error_text)}</div>" if error_text else ''
    body_html = """
<section class="panel market-hero" data-reveal style="--reveal:0">
  <p class="eyebrow">Приложение для Bitrix24</p>
  <h1 class="page-title" style="font-size:clamp(28px,4vw,42px);margin-bottom:10px">Oko Systems</h1>
  <p class="page-subtitle market-subtitle">
    AI-приложение для Bitrix24, которое собирает коммуникации по сделке, расшифровывает звонки,
    строит хронологию касаний и формирует отчёт по качеству работы отдела продаж на демо- и рабочих данных портала.
  </p>
  <div class="market-hero-actions">
    <a class="action-link" href="mailto:support@salmetov.fun">Связаться с разработчиком</a>
    <a class="action-link secondary" href="mailto:support@salmetov.fun?subject=Запрос%20демонстрации%20Oko%20Systems">Запросить демонстрацию</a>
  </div>
</section>

<section class="market-grid">
  <article class="panel market-card" data-reveal style="--reveal:1">
    <div class="market-card-head">
      <p class="market-kicker">Что делает приложение</p>
    </div>
    <div class="market-card-body">
      <ul class="market-list">
      <li>Получает данные сделки, контакта, активностей и комментариев таймлайна Bitrix24.</li>
      <li>Находит звонки, загружает аудио и расшифровывает разговоры.</li>
      <li>Определяет сотрудника, который вёл коммуникацию, и собирает полную хронологию взаимодействия.</li>
      <li>Формирует AI-отчёт по скрипту, качеству обработки лида и точкам роста сотрудника.</li>
      </ul>
    </div>
  </article>

  <article class="panel market-card" data-reveal style="--reveal:2">
    <div class="market-card-head">
      <p class="market-kicker">Поддержка и обратная связь</p>
    </div>
    <div class="market-card-body">
      <div class="market-facts">
        <div class="market-fact"><span class="market-fact-label">Канал</span><span class="market-fact-value"><a href="mailto:support@salmetov.fun">support@salmetov.fun</a></span></div>
        <div class="market-fact"><span class="market-fact-label">Сайт</span><span class="market-fact-value"><a href="https://ai.salmetov.fun/app">ai.salmetov.fun/app</a></span></div>
        <div class="market-fact"><span class="market-fact-label">Часы работы</span><span class="market-fact-value">пн-пт, 10:00-19:00</span></div>
        <div class="market-fact"><span class="market-fact-label">Часовой пояс</span><span class="market-fact-value">UTC+5, Asia/Almaty</span></div>
        <div class="market-fact"><span class="market-fact-label">Время реакции</span><span class="market-fact-value">обычно до 4 рабочих часов, в сложных случаях до 1 рабочего дня</span></div>
      </div>
    </div>
  </article>

  <article class="panel market-card" data-reveal style="--reveal:3">
    <div class="market-card-head">
      <p class="market-kicker">Как проходит подключение</p>
    </div>
    <div class="market-card-body">
      <ol class="market-steps">
        <li>Пользователь устанавливает приложение из Маркета Bitrix24.</li>
        <li>После установки открывается экран с инструкцией по подключению портала.</li>
        <li>Администратор подтверждает доступ к Bitrix24 и возвращается в кабинет Oko Systems.</li>
        <li>После авторизации становятся доступны анализ сделок, хронология коммуникаций и AI-отчёты.</li>
      </ol>
    </div>
  </article>
  <article class="panel market-card" data-reveal style="--reveal:4">
    <div class="market-card-head">
      <p class="market-kicker">Контакты</p>
    </div>
    <div class="market-card-body">
      <p class="market-copy">
        Для вопросов по установке, демонстрации и технической поддержке используйте форму связи через email.
        При обращении укажите домен вашего Bitrix24 и кратко опишите задачу.
      </p>
      <div class="market-hero-actions market-hero-actions-compact">
        <a class="action-link" href="mailto:support@salmetov.fun?subject=Поддержка%20Oko%20Systems">Написать в поддержку</a>
      </div>
    </div>
  </article>

  <article class="panel market-card market-form-card" data-reveal style="--reveal:5">
    <div class="market-card-head">
      <p class="market-kicker">Форма связи</p>
    </div>
    <div class="market-card-body">
    """ + notice_html + error_html + f"""
    <form method="post" action="/app/contact" class="market-form">
      <input type="hidden" name="lang" value="{html_escape(lang)}" />
      <label>
        <span class="field-label">Ваше имя</span>
        <input class="field-input" type="text" name="name" maxlength="120" value="{name_value}" required />
      </label>
      <label>
        <span class="field-label">Email</span>
        <input class="field-input" type="email" name="email" maxlength="160" value="{email_value}" required />
      </label>
      <label>
        <span class="field-label">Компания / Bitrix24</span>
        <input class="field-input" type="text" name="company" maxlength="160" value="{company_value}" placeholder="Например: Ferrum / ferrum.bitrix24.kz" />
      </label>
      <label>
        <span class="field-label">Сообщение</span>
        <textarea class="field-textarea" name="message" maxlength="3000" required>{message_value}</textarea>
      </label>
      <button class="submit-btn" type="submit">Отправить запрос</button>
    </form>
    </div>
  </article>
</section>
"""
    extra_style = """
.market-hero{max-width:920px;width:min(920px,100%);margin:24px auto 18px;padding:32px;display:grid;gap:18px;box-sizing:border-box}
.market-subtitle{max-width:none}
.market-hero .page-subtitle{max-width:none}
.market-grid{max-width:920px;margin:0 auto;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}
.market-card{padding:24px;display:grid;grid-template-rows:auto 1fr;gap:16px;min-height:100%}
.market-card-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;padding-bottom:14px;border-bottom:1px solid rgba(33,35,43,.08)}
.market-card-body{display:grid;gap:16px;align-content:start}
.market-form-card{grid-column:1 / -1}
.market-kicker{margin:0;font-size:12px;font-weight:900;letter-spacing:.14em;text-transform:uppercase;color:var(--ink-faint)}
.market-copy{margin:0;color:var(--ink-soft);line-height:1.65}
.market-list,.market-steps{margin:0;padding-left:18px;color:var(--ink-soft);line-height:1.65}
.market-list li+.market-list li,.market-steps li+.market-steps li{margin-top:8px}
.market-facts{display:grid;gap:12px}
.market-fact{display:grid;gap:4px;padding-bottom:12px;border-bottom:1px solid rgba(33,35,43,.06)}
.market-fact:last-child{padding-bottom:0;border-bottom:0}
.market-fact-label{font-size:11px;font-weight:900;letter-spacing:.12em;text-transform:uppercase;color:var(--ink-faint)}
.market-fact-value{color:var(--ink-soft);line-height:1.6}
.market-fact-value a{color:var(--ink-soft)}
.market-hero-actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:4px}
.market-hero-actions-compact{margin-top:2px}
.market-form{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}
.market-form label:last-of-type{grid-column:1 / -1}
.market-form .submit-btn{grid-column:1 / -1;justify-self:start}
.market-feedback{max-width:720px}
@media(max-width:720px){
  .market-hero{margin:16px auto;padding:22px 18px}
  .market-grid{grid-template-columns:1fr;gap:14px}
  .market-card{padding:18px}
  .market-hero-actions{display:grid;grid-template-columns:1fr}
  .market-form{grid-template-columns:1fr}
}
"""
    return render_page_frame(lang, 'Oko Systems для Bitrix24', body_html, extra_style=extra_style)


def render_marketplace_install_page(lang: str, title: str, subtitle: str, status: str = 'info', action_href: str = '/login', action_label: str = 'Открыть кабинет', next_steps: list[str] | None = None) -> str:
    status_cls = 'warn'
    if status == 'success':
        status_cls = 'good'
    elif status == 'error':
        status_cls = 'bad'
    steps = next_steps or []
    steps_html = ''.join(f"<li>{item}</li>" for item in steps)
    note_html = ''
    if steps_html:
        note_html = f"""
  <div class="install-note {status_cls}">
    <strong>Что делать дальше:</strong>
    <ul>
      {steps_html}
    </ul>
  </div>
"""
    body_html = f"""
<section class="panel install-page" data-reveal style="--reveal:0">
  <p class="eyebrow">Установка приложения Bitrix24</p>
  <h1 class="page-title" style="font-size:clamp(26px,3.5vw,38px);margin-bottom:10px">{html_escape(title)}</h1>
  <p class="page-subtitle install-subtitle">{html_escape(subtitle)}</p>

  {note_html}

  <div class="install-actions">
    <a class="action-link" href="{html_escape(action_href)}" target="_blank" rel="noopener noreferrer">{html_escape(action_label)}</a>
    <a class="action-link secondary" href="/app" target="_blank" rel="noopener noreferrer">Инструкция и контакты</a>
  </div>
</section>
"""
    extra_style = """
.install-page{max-width:720px;margin:40px auto;padding:32px}
.install-subtitle{max-width:620px}
.install-note{margin-top:22px;padding:18px 20px;border-radius:18px;border:1px solid var(--border);background:var(--surface-muted);color:var(--ink-soft);line-height:1.65}
.install-note.good{background:var(--good-soft);border-color:#cde7d7;color:var(--good)}
.install-note.warn{background:var(--warn-soft);border-color:#f1dfbb;color:#6f5318}
.install-note.bad{background:var(--bad-soft);border-color:#f0d2ce;color:var(--bad)}
.install-note strong{display:block;margin-bottom:10px;color:var(--ink)}
.install-note ul{margin:0;padding-left:18px}
.install-note a{color:inherit}
.install-actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:22px}
@media(max-width:600px){
  .install-page{margin:16px auto;padding:22px 18px}
  .install-actions{display:grid;grid-template-columns:1fr}
}
    """
    return render_page_frame(lang, 'Установка Oko Systems', body_html, extra_style=extra_style)


def render_bitrix_embedded_page(
    lang: str,
    auth_session: dict | None = None,
    domain: str = '',
    member_id: str = '',
    current_path: str = '/connect/bitrix',
    query_params: dict | None = None,
    install_token: str = '',
    error_text: str = '',
    register_values: dict | None = None,
    login_value: str = '',
) -> str:
    domain_value = str(domain or '').strip()
    member_value = str(member_id or '').strip()
    has_auth = bool(auth_session)
    install_token_value = str(install_token or '').strip()
    register_values = register_values or {}
    quick_name_value = html_escape(str(register_values.get('name') or '').strip())
    quick_email_value = html_escape(str(register_values.get('email') or '').strip())
    login_input_value = html_escape(str(login_value or '').strip())
    error_html = f"<div class='form-error embedded-error'>{html_escape(error_text)}</div>" if error_text else ''

    status_title = 'Oko Systems для Bitrix24'
    status_copy = 'Войдите по коду из письма или создайте аккаунт через email.'
    primary_href = '/login?lang=ru'
    primary_label = 'Войти'
    secondary_href = '/register?lang=ru'
    secondary_label = 'Создать аккаунт'

    if has_auth:
        status_title = 'Bitrix24 готов'
        status_copy = 'Профиль Oko Systems найден. Можно продолжить работу в кабинете.'
        primary_href = "/"
        primary_label = 'Открыть кабинет'
        secondary_href = "/connect/bitrix"
        secondary_label = 'Подключить Bitrix24'
    elif install_token_value:
        status_title = 'Быстрый вход в Oko Systems'
        status_copy = 'Один код на почту для входа или регистрации. После подтверждения продолжим прямо из Bitrix24.'
    elif member_value or domain_value:
        status_title = 'Приложение установлено в Bitrix24'
        status_copy = 'Войдите в Oko Systems, чтобы привязать портал и перейти в кабинет.'

    onboarding_html = ''
    top_actions_html = f"""
  <div class="top-actions">
    <a class="action-link primary" href="{html_escape(add_lang_to_href(primary_href, lang))}">{html_escape(primary_label)}</a>
    <a class="action-link secondary" href="{html_escape(add_lang_to_href(secondary_href, lang))}">{html_escape(secondary_label)}</a>
  </div>
"""
    page_script = ''
    if install_token_value and not has_auth:
        next_href = html_escape(add_lang_to_href(f"/connect/bitrix?install_token={install_token_value}", lang))
        top_actions_html = """
  <div class="top-actions">
    <button type="button" class="action-link primary embedded-top-toggle active" data-auth-mode="login">Войти</button>
    <button type="button" class="action-link secondary embedded-top-toggle" data-auth-mode="register">Создать аккаунт</button>
  </div>
"""
        onboarding_html = f"""
<div class="embedded-inline-auth" data-reveal style="--reveal:1">
  <div class="embedded-auth-panel active" data-auth-panel="login">
    <div class="embedded-inline-copy">
      <p class="embedded-kicker">Вход</p>
      <h2 class="embedded-card-title">Войти по коду</h2>
      <p class="embedded-card-copy">Введите email. Мы отправим одноразовый код и после подтверждения сразу продолжим из Bitrix24.</p>
      {error_html}
    </div>
    <form method="post" action="/login" class="auth-form embedded-inline-form">
      <input type="hidden" name="install_token" value="{html_escape(install_token_value)}" />
      <input type="hidden" name="next" value="{next_href}" />
      <label class="auth-label" for="embedded-login-email">Email</label>
      <input class="auth-input" id="embedded-login-email" name="email" type="email" autocomplete="email" value="{login_input_value}" required />
      <button class="auth-submit" type="submit">Отправить код</button>
    </form>
  </div>
  <div class="embedded-auth-panel" data-auth-panel="register">
    <div class="embedded-inline-copy">
      <p class="embedded-kicker">Регистрация</p>
      <h2 class="embedded-card-title">Создать аккаунт</h2>
      <p class="embedded-card-copy">Укажите имя и email. Мы отправим код подтверждения и после него сразу откроем кабинет.</p>
    </div>
    <form method="post" action="/register" class="auth-form embedded-inline-form">
      <input type="hidden" name="install_token" value="{html_escape(install_token_value)}" />
      <label class="auth-label" for="embedded-register-name">Имя</label>
      <input class="auth-input" id="embedded-register-name" name="name" type="text" autocomplete="name" value="{quick_name_value}" required />
      <label class="auth-label" for="embedded-register-email">Email</label>
      <input class="auth-input" id="embedded-register-email" name="email" type="email" autocomplete="email" value="{quick_email_value}" required />
      <button class="auth-submit" type="submit">Создать и получить код</button>
    </form>
  </div>
</div>
"""
        page_script = """
<script>
(function(){
  var toggles = Array.prototype.slice.call(document.querySelectorAll('[data-auth-mode]'));
  var panels = Array.prototype.slice.call(document.querySelectorAll('[data-auth-panel]'));
  if (!toggles.length || !panels.length) return;
  function setMode(mode){
    toggles.forEach(function(btn){
      var active = btn.getAttribute('data-auth-mode') === mode;
      btn.classList.toggle('active', active);
      btn.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
    panels.forEach(function(panel){
      panel.classList.toggle('active', panel.getAttribute('data-auth-panel') === mode);
    });
  }
  toggles.forEach(function(btn){
    btn.addEventListener('click', function(){ setMode(btn.getAttribute('data-auth-mode')); });
  });
  setMode('login');
})();
</script>
"""

    body_html = f"""
<section class="panel embedded-hero" data-reveal style="--reveal:0">
  <p class="eyebrow">Приложение Bitrix24</p>
  <h1 class="page-title" style="font-size:clamp(28px,4vw,40px);margin-bottom:10px">{html_escape(status_title)}</h1>
  <p class="page-subtitle embedded-copy">{html_escape(status_copy)}</p>
  {top_actions_html}
  {onboarding_html}
</section>
"""
    extra_style = """
.embedded-hero{max-width:960px;margin:24px auto 18px;padding:28px}
.embedded-copy{max-width:760px}
.embedded-inline-auth{display:grid;gap:18px;margin-top:24px;padding:22px;border:1px solid var(--border);border-radius:22px;background:linear-gradient(180deg,#fffef8 0%,#fff 100%)}
.embedded-auth-panel{display:none;grid-template-columns:minmax(0,1.1fr) minmax(320px,.9fr);gap:18px;align-items:end}
.embedded-auth-panel.active{display:grid}
.embedded-inline-copy{display:grid;align-content:start}
.embedded-inline-form{margin-top:0}
.embedded-top-toggle{appearance:none;border:none;cursor:pointer}
.embedded-top-toggle.active{background:var(--ink);color:var(--surface);border-color:var(--ink)}
.embedded-kicker{margin:0 0 14px;font-size:12px;font-weight:900;letter-spacing:.14em;text-transform:uppercase;color:var(--ink-faint)}
.embedded-card-title{margin:0 0 10px;font-size:clamp(20px,3vw,28px);line-height:1.15}
.embedded-card-copy{margin:0 0 18px;color:var(--ink-soft);line-height:1.6}
.embedded-error{margin-bottom:16px}
@media(max-width:720px){
  .embedded-hero{margin:16px auto;padding:20px 18px}
  .embedded-inline-auth{padding:18px}
  .embedded-auth-panel,.embedded-auth-panel.active{grid-template-columns:1fr}
}
"""
    return render_page_frame(lang, 'Oko Systems для Bitrix24', body_html, extra_style=extra_style, script=page_script)


def render_login_page(lang: str, error_text: str = '', login_value: str = '', current_path: str = '/login', query_params: dict | None = None, mode: str = 'password') -> str:
    login_input_value = html_escape(str(login_value or '').strip())
    next_value = ''
    install_token_value = ''
    if isinstance(query_params, dict):
        next_value = str((query_params.get('next') or [''])[0] or '').strip()
        install_token_value = str((query_params.get('install_token') or [''])[0] or '').strip()
    next_input = f"<input type='hidden' name='next' value='{html_escape(next_value)}' />" if next_value.startswith('/') else ''
    install_token_input = f"<input type='hidden' name='install_token' value='{html_escape(install_token_value)}' />" if install_token_value else ''
    error_html = f"<div class='a-error'>{html_escape(error_text)}</div>" if error_text else ''
    lang_ru_active = 'a-lang-btn active' if lang == 'ru' else 'a-lang-btn'
    lang_kk_active = 'a-lang-btn active' if lang == 'kk' else 'a-lang-btn'
    lang_ru_href = html_escape(lang_query_href(current_path, query_params, 'ru'))
    lang_kk_href = html_escape(lang_query_href(current_path, query_params, 'kk'))
    return f"""<!doctype html>
<html lang="{html_escape(lang)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html_escape(t(lang, 'login_title'))} — Oko Systems</title>
<link rel="icon" type="image/svg+xml" href="/favicon.svg?v=2">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
html,body{{height:100%}}
body{{font-family:'Manrope',system-ui,sans-serif;font-size:15px;font-weight:500;line-height:1.55;background:#08080E;color:#0C0C14;-webkit-font-smoothing:antialiased;display:flex;flex-direction:column;min-height:100vh}}
/* layout */
.a-wrap{{flex:1;display:flex;align-items:center;justify-content:center;padding:24px 16px;position:relative;overflow:hidden}}
.a-wrap-install{{padding-top:88px;padding-bottom:28px;align-items:flex-start;overflow:auto}}
.a-glow{{position:absolute;top:-150px;left:50%;transform:translateX(-50%);width:700px;height:500px;background:radial-gradient(ellipse,rgba(91,106,249,.22) 0%,transparent 70%);pointer-events:none}}
/* top bar */
.a-topbar{{position:fixed;top:0;left:0;right:0;height:60px;display:flex;align-items:center;justify-content:space-between;padding:0 24px;z-index:10}}
.a-logo{{display:flex;align-items:center;gap:9px;text-decoration:none;color:#fff;font-size:16px;font-weight:800}}
.a-logo-icon{{width:28px;height:28px;background:#5B6AF9;border-radius:7px;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:900;color:#fff;flex-shrink:0}}
.a-topbar-right{{display:flex;align-items:center;gap:8px}}
.a-lang-btn{{height:30px;padding:0 12px;border-radius:8px;border:1px solid rgba(255,255,255,.12);background:transparent;color:rgba(255,255,255,.45);font-family:inherit;font-size:12px;font-weight:700;cursor:pointer;text-decoration:none;display:inline-flex;align-items:center;transition:all .2s}}
.a-lang-btn.active,.a-lang-btn:hover{{background:rgba(255,255,255,.08);color:#fff;border-color:rgba(255,255,255,.25)}}
/* card */
.a-card{{background:#fff;border-radius:24px;padding:36px;width:100%;max-width:400px;box-shadow:0 0 0 1px rgba(91,106,249,.15),0 24px 64px rgba(0,0,0,.45);position:relative;z-index:1;animation:cardIn .5s ease both}}
@keyframes cardIn{{from{{opacity:0;transform:translateY(16px)}}to{{opacity:1;transform:none}}}}
.a-card-eyebrow{{font-size:11px;font-weight:800;letter-spacing:.12em;text-transform:uppercase;color:#5B6AF9;margin-bottom:8px}}
.a-card-title{{font-size:26px;font-weight:900;letter-spacing:-.02em;color:#0C0C14;margin-bottom:4px}}
.a-card-sub{{font-size:13px;color:#6B7280;margin-bottom:24px}}
/* form */
.a-form{{display:flex;flex-direction:column;gap:14px}}
.a-label{{font-size:12px;font-weight:700;color:#6B7280;display:block;margin-bottom:5px}}
.a-input{{width:100%;height:46px;padding:0 14px;border:1.5px solid #E5E7EB;border-radius:11px;font-family:inherit;font-size:15px;font-weight:500;color:#0C0C14;background:#fff;outline:none;transition:border-color .2s}}
.a-password-wrap{{position:relative}}
.a-input-password{{padding-right:56px}}
.a-password-toggle{{position:absolute;top:50%;right:8px;transform:translateY(-50%);width:36px;height:36px;padding:0;border:1px solid #E5E7EB;border-radius:10px;background:#F8FAFC;color:#6B7280;display:inline-flex;align-items:center;justify-content:center;appearance:none;-webkit-appearance:none;box-shadow:0 1px 2px rgba(12,12,20,.04);cursor:pointer;transition:border-color .2s,background .2s,color .2s,box-shadow .2s}}
.a-password-toggle:hover{{background:#EEF2FF;border-color:#D8DEFE;color:#334155}}
.a-password-toggle:focus-visible{{outline:none;border-color:#5B6AF9;box-shadow:0 0 0 3px rgba(91,106,249,.14)}}
.a-password-toggle svg{{width:18px;height:18px;display:block;fill:none;stroke:currentColor;stroke-width:1.9;stroke-linecap:round;stroke-linejoin:round}}
.a-password-toggle .icon-eye-off{{display:none}}
.a-password-toggle[aria-pressed='true']{{background:#EEF2FF;border-color:#C7D2FE;color:#5B6AF9}}
.a-password-toggle[aria-pressed='true'] .icon-eye{{display:none}}
.a-password-toggle[aria-pressed='true'] .icon-eye-off{{display:block}}
.a-input:focus{{border-color:#5B6AF9;box-shadow:0 0 0 3px rgba(91,106,249,.1)}}
.a-submit{{width:100%;height:48px;background:#5B6AF9;color:#fff;border:none;border-radius:12px;font-family:inherit;font-size:15px;font-weight:800;cursor:pointer;transition:background .2s,transform .15s;margin-top:2px}}
.a-submit:hover{{background:#7B87FF;transform:translateY(-1px)}}
/* links */
.a-links{{display:flex;justify-content:space-between;gap:8px;margin-top:12px}}
.a-links a{{font-size:12px;color:#9CA3AF;text-decoration:none;transition:color .2s}}
.a-links a:hover{{color:#5B6AF9}}
/* error */
.a-error{{background:#FEF2F2;border:1px solid #FECACA;border-radius:10px;padding:10px 14px;font-size:13px;color:#DC2626;margin-bottom:4px}}
/* page footer */
.a-page-footer{{padding:20px 24px;text-align:center}}
.a-page-footer-copy{{font-size:12px;color:rgba(255,255,255,.2)}}
@media(max-width:480px){{.a-card{{padding:28px 20px 24px}}.a-topbar{{padding:0 16px}}}}
</style>
</head>
<body>

<div class="a-topbar">
  <a href="/" class="a-logo">
    <div class="a-logo-icon">О</div>
    Oko Systems
  </a>
  <div class="a-topbar-right">
    <a href="{lang_ru_href}" class="{lang_ru_active}">Рус</a>
    <a href="{lang_kk_href}" class="{lang_kk_active}">Қаз</a>
  </div>
</div>

<div class="a-wrap">
  <div class="a-glow"></div>
  <div class="a-card">
    <div class="a-card-eyebrow">AI-аналитика звонков</div>
    <div class="a-card-title">Войти в Oko Systems</div>
    <div class="a-card-sub">{html_escape(t(lang, 'login_page_subtitle'))}</div>

    {error_html}
    <form method="post" action="/login" class="a-form">
      <input type="hidden" name="method" value="password" />
      {next_input}{install_token_input}
      <div>
        <label class="a-label" for="pw-email">{html_escape(t(lang, 'login_field'))}</label>
        <input class="a-input" id="pw-email" name="email" type="email" autocomplete="email" value="{login_input_value}" placeholder="email@example.com" required />
      </div>
      <div>
        <label class="a-label" for="pw-password">{html_escape(t(lang, 'password'))}</label>
        <div class="a-password-wrap">
          <input class="a-input a-input-password" id="pw-password" name="password" type="password" autocomplete="current-password" placeholder="••••••••" required />
          <button class="a-password-toggle" type="button" data-toggle-password="pw-password" aria-label="Показать пароль" aria-pressed="false">
            <svg class="icon-eye" viewBox="0 0 24 24" aria-hidden="true">
              <path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6Z"></path>
              <circle cx="12" cy="12" r="3"></circle>
            </svg>
            <svg class="icon-eye-off" viewBox="0 0 24 24" aria-hidden="true">
              <path d="M3 3l18 18"></path>
              <path d="M10.58 10.58A2 2 0 0 0 12 14a2 2 0 0 0 1.42-.58"></path>
              <path d="M6.71 6.7C4.63 8.06 3.19 10.06 2.5 12c1.5 3.37 4.94 6 9.5 6 1.96 0 3.72-.49 5.2-1.34"></path>
              <path d="M9.88 4.24A11.6 11.6 0 0 1 12 4c4.56 0 8 2.63 9.5 6-.5 1.13-1.22 2.19-2.12 3.08"></path>
            </svg>
          </button>
        </div>
      </div>
      <button class="a-submit" type="submit">{html_escape(t(lang, 'login_enter_password'))}</button>
    </form>
    <div class="a-links">
      <a href="/forgot-password">{html_escape(t(lang, 'forgot_password'))}</a>
      <a href="/register">{html_escape(t(lang, 'no_account'))} {html_escape(t(lang, 'register'))}</a>
    </div>

  </div>
</div>

<div class="a-page-footer">
  <div class="a-page-footer-copy">© 2026 Oko Systems</div>
</div>

<script>
(function(){{
  Array.prototype.forEach.call(document.querySelectorAll('[data-toggle-password]'), function(btn){{
    btn.addEventListener('click', function(){{
      var input=document.getElementById(btn.getAttribute('data-toggle-password'));
      if(!input) return;
      var isVisible=input.type==='text';
      input.type=isVisible?'password':'text';
      btn.setAttribute('aria-label', isVisible?'Показать пароль':'Скрыть пароль');
      btn.setAttribute('aria-pressed', isVisible?'false':'true');
    }});
  }});
}})();
</script>
</body>
</html>"""


def render_register_page(lang: str, error_text: str = '', values: dict | None = None, current_path: str = '/register', query_params: dict | None = None) -> str:
    values = values or {}
    error_html = f"<div class='a-error'>{html_escape(error_text)}</div>" if error_text else ''
    name_value = html_escape(str(values.get('name') or '').strip())
    email_value = html_escape(str(values.get('email') or '').strip())
    next_value = ''
    install_token_value = ''
    if isinstance(query_params, dict):
        next_value = str((query_params.get('next') or [''])[0] or '').strip()
        install_token_value = str((query_params.get('install_token') or [''])[0] or '').strip()
    next_input = f"<input type='hidden' name='next' value='{html_escape(next_value)}' />" if next_value.startswith('/') else ''
    install_token_input = f"<input type='hidden' name='install_token' value='{html_escape(install_token_value)}' />" if install_token_value else ''
    lang_ru_active = 'a-lang-btn active' if lang == 'ru' else 'a-lang-btn'
    lang_kk_active = 'a-lang-btn active' if lang == 'kk' else 'a-lang-btn'
    lang_ru_href = html_escape(lang_query_href(current_path, query_params, 'ru'))
    lang_kk_href = html_escape(lang_query_href(current_path, query_params, 'kk'))
    login_href = html_escape(lang_query_href('/login', query_params, lang))
    is_install_flow = bool(install_token_value)
    card_title = 'Создать аккаунт'
    card_subtitle = 'Создайте аккаунт по email. Придумайте надёжный пароль.'
    submit_label = html_escape(t(lang, 'register'))
    password_fields_html = f"""
      <div class="a-field">
        <label class="a-label" for="register-password">{html_escape(t(lang, 'password'))}</label>
        <div class="a-password-wrap">
          <input class="a-input a-input-password" id="register-password" name="password" type="password" autocomplete="new-password" placeholder="Минимум 8 символов" required />
          <button class="a-password-toggle" type="button" data-toggle-password="register-password" aria-label="Показать пароль" aria-pressed="false">
            <svg class="icon-eye" viewBox="0 0 24 24" aria-hidden="true">
              <path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6Z"></path>
              <circle cx="12" cy="12" r="3"></circle>
            </svg>
            <svg class="icon-eye-off" viewBox="0 0 24 24" aria-hidden="true">
              <path d="M3 3l18 18"></path>
              <path d="M10.58 10.58A2 2 0 0 0 12 14a2 2 0 0 0 1.42-.58"></path>
              <path d="M6.71 6.7C4.63 8.06 3.19 10.06 2.5 12c1.5 3.37 4.94 6 9.5 6 1.96 0 3.72-.49 5.2-1.34"></path>
              <path d="M9.88 4.24A11.6 11.6 0 0 1 12 4c4.56 0 8 2.63 9.5 6-.5 1.13-1.22 2.19-2.12 3.08"></path>
            </svg>
          </button>
        </div>
      </div>
      <div class="a-field">
        <label class="a-label" for="register-password2">{html_escape(t(lang, 'password_confirm'))}</label>
        <div class="a-password-wrap">
          <input class="a-input a-input-password" id="register-password2" name="password2" type="password" autocomplete="new-password" placeholder="••••••••" required />
          <button class="a-password-toggle" type="button" data-toggle-password="register-password2" aria-label="Показать пароль" aria-pressed="false">
            <svg class="icon-eye" viewBox="0 0 24 24" aria-hidden="true">
              <path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6Z"></path>
              <circle cx="12" cy="12" r="3"></circle>
            </svg>
            <svg class="icon-eye-off" viewBox="0 0 24 24" aria-hidden="true">
              <path d="M3 3l18 18"></path>
              <path d="M10.58 10.58A2 2 0 0 0 12 14a2 2 0 0 0 1.42-.58"></path>
              <path d="M6.71 6.7C4.63 8.06 3.19 10.06 2.5 12c1.5 3.37 4.94 6 9.5 6 1.96 0 3.72-.49 5.2-1.34"></path>
              <path d="M9.88 4.24A11.6 11.6 0 0 1 12 4c4.56 0 8 2.63 9.5 6-.5 1.13-1.22 2.19-2.12 3.08"></path>
            </svg>
          </button>
        </div>
      </div>
"""
    footer_html = ''
    page_footer_html = """
<div class="a-page-footer">
  <div class="a-page-footer-copy">© 2026 Oko Systems</div>
</div>
"""
    if is_install_flow:
        page_footer_html = ''
    return f"""<!doctype html>
<html lang="{html_escape(lang)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html_escape(t(lang, 'register_title'))} — Oko Systems</title>
<link rel="icon" type="image/svg+xml" href="/favicon.svg?v=2">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
html,body{{height:100%}}
body{{font-family:'Manrope',system-ui,sans-serif;font-size:15px;font-weight:500;line-height:1.55;background:#08080E;color:#0C0C14;-webkit-font-smoothing:antialiased;display:flex;flex-direction:column;min-height:100vh}}
.a-wrap{{flex:1;display:flex;align-items:center;justify-content:center;padding:24px 16px;position:relative;overflow:hidden}}
.a-wrap-install{{padding-top:74px;padding-bottom:16px;align-items:flex-start;overflow:auto}}
.a-glow{{position:absolute;top:-150px;left:50%;transform:translateX(-50%);width:700px;height:500px;background:radial-gradient(ellipse,rgba(91,106,249,.22) 0%,transparent 70%);pointer-events:none}}
.a-topbar{{position:fixed;top:0;left:0;right:0;height:60px;display:flex;align-items:center;justify-content:space-between;padding:0 24px;z-index:10}}
.a-logo{{display:flex;align-items:center;gap:9px;text-decoration:none;color:#fff;font-size:16px;font-weight:800}}
.a-logo-icon{{width:28px;height:28px;background:#5B6AF9;border-radius:7px;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:900;color:#fff;flex-shrink:0}}
.a-topbar-right{{display:flex;align-items:center;gap:8px}}
.a-lang-btn{{height:30px;padding:0 12px;border-radius:8px;border:1px solid rgba(255,255,255,.12);background:transparent;color:rgba(255,255,255,.45);font-family:inherit;font-size:12px;font-weight:700;cursor:pointer;text-decoration:none;display:inline-flex;align-items:center;transition:all .2s}}
.a-lang-btn.active,.a-lang-btn:hover{{background:rgba(255,255,255,.08);color:#fff;border-color:rgba(255,255,255,.25)}}
.a-card{{background:#fff;border-radius:22px;padding:22px 22px 16px;width:100%;max-width:368px;box-shadow:0 0 0 1px rgba(91,106,249,.15),0 24px 64px rgba(0,0,0,.45);position:relative;z-index:1;animation:cardIn .5s ease both}}
@keyframes cardIn{{from{{opacity:0;transform:translateY(16px)}}to{{opacity:1;transform:none}}}}
.a-card-eyebrow{{font-size:10px;font-weight:800;letter-spacing:.12em;text-transform:uppercase;color:#5B6AF9;margin-bottom:6px}}
.a-card-title{{font-size:21px;font-weight:900;letter-spacing:-.02em;color:#0C0C14;margin-bottom:4px;line-height:1.06}}
.a-card-sub{{font-size:12px;color:#6B7280;margin-bottom:14px;line-height:1.45}}
.a-form{{display:flex;flex-direction:column;gap:9px}}
.a-field{{display:flex;flex-direction:column;gap:4px}}
.a-label{{font-size:11px;font-weight:700;color:#6B7280;display:block}}
.a-input{{width:100%;height:39px;padding:0 12px;border:1.5px solid #E5E7EB;border-radius:11px;font-family:inherit;font-size:14px;font-weight:500;color:#0C0C14;background:#fff;outline:none;transition:border-color .2s}}
.a-password-wrap{{position:relative}}
.a-input-password{{padding-right:54px}}
.a-password-toggle{{position:absolute;top:50%;right:6px;transform:translateY(-50%);width:32px;height:32px;padding:0;border:1px solid #E5E7EB;border-radius:10px;background:#F8FAFC;color:#6B7280;display:inline-flex;align-items:center;justify-content:center;appearance:none;-webkit-appearance:none;box-shadow:0 1px 2px rgba(12,12,20,.04);cursor:pointer;transition:border-color .2s,background .2s,color .2s,box-shadow .2s}}
.a-password-toggle:hover{{background:#EEF2FF;border-color:#D8DEFE;color:#334155}}
.a-password-toggle:focus-visible{{outline:none;border-color:#5B6AF9;box-shadow:0 0 0 3px rgba(91,106,249,.14)}}
.a-password-toggle svg{{width:16px;height:16px;display:block;fill:none;stroke:currentColor;stroke-width:1.9;stroke-linecap:round;stroke-linejoin:round}}
.a-password-toggle .icon-eye-off{{display:none}}
.a-password-toggle[aria-pressed='true']{{background:#EEF2FF;border-color:#C7D2FE;color:#5B6AF9}}
.a-password-toggle[aria-pressed='true'] .icon-eye{{display:none}}
.a-password-toggle[aria-pressed='true'] .icon-eye-off{{display:block}}
.a-input:focus{{border-color:#5B6AF9;box-shadow:0 0 0 3px rgba(91,106,249,.1)}}
.a-submit{{width:100%;height:41px;background:#5B6AF9;color:#fff;border:none;border-radius:12px;font-family:inherit;font-size:14px;font-weight:800;cursor:pointer;transition:background .2s,transform .15s;margin-top:2px}}
.a-submit:hover{{background:#7B87FF;transform:translateY(-1px)}}
.a-links{{display:flex;justify-content:flex-start;gap:8px;margin-top:8px}}
.a-links a{{font-size:12px;color:#9CA3AF;text-decoration:none;transition:color .2s}}
.a-links a:hover{{color:#5B6AF9}}
.a-error{{background:#FEF2F2;border:1px solid #FECACA;border-radius:10px;padding:8px 10px;font-size:12px;color:#DC2626;margin-bottom:2px}}
.a-page-footer{{padding:20px 24px;text-align:center}}
.a-page-footer-copy{{font-size:12px;color:rgba(255,255,255,.2)}}
@media(max-width:480px){{.a-card{{padding:18px 16px 14px;max-width:100%}}.a-topbar{{padding:0 16px}}.a-wrap-install{{padding-top:68px;padding-bottom:14px}}}}
</style>
</head>
<body>

<div class="a-topbar">
  <a href="/" class="a-logo">
    <div class="a-logo-icon">О</div>
    Oko Systems
  </a>
  <div class="a-topbar-right">
    <a href="{lang_ru_href}" class="{lang_ru_active}">Рус</a>
    <a href="{lang_kk_href}" class="{lang_kk_active}">Қаз</a>
  </div>
</div>

<div class="a-wrap{' a-wrap-install' if is_install_flow else ''}">
  <div class="a-glow"></div>
  <div class="a-card">
    <div class="a-card-eyebrow">AI-аналитика звонков</div>
    <div class="a-card-title">{card_title}</div>
    <div class="a-card-sub">{card_subtitle}</div>

    {error_html}

    <form method="post" action="/register" class="a-form">
      {next_input}
      {install_token_input}
      <div class="a-field">
        <label class="a-label" for="register-name">{html_escape(t(lang, 'name_field'))}</label>
        <input class="a-input" id="register-name" name="name" type="text" autocomplete="name" value="{name_value}" required />
      </div>
      <div class="a-field">
        <label class="a-label" for="register-email">{html_escape(t(lang, 'email'))}</label>
        <input class="a-input" id="register-email" name="email" type="email" autocomplete="email" value="{email_value}" placeholder="email@example.com" required />
      </div>
      {password_fields_html}
      <button class="a-submit" type="submit">{submit_label}</button>
    </form>

    <div class="a-links">
      <a href="{login_href}">{html_escape(t(lang, 'have_account'))} {html_escape(t(lang, 'login'))}</a>
    </div>

    {footer_html}
  </div>
</div>

{page_footer_html}
<script>
(function(){{
  Array.prototype.forEach.call(document.querySelectorAll('[data-toggle-password]'), function(btn){{
    btn.addEventListener('click', function(){{
      var input=document.getElementById(btn.getAttribute('data-toggle-password'));
      if(!input) return;
      var isVisible=input.type==='text';
      input.type=isVisible?'password':'text';
      btn.setAttribute('aria-label', isVisible?'Показать пароль':'Скрыть пароль');
      btn.setAttribute('aria-pressed', isVisible?'false':'true');
    }});
  }});
}})();
</script>
</body>
</html>"""


def render_email_code_page(lang: str, token: str, email: str, error_text: str = '', notice_text: str = '', current_path: str = '/verify-code', query_params: dict | None = None) -> str:
    error_html = f"<div class='form-error' style='margin-bottom:16px'>{html_escape(error_text)}</div>" if error_text else ''
    notice_html = f"<div class='form-notice' style='margin-bottom:16px'>{html_escape(notice_text)}</div>" if notice_text else ''
    lang_switch = render_lang_switch(current_path, query_params, lang)
    subtitle = t(lang, 'auth_code_subtitle').replace('{email}', email)
    body_html = f"""
<section class="panel auth-page auth-card" data-reveal style="--reveal:0">
  <div class="auth-topbar">{lang_switch}</div>
  <p class="eyebrow">AI Аналитика</p>
  <h1 class="page-title" style="font-size:clamp(26px,3.5vw,36px)">{html_escape(t(lang, 'auth_code_title'))}</h1>
  <p class="page-subtitle">{html_escape(subtitle)}</p>
  {notice_html}
  {error_html}

  <form method="post" action="/verify-code" class="auth-form" style="margin-top:28px">
    <input type="hidden" name="token" value="{html_escape(token)}" />
    <label class="auth-label" for="auth-code">{html_escape(t(lang, 'auth_code_field'))}</label>
    <input class="auth-input" id="auth-code" name="code" type="text" inputmode="numeric" autocomplete="one-time-code" maxlength="6" placeholder="123456" required />
    <button class="auth-submit" type="submit">{html_escape(t(lang, 'auth_code_submit'))}</button>
  </form>

  <div class="auth-links">
    <a href="/login">{html_escape(t(lang, 'login_title'))}</a>
    <a href="/register">{html_escape(t(lang, 'register_title'))}</a>
  </div>
</section>
"""
    return render_page_frame(lang, t(lang, 'auth_code_title'), body_html, extra_style="""
.auth-page{max-width:420px;margin:60px auto;padding:36px 32px 40px}
.auth-topbar{display:flex;justify-content:flex-end;margin-bottom:18px}
.auth-topbar .lang-switch{margin-bottom:0;background:#F3F4F6;border-color:#E5E7EB}
.auth-topbar .lang-btn{color:var(--ink-soft)}
.auth-topbar .lang-btn:hover{color:var(--ink)}
.auth-topbar .lang-btn.active{background:#5B6AF9;color:#fff}
.auth-form{display:flex;flex-direction:column;gap:14px}
.auth-label{font-size:12px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;color:var(--ink-faint)}
.auth-input{width:100%;height:46px;padding:0 14px;border-radius:12px;border:1px solid var(--border);background:var(--panel-soft);color:var(--ink);font:inherit;box-sizing:border-box}
.auth-input:focus{outline:none;border-color:var(--ink-faint);box-shadow:0 0 0 3px rgba(33,35,43,.08)}
.auth-submit{display:flex;align-items:center;justify-content:center;width:100%;height:46px;padding:0 20px;border:none;border-radius:12px;background:var(--ink);color:var(--surface);font-size:15px;font-weight:800;cursor:pointer;transition:opacity .15s}
.auth-submit:hover{opacity:.9}
.auth-links{display:flex;justify-content:space-between;gap:12px;margin-top:16px}
.auth-links a{font-size:12px;color:var(--ink-faint);text-decoration:none}
.auth-links a:hover{color:var(--ink-soft);text-decoration:underline}
@media(max-width:480px){.auth-page{margin:24px auto;padding:24px 20px 28px}}
""")


def render_forgot_password_page(lang: str, error_text: str = '', notice_text: str = '', email_value: str = '', current_path: str = '/forgot-password', query_params: dict | None = None) -> str:
    error_html = f"<div class='form-error' style='margin-bottom:16px'>{html_escape(error_text)}</div>" if error_text else ''
    notice_html = f"<div class='form-notice' style='margin-bottom:16px'>{html_escape(notice_text)}</div>" if notice_text else ''
    email_input_value = html_escape(str(email_value or '').strip())
    lang_switch = render_lang_switch(current_path, query_params, lang)
    body_html = f"""
<section class="panel auth-page auth-card" data-reveal style="--reveal:0">
  <div class="auth-topbar">{lang_switch}</div>
  <p class="eyebrow">AI Аналитика</p>
  <h1 class="page-title" style="font-size:clamp(26px,3.5vw,36px)">Oko Systems</h1>
  <p class="page-subtitle">{html_escape(t(lang, 'forgot_password_page_subtitle'))}</p>
  {error_html}
  {notice_html}

  <form method="post" action="/forgot-password" class="auth-form" style="margin-top:28px">
    <label class="auth-label" for="forgot-email">{html_escape(t(lang, 'email'))}</label>
    <input class="auth-input" id="forgot-email" name="email" type="email" autocomplete="email" value="{email_input_value}" required />
    <button class="auth-submit" type="submit">{html_escape(t(lang, 'forgot_password_submit'))}</button>
  </form>

  <div class="auth-links">
    <a href="/login">{html_escape(t(lang, 'login'))}</a>
    <a href="/register">{html_escape(t(lang, 'register'))}</a>
  </div>
</section>
"""
    return render_page_frame(lang, t(lang, 'forgot_password_title'), body_html, extra_style="""
.auth-page{max-width:420px;margin:60px auto;padding:36px 32px 40px}
.auth-topbar{display:flex;justify-content:flex-end;margin-bottom:18px}
.auth-topbar .lang-switch{margin-bottom:0;background:#F3F4F6;border-color:#E5E7EB}
.auth-topbar .lang-btn{color:var(--ink-soft)}
.auth-topbar .lang-btn:hover{color:var(--ink)}
.auth-topbar .lang-btn.active{background:#5B6AF9;color:#fff}
.auth-form{display:flex;flex-direction:column;gap:14px}
.auth-label{font-size:12px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;color:var(--ink-faint)}
.auth-input{width:100%;height:46px;padding:0 14px;border-radius:12px;border:1px solid var(--border);background:var(--panel-soft);color:var(--ink);font:inherit;box-sizing:border-box}
.auth-input:focus{outline:none;border-color:var(--ink-faint);box-shadow:0 0 0 3px rgba(33,35,43,.08)}
.auth-submit{display:flex;align-items:center;justify-content:center;width:100%;height:46px;padding:0 20px;border:none;border-radius:12px;background:var(--ink);color:var(--surface);font-size:15px;font-weight:800;cursor:pointer;transition:opacity .15s}
.auth-submit:hover{opacity:.9}
.auth-links{display:flex;justify-content:space-between;gap:12px;margin-top:16px}
.auth-links a{font-size:12px;color:var(--ink-faint);text-decoration:none}
.auth-links a:hover{color:var(--ink-soft);text-decoration:underline}
.form-notice{padding:12px 14px;border-radius:12px;background:#eef6ef;color:#30553a;font-size:13px;line-height:1.5}
@media(max-width:480px){.auth-page{margin:24px auto;padding:24px 20px 28px}}
""")


def render_reset_password_page(lang: str, token: str, error_text: str = '', notice_text: str = '', valid: bool = True, current_path: str = '/reset-password', query_params: dict | None = None) -> str:
    error_html = f"<div class='form-error' style='margin-bottom:16px'>{html_escape(error_text)}</div>" if error_text else ''
    notice_html = f"<div class='form-notice' style='margin-bottom:16px'>{html_escape(notice_text)}</div>" if notice_text else ''
    token_value = html_escape(str(token or ''))
    lang_switch = render_lang_switch(current_path, query_params, lang)
    form_html = f"""
  <form method="post" action="/reset-password" class="auth-form" style="margin-top:28px">
    <input type="hidden" name="token" value="{token_value}" />
    <label class="auth-label" for="reset-password">{html_escape(t(lang, 'password'))}</label>
    <input class="auth-input" id="reset-password" name="password" type="password" autocomplete="new-password" required />
    <label class="auth-label" for="reset-password-confirm">{html_escape(t(lang, 'password_confirm'))}</label>
    <input class="auth-input" id="reset-password-confirm" name="password_confirm" type="password" autocomplete="new-password" required />
    <button class="auth-submit" type="submit">{html_escape(t(lang, 'reset_password_submit'))}</button>
  </form>
""" if valid else ''
    body_html = f"""
<section class="panel auth-page auth-card" data-reveal style="--reveal:0">
  <div class="auth-topbar">{lang_switch}</div>
  <p class="eyebrow">AI Аналитика</p>
  <h1 class="page-title" style="font-size:clamp(26px,3.5vw,36px)">Oko Systems</h1>
  <p class="page-subtitle">{html_escape(t(lang, 'reset_password_page_subtitle'))}</p>
  {error_html}
  {notice_html}
  {form_html}
  <div class="auth-links">
    <a href="/login">{html_escape(t(lang, 'login'))}</a>
    <a href="/forgot-password">{html_escape(t(lang, 'forgot_password'))}</a>
  </div>
</section>
"""
    return render_page_frame(lang, t(lang, 'reset_password_title'), body_html, extra_style="""
.auth-page{max-width:420px;margin:60px auto;padding:36px 32px 40px}
.auth-topbar{display:flex;justify-content:flex-end;margin-bottom:18px}
.auth-topbar .lang-switch{margin-bottom:0;background:#F3F4F6;border-color:#E5E7EB}
.auth-topbar .lang-btn{color:var(--ink-soft)}
.auth-topbar .lang-btn:hover{color:var(--ink)}
.auth-topbar .lang-btn.active{background:#5B6AF9;color:#fff}
.auth-form{display:flex;flex-direction:column;gap:14px}
.auth-label{font-size:12px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;color:var(--ink-faint)}
.auth-input{width:100%;height:46px;padding:0 14px;border-radius:12px;border:1px solid var(--border);background:var(--panel-soft);color:var(--ink);font:inherit;box-sizing:border-box}
.auth-input:focus{outline:none;border-color:var(--ink-faint);box-shadow:0 0 0 3px rgba(33,35,43,.08)}
.auth-submit{display:flex;align-items:center;justify-content:center;width:100%;height:46px;padding:0 20px;border:none;border-radius:12px;background:var(--ink);color:var(--surface);font-size:15px;font-weight:800;cursor:pointer;transition:opacity .15s}
.auth-submit:hover{opacity:.9}
.auth-links{display:flex;justify-content:space-between;gap:12px;margin-top:16px}
.auth-links a{font-size:12px;color:var(--ink-faint);text-decoration:none}
.auth-links a:hover{color:var(--ink-soft);text-decoration:underline}
.form-notice{padding:12px 14px;border-radius:12px;background:#eef6ef;color:#30553a;font-size:13px;line-height:1.5}
@media(max-width:480px){.auth-page{margin:24px auto;padding:24px 20px 28px}}
""")


def render_connect_bitrix_page(lang: str, connect_token: str, rop_id: str, error_text: str = '') -> str:
    """Page shown before Bitrix24 OAuth redirect — explains what will happen."""
    oauth_url = (
        f"https://oauth.bitrix.info/oauth/authorize/"
        f"?client_id={MT_CLIENT_ID}"
        f"&response_type=code"
        f"&redirect_uri={MT_REDIRECT_URI}"
        f"&state={connect_token}"
    )
    error_html = f"<div class='form-error' style='margin-bottom:16px'>{html_escape(error_text)}</div>" if error_text else ''
    fallback_path = f"/{str(rop_id).lstrip('/')}" if rop_id else '/'
    public_connect_url = f"{APP_BASE_URL.rstrip('/')}/connect/bitrix/{connect_token}" if connect_token else f"{APP_BASE_URL.rstrip('/')}{fallback_path}"
    body_html = f"""
<section class="panel auth-page auth-card" data-reveal style="--reveal:0">
  <p class="eyebrow">Подключение Bitrix24</p>
  <h1 class="page-title" style="font-size:clamp(24px,3vw,32px)">Авторизация в Bitrix24</h1>
  {error_html}
  <p class="page-subtitle">
    Нажмите кнопку ниже, чтобы перейти к авторизации в вашем Bitrix24.
    Вы будете перенаправлены на страницу Bitrix24 для подтверждения доступа.
  </p>
  <div class="info-box" style="margin:20px 0">
    <p class="info-box-title">Для загрузки аудиозаписей звонков</p>
    <p class="info-box-text">
      Необходим доступ администратора Bitrix24. Если вы не являетесь администратором —
      скопируйте эту ссылку и отправьте вашему администратору:
    </p>
    <div class="copy-link-row">
      <code class="copy-link-code" id="connect-url">{html_escape(public_connect_url)}</code>
      <button class="copy-btn" onclick="navigator.clipboard.writeText(document.getElementById('connect-url').textContent)">Копировать</button>
    </div>
  </div>
  <div style="display:flex;align-items:center;gap:12px;margin-top:8px;flex-wrap:wrap">
    <a class="btn-primary" href="{html_escape(oauth_url)}">Авторизоваться в Bitrix24</a>
    <a class="btn-back" href="{html_escape(fallback_path)}">← Назад</a>
  </div>
</section>
"""
    extra_style = """
.auth-page{max-width:480px;margin:60px auto;padding:36px 32px 40px}
.info-box{background:var(--surface-muted);border:1px solid var(--border);border-radius:14px;padding:16px 18px}
.info-box-title{margin:0 0 6px;font-size:13px;font-weight:700;color:var(--ink)}
.info-box-text{margin:0 0 12px;font-size:13px;color:var(--ink-soft);line-height:1.5}
.copy-link-row{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.copy-link-code{font-size:11px;word-break:break-all;background:rgba(0,0,0,.04);border-radius:6px;padding:6px 8px;flex:1;min-width:0}
.copy-btn{flex-shrink:0;height:32px;padding:0 12px;border-radius:8px;border:1px solid var(--border-strong);background:var(--surface);font-size:12px;font-weight:700;cursor:pointer;font-family:inherit}
.copy-btn:hover{background:var(--surface-muted)}
.btn-primary{display:inline-flex;align-items:center;height:44px;padding:0 20px;border-radius:12px;background:var(--ink);color:#fff;font-size:15px;font-weight:700;text-decoration:none;transition:opacity .15s}
.btn-primary:hover{opacity:.85}
.btn-back{display:inline-flex;align-items:center;height:44px;padding:0 16px;border-radius:12px;border:1px solid var(--border-strong);background:var(--surface);color:var(--ink-soft);font-size:14px;font-weight:700;text-decoration:none;transition:background .15s}
.btn-back:hover{background:var(--surface-muted)}
@media(max-width:520px){.auth-page{margin:24px auto;padding:24px 18px 28px}}
"""
    return render_page_frame(lang, 'Подключение Bitrix24', body_html, extra_style=extra_style)


def render_oauth_success_page(lang: str, rop_id: str) -> str:
    """Shown after successful Bitrix24 OAuth."""
    rop_href = html_escape(f"/{str(rop_id or 'analysis').lstrip('/')}")
    body_html = f"""
<section class="panel auth-page auth-card" data-reveal style="--reveal:0">
  <p class="eyebrow">Подключение завершено</p>
  <h1 class="page-title" style="font-size:clamp(24px,3vw,32px)">Bitrix24 подключен!</h1>
  <p class="page-subtitle">Авторизация прошла успешно. Теперь вы можете использовать платформу.</p>
  <div class="top-actions" style="margin-top:24px">
    <a class="btn-primary" href="{rop_href}">Перейти к анализу</a>
  </div>
</section>
"""
    extra_style = """
.auth-page{max-width:440px;margin:80px auto;padding:40px 32px}
.btn-primary{display:inline-flex;align-items:center;height:44px;padding:0 20px;border-radius:12px;background:var(--ink);color:#fff;font-size:15px;font-weight:700;text-decoration:none;transition:opacity .15s}
.btn-primary:hover{opacity:.85}
"""
    return render_page_frame(lang, 'Bitrix24 подключен', body_html, extra_style=extra_style)


def operator_progress_available(operator_id: int | None, user_id: int | None = None) -> bool:
    oid = safe_int(operator_id)
    if not oid:
        return False
    progress_valid_from = parse_iso_datetime(OPERATOR_PROGRESS_VALID_FROM_UTC, datetime(2026, 3, 14, 0, 0, 0, tzinfo=timezone.utc))
    row = db_one(
        """
        SELECT 1
        FROM qa_analysis_runs r
        JOIN analysis_exports te ON te.id = r.export_id
        JOIN qa_analysis_summary s ON s.run_id = r.id
        WHERE r.status = 'completed'
          AND te.responsible_id = %s
          AND (%s IS NULL OR te.user_id = %s)
          AND COALESCE(r.created_at, te.created_at) >= %s
        LIMIT 1
        """,
        (oid, user_id, user_id, progress_valid_from),
    )
    return bool(row)


# Error classification — drives auto-retry queue and what gets shown to end users vs founder.
ERROR_KIND_BILLING = 'billing'
ERROR_KIND_NETWORK = 'network'
ERROR_KIND_RATE_LIMIT = 'rate_limit'
ERROR_KIND_UNKNOWN = 'unknown'

# Generic, provider-neutral labels shown to end users. Founders see real provider details via Telegram.
USER_ERROR_LABELS = {
    ERROR_KIND_BILLING: 'Технический сбой',
    ERROR_KIND_NETWORK: 'Сетевой сбой',
    ERROR_KIND_RATE_LIMIT: 'Сервис перегружен',
    ERROR_KIND_UNKNOWN: 'Технический сбой',
}


def classify_error_summary(text: str | None) -> tuple[str, str]:
    """Returns (kind, provider). Provider is best-guess for founder alerts: 'soniox' | 'anthropic' | ''."""
    raw = str(text or '').lower()
    if not raw:
        return ERROR_KIND_UNKNOWN, ''
    provider = ''
    if 'anthropic' in raw or 'claude' in raw:
        provider = 'anthropic'
    elif 'soniox' in raw or 'transcription' in raw or 'api.soniox.com' in raw:
        provider = 'soniox'
    if any(s in raw for s in ('insufficient_credit_balance', 'insufficient_quota', 'credit_balance_too_low',
                              'billing', 'payment_required', 'quota_exceeded', 'out_of_credits')):
        return ERROR_KIND_BILLING, provider
    if any(s in raw for s in ('rate_limit', 'rate-limit', 'too_many_requests', '429',
                              'query_limit_exceeded', 'too many requests')):
        # Bitrix-specific: the API returns {"error": "QUERY_LIMIT_EXCEEDED", "error_description": "Too many requests"}
        return ERROR_KIND_RATE_LIMIT, provider
    if any(s in raw for s in ('connecttimeout', 'connection timed out', 'readtimeout', 'connectionerror',
                              'max retries exceeded', 'temporary failure in name resolution')):
        return ERROR_KIND_NETWORK, provider
    return ERROR_KIND_UNKNOWN, provider


# Throttle billing alerts: at most one Telegram per provider per hour, kept in-process.
_BILLING_ALERT_LAST_SENT: dict[str, float] = {}
_BILLING_ALERT_THROTTLE_SEC = 60 * 60


def send_billing_alert(provider: str, batch_id: int | None, deal_id: int | None, error_summary: str):
    """Notify founder via Telegram that paid API balance is exhausted. Throttled per provider."""
    if not (TELEGRAM_BOT_TOKEN and DEMO_NOTIFY_CHAT_ID):
        return
    key = provider or 'unknown'
    now = time.time()
    last = _BILLING_ALERT_LAST_SENT.get(key, 0)
    if now - last < _BILLING_ALERT_THROTTLE_SEC:
        return
    _BILLING_ALERT_LAST_SENT[key] = now
    provider_label = {'anthropic': 'Anthropic / Claude', 'soniox': 'Soniox STT'}.get(provider, provider or '?')
    short = (error_summary or '').strip()
    if len(short) > 500:
        short = short[:500] + '…'
    text = (
        "⚠️ *Закончились средства*\n\n"
        f"*Провайдер:* {provider_label}\n"
        f"*Batch:* #{batch_id or '?'}\n"
        f"*Сделка:* #{deal_id or '?'}\n\n"
        "Анализ переведён в авто-восстановление: каждые 30 минут до 24ч пробуем снова. "
        "Пополни баланс — система сама догонит.\n\n"
        f"```\n{short}\n```"
    )
    try:
        payload = json.dumps({'chat_id': DEMO_NOTIFY_CHAT_ID, 'text': text, 'parse_mode': 'Markdown'}).encode('utf-8')
        req = Request(
            f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage',
            data=payload,
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        urlopen(req, timeout=10)
    except Exception as exc:
        db_log('telegram', 'billing_alert_failed', str(batch_id or ''), {'provider': provider}, 'error', str(exc))


# Auto-retry parameters for billing-class failures
RETRY_INTERVAL_SEC = 30 * 60        # 30 minutes between attempts
RETRY_MAX_ATTEMPTS = 48             # 24h total (48 × 30min)


def record_export_failure(export_id: int, error_summary: str) -> str:
    """Classify the failure, persist error_kind. For billing-class failures within the retry
    budget, schedule auto-retry and notify the founder via Telegram. Returns the kind."""
    kind, provider = classify_error_summary(error_summary)
    row = db_one(
        "SELECT batch_id, deal_id, retry_count FROM analysis_exports WHERE id=%s",
        (export_id,),
    ) or {}
    retry_count = int(row.get('retry_count') or 0)
    batch_id = safe_int(row.get('batch_id'))
    deal_id = safe_int(row.get('deal_id'))

    # Auto-retry billing, network, and rate-limit errors. Different causes, same recipe:
    #   billing → wait for funds → retry
    #   network → wait for the flaky route to recover → retry
    #   rate_limit → wait for Bitrix's per-app token bucket to refill → retry
    auto_retry_kinds = (ERROR_KIND_BILLING, ERROR_KIND_NETWORK, ERROR_KIND_RATE_LIMIT)
    if kind in auto_retry_kinds and retry_count < RETRY_MAX_ATTEMPTS:
        # rate_limit recovers in seconds; network in minutes; billing only after the founder tops up.
        if kind == ERROR_KIND_RATE_LIMIT:
            retry_delay = 60       # 1 minute — Bitrix bucket is back well before this
        elif kind == ERROR_KIND_NETWORK:
            retry_delay = 5 * 60   # 5 minutes
        else:
            retry_delay = RETRY_INTERVAL_SEC  # billing — 30 minutes
        db_exec(
            """
            UPDATE analysis_exports
            SET error_kind = %s,
                retry_after = NOW() + make_interval(secs => %s),
                retry_count = retry_count + 1,
                updated_at = NOW()
            WHERE id = %s
            """,
            (kind, retry_delay, export_id),
        )
        if kind == ERROR_KIND_BILLING:
            send_billing_alert(provider, batch_id, deal_id, error_summary)
    else:
        db_exec(
            "UPDATE analysis_exports SET error_kind = %s, retry_after = NULL, updated_at = NOW() WHERE id = %s",
            (kind, export_id),
        )
    return kind


def derive_export_ui_state(export_status: str, run_status: str, processing_stage: str, error_summary: str, run_error: str, has_report: bool) -> tuple[str, str]:
    export_state = str(export_status or 'received').strip() or 'received'
    run_state = str(run_status or '').strip()
    stage = str(processing_stage or '').strip()
    if export_state == 'awaiting_operator':
        return 'awaiting_operator', stage
    if export_state == 'failed':
        return 'failed', stage or run_error or error_summary
    if run_state == 'failed':
        return 'failed', run_error or error_summary or stage
    if run_state in ('queued', 'processing'):
        return 'processing', stage or ('Данные отправлены в Claude, жду ответ' if run_state == 'processing' else 'Подготовил данные, отправляю в Claude')
    if run_state == 'completed' and has_report:
        return export_state if export_state in ('completed', 'completed_with_errors') else 'completed', 'Анализ готов'
    if export_state in ('completed', 'completed_with_errors'):
        return 'processing', stage or 'Подготовил данные, отправляю в Claude'
    return export_state, stage
def get_batch_status_payload(batch_id: int, user_id: int | None = None):
    batch = db_one(
        "SELECT * FROM analysis_batches WHERE id=%s AND (%s IS NULL OR user_id = %s)",
        (batch_id, user_id, user_id),
    )
    if not batch:
        return None
    exports = db_all(
        """
        SELECT te.*, ar.id AS run_id, ar.status AS run_status, ar.error_text AS run_error, qrl.public_id
        FROM analysis_exports te
        LEFT JOIN LATERAL (
          SELECT *
          FROM qa_analysis_runs
          WHERE export_id = te.id
          ORDER BY run_version DESC, id DESC
          LIMIT 1
        ) ar ON TRUE
        LEFT JOIN qa_report_links qrl ON qrl.run_id = ar.id AND qrl.is_active = TRUE
        WHERE te.batch_id = %s
          AND (%s IS NULL OR te.user_id = %s)
        ORDER BY te.id ASC
        """,
        (batch_id, user_id, user_id),
    )
    items = []
    for row in exports:
        options = row.get('selection_options_json')
        if isinstance(options, str):
            try:
                options = json.loads(options)
            except Exception:
                options = []
        if not isinstance(options, list):
            options = []
        public_id = str(row.get('public_id') or '').strip()
        operator_id = safe_int(row.get('responsible_id'))
        report_href = add_lang_to_href(report_path(public_id, operator_id), 'ru') if public_id else ''
        timeline_href = add_lang_to_href(chronology_path(public_id, operator_id), 'ru') if public_id else ''
        ui_status, ui_stage = derive_export_ui_state(
            str(row.get('status') or 'received'),
            str(row.get('run_status') or '').strip(),
            str(row.get('processing_stage') or '').strip(),
            str(row.get('error_summary') or '').strip(),
            '',
            bool(report_href),
        )
        items.append({
            'export_id': int(row['id']),
            'deal_id': safe_int(row.get('deal_id')),
            'status': str(row.get('status') or 'received'),
            'ui_status': ui_status,
            'processing_stage': str(row.get('processing_stage') or '').strip(),
            'ui_stage': ui_stage,
            'selected_operator_name': str(row.get('selected_operator_name') or '').strip(),
            'selection_options': options,
            'report_href': report_href,
            'timeline_href': timeline_href,
            'operator_href': add_lang_to_href(f"/operator/{operator_id}", 'ru') if operator_id and operator_progress_available(operator_id, user_id=user_id) else '',
        })
    return {
        'batch_id': int(batch['id']),
        'status': str(batch.get('status') or 'queued'),
        'items': items,
    }
def _bitrix_context_cache_key(bitrix_ctx: dict | None) -> str:
    if not isinstance(bitrix_ctx, dict):
        return 'global'
    connection_id = safe_int(bitrix_ctx.get('bitrix_connection_id'))
    if connection_id:
        return f"connection:{connection_id}"
    domain = str(bitrix_ctx.get('domain') or '').strip().casefold()
    if domain:
        return f"domain:{domain}"
    member_id = str(bitrix_ctx.get('member_id') or '').strip()
    if member_id:
        return f"member:{member_id}"
    return 'global'


def fetch_user_profile(user_id: int, bitrix_ctx: dict | None = None) -> dict:
    uid = safe_int(user_id)
    if not uid:
        return {}
    cache_key = (_bitrix_context_cache_key(bitrix_ctx), uid)
    cached = USER_PROFILE_CACHE.get(cache_key)
    if cached:
        return cached

    profile = {}
    try:
        rows = bitrix_list_all('user.get', {'FILTER[ID]': uid}, bitrix_ctx=bitrix_ctx)
        if rows:
            profile = rows[0] if isinstance(rows[0], dict) else {}
    except Exception:
        profile = {}

    if not profile:
        try:
            result = bitrix_api('user.get', {'ID': uid}, bitrix_ctx=bitrix_ctx).get('result', [])
            if isinstance(result, list) and result and isinstance(result[0], dict):
                profile = result[0]
            elif isinstance(result, dict):
                profile = result
        except Exception:
            profile = {}

    # Only cache successful (non-empty) lookups so a transient OAuth/network error
    # doesn't poison subsequent retries for the lifetime of the process.
    if profile:
        USER_PROFILE_CACHE[cache_key] = profile
    return profile


def resolve_user_name_position(user_id: int, fallback_name: str = '', fallback_position: str = '', bitrix_ctx: dict | None = None) -> tuple[str, str]:
    name = str(fallback_name or '').strip()
    position = str(fallback_position or '').strip()

    if (not is_placeholder_text(name)) and (not is_placeholder_text(position)):
        return name, position

    uid = safe_int(user_id)
    if uid:
        p = fetch_user_profile(uid, bitrix_ctx=bitrix_ctx)
        if is_placeholder_text(name):
            parts = [p.get('NAME', ''), p.get('LAST_NAME', ''), p.get('SECOND_NAME', '')]
            from_user = ' '.join([str(x).strip() for x in parts if str(x).strip()]).strip()
            if from_user:
                name = from_user
        if is_placeholder_text(position):
            wp = str(p.get('WORK_POSITION') or '').strip()
            if wp:
                position = wp

    if is_placeholder_text(name):
        name = '<не доступно>'
    if is_placeholder_text(position):
        position = '<не доступно>'
    return name, position


def _vote_operator(votes: dict, user_id: int, weight: int, happened_at=None):
    uid = safe_int(user_id)
    if not uid:
        return
    item = votes.get(uid)
    if not item:
        votes[uid] = {'score': 0, 'latest_at': None}
        item = votes[uid]
    item['score'] += int(weight)
    ts = parse_ts(happened_at) if isinstance(happened_at, str) else happened_at
    if ts and (item['latest_at'] is None or ts > item['latest_at']):
        item['latest_at'] = ts


def infer_operator_identity(
    activities: list[dict] | None = None,
    comments: list[dict] | None = None,
    fallback_id: int | None = None,
    fallback_name: str = '',
    fallback_position: str = '',
) -> tuple[int | None, str, str]:
    call_summary = summarize_call_participants(activities or [])
    primary_call_operator = call_summary.get('primary_call_operator') if isinstance(call_summary, dict) else None
    if isinstance(primary_call_operator, dict) and safe_int(primary_call_operator.get('user_id')):
        uid = safe_int(primary_call_operator.get('user_id'))
        return uid, str(primary_call_operator.get('user_name') or '<не доступно>'), str(primary_call_operator.get('user_position') or '<не доступно>')

    votes = {}

    for act in activities or []:
        uid = safe_int(act.get('AUTHOR_ID')) or safe_int(act.get('RESPONSIBLE_ID'))
        if not uid:
            continue
        if str(act.get('TYPE_ID') or '') == '2':
            call_info = classify_call_activity(act)
            if call_info['status'] == 'handled':
                weight = 10 + min(20, max(1, int(call_info['duration_sec'] // 30)))
            elif call_info['status'] == 'ndz':
                weight = 1
            else:
                weight = 1
        else:
            weight = 1
        _vote_operator(votes, uid, weight, act.get('START_TIME') or act.get('END_TIME') or act.get('DEADLINE'))

    for comment in comments or []:
        uid = safe_int(comment.get('AUTHOR_ID'))
        if not uid:
            continue
        _vote_operator(votes, uid, 2, comment.get('CREATED'))

    chosen_id = safe_int(fallback_id)
    if votes:
        chosen_id = sorted(
            votes.items(),
            key=lambda item: (
                -int(item[1].get('score') or 0),
                -(item[1].get('latest_at').timestamp() if item[1].get('latest_at') else 0),
                int(item[0]),
            ),
        )[0][0]

    if chosen_id:
        name, position = resolve_user_name_position(chosen_id, fallback_name, fallback_position)
        return chosen_id, name, position
    return None, '<не доступно>', '<не доступно>'


def infer_operator_identity_from_event_rows(
    rows: list[dict],
    fallback_id: int | None = None,
    fallback_name: str = '',
    fallback_position: str = '',
) -> tuple[int | None, str, str]:
    votes = {}
    seen = set()
    for row in rows or []:
        source_type = str(row.get('source_type') or '')
        source_id = safe_int(row.get('source_id'))
        dedupe_key = (source_type, source_id)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        raw = row.get('raw_json') if isinstance(row.get('raw_json'), dict) else {}
        when = row.get('event_at')
        uid = None
        weight = 1
        if source_type == 'activity':
            uid = safe_int(raw.get('AUTHOR_ID')) or safe_int(raw.get('RESPONSIBLE_ID')) or safe_int(row.get('actor_id'))
            if str(raw.get('TYPE_ID') or row.get('event_type') or '') == '2' or str(row.get('event_type') or '') == 'call':
                weight = 4
        elif source_type == 'timeline':
            uid = safe_int(raw.get('AUTHOR_ID')) or safe_int(row.get('actor_id'))
            weight = 2
        elif source_type == 'deal':
            uid = safe_int(row.get('actor_id')) or safe_int(fallback_id)
        _vote_operator(votes, uid, weight, when)

    chosen_id = safe_int(fallback_id)
    if votes:
        chosen_id = sorted(
            votes.items(),
            key=lambda item: (
                -int(item[1].get('score') or 0),
                -(item[1].get('latest_at').timestamp() if item[1].get('latest_at') else 0),
                int(item[0]),
            ),
        )[0][0]

    if chosen_id:
        name, position = resolve_user_name_position(chosen_id, fallback_name, fallback_position)
        return chosen_id, name, position
    return None, '<не доступно>', '<не доступно>'


def resolve_operator_for_deal(
    deal_id: int | None,
    fallback_id: int | None = None,
    fallback_name: str = '',
    fallback_position: str = '',
    event_rows: list[dict] | None = None,
) -> tuple[int | None, str, str]:
    did = safe_int(deal_id)
    if event_rows is None and did:
        try:
            event_rows = get_deal_events_for_export(did)
        except Exception:
            event_rows = []
    if event_rows:
        return infer_operator_identity_from_event_rows(
            event_rows,
            fallback_id=fallback_id,
            fallback_name=fallback_name,
            fallback_position=fallback_position,
        )
    return infer_operator_identity(
        activities=[],
        comments=[],
        fallback_id=fallback_id,
        fallback_name=fallback_name,
        fallback_position=fallback_position,
    )


def classify_call_activity(activity: dict) -> dict:
    raw = activity if isinstance(activity, dict) else {}
    direction = str(raw.get('DIRECTION') or '')
    start_dt = parse_ts(raw.get('START_TIME'))
    end_dt = parse_ts(raw.get('END_TIME')) or start_dt
    duration_sec = 0
    if isinstance(start_dt, datetime) and isinstance(end_dt, datetime):
        duration_sec = max(0, int((end_dt - start_dt).total_seconds()))
    settings = raw.get('SETTINGS') if isinstance(raw.get('SETTINGS'), dict) else {}
    is_missed = bool(settings.get('MISSED_CALL'))
    is_outgoing = direction == '2'
    is_incoming = direction == '1'
    if is_missed:
        call_status = 'missed'
    elif is_outgoing and duration_sec <= 2:
        call_status = 'ndz'
    else:
        call_status = 'handled'
    return {
        'direction': direction,
        'is_outgoing': is_outgoing,
        'is_incoming': is_incoming,
        'duration_sec': duration_sec,
        'status': call_status,
        'start_dt': start_dt,
        'end_dt': end_dt,
    }


def summarize_call_participants(activities: list[dict]) -> dict:
    participants = {}
    handled_calls = []
    for act in activities or []:
        if str(act.get('TYPE_ID') or '') != '2':
            continue
        uid = safe_int(act.get('AUTHOR_ID')) or safe_int(act.get('RESPONSIBLE_ID'))
        if not uid:
            continue
        call_info = classify_call_activity(act)
        name, position = resolve_user_name_position(uid, '', '')
        item = participants.get(uid)
        if not item:
            item = {
                'user_id': uid,
                'user_name': name,
                'user_position': position,
                'handled_calls': 0,
                'missed_calls': 0,
                'ndz_calls': 0,
                'total_duration_sec': 0,
                'latest_call_at': None,
            }
            participants[uid] = item
        if call_info['status'] == 'handled':
            item['handled_calls'] += 1
            item['total_duration_sec'] += int(call_info['duration_sec'])
            handled_calls.append({
                'user_id': uid,
                'user_name': name,
                'user_position': position,
                'duration_sec': int(call_info['duration_sec']),
                'event_at': call_info['start_dt'],
                'activity_id': safe_int(act.get('ID')),
            })
        elif call_info['status'] == 'missed':
            item['missed_calls'] += 1
        else:
            item['ndz_calls'] += 1
        if call_info['start_dt'] and (item['latest_call_at'] is None or call_info['start_dt'] > item['latest_call_at']):
            item['latest_call_at'] = call_info['start_dt']

    ordered = sorted(
        participants.values(),
        key=lambda p: (
            -int(p['handled_calls']),
            -int(p['total_duration_sec']),
            -int(p['ndz_calls']),
            -(p['latest_call_at'].timestamp() if p['latest_call_at'] else 0),
            int(p['user_id']),
        ),
    )
    primary = None
    if handled_calls:
        primary = sorted(
            handled_calls,
            key=lambda c: (
                -int(c['duration_sec']),
                -(c['event_at'].timestamp() if c['event_at'] else 0),
                int(c['user_id']),
            ),
        )[0]
    elif ordered:
        top = ordered[0]
        primary = {
            'user_id': top['user_id'],
            'user_name': top['user_name'],
            'user_position': top['user_position'],
            'duration_sec': 0,
            'event_at': top['latest_call_at'],
            'activity_id': None,
        }

    for item in ordered:
        if isinstance(item.get('latest_call_at'), datetime):
            item['latest_call_at'] = item['latest_call_at'].astimezone(timezone.utc).isoformat()
    if primary and isinstance(primary.get('event_at'), datetime):
        primary['event_at'] = primary['event_at'].astimezone(timezone.utc).isoformat()

    return {
        'primary_call_operator': primary,
        'participants': ordered,
    }


def load_qa_system_prompt() -> str:
    global SYSTEM_PROMPT_CACHE
    if SYSTEM_PROMPT_CACHE is not None:
        return SYSTEM_PROMPT_CACHE
    try:
        txt = QA_SYSTEM_PROMPT_PATH.read_text(encoding='utf-8').strip()
        if not txt:
            raise RuntimeError('empty_system_prompt')
        SYSTEM_PROMPT_CACHE = txt
        return txt
    except Exception:
        # Safe fallback to keep service operational if file is missing.
        SYSTEM_PROMPT_CACHE = (
            "Ты QA-аудитор звонков отдела продаж. "
            "Оценивай ТОЛЬКО по предоставленным модулям и только по тексту звонка. "
            "Верни ответ СТРОГО как один JSON-объект. "
            "Запрещено: markdown, кодовые блоки, комментарии, пояснения до/после JSON."
        )
        return SYSTEM_PROMPT_CACHE


def load_qa_user_prompt_template() -> str:
    global USER_PROMPT_TEMPLATE_CACHE
    if USER_PROMPT_TEMPLATE_CACHE is not None:
        return USER_PROMPT_TEMPLATE_CACHE
    try:
        txt = QA_USER_PROMPT_PATH.read_text(encoding='utf-8').strip()
        if not txt:
            raise RuntimeError('empty_user_prompt_template')
        USER_PROMPT_TEMPLATE_CACHE = txt
        return txt
    except Exception:
        USER_PROMPT_TEMPLATE_CACHE = (
            "Верни строго валидный JSON по формату qa_call_analysis_v1.\n"
            "Export ID: __EXPORT_ID__\n"
            "Standard Version ID: __STANDARD_VERSION_ID__\n"
        )
        return USER_PROMPT_TEMPLATE_CACHE


def parse_body_json(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get('Content-Length', '0'))
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    return json.loads(raw.decode('utf-8'))


def safe_int(value):
    if value is None or value == '':
        return None
    try:
        return int(value)
    except Exception:
        return None


def parse_ts(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace('Z', '+00:00'))
        except Exception:
            pass
        for fmt in ('%d.%m.%Y %H:%M:%S', '%d.%m.%Y %H:%M'):
            try:
                dt = datetime.strptime(value, fmt)
                return dt.replace(tzinfo=timezone.utc)
            except Exception:
                pass
    return None


def bitrix_token_expires_at(*, expires=None, expires_in=None, expires_at=None) -> int:
    absolute = safe_int(expires_at)
    if absolute:
        return absolute
    ttl = safe_int(expires_in)
    if ttl and ttl > 0:
        return now_ts() + ttl
    raw_expires = safe_int(expires)
    if not raw_expires:
        return 0
    if raw_expires > 1_000_000_000:
        return raw_expires
    return now_ts() + raw_expires


def fmt_ts(dt):
    if not dt:
        return 'unknown-time'
    return dt.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')


def sanitize_url_for_storage(url: str) -> str:
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    if 'auth' in params:
        params['auth'] = ['<redacted>']
    query = urlencode({k: v[0] if len(v) == 1 else v for k, v in params.items()}, doseq=True)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}" + (f"?{query}" if query else "")


def to_jsonable(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: to_jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [to_jsonable(v) for v in value]
    if isinstance(value, tuple):
        return [to_jsonable(v) for v in value]
    return value


def parse_percent(value: str | None):
    if not value:
        return None
    s = str(value).strip()
    if not s:
        return None
    s = s.replace('%', '').replace(' ', '').replace(',', '.')
    try:
        return float(Decimal(s).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError):
        return None


def quant2(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))


def generate_public_id() -> str:
    return secrets.token_urlsafe(9).replace('-', 'a').replace('_', 'b')


# Claude (LLM) transport — call_claude_json + JSON extractor — lives in oko_llm.py.
from oko_llm import call_claude_json, extract_json_object


def clean_comment_text(value: str) -> str:
    if not value:
        return ''
    txt = unescape(value)
    txt = re.sub(r'\[img\][^\[]*\[/img\]', '', txt, flags=re.IGNORECASE)
    txt = re.sub(r'\[/?img[^\]]*\]', '', txt, flags=re.IGNORECASE)
    txt = re.sub(r'\[/?url[^\]]*\]', '', txt, flags=re.IGNORECASE)
    txt = txt.replace('&nbsp;', ' ')
    return txt.strip()


def extract_urls_from_comment(value: str) -> list[str]:
    if not value:
        return []
    cleaned = re.sub(r'\[img\][^\[]*\[/img\]', '', value, flags=re.IGNORECASE)
    urls = []
    urls.extend(BBCODE_URL_RE.findall(cleaned))
    urls.extend(URL_RE.findall(cleaned))
    dedup = []
    seen = set()
    for raw in urls:
        url = raw.strip()
        if not url:
            continue
        low = url.lower()
        if 'static.wazzup24.com/images/bitrix/whatsapp.png' in low:
            continue
        if url in seen:
            continue
        seen.add(url)
        dedup.append(url)
    return dedup


def is_terminal_transcription_status(status: str | None) -> bool:
    if not status:
        return False
    s = status.lower()
    return s in ('completed', 'done', 'success', 'failed', 'error', 'cancelled', 'canceled')


def is_success_transcription_status(status: str | None) -> bool:
    if not status:
        return False
    return status.lower() in ('completed', 'done', 'success')


def speaker_label(speaker_id: str | None) -> str:
    if not speaker_id:
        return 'Спикер ?'
    m = SPEAKER_DIGIT_RE.search(str(speaker_id))
    if m:
        return f"Спикер {m.group(1)}"
    return f"Спикер {speaker_id}"


def format_transcript_for_txt(transcript_text: str | None, response_payload):
    words = []
    if isinstance(response_payload, dict):
        w = response_payload.get('words')
        if isinstance(w, list):
            words = w
    if not words:
        return (transcript_text or '').strip()

    speaker_set = set()
    for token in words:
        if isinstance(token, dict) and token.get('speaker_id'):
            speaker_set.add(str(token.get('speaker_id')))
    if len(speaker_set) <= 1:
        return (transcript_text or '').strip()

    lines = []
    cur_speaker = None
    buf = []
    for token in words:
        if not isinstance(token, dict):
            continue
        txt = token.get('text')
        if txt is None:
            continue
        txt = str(txt)
        sp = str(token.get('speaker_id') or 'unknown')
        if cur_speaker is None:
            cur_speaker = sp
        if sp != cur_speaker:
            utterance = ''.join(buf).strip()
            if utterance:
                lines.append(f"{speaker_label(cur_speaker)}: {utterance}")
            cur_speaker = sp
            buf = []
        buf.append(txt)
    tail = ''.join(buf).strip()
    if tail:
        lines.append(f"{speaker_label(cur_speaker)}: {tail}")
    if not lines:
        return (transcript_text or '').strip()
    return '\n'.join(lines).strip()


def require_admin_token_from_query(params: dict) -> tuple[bool, str]:
    if not ADMIN_TOKEN:
        return True, ''
    provided = (params.get('admin_token') or [''])[0]
    if provided != ADMIN_TOKEN:
        return False, 'forbidden'
    return True, ''


def require_admin_token_from_body(data: dict) -> tuple[bool, str]:
    if not ADMIN_TOKEN:
        return True, ''
    if data.get('admin_token') != ADMIN_TOKEN:
        return False, 'forbidden'
    return True, ''


# Database access (pool + query helpers) now lives in oko_db.py.
from oko_db import db_conn, db_tx, db_one, db_all, db_exec, init_db, close_db_pool


# ---------------------------------------------------------------------------
# User auth + session helpers
# Основной продуктовый сценарий: passwordless вход по коду из письма.
# Password/reset helpers ниже пока оставлены как совместимый технический хвост.
# ---------------------------------------------------------------------------

def normalize_login(value: str) -> str:
    return re.sub(r'[^a-z0-9._@-]+', '', str(value or '').strip().lower())


def normalize_email(value: str) -> str:
    return str(value or '').strip().lower()


def is_valid_email(value: str) -> bool:
    raw = normalize_email(value)
    return bool(re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', raw))


def hash_password(password: str, *, iterations: int = 390000) -> str:
    secret = str(password or '')
    if not secret:
        raise ValueError('password_required')
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac('sha256', secret.encode('utf-8'), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    raw = str(password_hash or '').strip()
    if not raw:
        return False
    try:
        algorithm, iterations_raw, salt_hex, digest_hex = raw.split('$', 3)
        if algorithm != 'pbkdf2_sha256':
            return False
        iterations = int(iterations_raw)
        expected = bytes.fromhex(digest_hex)
        salt = bytes.fromhex(salt_hex)
    except Exception:
        return False
    actual = hashlib.pbkdf2_hmac('sha256', str(password or '').encode('utf-8'), salt, iterations)
    return hmac.compare_digest(actual, expected)


def get_user_by_email(email: str) -> dict | None:
    normalized = normalize_email(email)
    if not normalized:
        return None
    row = db_one("SELECT * FROM users WHERE email = %s AND is_active = TRUE", (normalized,))
    return dict(row) if row else None
def create_local_user_email_only(name: str, email: str, *, username: str = '') -> dict:
    normalized_name = str(name or '').strip()
    normalized_email = normalize_email(email)
    if not normalized_name or not normalized_email:
        raise ValueError('missing_fields')
    if not is_valid_email(normalized_email):
        raise ValueError('invalid_email')
    if get_user_by_email(normalized_email):
        raise ValueError('email_taken')
    row = db_one(
        """
        INSERT INTO users (email, first_name, username, is_active, updated_at)
        VALUES (%s, %s, %s, TRUE, NOW())
        RETURNING *
        """,
        (normalized_email, normalized_name, str(username or '').strip()),
    )
    return dict(row)


def create_local_user(name: str, password: str, email: str, *, username: str = '') -> dict:
    normalized_name = str(name or '').strip()
    normalized_email = normalize_email(email)
    if not normalized_name or not normalized_email:
        raise ValueError('missing_fields')
    if not is_valid_email(normalized_email):
        raise ValueError('invalid_email')
    if get_user_by_email(normalized_email):
        raise ValueError('email_taken')
    password_hash = hash_password(password)
    row = db_one(
        """
        INSERT INTO users (email, password_hash, first_name, username, is_active, updated_at)
        VALUES (%s, %s, %s, %s, TRUE, NOW())
        RETURNING *
        """,
        (normalized_email, password_hash, normalized_name, str(username or '').strip()),
    )
    return dict(row)


def hash_auth_email_code(token: str, code: str) -> str:
    raw = f"{str(token or '').strip()}:{str(code or '').strip()}".encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def generate_auth_email_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def create_auth_email_code(email: str, *, purpose: str, user_id: int | None = None, first_name: str = '', install_token: str = '', next_path: str = '') -> tuple[str, str]:
    normalized_email = normalize_email(email)
    token = secrets.token_urlsafe(24)
    code = generate_auth_email_code()
    code_hash = hash_auth_email_code(token, code)
    db_exec(
        """
        INSERT INTO auth_email_codes (token, user_id, email, first_name, purpose, code_hash, install_token, next_path, expires_at)
        VALUES (%s, %s, %s, %s, %s, %s, NULLIF(%s, ''), NULLIF(%s, ''), NOW() + %s * INTERVAL '1 second')
        """,
        (
            token,
            int(user_id) if user_id else None,
            normalized_email,
            str(first_name or '').strip(),
            str(purpose or 'login').strip() or 'login',
            code_hash,
            str(install_token or '').strip(),
            str(next_path or '').strip(),
            AUTH_EMAIL_CODE_TTL_SEC,
        ),
    )
    return token, code


def get_auth_email_code_record(token: str) -> dict | None:
    row = db_one(
        """
        SELECT *
        FROM auth_email_codes
        WHERE token = %s
          AND used_at IS NULL
          AND expires_at > NOW()
        ORDER BY id DESC
        LIMIT 1
        """,
        (str(token or '').strip(),),
    )
    return dict(row) if row else None


def mark_auth_email_code_used(token: str) -> None:
    db_exec("UPDATE auth_email_codes SET used_at = NOW() WHERE token = %s", (str(token or '').strip(),))
def update_user_password(user_id: int, password: str):
    db_exec(
        "UPDATE users SET password_hash = %s, updated_at = NOW() WHERE id = %s",
        (hash_password(password), int(user_id)),
    )


def create_password_reset_token(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    db_exec(
        """
        INSERT INTO password_reset_tokens (token, user_id, expires_at)
        VALUES (%s, %s, NOW() + %s * INTERVAL '1 second')
        """,
        (token, int(user_id), PASSWORD_RESET_TTL_SEC),
    )
    return token


def get_password_reset_token_record(token: str) -> dict | None:
    row = db_one(
        """
        SELECT prt.*, u.email, u.login
        FROM password_reset_tokens prt
        JOIN users u ON u.id = prt.user_id
        WHERE prt.token = %s AND prt.used_at IS NULL AND prt.expires_at > NOW() AND u.is_active = TRUE
        """,
        (str(token or '').strip(),),
    )
    return dict(row) if row else None


def mark_password_reset_token_used(token: str):
    db_exec("UPDATE password_reset_tokens SET used_at = NOW() WHERE token = %s", (str(token or '').strip(),))


def invalidate_password_reset_tokens_for_user(user_id: int):
    db_exec("UPDATE password_reset_tokens SET used_at = NOW() WHERE user_id = %s AND used_at IS NULL", (int(user_id),))


def send_mailtrap_email(to_email: str, subject: str, text: str, html_body: str = '', category: str = 'auth') -> dict:
    if not MAILTRAP_API_TOKEN or not MAILTRAP_FROM_EMAIL:
        raise RuntimeError('mailtrap_not_configured')
    payload = {
        'from': {'email': MAILTRAP_FROM_EMAIL, 'name': MAILTRAP_FROM_NAME},
        'to': [{'email': normalize_email(to_email)}],
        'subject': str(subject or '').strip(),
        'text': str(text or '').strip(),
        'category': str(category or 'auth').strip() or 'auth',
    }
    if html_body:
        payload['html'] = html_body
    resp = requests.post(
        f"{MAILTRAP_API_BASE_URL}/api/send",
        headers={
            'Authorization': f'Bearer {MAILTRAP_API_TOKEN}',
            'Content-Type': 'application/json',
        },
        json=payload,
        timeout=20,
    )
    parsed = {}
    try:
        parsed = resp.json()
    except Exception:
        parsed = {'raw': resp.text[:1000]}
    if resp.status_code >= 400 or not parsed.get('success', False):
        raise RuntimeError(json.dumps({'status': resp.status_code, 'response': parsed}, ensure_ascii=False))
    return parsed


def send_password_reset_email(user: dict, token: str, lang: str = 'ru') -> dict:
    email = normalize_email(user.get('email') or '')
    if not email:
        raise RuntimeError('missing_user_email')
    reset_url = f"{APP_BASE_URL}/reset-password?{urlencode({'token': token, 'lang': lang})}"
    subject = 'Сброс пароля — Oko Systems'
    text = (
        "Вы запросили сброс пароля для Oko Systems.\n\n"
        f"Перейдите по ссылке, чтобы задать новый пароль:\n{reset_url}\n\n"
        f"Ссылка действует {max(1, PASSWORD_RESET_TTL_SEC // 60)} минут.\n"
        "Если вы не запрашивали сброс пароля, просто проигнорируйте это письмо."
    )
    html_body = (
        "<p>Вы запросили сброс пароля для <strong>Oko Systems</strong>.</p>"
        f"<p><a href=\"{html_escape(reset_url)}\">Открыть страницу сброса пароля</a></p>"
        f"<p>Ссылка действует {max(1, PASSWORD_RESET_TTL_SEC // 60)} минут.</p>"
        "<p>Если вы не запрашивали сброс пароля, просто проигнорируйте это письмо.</p>"
    )
    return send_mailtrap_email(email, subject, text, html_body=html_body, category='password-reset')


def send_auth_code_email(email: str, code: str, lang: str = 'ru', purpose: str = 'login') -> dict:
    normalized_email = normalize_email(email)
    if not normalized_email:
        raise RuntimeError('missing_user_email')
    purpose_label = 'входа' if str(purpose or 'login') == 'login' else 'подтверждения'
    subject = f'Код {purpose_label} — Oko Systems'
    minutes = max(1, AUTH_EMAIL_CODE_TTL_SEC // 60)
    text = (
        f"Ваш код для Oko Systems: {code}\n\n"
        f"Код действует {minutes} минут.\n"
        "Если вы не запрашивали код, просто проигнорируйте это письмо."
    )
    html_body = (
        "<p>Ваш код для <strong>Oko Systems</strong>:</p>"
        f"<p style=\"font-size:28px;font-weight:800;letter-spacing:.18em\">{html_escape(code)}</p>"
        f"<p>Код действует {minutes} минут.</p>"
        "<p>Если вы не запрашивали код, просто проигнорируйте это письмо.</p>"
    )
    return send_mailtrap_email(normalized_email, subject, text, html_body=html_body, category='auth-code')


def send_marketplace_contact_email(name: str, email: str, company: str, message: str) -> dict:
    sender_name = str(name or '').strip()
    sender_email = normalize_email(email)
    company_name = str(company or '').strip()
    body_message = str(message or '').strip()
    if not sender_name or not sender_email or not body_message:
        raise ValueError('missing_fields')
    if not is_valid_email(sender_email):
        raise ValueError('invalid_email')
    subject = f"Запрос с лендинга Oko Systems от {sender_name}"
    company_line = company_name or 'не указана'
    text = (
        "Новая заявка с лендинга приложения Oko Systems.\n\n"
        f"Имя: {sender_name}\n"
        f"Email: {sender_email}\n"
        f"Компания / портал: {company_line}\n\n"
        "Сообщение:\n"
        f"{body_message}\n"
    )
    html_body = (
        "<p>Новая заявка с лендинга приложения <strong>Oko Systems</strong>.</p>"
        f"<p><strong>Имя:</strong> {html_escape(sender_name)}<br>"
        f"<strong>Email:</strong> {html_escape(sender_email)}<br>"
        f"<strong>Компания / портал:</strong> {html_escape(company_line)}</p>"
        f"<p><strong>Сообщение:</strong><br>{html_escape(body_message).replace(chr(10), '<br>')}</p>"
    )
    return send_mailtrap_email('support@salmetov.fun', subject, text, html_body=html_body, category='marketplace-contact')


# ---------------------------------------------------------------------------
# Sessions (DB-backed user sessions)
# ---------------------------------------------------------------------------

def create_tg_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    db_exec(
        "INSERT INTO sessions (session_token, user_id, expires_at) VALUES (%s, %s, NOW() + %s * INTERVAL '1 second')",
        (token, user_id, TG_SESSION_MAX_AGE_SEC),
    )
    return token


def get_tg_session(handler: BaseHTTPRequestHandler) -> dict | None:
    token = get_cookie_value(handler, TG_SESSION_COOKIE)
    if not token:
        return None
    row = db_one(
        """
        SELECT s.id, s.user_id, s.expires_at,
               u.login, u.email, u.first_name, u.last_name, u.username
        FROM sessions s
        JOIN users u ON u.id = s.user_id
        WHERE s.session_token = %s AND s.expires_at > NOW() AND u.is_active = TRUE
        """,
        (token,),
    )
    return dict(row) if row else None
def invalidate_tg_session(handler: BaseHTTPRequestHandler):
    token = get_cookie_value(handler, TG_SESSION_COOKIE)
    if token:
        db_exec('DELETE FROM sessions WHERE session_token = %s', (token,))


def get_user_bitrix_connections(user_id: int) -> list[dict]:
    rows = db_all(
        """
        SELECT *
        FROM user_bitrix_connections
        WHERE user_id = %s
        ORDER BY is_primary DESC, created_at ASC, id ASC
        """,
        (user_id,),
    )
    return [dict(row) for row in rows]


def get_primary_bitrix_connection(user_id: int) -> dict | None:
    row = db_one(
        """
        SELECT *
        FROM user_bitrix_connections
        WHERE user_id = %s
        ORDER BY is_primary DESC, created_at ASC, id ASC
        LIMIT 1
        """,
        (user_id,),
    )
    return dict(row) if row else None


def get_bitrix_connection_by_member_id_or_domain(member_id: str = '', domain: str = '') -> dict | None:
    member_value = str(member_id or '').strip()
    domain_value = str(domain or '').strip().casefold()
    if member_value:
        row = db_one("SELECT * FROM user_bitrix_connections WHERE member_id = %s ORDER BY id ASC LIMIT 1", (member_value,))
        if row:
            return dict(row)
    if domain_value:
        row = db_one("SELECT * FROM user_bitrix_connections WHERE bitrix_domain = %s ORDER BY id ASC LIMIT 1", (domain_value,))
        if row:
            return dict(row)
    return None


def ensure_user_bitrix_connection(user_id: int, title: str = '') -> dict:
    existing = get_primary_bitrix_connection(user_id)
    if existing:
        return existing
    row = db_one(
        """
        INSERT INTO user_bitrix_connections (user_id, title, status, is_primary, updated_at)
        VALUES (%s, %s, 'pending', TRUE, NOW())
        RETURNING *
        """,
        (user_id, str(title or '').strip() or 'Bitrix24'),
    )
    return dict(row)



def create_bitrix_connect_token_for_user(user_id: int) -> str:
    ensure_user_bitrix_connection(user_id)
    token = secrets.token_urlsafe(32)
    db_exec(
        "INSERT INTO bitrix_connect_tokens (token, user_id, expires_at) VALUES (%s, %s, NOW() + INTERVAL '24 hours')",
        (token, user_id),
    )
    return token


def auth_user_id(user: dict) -> int:
    return safe_int(user.get('user_id')) or safe_int(user.get('id'))


def get_post_login_redirect_path(user: dict) -> str:
    user_id = auth_user_id(user)
    if not user_id:
        return '/login'
    return '/dash'


def get_connect_token_record(token: str) -> dict | None:
    row = db_one(
        'SELECT * FROM bitrix_connect_tokens WHERE token = %s AND expires_at > NOW() AND used_at IS NULL',
        (token,),
    )
    return dict(row) if row else None


def mark_connect_token_used(token: str):
    db_exec('UPDATE bitrix_connect_tokens SET used_at = NOW() WHERE token = %s', (token,))


def create_bitrix_install_event(member_id: str, domain: str, access_token: str, refresh_token: str, expires_at: int, scope: str) -> str:
    row = db_one(
        """
        INSERT INTO bitrix_install_events (member_id, domain, access_token, refresh_token, expires_at, scope)
        VALUES (%s, %s, %s, %s, CASE WHEN %s > 0 THEN to_timestamp(%s) ELSE NULL END, %s)
        RETURNING token
        """,
        (member_id, domain, access_token, refresh_token, expires_at, expires_at, scope),
    )
    return str(row['token'])


def get_bitrix_install_event(token: str) -> dict | None:
    row = db_one(
        """
        SELECT *
        FROM bitrix_install_events
        WHERE token = %s
          AND used_at IS NULL
          AND (expires_at IS NULL OR expires_at > NOW())
        ORDER BY id DESC
        LIMIT 1
        """,
        (token,),
    )
    return dict(row) if row else None


def mark_bitrix_install_event_used(token: str) -> None:
    db_exec('UPDATE bitrix_install_events SET used_at = NOW() WHERE token = %s', (token,))


def finalize_bitrix_install_event(auth_session: dict, install_event: dict) -> dict:
    user_id = auth_user_id(auth_session)
    member_id = str(install_event.get('member_id') or '').strip()
    domain = str(install_event.get('domain') or '').strip()
    access_token = str(install_event.get('access_token') or '').strip()
    refresh_token = str(install_event.get('refresh_token') or '').strip()
    expires_at = parse_ts(install_event.get('expires_at'))
    expires_at_ts = int(expires_at.timestamp()) if isinstance(expires_at, datetime) else 0
    scope = str(install_event.get('scope') or '').strip()
    if not user_id:
        raise RuntimeError('install_target_user_not_found')
    connection = activate_user_bitrix_connection(user_id, member_id, domain, access_token, refresh_token, expires_at_ts, scope)
    mark_bitrix_install_event_used(str(install_event['token']))
    return connection


def activate_user_bitrix_connection(user_id: int, member_id: str, domain: str, access_token: str, refresh_token: str, expires_at: int, scope: str) -> dict:
    uid = safe_int(user_id)
    if not uid:
        raise RuntimeError('missing_user_id')
    normalized_domain = str(domain or '').strip().casefold()
    normalized_member_id = str(member_id or '').strip()
    connection_title = normalized_domain or (f"Bitrix {normalized_member_id[:8]}" if normalized_member_id else 'Bitrix24')
    existing = get_bitrix_connection_by_member_id_or_domain(member_id=normalized_member_id, domain=normalized_domain)
    if existing and safe_int(existing.get('user_id')) != uid:
        raise RuntimeError('bitrix_connection_belongs_to_other_user')
    if existing is None:
        existing = get_primary_bitrix_connection(uid)
    if existing:
        row = db_one(
            """
            UPDATE user_bitrix_connections
            SET member_id = %s,
                bitrix_domain = %s,
                title = %s,
                status = 'active',
                is_primary = TRUE,
                bitrix_access_token = %s,
                bitrix_refresh_token = %s,
                bitrix_expires_at = CASE WHEN %s > 0 THEN to_timestamp(%s) ELSE NULL END,
                bitrix_scope = %s,
                updated_at = NOW()
            WHERE id = %s
            RETURNING *
            """,
            (normalized_member_id, normalized_domain, connection_title, access_token, refresh_token, expires_at, expires_at, scope, int(existing['id'])),
        )
    else:
        row = db_one(
            """
            INSERT INTO user_bitrix_connections (
              user_id, member_id, bitrix_domain, title, status, is_primary,
              bitrix_access_token, bitrix_refresh_token, bitrix_expires_at, bitrix_scope, updated_at
            )
            VALUES (%s, %s, %s, %s, 'active', TRUE, %s, %s, CASE WHEN %s > 0 THEN to_timestamp(%s) ELSE NULL END, %s, NOW())
            RETURNING *
            """,
            (uid, normalized_member_id, normalized_domain, connection_title, access_token, refresh_token, expires_at, expires_at, scope),
        )
    db_exec("UPDATE user_bitrix_connections SET is_primary = FALSE WHERE user_id = %s AND id <> %s", (uid, int(row['id'])))
    return dict(row)


def disconnect_user_bitrix_connection(user_id: int, connection_id: int | None = None) -> None:
    uid = safe_int(user_id)
    cid = safe_int(connection_id)
    if not uid:
        raise RuntimeError('missing_user_id')
    if not cid:
        current = get_primary_bitrix_connection(uid)
        cid = safe_int(current.get('id')) if current else None
    if not cid:
        return
    db_exec(
        """
        UPDATE user_bitrix_connections
        SET bitrix_access_token = NULL,
            bitrix_refresh_token = NULL,
            bitrix_expires_at = NULL,
            bitrix_scope = NULL,
            member_id = NULL,
            bitrix_domain = NULL,
            status = 'pending',
            updated_at = NOW()
        WHERE id = %s AND user_id = %s
        """,
        (cid, uid),
    )


def delete_user_bitrix_connection(user_id: int, connection_id: int) -> None:
    uid = safe_int(user_id)
    cid = safe_int(connection_id)
    if not uid or not cid:
        raise RuntimeError('missing_ids')
    db_exec(
        "DELETE FROM user_bitrix_connections WHERE id = %s AND user_id = %s",
        (cid, uid),
    )


def set_primary_bitrix_connection(user_id: int, connection_id: int) -> dict | None:
    uid = safe_int(user_id)
    cid = safe_int(connection_id)
    if not uid or not cid:
        return None
    row = db_one(
        """
        SELECT *
        FROM user_bitrix_connections
        WHERE id = %s AND user_id = %s
        LIMIT 1
        """,
        (cid, uid),
    )
    if not row:
        return None
    db_exec("UPDATE user_bitrix_connections SET is_primary = FALSE WHERE user_id = %s", (uid,))
    updated = db_one(
        """
        UPDATE user_bitrix_connections
        SET is_primary = TRUE,
            updated_at = NOW()
        WHERE id = %s AND user_id = %s
        RETURNING *
        """,
        (cid, uid),
    )
    return dict(updated) if updated else None


def get_user_bitrix_context(user_id: int, force_refresh: bool = False, connection_id: int | None = None) -> dict:
    uid = safe_int(user_id)
    cid = safe_int(connection_id)
    if not uid:
        raise RuntimeError('missing_user_id')
    if cid:
        connection = db_one(
            """
            SELECT *
            FROM user_bitrix_connections
            WHERE id = %s AND user_id = %s
            """,
            (cid, uid),
        )
    else:
        connection = get_primary_bitrix_connection(uid)
    if not connection:
        raise RuntimeError('bitrix_connection_not_found')
    domain = str(connection.get('bitrix_domain') or '').strip().casefold()
    access_token = str(connection.get('bitrix_access_token') or '').strip()
    refresh_token = str(connection.get('bitrix_refresh_token') or '').strip()
    if not domain:
        raise RuntimeError('missing_bitrix_domain')
    expires_at = parse_ts(connection.get('bitrix_expires_at'))
    expires_at_ts = int(expires_at.timestamp()) if isinstance(expires_at, datetime) else 0
    need_refresh = force_refresh or not access_token or expires_at_ts == 0 or (expires_at_ts - now_ts()) <= AUTO_REFRESH_BUFFER_SEC
    if need_refresh:
        if not refresh_token:
            raise RuntimeError('missing_bitrix_refresh_token')
        # Central endpoint is documented for marketplace OAuth and works for both cloud and self-hosted boxes.
        # Per-portal /oauth/token/ is left as a fallback in case the central endpoint is temporarily unreachable.
        try:
            payload = refresh_tokens_central(refresh_token, MT_CLIENT_ID, MT_CLIENT_SECRET)
        except Exception:
            payload = refresh_tokens_for_domain(refresh_token, domain, MT_CLIENT_ID, MT_CLIENT_SECRET)
        access_token = str(payload.get('access_token') or '').strip()
        refresh_token = str(payload.get('refresh_token') or refresh_token).strip()
        # Central endpoint returns domain='oauth.bitrix.info'; the actual portal host lives in client_endpoint.
        # Per-portal endpoint returns the real portal host directly.
        payload_domain = str(payload.get('domain') or '').strip().casefold()
        client_endpoint = str(payload.get('client_endpoint') or '').strip()
        portal_from_client = normalize_bitrix_domain(client_endpoint) if client_endpoint else ''
        if payload_domain and payload_domain != 'oauth.bitrix.info':
            refreshed_domain = payload_domain
        elif portal_from_client:
            refreshed_domain = portal_from_client
        else:
            refreshed_domain = domain
        if not access_token:
            raise RuntimeError('bitrix_refresh_missing_access_token')
        expires_at_ts = bitrix_token_expires_at(
            expires=payload.get('expires'),
            expires_in=payload.get('expires_in'),
            expires_at=payload.get('expires_at'),
        )
        scope = str(payload.get('scope') or connection.get('bitrix_scope') or '')
        connection = activate_user_bitrix_connection(uid, str(connection.get('member_id') or ''), refreshed_domain, access_token, refresh_token, expires_at_ts, scope)
        domain = str(connection.get('bitrix_domain') or refreshed_domain or '').strip().casefold()
        access_token = str(connection.get('bitrix_access_token') or access_token).strip()
        refresh_token = str(connection.get('bitrix_refresh_token') or refresh_token).strip()
    return {
        'user_id': uid,
        'bitrix_connection_id': int(connection['id']),
        'member_id': str(connection.get('member_id') or '').strip(),
        'domain': domain,
        'access_token': access_token,
        'refresh_token': refresh_token,
        'scope': str(connection.get('bitrix_scope') or '').strip(),
    }


def db_log(source: str, event_type: str, reference_id: str | None, payload: dict, status: str, error_text: str | None = None):
    db_exec(
        """
        INSERT INTO sync_log(source, event_type, reference_id, payload, status, error_text)
        VALUES (%s, %s, %s, %s::jsonb, %s, %s)
        """,
        (source, event_type, reference_id, json.dumps(payload, ensure_ascii=False), status, error_text),
    )


def delete_employee_data(operator_id: int) -> dict:
    oid = safe_int(operator_id)
    if not oid:
        return {'deleted_exports': 0, 'deleted_batches': 0, 'employee_name': ''}
    with db_tx() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, batch_id, responsible_name, selected_operator_name
                FROM analysis_exports
                WHERE responsible_id = %s OR selected_operator_id = %s
                ORDER BY created_at DESC
                """,
                (oid, oid),
            )
            rows = cur.fetchall()
            if not rows:
                conn.rollback()
                return {'deleted_exports': 0, 'deleted_batches': 0, 'employee_name': ''}
            export_ids = [int(row['id']) for row in rows]
            batch_ids = sorted({safe_int(row.get('batch_id')) for row in rows if safe_int(row.get('batch_id'))})
            operator_name = ''
            for row in rows:
                operator_name = str(row.get('responsible_name') or row.get('selected_operator_name') or '').strip()
                if operator_name:
                    break
            cur.execute("DELETE FROM analysis_exports WHERE id = ANY(%s)", (export_ids,))
            deleted_exports = cur.rowcount
            deleted_batches = 0
            if batch_ids:
                cur.execute(
                    """
                    DELETE FROM analysis_batches b
                    WHERE b.id = ANY(%s)
                      AND NOT EXISTS (
                        SELECT 1
                        FROM analysis_exports te
                        WHERE te.batch_id = b.id
                      )
                    """,
                    (batch_ids,),
                )
                deleted_batches = cur.rowcount
        conn.commit()
    return {
        'deleted_exports': deleted_exports,
        'deleted_batches': deleted_batches,
        'employee_name': operator_name,
    }


def get_active_standard_version():
    return db_one("SELECT id, name, status FROM qa_standard_versions WHERE status='active' ORDER BY id DESC LIMIT 1")


def get_user_default_standard_version(user_id: int | None):
    """Return the user's default standard, falling back to the latest active one."""
    uid = safe_int(user_id)
    if uid:
        row = db_one(
            """
            SELECT v.id, v.name, v.status
            FROM users u
            JOIN qa_standard_versions v ON v.id = u.default_standard_id
            WHERE u.id = %s AND v.status = 'active'
            """,
            (uid,),
        )
        if row:
            return row
    return get_active_standard_version()


def get_standard_card_fields(standard_id: int | None) -> list[dict]:
    sid = safe_int(standard_id)
    if not sid:
        return []
    row = db_one("SELECT card_fields_json FROM qa_standard_versions WHERE id = %s", (sid,))
    data = (row or {}).get('card_fields_json')
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:
            return []
    if not isinstance(data, list):
        return []
    return [f for f in data if isinstance(f, dict)]


def save_standard_card_fields(standard_id: int, fields: list[dict]) -> dict:
    sid = safe_int(standard_id)
    if not sid:
        raise RuntimeError('standard_required')
    if not isinstance(fields, list):
        raise RuntimeError('fields_must_be_list')
    cleaned: list[dict] = []
    seen = set()
    for f in fields:
        if not isinstance(f, dict):
            continue
        field_code = str(f.get('field_code') or '').strip()
        if not field_code:
            continue
        entity_type = str(f.get('entity_type') or 'deal').strip().lower() or 'deal'
        if entity_type not in ('deal', 'lead'):
            entity_type = 'deal'
        key = (entity_type, field_code)
        if key in seen:
            continue
        seen.add(key)
        cleaned.append({
            'label': str(f.get('label') or '').strip() or field_code,
            'entity_type': entity_type,
            'field_code': field_code,
        })
    db_exec(
        "UPDATE qa_standard_versions SET card_fields_json = %s::jsonb WHERE id = %s",
        (json.dumps(cleaned, ensure_ascii=False), sid),
    )
    return {'id': sid, 'fields': cleaned}


def set_user_default_standard(user_id: int, standard_id: int) -> dict:
    uid = safe_int(user_id)
    sid = safe_int(standard_id)
    if not uid:
        raise RuntimeError('user_required')
    if not sid:
        raise RuntimeError('standard_required')
    version = db_one("SELECT id, status FROM qa_standard_versions WHERE id = %s", (sid,))
    if not version:
        raise RuntimeError('standard_not_found')
    if str(version.get('status') or '') != 'active':
        raise RuntimeError('standard_not_active')
    db_exec("UPDATE users SET default_standard_id = %s, updated_at = NOW() WHERE id = %s", (sid, uid))
    return {'user_id': uid, 'default_standard_id': sid}


def _parse_fixed_standard_csv(path: Path):
    rows = []
    with path.open('r', encoding='utf-8', newline='') as f:
        rows = list(csv.reader(f))
    header_idx = None
    for i, row in enumerate(rows):
        if len(row) >= 2 and (row[0] or '').strip() == 'Блок' and (row[1] or '').strip() == 'Модули':
            header_idx = i
            break
    if header_idx is None:
        raise RuntimeError('standard_csv_header_not_found')

    block_sort = 0
    module_sort = 0
    blocks = []
    modules = []
    block_seen = {}
    current_block_name = None
    current_block_weight = None

    for row in rows[header_idx + 1:]:
        cols = list(row) + [''] * (9 - len(row))
        c0 = (cols[0] or '').strip()
        c1 = (cols[1] or '').strip()
        c2 = (cols[2] or '').strip()
        c3 = (cols[3] or '').strip()
        c4 = (cols[4] or '').strip()
        c5 = (cols[5] or '').strip()

        if c0.startswith('ИИ Рекомендации') or c0.startswith('Текст рекомендаций'):
            break
        if c3 == '100%' or c4.startswith('Итог'):
            break
        if not c0 and not c1 and not c2 and not c3 and not c4 and not c5:
            continue
        if c1 == '':
            continue

        if c0:
            current_block_name = c0
            current_block_weight = parse_percent(c3) if c3 else current_block_weight
            if current_block_name not in block_seen:
                block_sort += 1
                bw = current_block_weight if current_block_weight is not None else 0.0
                block_seen[current_block_name] = {'sort_order': block_sort, 'weight': bw}
                blocks.append({'block_name': current_block_name, 'block_weight_percent': bw, 'sort_order': block_sort})
        elif current_block_name is None:
            continue

        module_weight = parse_percent(c4)
        # business override agreed with user for this fixed standard
        if current_block_name == 'Закрытие на встречу онлайн/оффлайн':
            if c1 == 'Предложить клиенту встречу онлайн/оффлайн':
                module_weight = 5.0
            elif c1 == 'Договориться с клиентом о следующем шаге/действии':
                module_weight = 5.0
            elif c1.startswith('Резюмировать общее решение'):
                module_weight = 10.0

        if module_weight is None:
            module_weight = 0.0

        module_sort += 1
        modules.append({
            'block_name': current_block_name,
            'module_name': c1,
            'module_details': c2,
            'module_weight_percent': module_weight,
            'scoring_rules': c5,
            'is_scored': module_weight > 0,
            'sort_order': module_sort,
        })

    if not blocks or not modules:
        raise RuntimeError('standard_csv_empty_after_parse')
    return blocks, modules


def _load_standard_signature(version_id: int):
    blocks = db_all(
        """
        SELECT block_name, block_weight_percent, sort_order
        FROM qa_standard_blocks
        WHERE standard_version_id=%s
        ORDER BY sort_order ASC
        """,
        (version_id,),
    )
    modules = db_all(
        """
        SELECT b.block_name, m.module_name, m.module_details, m.module_weight_percent, m.scoring_rules, m.is_scored, m.sort_order
        FROM qa_standard_modules m
        JOIN qa_standard_blocks b ON b.id = m.block_id
        WHERE m.standard_version_id=%s
        ORDER BY m.sort_order ASC
        """,
        (version_id,),
    )
    normalized_blocks = [
        {
            'block_name': str(b['block_name']),
            'block_weight_percent': quant2(float(b['block_weight_percent'])),
            'sort_order': int(b['sort_order']),
        }
        for b in blocks
    ]
    normalized_modules = [
        {
            'block_name': str(m['block_name']),
            'module_name': str(m['module_name']),
            'module_details': str(m.get('module_details') or ''),
            'module_weight_percent': quant2(float(m['module_weight_percent'])),
            'scoring_rules': str(m.get('scoring_rules') or ''),
            'is_scored': bool(m['is_scored']),
            'sort_order': int(m['sort_order']),
        }
        for m in modules
    ]
    return normalized_blocks, normalized_modules


def _create_standard_version(blocks: list[dict], modules: list[dict], name: str = 'Oko QA fixed standard',
                              source_type: str = 'csv', source_file_name: str | None = None,
                              archive_existing_active: bool = True):
    with db_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        if archive_existing_active:
            cur.execute("UPDATE qa_standard_versions SET status='archived', archived_at=NOW() WHERE status='active'")
        cur.execute(
            """
            INSERT INTO qa_standard_versions(name, source_type, source_file_name, status)
            VALUES (%s, %s, %s, 'active')
            RETURNING id
            """,
            (name, source_type, source_file_name if source_file_name is not None else FIXED_STANDARD_CSV_PATH.name),
        )
        version_id = cur.fetchone()['id']
        block_ids = {}
        for b in blocks:
            cur.execute(
                """
                INSERT INTO qa_standard_blocks(standard_version_id, block_name, block_weight_percent, sort_order)
                VALUES (%s, %s, %s, %s)
                RETURNING id
                """,
                (version_id, b['block_name'], b['block_weight_percent'], b['sort_order']),
            )
            block_ids[b['block_name']] = cur.fetchone()['id']
        for m in modules:
            cur.execute(
                """
                INSERT INTO qa_standard_modules(
                  standard_version_id, block_id, module_name, module_details,
                  module_weight_percent, scoring_rules, is_scored, sort_order
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    version_id,
                    block_ids[m['block_name']],
                    m['module_name'],
                    m['module_details'],
                    m['module_weight_percent'],
                    m['scoring_rules'],
                    m['is_scored'],
                    m['sort_order'],
                ),
            )
    return version_id


def ensure_fixed_standard_seed():
    if not FIXED_STANDARD_CSV_PATH.exists():
        db_log('qa', 'standard_seed', None, {'path': str(FIXED_STANDARD_CSV_PATH)}, 'error', 'fixed_standard_csv_missing')
        return None

    blocks, modules = _parse_fixed_standard_csv(FIXED_STANDARD_CSV_PATH)
    block_sum = quant2(sum(float(b['block_weight_percent']) for b in blocks))
    module_sum = quant2(sum(float(m['module_weight_percent']) for m in modules if m['is_scored']))
    if block_sum != 100.0 or module_sum != 100.0:
        raise RuntimeError(f'standard_weights_invalid:block_sum={block_sum};module_sum={module_sum}')

    active = get_active_standard_version()
    if active:
        cur_blocks, cur_modules = _load_standard_signature(int(active['id']))
        exp_blocks = [
            {'block_name': b['block_name'], 'block_weight_percent': quant2(float(b['block_weight_percent'])), 'sort_order': int(b['sort_order'])}
            for b in blocks
        ]
        exp_modules = [
            {
                'block_name': m['block_name'],
                'module_name': m['module_name'],
                'module_details': str(m.get('module_details') or ''),
                'module_weight_percent': quant2(float(m['module_weight_percent'])),
                'scoring_rules': str(m.get('scoring_rules') or ''),
                'is_scored': bool(m['is_scored']),
                'sort_order': int(m['sort_order']),
            }
            for m in modules
        ]
        if cur_blocks == exp_blocks and cur_modules == exp_modules:
            return int(active['id'])
        version_id = _create_standard_version(blocks, modules, name='Oko QA fixed standard (reseed)')
        db_log('qa', 'standard_reseed', str(version_id), {'path': str(FIXED_STANDARD_CSV_PATH), 'replaced_version_id': active['id']}, 'ok', None)
        return version_id

    version_id = _create_standard_version(blocks, modules)
    db_log('qa', 'standard_seed', str(version_id), {'path': str(FIXED_STANDARD_CSV_PATH)}, 'ok', None)
    return version_id


# Bitrix24 transport (OAuth + rate-limited REST primitives) lives in oko_bitrix.py.
from oko_bitrix import (
    exchange_code_for_tokens_mt,
    refresh_tokens_central,
    refresh_tokens_for_domain,
    bitrix_api,
    bitrix_batch,
    bitrix_list_all,
)


def extract_job_id(payload: dict) -> str | None:
    for key in ('id', 'transcript_id', 'job_id', 'request_id'):
        val = payload.get(key)
        if isinstance(val, (str, int)) and str(val):
            return str(val)
    data = payload.get('data')
    if isinstance(data, dict):
        for key in ('id', 'transcript_id', 'job_id', 'request_id'):
            val = data.get(key)
            if isinstance(val, (str, int)) and str(val):
                return str(val)
    return None


def extract_transcript_text(payload: dict) -> str | None:
    for key in ('text', 'transcript', 'transcript_text'):
        val = payload.get(key)
        if isinstance(val, str) and val:
            return val
    data = payload.get('data')
    if isinstance(data, dict):
        for key in ('text', 'transcript', 'transcript_text'):
            val = data.get(key)
            if isinstance(val, str) and val:
                return val
    return None


def extract_segments(payload: dict):
    for key in ('segments', 'words', 'chunks'):
        val = payload.get(key)
        if isinstance(val, list):
            return val
    data = payload.get('data')
    if isinstance(data, dict):
        for key in ('segments', 'words', 'chunks'):
            val = data.get(key)
            if isinstance(val, list):
                return val
    return []


def _soniox_tokens_to_words(tokens: list) -> list:
    out = []
    for t in tokens or []:
        if not isinstance(t, dict):
            continue
        speaker = t.get('speaker')
        out.append({
            'text': t.get('text', ''),
            'start': (t.get('start_ms') or 0) / 1000.0,
            'end': (t.get('end_ms') or 0) / 1000.0,
            'speaker_id': f"speaker_{speaker}" if speaker is not None else None,
            'language': t.get('language'),
            'type': 'audio_event' if t.get('is_audio_event') else 'word',
            'confidence': t.get('confidence'),
        })
    return out


def _request_with_retries(method: str, url: str, *, retries: int = 3, base_delay: float = 1.5, **kwargs):
    """HTTP_SESSION.{post,get} with exponential backoff + jitter on connection-level errors.
    KZ→AWS-us-east-1 is flaky, this softens transient timeouts. Application-level errors
    (HTTP 4xx/5xx in the response) are NOT retried — the caller decides. The shared session
    has TCP_USER_TIMEOUT set, so zombie connections die at the kernel level too."""
    import random as _rnd
    func = HTTP_SESSION.post if method.upper() == 'POST' else HTTP_SESSION.get
    transient = (
        requests.exceptions.ConnectTimeout,
        requests.exceptions.ReadTimeout,
        requests.exceptions.ConnectionError,
    )
    for attempt in range(retries + 1):
        try:
            return func(url, **kwargs)
        except transient:
            if attempt >= retries:
                raise
            # Jitter avoids thundering-herd retries when many submits hit the same flap together.
            time.sleep(base_delay * (2 ** attempt) + _rnd.uniform(0, 0.7))


def soniox_submit_only(audio_url: str, context_terms: list[str] | None = None) -> dict:
    """Async-friendly submit: POSTs to Soniox, returns the job tid immediately. Does NOT poll
    or fetch the transcript — that's handled by `transcription_poll_worker_loop`."""
    if not SONIOX_API_KEY:
        raise RuntimeError('missing_soniox_api_key')

    headers = {'Authorization': f'Bearer {SONIOX_API_KEY}', 'Content-Type': 'application/json'}
    create_payload: dict = {
        'audio_url': audio_url,
        'model': SONIOX_MODEL,
        'enable_speaker_diarization': True,
        'enable_language_identification': True,
        'language_hints': list(SONIOX_LANGUAGE_HINTS),
    }
    terms = [str(s).strip() for s in (context_terms or []) if s and str(s).strip()]
    if terms:
        create_payload['context'] = '\n'.join(terms[:50])

    # 3 attempts with jitter — same resilience profile as the Claude call. TCP_USER_TIMEOUT
    # caps each attempt at ~30s on a frozen socket, so worst case stays bounded (~2 minutes)
    # even when the route is flapping. Submits run in parallel inside the pool, so a slow
    # one doesn't block its siblings.
    create_resp = _request_with_retries(
        'POST', f'{SONIOX_API_BASE}/transcriptions',
        headers=headers, json=create_payload,
        timeout=(10, 30),  # (connect, read)
        retries=3, base_delay=1.5,
    )
    if create_resp.status_code >= 400:
        try:
            err = create_resp.json()
        except Exception:
            err = {'raw': create_resp.text}
        raise RuntimeError(json.dumps({'stage': 'soniox_submit', 'status': create_resp.status_code, 'response': err}, ensure_ascii=False))
    created = create_resp.json()
    tid = created.get('id') or created.get('transcription_id')
    if not tid:
        raise RuntimeError(f'soniox_no_transcription_id: {json.dumps(created, ensure_ascii=False)[:300]}')

    initial_status = str(created.get('status') or 'submitted').lower()
    response_payload = {
        'id': tid,
        'soniox_status': initial_status,
        'provider': 'soniox',
    }
    return {
        'provider': 'soniox',
        'request_payload': create_payload,
        'response_payload': response_payload,
        'tid': tid,
        'initial_status': initial_status,
    }


def soniox_fetch_state(tid: str) -> dict | None:
    """Single-shot poll. Returns:
    - None if still in flight (caller should retry later)
    - {'status': 'completed', 'response_payload': {...full transcript...}} on success
    - {'status': 'failed'|'error', 'error': '...', 'response_payload': {...}} on terminal failure
    Network errors raise — caller decides whether to retry the tick."""
    if not SONIOX_API_KEY:
        raise RuntimeError('missing_soniox_api_key')
    headers = {'Authorization': f'Bearer {SONIOX_API_KEY}', 'Content-Type': 'application/json'}
    # Same retry profile as Claude: 3 attempts with jitter on transient network errors.
    # TCP_USER_TIMEOUT caps each attempt; the outer poll loop will also re-tick if all fail.
    try:
        st = _request_with_retries(
            'GET', f'{SONIOX_API_BASE}/transcriptions/{tid}',
            headers=headers, timeout=(10, 15),
            retries=2, base_delay=1.5,
        )
    except (requests.exceptions.ConnectTimeout,
            requests.exceptions.ReadTimeout,
            requests.exceptions.ConnectionError):
        return None
    if st.status_code >= 400:
        return None
    body = st.json()
    status = str(body.get('status') or '').lower()
    if status not in ('completed', 'error', 'failed'):
        return None
    if status != 'completed':
        return {
            'status': status,
            'error': str(body.get('error_message') or body.get('error_type') or 'transcription_failed'),
            'response_payload': {'id': tid, 'provider': 'soniox', 'soniox_status': status},
        }
    # Completed — fetch the transcript body. Retry the fetch on transient errors since we already paid for it.
    tr_resp = _request_with_retries('GET', f'{SONIOX_API_BASE}/transcriptions/{tid}/transcript', headers=headers, timeout=60)
    if tr_resp.status_code >= 400:
        try:
            err = tr_resp.json()
        except Exception:
            err = {'raw': tr_resp.text[:300]}
        return {'status': 'failed', 'error': json.dumps(err, ensure_ascii=False), 'response_payload': {}}
    transcript = tr_resp.json()
    tokens = transcript.get('tokens') or []
    response_payload = {
        'id': transcript.get('id') or tid,
        'text': transcript.get('text') or '',
        'words': _soniox_tokens_to_words(tokens),
        'tokens': tokens,
        'soniox_status': body.get('status'),
        'audio_duration_ms': body.get('audio_duration_ms'),
        'language_hints': body.get('language_hints'),
        'provider': 'soniox',
    }
    return {'status': 'completed', 'response_payload': response_payload}


def upsert_call(data: dict, audio_url: str) -> dict:
    activity_id = int(data['bitrix_activity_id'])
    q = """
    INSERT INTO calls(
      bitrix_activity_id, bitrix_file_id, owner_type_id, owner_id,
      deal_id, contact_id, responsible_id, phone, direction,
      started_at, ended_at, duration_seconds, audio_url, source_payload, updated_at
    ) VALUES (
      %(bitrix_activity_id)s, %(bitrix_file_id)s, %(owner_type_id)s, %(owner_id)s,
      %(deal_id)s, %(contact_id)s, %(responsible_id)s, %(phone)s, %(direction)s,
      %(started_at)s, %(ended_at)s, %(duration_seconds)s, %(audio_url)s, %(source_payload)s::jsonb, NOW()
    )
    ON CONFLICT (bitrix_activity_id)
    DO UPDATE SET
      bitrix_file_id = EXCLUDED.bitrix_file_id,
      owner_type_id = EXCLUDED.owner_type_id,
      owner_id = EXCLUDED.owner_id,
      deal_id = EXCLUDED.deal_id,
      contact_id = EXCLUDED.contact_id,
      responsible_id = EXCLUDED.responsible_id,
      phone = EXCLUDED.phone,
      direction = EXCLUDED.direction,
      started_at = EXCLUDED.started_at,
      ended_at = EXCLUDED.ended_at,
      duration_seconds = EXCLUDED.duration_seconds,
      audio_url = EXCLUDED.audio_url,
      source_payload = EXCLUDED.source_payload,
      updated_at = NOW()
    RETURNING id, bitrix_activity_id;
    """
    params = {
        'bitrix_activity_id': activity_id,
        'bitrix_file_id': data.get('bitrix_file_id'),
        'owner_type_id': data.get('owner_type_id'),
        'owner_id': data.get('owner_id'),
        'deal_id': data.get('deal_id'),
        'contact_id': data.get('contact_id'),
        'responsible_id': data.get('responsible_id'),
        'phone': data.get('phone'),
        'direction': data.get('direction'),
        'started_at': data.get('started_at'),
        'ended_at': data.get('ended_at'),
        'duration_seconds': data.get('duration_seconds'),
        'audio_url': sanitize_url_for_storage(audio_url),
        'source_payload': json.dumps(data, ensure_ascii=False),
    }
    with db_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(q, params)
        return cur.fetchone()


def create_transcription(call_id: int, request_payload: dict, response_payload: dict, provider: str | None = None) -> dict:
    provider_job_id = extract_job_id(response_payload)
    status = str(response_payload.get('status') or 'submitted')
    prov = (provider or response_payload.get('provider') or ACTIVE_TRANSCRIBE_PROVIDER).strip().lower()
    q = """
    INSERT INTO transcriptions(
      call_id, provider, provider_job_id, status,
      request_payload, response_payload, created_at, updated_at
    ) VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, NOW(), NOW())
    ON CONFLICT (provider, provider_job_id)
      WHERE provider_job_id IS NOT NULL
    DO UPDATE SET
      status = EXCLUDED.status,
      request_payload = EXCLUDED.request_payload,
      response_payload = EXCLUDED.response_payload,
      updated_at = NOW()
    RETURNING id, provider, provider_job_id, status;
    """
    with db_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(q, (call_id, prov, provider_job_id, status, json.dumps(request_payload, ensure_ascii=False), json.dumps(response_payload, ensure_ascii=False)))
        return cur.fetchone()


def parse_deal_ids_from_text(text: str) -> list[int]:
    if not text:
        return []
    found = []
    seen = set()
    for match in DEAL_LINK_RE.finditer(text):
        deal_id = safe_int(match.group(1))
        if not deal_id or deal_id in seen:
            continue
        seen.add(deal_id)
        found.append(deal_id)
    return found


def parse_entity_refs_from_text(text: str) -> list[tuple[str, int]]:
    """Extract Bitrix entity refs (deals + leads) from a text blob. Preserves order, dedupes."""
    if not text:
        return []
    found: list[tuple[str, int]] = []
    seen = set()
    for entity_type, regex in (('deal', DEAL_LINK_RE), ('lead', LEAD_LINK_RE)):
        for match in regex.finditer(text):
            eid = safe_int(match.group(1))
            key = (entity_type, eid)
            if not eid or key in seen:
                continue
            seen.add(key)
            found.append(key)
    return found


def create_export_batch(source: str, text: str, deal_ids: list[int], user_id: int | None = None, bitrix_connection_id: int | None = None):
    source_name = str(source or 'web').strip() or 'web'
    return db_one(
        """
        INSERT INTO analysis_batches(
          source, source_text, total_deals, status, auto_qa, user_id, bitrix_connection_id, created_at, updated_at
        ) VALUES (%s, %s, %s, 'queued', TRUE, %s, %s, NOW(), NOW())
        RETURNING *;
        """,
        (source_name, text, len(deal_ids), user_id, bitrix_connection_id),
    )


def update_export_status_stage(export_id: int, stage: str, stage_text: str | None = None, append_error: str | None = None):
    db_exec(
        "UPDATE analysis_exports SET processing_stage=%s, updated_at=NOW() WHERE id=%s",
        (stage_text or stage, export_id),
    )


def normalize_person_name(value: str | None) -> str:
    text = re.sub(r'\s+', ' ', str(value or '').strip()).casefold()
    return text


def discover_operator_candidates(activities: list[dict], comments: list[dict], bitrix_ctx: dict | None = None) -> list[dict]:
    participants = {}

    def ensure(uid: int):
        item = participants.get(uid)
        if item:
            return item
        name, position = resolve_user_name_position(uid, '', '', bitrix_ctx=bitrix_ctx)
        item = {
            'user_id': uid,
            'user_name': name,
            'user_position': position,
            'call_count': 0,
            'handled_calls': 0,
            'missed_calls': 0,
            'ndz_calls': 0,
            'comment_count': 0,
            'activity_count': 0,
            'latest_at': None,
        }
        participants[uid] = item
        return item

    for act in activities or []:
        uid = safe_int(act.get('AUTHOR_ID')) or safe_int(act.get('RESPONSIBLE_ID'))
        if not uid:
            continue
        item = ensure(uid)
        item['activity_count'] += 1
        if str(act.get('TYPE_ID') or '') == '2':
            item['call_count'] += 1
            call_info = classify_call_activity(act)
            if call_info['status'] == 'handled':
                item['handled_calls'] += 1
            elif call_info['status'] == 'missed':
                item['missed_calls'] += 1
            else:
                item['ndz_calls'] += 1
            event_at = call_info.get('start_dt')
        else:
            event_at = parse_ts(act.get('START_TIME')) or parse_ts(act.get('END_TIME')) or parse_ts(act.get('DEADLINE'))
        if event_at and (item['latest_at'] is None or event_at > item['latest_at']):
            item['latest_at'] = event_at

    for comment in comments or []:
        uid = safe_int(comment.get('AUTHOR_ID'))
        if not uid:
            continue
        item = ensure(uid)
        item['comment_count'] += 1
        event_at = parse_ts(comment.get('CREATED'))
        if event_at and (item['latest_at'] is None or event_at > item['latest_at']):
            item['latest_at'] = event_at

    ordered = sorted(
        participants.values(),
        key=lambda item: (
            -int(item.get('handled_calls') or 0),
            -int(item.get('call_count') or 0),
            -int(item.get('comment_count') or 0),
            -(item.get('latest_at').timestamp() if item.get('latest_at') else 0),
            int(item.get('user_id') or 0),
        ),
    )
    for item in ordered:
        if isinstance(item.get('latest_at'), datetime):
            item['latest_at'] = item['latest_at'].astimezone(timezone.utc).isoformat()
    return ordered


def event_matches_selected_operator(event: dict, selected_operator_id: int | None, selected_operator_name: str = '') -> bool:
    uid = safe_int(selected_operator_id)
    name_norm = normalize_person_name(selected_operator_name)
    actor_id = safe_int(event.get('actor_id'))
    actor_name = normalize_person_name(event.get('actor_name'))
    if uid and actor_id == uid:
        return True
    if name_norm and actor_name and actor_name == name_norm:
        return True
    raw = event.get('raw_json') if isinstance(event.get('raw_json'), dict) else {}
    raw_author_id = safe_int(raw.get('AUTHOR_ID')) or safe_int(raw.get('RESPONSIBLE_ID'))
    if uid and raw_author_id == uid:
        return True
    return False


def build_selected_call_summary(ctx: dict, selected_operator_id: int | None, selected_operator_name: str = '') -> dict:
    base = ctx.get('call_summary') if isinstance(ctx.get('call_summary'), dict) else {}
    participants = base.get('participants') if isinstance(base.get('participants'), list) else []
    uid = safe_int(selected_operator_id)
    name_norm = normalize_person_name(selected_operator_name)
    selected = None
    others = []
    for item in participants:
        item_uid = safe_int(item.get('user_id'))
        item_name_norm = normalize_person_name(item.get('user_name'))
        if (uid and item_uid == uid) or (name_norm and item_name_norm == name_norm):
            selected = item
        else:
            others.append(item)
    primary = None
    if selected:
        primary = {
            'user_id': safe_int(selected.get('user_id')),
            'user_name': selected.get('user_name'),
            'user_position': selected.get('user_position'),
            'duration_sec': int(selected.get('total_duration_sec') or 0),
            'event_at': selected.get('latest_call_at'),
            'activity_id': None,
        }
    return {
        'primary_call_operator': primary,
        'participants': [selected] + others if selected else others,
    }


def apply_selected_operator_context(ctx: dict, selected_operator_id: int | None, selected_operator_name: str = '') -> dict:
    out = dict(ctx or {})
    uid = safe_int(selected_operator_id)
    selected_name = str(selected_operator_name or '').strip()
    if uid or selected_name:
        name, position = resolve_user_name_position(uid or 0, selected_name, '')
        out['responsible_id'] = uid or out.get('responsible_id')
        out['responsible_name'] = name
        out['executor_position'] = position
        out['selected_operator_id'] = uid
        out['selected_operator_name'] = name
        out['call_summary'] = build_selected_call_summary(out, uid, name)
    return out



def fetch_deal_context(deal_id: int, bitrix_ctx: dict | None = None, entity_type: str = 'deal'):
    errors = []
    method = BITRIX_GET_METHOD_BY_ENTITY.get(entity_type, 'crm.deal.get')
    entity = bitrix_api(method, {'id': deal_id}, bitrix_ctx=bitrix_ctx).get('result', {})
    if not entity:
        raise RuntimeError(f'{entity_type}_not_found:{deal_id}')

    responsible_id = safe_int(entity.get('ASSIGNED_BY_ID'))
    exec_first = (entity.get('ASSIGNED_BY_NAME') or '').strip()
    exec_last = (entity.get('ASSIGNED_BY_LAST_NAME') or '').strip()
    responsible_name = f"{exec_first} {exec_last}".strip()
    executor_position = (entity.get('ASSIGNED_BY_WORK_POSITION') or '').strip()
    responsible_name, executor_position = resolve_user_name_position(
        responsible_id,
        responsible_name,
        executor_position,
        bitrix_ctx=bitrix_ctx,
    )

    contact_id = safe_int(entity.get('CONTACT_ID'))
    company_id = safe_int(entity.get('COMPANY_ID'))
    client_name = '<не указан>'

    if entity_type == 'lead':
        # Lead carries client name fields directly on the entity (NAME / LAST_NAME / SECOND_NAME).
        parts = [entity.get('NAME', ''), entity.get('LAST_NAME', ''), entity.get('SECOND_NAME', '')]
        client_name = ' '.join([p.strip() for p in parts if p and p.strip()]).strip() or '<не указан>'
        if client_name == '<не указан>':
            title = (entity.get('TITLE') or '').strip()
            if title and not is_placeholder_text(title):
                client_name = title
    else:
        deal_fio = entity.get('UF_CRM_1769753561828')
        if isinstance(deal_fio, (list, tuple)):
            deal_fio = ' '.join([str(x).strip() for x in deal_fio if str(x).strip()]).strip()
        else:
            deal_fio = str(deal_fio or '').strip()
        if deal_fio and not is_placeholder_text(deal_fio):
            client_name = deal_fio

    contact = {}
    if client_name == '<не указан>' and contact_id:
        try:
            contact = bitrix_api('crm.contact.get', {'id': contact_id}, bitrix_ctx=bitrix_ctx).get('result', {})
            parts = [contact.get('NAME', ''), contact.get('LAST_NAME', ''), contact.get('SECOND_NAME', '')]
            client_name = ' '.join([p.strip() for p in parts if p and p.strip()]).strip() or '<не указан>'
        except Exception as exc:
            errors.append(f'contact_lookup_error: {exc}')

    if client_name == '<не указан>' and company_id:
        try:
            company = bitrix_api('crm.company.get', {'id': company_id}, bitrix_ctx=bitrix_ctx).get('result', {})
            client_name = (company.get('TITLE') or '').strip() or '<не указан>'
        except Exception as exc:
            errors.append(f'company_lookup_error: {exc}')

    return {
        'deal': entity,
        'contact': contact,
        'responsible_id': responsible_id,
        'responsible_name': responsible_name,
        'executor_position': executor_position,
        'contact_id': contact_id,
        'company_id': company_id,
        'client_name': client_name,
        'errors': errors,
    }


def fetch_deal_activities(deal_id: int, bitrix_ctx: dict | None = None, entity_type: str = 'deal'):
    try:
        rows = bitrix_list_all('crm.activity.list', {
            'filter[OWNER_TYPE_ID]': BITRIX_OWNER_TYPE_BY_ENTITY.get(entity_type, 2),
            'filter[OWNER_ID]': deal_id,
            'order[START_TIME]': 'ASC',
            'select[]': [
                'ID', 'TYPE_ID', 'PROVIDER_ID', 'SUBJECT', 'START_TIME', 'END_TIME', 'DEADLINE',
                'RESPONSIBLE_ID', 'AUTHOR_ID', 'FILES', 'DIRECTION', 'DESCRIPTION', 'COMPLETED',
                'SETTINGS', 'STATUS', 'RESULT_STREAM'
            ]
        }, bitrix_ctx=bitrix_ctx)
        return rows, None
    except Exception as exc:
        return [], f'activities_fetch_error: {exc}'


def fetch_deal_timeline_comments(deal_id: int, bitrix_ctx: dict | None = None, entity_type: str = 'deal'):
    try:
        rows = bitrix_list_all('crm.timeline.comment.list', {
            'filter[ENTITY_ID]': deal_id,
            'filter[ENTITY_TYPE]': entity_type if entity_type in ('deal', 'lead') else 'deal',
        }, bitrix_ctx=bitrix_ctx)
        return rows, None
    except Exception as exc:
        return [], f'timeline_fetch_error: {exc}'


def _field_title_values(meta: dict):
    titles = set()
    if not isinstance(meta, dict):
        return titles
    for k in ('title', 'formLabel', 'listLabel', 'filterLabel'):
        v = meta.get(k)
        if isinstance(v, str) and v.strip():
            titles.add(v.strip().casefold())
    return titles
def _is_filled(value):
    if value is None:
        return False
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return False
        if s.casefold() in ('не заполнено', 'none', 'null', '-'):
            return False
        return True
    if isinstance(value, (list, tuple, set)):
        return any(_is_filled(v) for v in value)
    if isinstance(value, dict):
        # Common Bitrix structures: {'VALUE': '...'} or {'value': '...'}
        if 'VALUE' in value:
            return _is_filled(value.get('VALUE'))
        if 'value' in value:
            return _is_filled(value.get('value'))
        return any(_is_filled(v) for v in value.values())
    return True


def calculate_card_completeness(ctx: dict, card_fields: list[dict] | None = None, entity_type: str = 'deal'):
    """Score completeness of the Bitrix client card. `card_fields` is a per-standard config
    of [{label, entity_type, field_code}, ...]. Empty list → not configured → block hidden."""
    entity = ctx.get('deal') or {}
    fields = card_fields or []

    filled = 0
    details = []
    for f in fields:
        if not isinstance(f, dict):
            continue
        f_entity = str(f.get('entity_type') or 'deal').strip().lower() or 'deal'
        # Only score fields that match this entity_type; others (cross-entity) are skipped silently.
        if f_entity != entity_type:
            continue
        label = str(f.get('label') or '').strip()
        field_code = str(f.get('field_code') or '').strip()
        if not field_code:
            continue
        val = entity.get(field_code)
        ok = _is_filled(val)
        if ok:
            filled += 1
        details.append({
            'label': label or field_code,
            'filled': ok,
            'source': f_entity,
            'field_code': field_code,
        })

    total = len(details)
    percent = quant2((filled / total) * 100.0) if total else 0.0
    return {
        'filled': filled,
        'total': total,
        'percent': percent,
        'details': details,
        'unmapped_labels': [],
    }


def extract_actor_and_message(clean_text: str) -> tuple[str | None, str]:
    if not clean_text:
        return None, ''
    first, _, rest = clean_text.partition('\n')
    m = re.match(r'^\s*([^:]+):\s*(.*)$', first)
    if m:
        actor = (m.group(1) or '').strip() or None
        tail = (m.group(2) or '').strip()
        message = '\n'.join([p for p in [tail, rest.strip()] if p]).strip()
        return actor, message
    return None, clean_text.strip()


def build_crm_file_url(file_id: int, owner_id: int, owner_type_id: int = 6, bitrix_ctx: dict | None = None) -> str:
    access_token = str((bitrix_ctx or {}).get('access_token') or '').strip()
    domain = str((bitrix_ctx or {}).get('domain') or '').strip()
    if not access_token:
        raise RuntimeError('missing_access_token')
    if not domain:
        raise RuntimeError('missing_bitrix_domain')
    return (
        f"https://{domain}/bitrix/tools/crm_show_file.php"
        f"?fileId={int(file_id)}&ownerTypeId={int(owner_type_id)}&ownerId={int(owner_id)}&auth={access_token}"
    )


def collect_communication_events(deal_id: int, bitrix_ctx: dict | None = None, entity_type: str = 'deal', card_fields: list[dict] | None = None):
    ctx = fetch_deal_context(deal_id, bitrix_ctx=bitrix_ctx, entity_type=entity_type)
    activities, activities_error = fetch_deal_activities(deal_id, bitrix_ctx=bitrix_ctx, entity_type=entity_type)
    if activities_error:
        ctx['errors'].append(activities_error)

    comments, comments_error = fetch_deal_timeline_comments(deal_id, bitrix_ctx=bitrix_ctx, entity_type=entity_type)
    if comments_error:
        ctx['errors'].append(comments_error)

    operator_id, operator_name, operator_position = infer_operator_identity(
        activities=activities,
        comments=comments,
        fallback_id=ctx.get('responsible_id'),
        fallback_name=ctx.get('responsible_name'),
        fallback_position=ctx.get('executor_position'),
    )
    ctx['call_summary'] = summarize_call_participants(activities)
    ctx['responsible_id'] = operator_id
    ctx['responsible_name'] = operator_name
    ctx['executor_position'] = operator_position
    ctx['assigned_by_id'] = safe_int(ctx.get('deal', {}).get('ASSIGNED_BY_ID'))
    ctx['card_completeness'] = calculate_card_completeness(ctx, card_fields=card_fields, entity_type=entity_type)
    deal = ctx['deal']
    errors = list(ctx['errors'])
    created_dt = parse_ts(deal.get('DATE_CREATE')) or datetime.now(timezone.utc)
    events = []

    deal_comment = str(deal.get('COMMENTS') or '').strip()
    if deal_comment:
        events.append({
            'event_at': created_dt,
            'event_type': 'deal_comment',
            'channel': 'deal',
            'actor_role': 'executor',
            'actor_name': ctx['responsible_name'] if ctx['responsible_name'] != '<не доступно>' else None,
            'actor_id': ctx['responsible_id'],
            'text_content': deal_comment,
            'source_type': 'deal',
            'source_id': -1,
            'raw_json': {'COMMENTS': deal_comment},
            'media': [],
        })

    for act in activities:
        act_id = safe_int(act.get('ID'))
        if not act_id:
            continue
        typ = str(act.get('TYPE_ID') or '')
        st = parse_ts(act.get('START_TIME')) or parse_ts(act.get('END_TIME')) or parse_ts(act.get('DEADLINE')) or created_dt
        subj = (act.get('SUBJECT') or '').strip()
        desc = clean_comment_text((act.get('DESCRIPTION') or '').strip())
        provider_id = str(act.get('PROVIDER_ID') or '').strip()
        activity_actor_id = safe_int(act.get('AUTHOR_ID')) or safe_int(act.get('RESPONSIBLE_ID')) or ctx['responsible_id']
        activity_actor_name, _ = resolve_user_name_position(activity_actor_id, '', '', bitrix_ctx=bitrix_ctx)
        media = []
        event_type = 'activity'
        channel = 'activity'
        text_content = subj or desc or f'Активность CRM (TYPE_ID={typ})'
        if typ == '2':
            event_type = 'call'
            channel = 'call'
            files = act.get('FILES') or []
            for f in files:
                if not isinstance(f, dict):
                    continue
                file_id = safe_int(f.get('id') or f.get('ID'))
                if not file_id:
                    continue
                try:
                        media.append({
                            'media_type': 'audio',
                            'source_url': build_crm_file_url(file_id, act_id, 6, bitrix_ctx=bitrix_ctx),
                            'mime_type': None,
                        })
                except Exception as exc:
                    errors.append(f'call_audio_url_error:{act_id}:{exc}')
        else:
            low = f"{subj} {desc} {provider_id}".casefold()
            if 'напомин' in low or 'связат' in low or provider_id.casefold() in ('todo', 'crm_todo'):
                event_type = 'reminder'
            elif typ == '1':
                event_type = 'meeting'
            elif typ == '3':
                event_type = 'task'
            elif typ == '4':
                event_type = 'email'
        events.append({
            'event_at': st,
            'event_type': event_type,
            'channel': channel,
            'actor_role': 'executor',
            'actor_name': activity_actor_name if activity_actor_name != '<не доступно>' else None,
            'actor_id': activity_actor_id,
            'text_content': text_content,
            'source_type': 'activity',
            'source_id': act_id,
            'raw_json': act,
            'media': media,
        })

    for c in comments:
        cid = safe_int(c.get('ID'))
        if not cid:
            continue
        raw_comment = (c.get('COMMENT') or '').strip()
        cdt = parse_ts(c.get('CREATED')) or created_dt
        clean_text = clean_comment_text(raw_comment)
        if not clean_text:
            continue
        actor_name, message_text = extract_actor_and_message(clean_text)
        urls = extract_urls_from_comment(raw_comment)
        low_text = clean_text.lower()
        low_raw = raw_comment.lower()
        media = []
        is_whatsapp = ('whatsapp' in low_raw or 'wazzup24.com' in low_raw)
        event_type = 'timeline_comment'
        channel = 'timeline'
        if is_whatsapp:
            channel = 'whatsapp'
            event_type = 'whatsapp_message'
            if 'аудиосообщ' in low_text:
                event_type = 'whatsapp_audio'
                for url in urls:
                    media.append({'media_type': 'audio', 'source_url': url, 'mime_type': 'audio/mpeg'})
            elif urls and ('файл' in low_text or 'отправлено' in low_text):
                event_type = 'whatsapp_file'
                for url in urls:
                    media.append({'media_type': 'file', 'source_url': url, 'mime_type': None})
        elif 'напомин' in low_text or 'связат' in low_text:
            event_type = 'reminder'
        comment_actor_id = safe_int(c.get('AUTHOR_ID'))
        comment_author_name, _ = resolve_user_name_position(comment_actor_id, '', '')
        actor_role = None
        if actor_name and ctx['client_name'] != '<не указан>' and actor_name.casefold() == ctx['client_name'].casefold():
            actor_role = 'client'
        elif actor_name and ctx['responsible_name'] != '<не доступно>' and actor_name.casefold() == ctx['responsible_name'].casefold():
            actor_role = 'executor'
        if actor_role is None and comment_actor_id and ctx['responsible_id'] and comment_actor_id == ctx['responsible_id']:
            actor_role = 'executor'
        events.append({
            'event_at': cdt,
            'event_type': event_type,
            'channel': channel,
            'actor_role': actor_role,
            'actor_name': actor_name or (comment_author_name if comment_author_name != '<не доступно>' else None),
            'actor_id': comment_actor_id,
            'text_content': message_text or clean_text,
            'source_type': 'timeline',
            'source_id': cid,
            'raw_json': c,
            'media': media,
        })

    events.sort(key=lambda x: (x['event_at'] is None, x['event_at'] or datetime.now(timezone.utc)))

    return {
        'context': ctx,
        'events': events,
        'errors': errors,
        'deal': deal,
        'activities': activities,
        'timeline_comments': comments,
    }


def create_export_record(source: str, deal_id: int | None, batch_id: int | None = None, user_id: int | None = None, bitrix_connection_id: int | None = None, entity_type: str = 'deal'):
    source_name = str(source or 'web').strip() or 'web'
    et = entity_type if entity_type in ('deal', 'lead') else 'deal'
    q = """
    INSERT INTO analysis_exports(
      source, deal_id, entity_type, batch_id, user_id, bitrix_connection_id, status, created_at, updated_at
    ) VALUES (%s, %s, %s, %s, %s, %s, 'received', NOW(), NOW())
    RETURNING id, source, status, deal_id, entity_type, batch_id, user_id, bitrix_connection_id;
    """
    return db_one(q, (source_name, deal_id, et, batch_id, user_id, bitrix_connection_id))



def set_selected_operator(export_id: int, operator_id: int | None, operator_name: str | None):
    db_exec(
        """
        UPDATE analysis_exports
        SET selected_operator_id=%s, selected_operator_name=%s, updated_at=NOW()
        WHERE id=%s
        """,
        (operator_id, operator_name, export_id),
    )


def delete_analysis_batch(batch_id: int, user_id: int) -> bool:
    bid = safe_int(batch_id)
    uid = safe_int(user_id)
    if not bid or not uid:
        return False
    with db_tx() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT id FROM analysis_batches WHERE id=%s AND user_id=%s", (bid, uid))
            if not cur.fetchone():
                return False
            cur.execute("DELETE FROM analysis_exports WHERE batch_id=%s", (bid,))
            cur.execute("DELETE FROM analysis_batches WHERE id=%s AND user_id=%s", (bid, uid))
            conn.commit()
    return True


def _mark_batch_error_if_all_failed(export_id: int):
    row = db_one("""
        SELECT batch_id FROM analysis_exports WHERE id=%s
    """, (export_id,))
    if not row:
        return
    batch_id = row['batch_id']
    counts = db_one("""
        SELECT
            COUNT(*) as total,
            COUNT(*) FILTER (WHERE status='error') as failed
        FROM analysis_exports WHERE batch_id=%s
    """, (batch_id,))
    if counts and counts['total'] > 0 and counts['total'] == counts['failed']:
        db_exec("UPDATE analysis_batches SET status='error', updated_at=NOW() WHERE id=%s", (batch_id,))


def set_selection_options(export_id: int, options: list[dict]):
    db_exec(
        """
        UPDATE analysis_exports
        SET selection_options_json=%s::jsonb, updated_at=NOW()
        WHERE id=%s
        """,
        (json.dumps(to_jsonable(options or []), ensure_ascii=False), export_id),
    )


def initialize_export_selection(export_id: int, deal_id: int, user_id: int, bitrix_connection_id: int | None = None, entity_type: str = 'deal') -> dict:
    try:
        bitrix_ctx = get_user_bitrix_context(user_id, connection_id=bitrix_connection_id)
    except Exception as exc:
        err_msg = str(exc)
        set_analysis_export_status(export_id, 'error', err_msg)
        update_export_status_stage(export_id, 'error', f'Ошибка подключения Bitrix: {err_msg}')
        _mark_batch_error_if_all_failed(export_id)
        raise
    activities, activities_error = fetch_deal_activities(deal_id, bitrix_ctx=bitrix_ctx, entity_type=entity_type)
    comments, comments_error = fetch_deal_timeline_comments(deal_id, bitrix_ctx=bitrix_ctx, entity_type=entity_type)
    participant_errors = [err for err in (activities_error, comments_error) if err]
    participants = discover_operator_candidates(activities, comments, bitrix_ctx=bitrix_ctx)
    if len(participants) > 1:
        set_selection_options(export_id, participants)
        set_analysis_export_status(export_id, 'awaiting_operator', '; '.join(participant_errors) if participant_errors else None)
        update_export_status_stage(export_id, 'awaiting_operator', 'Данные из Bitrix получены. Ожидаю выбор сотрудника')
        return {
            'awaiting_operator': True,
            'participants': participants,
            'errors': participant_errors,
        }
    chosen = participants[0] if participants else None
    if chosen:
        operator_name = str(chosen.get('user_name') or '').strip()
        set_selected_operator(export_id, safe_int(chosen.get('user_id')), operator_name)
    set_selection_options(export_id, [])
    set_analysis_export_status(export_id, 'queued', '; '.join(participant_errors) if participant_errors else None)
    if chosen:
        update_export_status_stage(export_id, 'queued', f'Bitrix данные получены. Выбран сотрудник: {operator_name}. Ставлю в очередь на обработку')
    else:
        update_export_status_stage(export_id, 'queued', 'Bitrix данные получены. Сотрудник не определён автоматически, продолжаю обработку')
    ensure_export_worker()
    return {
        'awaiting_operator': False,
        'participants': participants,
        'errors': participant_errors,
    }


def queue_export_with_operator(export_id: int, operator_id: int, operator_name: str):
    set_selected_operator(export_id, operator_id, operator_name)
    set_selection_options(export_id, [])
    set_analysis_export_status(export_id, 'queued', None)
    update_export_status_stage(export_id, 'queued', f'Выбран сотрудник: {operator_name}. Начинаю обработку')
    ensure_export_worker()


def normalize_employee_name(name: str) -> str:
    """Normalize a person's name to a stable matching key. Handles Cyrillic + Latin,
    NFD-folds diacritics, lowercases, drops punctuation, sort tokens (so order doesn't matter)."""
    raw = (name or '').strip()
    if not raw:
        return ''
    import unicodedata as _ud
    folded = _ud.normalize('NFKD', raw)
    no_marks = ''.join(c for c in folded if _ud.category(c) != 'Mn')
    cleaned = re.sub(r'[^\w\s]', ' ', no_marks.lower())
    tokens = sorted(t for t in cleaned.split() if t)
    return ' '.join(tokens)


def resolve_employee_id(bitrix_account_id: int | None, bitrix_user_id: int | None, name: str) -> int | None:
    """Internal employee identity. Lookup-or-create against
    (bitrix_account_id, bitrix_user_id, normalized_name). If admin renames a Bitrix user
    (e.g. fired Фариза, recycled the slot for Сара), the normalized name changes and we
    auto-create a new employee — old analyses keep their original employee_id, new ones
    point at the new identity."""
    raw_name = (name or '').strip()
    if not raw_name:
        return None
    norm = normalize_employee_name(raw_name)
    if not norm:
        return None
    aid = safe_int(bitrix_account_id)
    bid = safe_int(bitrix_user_id)
    if not bid:
        return None  # No external identity — can't resolve
    row = db_one(
        """
        SELECT id FROM employees
        WHERE bitrix_account_id IS NOT DISTINCT FROM %s
          AND bitrix_user_id = %s
          AND normalized_name = %s
        LIMIT 1
        """,
        (aid, bid, norm),
    )
    if row:
        # Refresh the display name in case spelling/case shifted (still same normalized).
        db_exec(
            "UPDATE employees SET name = %s, updated_at = NOW() WHERE id = %s AND name <> %s",
            (raw_name, int(row['id']), raw_name),
        )
        return int(row['id'])
    inserted = db_one(
        """
        INSERT INTO employees(bitrix_account_id, bitrix_user_id, name, normalized_name, status)
        VALUES (%s, %s, %s, %s, 'active')
        ON CONFLICT (bitrix_account_id, bitrix_user_id, normalized_name)
          DO UPDATE SET updated_at = NOW(), name = EXCLUDED.name
        RETURNING id
        """,
        (aid, bid, raw_name, norm),
    )
    return int(inserted['id']) if inserted else None


def rename_standard(standard_id: int, new_name: str) -> dict:
    sid = safe_int(standard_id)
    if not sid:
        raise RuntimeError('invalid_standard_id')
    name = (new_name or '').strip()
    if not name:
        raise RuntimeError('name_required')
    if len(name) > 200:
        raise RuntimeError('name_too_long')
    exists = db_one("SELECT 1 FROM qa_standard_versions WHERE id = %s", (sid,))
    if not exists:
        raise RuntimeError('standard_not_found')
    db_exec("UPDATE qa_standard_versions SET name = %s WHERE id = %s", (name, sid))
    return {'id': sid, 'name': name}


def get_standards_list(user_id: int | None = None) -> list:
    """List all QA standard versions with quick aggregates for the standards browser."""
    rows = db_all(
        """
        SELECT v.id, v.name, v.status, v.source_type, v.source_file_name,
               v.imported_at, v.archived_at,
               (SELECT COUNT(*) FROM qa_standard_blocks b WHERE b.standard_version_id = v.id) AS block_count,
               (SELECT COUNT(*) FROM qa_standard_modules m WHERE m.standard_version_id = v.id) AS module_count
        FROM qa_standard_versions v
        ORDER BY (v.status = 'active') DESC, v.imported_at DESC
        """
    ) or []
    default_id = 0
    uid = safe_int(user_id)
    if uid:
        row = db_one("SELECT default_standard_id FROM users WHERE id = %s", (uid,))
        default_id = safe_int((row or {}).get('default_standard_id'))
    return [
        {
            'id': int(r['id']),
            'name': str(r.get('name') or ''),
            'status': str(r.get('status') or ''),
            'source_type': str(r.get('source_type') or ''),
            'source_file_name': str(r.get('source_file_name') or ''),
            'imported_at': str(r.get('imported_at') or ''),
            'archived_at': str(r.get('archived_at') or ''),
            'block_count': int(r.get('block_count') or 0),
            'module_count': int(r.get('module_count') or 0),
            'is_default': int(r['id']) == default_id,
        }
        for r in rows
    ]


def get_standard_payload(standard_id: int, user_id: int | None = None) -> dict | None:
    sid = safe_int(standard_id)
    if not sid:
        return None
    version = db_one(
        """
        SELECT id, name, status, source_type, source_file_name, imported_at, archived_at
        FROM qa_standard_versions WHERE id = %s
        """,
        (sid,),
    )
    if not version:
        return None
    is_default = False
    uid = safe_int(user_id)
    if uid:
        owner = db_one("SELECT default_standard_id FROM users WHERE id = %s", (uid,))
        is_default = safe_int((owner or {}).get('default_standard_id')) == sid
    blocks = db_all(
        """
        SELECT id, block_name, block_weight_percent, sort_order
        FROM qa_standard_blocks
        WHERE standard_version_id = %s
        ORDER BY sort_order
        """,
        (sid,),
    ) or []
    modules = db_all(
        """
        SELECT id, block_id, module_name, module_details, module_weight_percent,
               scoring_rules, is_scored, sort_order
        FROM qa_standard_modules
        WHERE standard_version_id = %s
        ORDER BY block_id, sort_order
        """,
        (sid,),
    ) or []
    by_block: dict[int, list] = {}
    for m in modules:
        by_block.setdefault(int(m['block_id']), []).append({
            'id': int(m['id']),
            'name': str(m.get('module_name') or ''),
            'details': str(m.get('module_details') or ''),
            'weight_percent': float(m.get('module_weight_percent') or 0),
            'scoring_rules': str(m.get('scoring_rules') or ''),
            'is_scored': bool(m.get('is_scored')),
            'sort_order': int(m.get('sort_order') or 0),
        })
    blocks_payload = [
        {
            'id': int(b['id']),
            'name': str(b.get('block_name') or ''),
            'weight_percent': float(b.get('block_weight_percent') or 0),
            'sort_order': int(b.get('sort_order') or 0),
            'modules': by_block.get(int(b['id']), []),
        }
        for b in blocks
    ]
    return {
        'id': int(version['id']),
        'name': str(version.get('name') or ''),
        'status': str(version.get('status') or ''),
        'source_type': str(version.get('source_type') or ''),
        'source_file_name': str(version.get('source_file_name') or ''),
        'imported_at': str(version.get('imported_at') or ''),
        'archived_at': str(version.get('archived_at') or ''),
        'blocks': blocks_payload,
        'total_modules': len(modules),
        'is_default': is_default,
        'card_fields': get_standard_card_fields(sid),
    }


def set_employee_status(employee_id: int, user_id: int, new_status: str) -> dict:
    """Soft delete (archive) / restore. Validates that the user owns at least one export for
    this employee — prevents one user from archiving another tenant's employees."""
    eid = safe_int(employee_id)
    uid = safe_int(user_id)
    if not eid or not uid:
        raise RuntimeError('invalid_args')
    if new_status not in ('active', 'archived'):
        raise RuntimeError('invalid_status')
    owns = db_one(
        "SELECT 1 FROM analysis_exports WHERE employee_id = %s AND user_id = %s LIMIT 1",
        (eid, uid),
    )
    if not owns:
        raise RuntimeError('employee_not_owned_by_user')
    db_exec(
        "UPDATE employees SET status = %s, updated_at = NOW() WHERE id = %s",
        (new_status, eid),
    )
    return {'employee_id': eid, 'status': new_status}


def employee_to_bitrix_user_id(employee_id) -> int | None:
    """Map an internal employees.id → linked Bitrix user_id. Used by plan/cycles endpoints
    that still key by Bitrix id internally; the API surface is unified on employee.id, so
    we translate at the entry points rather than refactoring the whole plan storage."""
    eid = safe_int(employee_id)
    if not eid:
        return None
    row = db_one("SELECT bitrix_user_id FROM employees WHERE id = %s", (eid,))
    return safe_int(row.get('bitrix_user_id')) if row else None


def update_analysis_export_result(export_id: int, payload: dict):
    # Resolve / create the internal employee record. Linked Bitrix account is taken from
    # the export row itself so a single update handles every variant of the call site.
    acc_row = db_one(
        "SELECT bitrix_connection_id FROM analysis_exports WHERE id = %s",
        (export_id,),
    ) or {}
    employee_id = resolve_employee_id(
        bitrix_account_id=acc_row.get('bitrix_connection_id'),
        bitrix_user_id=payload.get('responsible_id'),
        name=payload.get('responsible_name') or '',
    )
    q = """
    UPDATE analysis_exports
    SET
      deal_id = %s,
      client_name = %s,
      client_contact_id = %s,
      client_company_id = %s,
      responsible_id = %s,
      responsible_name = %s,
      executor_position = %s,
      source_snapshot_json = %s::jsonb,
      export_text = %s,
      status = %s,
      error_summary = %s,
      employee_id = COALESCE(%s, employee_id),
      completed_at = NOW(),
      updated_at = NOW()
    WHERE id = %s
    """
    db_exec(
        q,
        (
            payload.get('deal_id'),
            payload.get('client_name'),
            payload.get('client_contact_id'),
            payload.get('client_company_id'),
            payload.get('responsible_id'),
            payload.get('responsible_name'),
            payload.get('executor_position'),
            json.dumps(to_jsonable(payload.get('snapshot') or {}), ensure_ascii=False),
            payload.get('export_text'),
            payload.get('status'),
            payload.get('error_summary'),
            employee_id,
            export_id,
        ),
    )


def get_batch_progress(batch_id: int):
    batch = db_one("SELECT * FROM analysis_batches WHERE id=%s", (batch_id,))
    if not batch:
        return None
    exports = db_all(
        """
        SELECT
          te.id,
          te.deal_id,
          te.status,
          te.error_summary,
          te.responsible_id,
          te.responsible_name,
          qr.public_id
        FROM analysis_exports te
        LEFT JOIN LATERAL (
          SELECT rl.public_id
          FROM qa_analysis_runs ar
          JOIN qa_report_links rl ON rl.run_id = ar.id AND rl.is_active = TRUE
          WHERE ar.export_id = te.id
          ORDER BY ar.run_version DESC
          LIMIT 1
        ) qr ON TRUE
        WHERE te.batch_id = %s
        ORDER BY te.id ASC
        """,
        (batch_id,),
    )
    qa_runs = db_all(
        """
        SELECT export_id, status, error_text, run_version
        FROM qa_analysis_runs
        WHERE export_id IN (SELECT id FROM analysis_exports WHERE batch_id = %s)
        ORDER BY export_id ASC, run_version DESC
        """,
        (batch_id,),
    )
    latest_runs = {}
    for run in qa_runs:
        eid = int(run['export_id'])
        if eid not in latest_runs:
            latest_runs[eid] = run
    total = len(exports)
    export_done = 0
    export_failed = 0
    qa_done = 0
    qa_failed = 0
    pending = 0
    for exp in exports:
        status = str(exp.get('status') or '')
        if status in ('completed', 'completed_with_errors'):
            export_done += 1
        elif status == 'failed':
            export_failed += 1
        run = latest_runs.get(int(exp['id']))
        if run:
            rs = str(run.get('status') or '')
            if rs == 'completed':
                qa_done += 1
            elif rs == 'failed':
                qa_failed += 1
        if status in ('received', 'queued', 'processing') or (status in ('completed', 'completed_with_errors') and not run) or (run and str(run.get('status') or '') in ('queued', 'processing')):
            pending += 1
    return {
        'batch': batch,
        'exports': exports,
        'runs': latest_runs,
        'total': total,
        'export_done': export_done,
        'export_failed': export_failed,
        'qa_done': qa_done,
        'qa_failed': qa_failed,
        'pending': pending,
    }


def log_batch_progress(batch_id: int, stage: str):
    progress = get_batch_progress(batch_id)
    if not progress:
        return
    payload = {
        'batch_id': batch_id,
        'stage': stage,
        'total': progress['total'],
        'export_done': progress['export_done'],
        'export_failed': progress['export_failed'],
        'qa_done': progress['qa_done'],
        'qa_failed': progress['qa_failed'],
        'pending': progress['pending'],
    }
    db_log('analysis_batch', 'progress', str(batch_id), payload, 'ok', None)


def finalize_batch_if_ready(batch_id: int):
    progress = get_batch_progress(batch_id)
    if not progress:
        return
    if progress['pending'] > 0 or progress['total'] <= 0:
        return
    # Note: previously this short-circuited when final_message_sent_at was set, but that left
    # retried batches stuck in 'queued' after their successful re-run. We now always recompute
    # the batch status from the current export states — finalization is idempotent.

    lines = ['Пакет анализов готов:', '']
    for exp in progress['exports']:
        deal_id = exp.get('deal_id') or '<не указана>'
        op_name, _ = resolve_user_name_position(
            safe_int(exp.get('responsible_id')),
            str(exp.get('responsible_name') or '').strip(),
            '',
        )
        run = progress['runs'].get(int(exp['id']))
        report_url = f"{REPORT_PUBLIC_BASE_URL.rstrip('/')}{report_path(exp['public_id'], safe_int(exp.get('responsible_id')))}" if exp.get('public_id') else ''
        if run and str(run.get('status') or '') == 'completed' and report_url:
            lines.append(f"{deal_id} — {op_name}")
            lines.append(report_url)
        else:
            err = str((run or {}).get('error_text') or exp.get('error_summary') or 'анализ не сформирован').strip()
            lines.append(f"{deal_id} — {op_name}")
            lines.append(f"[ERROR] {err}")
        lines.append('')
    db_exec(
        "UPDATE analysis_batches SET status=%s, final_message_sent_at=NOW(), completed_at=NOW(), updated_at=NOW() WHERE id=%s",
        ('completed', batch_id),
    )
    db_log('analysis_batch', 'finalized', str(batch_id), {
        'batch_id': batch_id,
        'total': progress['total'],
        'export_done': progress['export_done'],
        'export_failed': progress['export_failed'],
        'qa_done': progress['qa_done'],
        'qa_failed': progress['qa_failed'],
    }, 'ok', None)

def upsert_call_text(export_id: int, deal_id: int | None, title: str, text_content: str):
    db_exec(
        """
        INSERT INTO qa_call_texts(export_id, deal_id, title, text_content, source, created_at, updated_at)
        VALUES (%s, %s, %s, %s, 'analysis_export', NOW(), NOW())
        ON CONFLICT (export_id)
        DO UPDATE SET
          deal_id = EXCLUDED.deal_id,
          title = EXCLUDED.title,
          text_content = EXCLUDED.text_content,
          updated_at = NOW()
        """,
        (export_id, deal_id, title, text_content),
    )


def get_call_text_by_public_id(public_id: str):
    return db_one(
        """
        SELECT
          rl.public_id,
          COALESCE(ct.title, 'Хронология сделки') AS title,
          COALESCE(ct.text_content, te.export_text) AS text_content,
          rl.export_id,
          COALESCE(ct.deal_id, te.deal_id) AS deal_id,
          te.entity_type AS entity_type,
          te.client_name AS client_name,
          te.responsible_name AS responsible_name,
          te.responsible_id AS responsible_id,
          te.user_id AS user_id,
          te.bitrix_connection_id AS bitrix_connection_id,
          uc.bitrix_domain AS bitrix_domain
        FROM qa_report_links rl
        LEFT JOIN qa_call_texts ct ON ct.export_id = rl.export_id
        LEFT JOIN analysis_exports te ON te.id = rl.export_id
        LEFT JOIN user_bitrix_connections uc ON uc.id = te.bitrix_connection_id
        WHERE rl.public_id = %s AND rl.is_active = TRUE
        """,
        (public_id,),
    )


def _looks_like_garbage_name(value: str) -> bool:
    """An actor_name like '12' (a stray digit), '<не доступно>', or pure punctuation is junk
    we caught from inconsistent Bitrix events. Don't trust it as a real person's name."""
    s = (value or '').strip()
    if not s or is_placeholder_text(s):
        return True
    if s.isdigit():
        return True
    if not re.search(r'[A-Za-zА-Яа-яҚқҒғҺһҢңӘәҮүҰұІіЁё]', s):
        return True
    return False


def resolve_event_creator_details(raw: dict, event: dict, bitrix_ctx: dict | None = None):
    creator_id = safe_int(raw.get('AUTHOR_ID')) or safe_int(raw.get('RESPONSIBLE_ID')) or safe_int(event.get('actor_id'))
    creator_name = ''
    creator_position = ''
    # Look up canonical name from Bitrix (or its cache) by id — actor_name from the event
    # cache is unreliable (we've seen '12', stray digits, etc., when timeline events were
    # serialized inconsistently).
    if creator_id:
        creator_name, creator_position = resolve_user_name_position(creator_id, '', '', bitrix_ctx=bitrix_ctx)
    # Only fall back to event.actor_name if it's a real-looking name.
    if is_placeholder_text(creator_name):
        candidate = str(event.get('actor_name') or '').strip()
        if not _looks_like_garbage_name(candidate):
            creator_name = candidate
    if is_placeholder_text(creator_name):
        creator_name = '<не доступно>'
    return creator_id, creator_name, creator_position


def resolve_event_scope(selected_operator_id: int | None, selected_operator_name: str, creator_id: int | None, creator_name: str, event: dict):
    if selected_operator_id and creator_id == selected_operator_id:
        return 'selected', 'В анализе'
    if selected_operator_name and normalize_person_name(creator_name) == normalize_person_name(selected_operator_name):
        return 'selected', 'В анализе'
    event_actor_name = str(event.get('actor_name') or '').strip()
    if selected_operator_name and normalize_person_name(event_actor_name) == normalize_person_name(selected_operator_name):
        return 'selected', 'В анализе'
    if creator_id or (creator_name and not is_placeholder_text(creator_name)):
        return 'other', 'Другой участник'
    return 'system', 'Системное'


def get_row_bitrix_context(row: dict | None) -> dict | None:
    if not isinstance(row, dict):
        return None
    user_id = safe_int(row.get('user_id'))
    connection_id = safe_int(row.get('bitrix_connection_id'))
    if not user_id:
        return None
    try:
        return get_user_bitrix_context(user_id, connection_id=connection_id)
    except Exception:
        return None


def get_row_bitrix_domain(row: dict | None) -> str:
    if not isinstance(row, dict):
        return ''
    return str(row.get('bitrix_domain') or '').strip().casefold()


def decode_wazzup_emoji_escapes(text: str) -> str:
    """Wazzup occasionally serializes emoji as `:f09f918d:` (the UTF-8 byte sequence for 👍
    written in hex between colons), instead of passing the raw character through. Decode
    every such match back to its actual emoji. Invalid sequences are left untouched."""
    if not text or ':' not in text:
        return text or ''
    def _decode(match):
        hex_str = match.group(1)
        if len(hex_str) % 2 != 0 or len(hex_str) < 4 or len(hex_str) > 32:
            return match.group(0)
        try:
            return bytes.fromhex(hex_str).decode('utf-8')
        except (ValueError, UnicodeDecodeError):
            return match.group(0)
    return re.sub(r':([0-9a-fA-F]+):', _decode, text)


def build_chronology_payload(public_id: str):
    row = get_call_text_by_public_id(public_id)
    if not row:
        return None
    deal_id = safe_int(row.get('deal_id'))
    if not deal_id:
        return None
    entity_type = str(row.get('entity_type') or 'deal').strip().lower() or 'deal'
    if entity_type not in ('deal', 'lead'):
        entity_type = 'deal'
    title = t('ru', 'chronology_title_default')
    client_name = str(row.get('client_name') or '').strip() or 'Клиент'
    selected_operator_id = safe_int(row.get('responsible_id'))
    selected_operator_name = str(row.get('responsible_name') or '').strip()
    bitrix_ctx = get_row_bitrix_context(row)
    bitrix_domain = get_row_bitrix_domain(row)
    deal_link = f"https://{bitrix_domain}/crm/{ENTITY_URL_PATH_BY_TYPE.get(entity_type, 'deal')}/details/{deal_id}/" if bitrix_domain else ''

    rows = get_deal_events_for_export(deal_id, entity_type=entity_type)
    grouped = {}
    for r in rows:
        eid = r.get('event_id')
        if not eid:
            continue
        if eid not in grouped:
            grouped[eid] = {
                'event_id': eid,
                'event_at': r.get('event_at'),
                'event_type': r.get('event_type'),
                'channel': r.get('channel'),
                'actor_name': r.get('actor_name'),
                'actor_id': r.get('actor_id'),
                'text': r.get('text_content') or '',
                'raw_json': r.get('raw_json') if isinstance(r.get('raw_json'), dict) else {},
                'media': [],
            }
        if r.get('media_type'):
            grouped[eid]['media'].append({
                'media_type': r.get('media_type'),
                'media_status': r.get('media_status'),
                'tr_status': r.get('tr_status'),
                'transcript_text': r.get('transcript_text'),
                'tr_payload': r.get('tr_payload'),
                'media_error': r.get('media_error'),
                'tr_error': r.get('tr_error'),
            })
    structured = list(grouped.values())
    structured.sort(key=lambda x: (x['event_at'] is None, x['event_at'] or datetime.now(timezone.utc)))

    activity_cache = {}
    items = []
    for e in structured:
        raw = e.get('raw_json') if isinstance(e.get('raw_json'), dict) else {}
        creator_id, creator_name, creator_position = resolve_event_creator_details(raw, e, bitrix_ctx=bitrix_ctx)
        scope_code, scope_label = resolve_event_scope(selected_operator_id, selected_operator_name, creator_id, creator_name, e)
        event_at = e.get('event_at')
        ts_iso = event_at.astimezone(timezone.utc).isoformat() if isinstance(event_at, datetime) else ''
        item = {
            'event_id': e.get('event_id'),
            'timestamp_utc': ts_iso,
            'channel': str(e.get('channel') or ''),
            'event_type': str(e.get('event_type') or ''),
            'creator_id': creator_id,
            'creator_name': creator_name,
            'creator_position': creator_position,
            'scope': scope_code,
            'scope_label': scope_label,
            'text': decode_wazzup_emoji_escapes(str(e.get('text') or '').strip()),
            'transcript': '',
        }
        if item['channel'] == 'call':
            act_id = safe_int(raw.get('ID'))
            if act_id and ('SETTINGS' not in raw or 'START_TIME' not in raw or 'END_TIME' not in raw or 'DIRECTION' not in raw):
                if act_id not in activity_cache:
                    try:
                        activity_cache[act_id] = bitrix_api('crm.activity.get', {'id': act_id}, bitrix_ctx=bitrix_ctx).get('result', {}) or {}
                    except Exception:
                        activity_cache[act_id] = {}
                for k in ('SETTINGS', 'START_TIME', 'END_TIME', 'DIRECTION', 'SUBJECT', 'STATUS', 'COMPLETED'):
                    if k not in raw and k in activity_cache.get(act_id, {}):
                        raw[k] = activity_cache.get(act_id, {}).get(k)
            subj = str(raw.get('SUBJECT') or e.get('text') or '').strip()
            phone_match = re.search(r'(\+?\d[\d\s()-]{6,}\d)', subj)
            phone = phone_match.group(1).strip() if phone_match else ''
            call_info = classify_call_activity(raw)
            duration_sec = int(call_info.get('duration_sec') or 0)
            if call_info['status'] == 'missed':
                title_text = 'Пропущен входящий звонок' if call_info.get('is_incoming') else 'Пропущен исходящий звонок'
                status_label = 'ПРОПУЩЕН'
            elif call_info['status'] == 'ndz':
                title_text = 'Завершенный исходящий звонок'
                status_label = 'НЕДОЗВОН'
            else:
                title_text = 'Обработан входящий звонок' if call_info.get('is_incoming') else 'Обработан исходящий звонок'
                status_label = 'ОБРАБОТАН'
            item.update({
                'title': title_text,
                'status': call_info['status'],
                'status_label': status_label,
                'client_name': client_name,
                'phone': phone,
                'duration_seconds': duration_sec,
            })
        else:
            label = 'Событие'
            if item['event_type'] == 'deal_comment':
                label = 'Комментарий'
            elif item['event_type'] == 'reminder':
                label = 'Напоминание о деле'
            elif item['channel'] == 'whatsapp':
                label = 'WhatsApp'
            elif item['channel'] == 'timeline':
                label = 'Комментарий таймлайна'
            item.update({
                'title': label,
                'status': None,
                'status_label': None,
            })
        for media in e.get('media') or []:
            if media.get('media_type') != 'audio':
                continue
            transcript = format_transcript_for_txt(media.get('transcript_text'), media.get('tr_payload'))
            if transcript:
                item['transcript'] = transcript
                break
        items.append(item)

    items = collapse_duplicate_call_events(items)
    items = collapse_duplicate_whatsapp_events(items)

    return {
        'public_id': public_id,
        'title': title,
        'deal_id': deal_id,
        'deal_url': deal_link,
        'report_url': report_path(public_id, safe_int(row.get('responsible_id'))),
        'client_name': client_name,
        'selected_operator_id': selected_operator_id,
        'selected_operator_name': selected_operator_name,
        'events': items,
    }


def collapse_duplicate_call_events(items: list[dict]) -> list[dict]:
    """Bitrix24 (VoxImplant) often emits two activity records per physical call — a registration
    one and a report one. Only one carries the audio. Detect adjacent call events with matching
    phone + duration within 120s and keep the richer of the pair (transcript > media > text)."""
    if len(items) < 2:
        return items

    def parse_ts(s: str | None):
        if not s:
            return None
        try:
            return datetime.fromisoformat(str(s).replace('Z', '+00:00'))
        except Exception:
            return None

    def richness(it: dict) -> tuple:
        return (
            1 if it.get('transcript') else 0,
            len(str(it.get('text') or '')),
        )

    out: list[dict] = []
    for it in items:
        if not out or it.get('channel') != 'call':
            out.append(it)
            continue
        prev = out[-1]
        if prev.get('channel') != 'call':
            out.append(it)
            continue
        same_phone = bool(prev.get('phone')) and prev.get('phone') == it.get('phone')
        same_duration = (prev.get('duration_seconds') or 0) == (it.get('duration_seconds') or 0)
        t1 = parse_ts(prev.get('timestamp_utc'))
        t2 = parse_ts(it.get('timestamp_utc'))
        close = bool(t1 and t2 and abs((t2 - t1).total_seconds()) <= 120)
        if same_phone and same_duration and close:
            if richness(it) > richness(prev):
                out[-1] = it
            continue
        out.append(it)
    return out


WHATSAPP_DEDUP_WINDOW_SEC = 6 * 60 * 60  # 6 hours


def collapse_duplicate_whatsapp_events(items: list[dict]) -> list[dict]:
    """Wazzup→Bitrix integration occasionally re-posts the same inbound WhatsApp deal-source
    timeline comment hours later (deal re-sync, route change, hook replay). Dedupe by exact
    normalized text within a deal in a 6-hour window. The earliest occurrence wins."""
    if len(items) < 2:
        return items

    def parse_ts(s: str | None):
        if not s:
            return None
        try:
            return datetime.fromisoformat(str(s).replace('Z', '+00:00'))
        except Exception:
            return None

    def norm(s: str | None) -> str:
        return re.sub(r'\s+', ' ', str(s or '')).strip()

    out: list[dict] = []
    # Maps normalized text → timestamp of first kept whatsapp event with that text.
    seen: dict[str, datetime] = {}
    for it in items:
        if it.get('channel') != 'whatsapp':
            out.append(it)
            continue
        key = norm(it.get('text'))
        if not key:
            out.append(it)
            continue
        ts = parse_ts(it.get('timestamp_utc'))
        prev_ts = seen.get(key)
        if prev_ts and ts and abs((ts - prev_ts).total_seconds()) <= WHATSAPP_DEDUP_WINDOW_SEC:
            continue  # drop dupe — keep the earliest occurrence already in `out`
        if ts:
            seen[key] = prev_ts if prev_ts and prev_ts < ts else ts
        out.append(it)
    return out
def set_analysis_export_status(export_id: int, status: str, error_summary: str | None = None):
    db_exec(
        "UPDATE analysis_exports SET status=%s, error_summary=%s, updated_at=NOW() WHERE id=%s",
        (status, error_summary, export_id),
    )


def upsert_deal_event(deal_id: int, event: dict, entity_type: str = 'deal'):
    q = """
    INSERT INTO deal_events(
      entity_type, deal_id, event_at, event_type, channel, actor_role, actor_name, actor_id,
      text_content, source_type, source_id, raw_json, updated_at
    ) VALUES (
      %s, %s, %s, %s, %s, %s, %s, %s,
      %s, %s, %s, %s::jsonb, NOW()
    )
    ON CONFLICT (entity_type, deal_id, source_type, source_id)
    DO UPDATE SET
      event_at = EXCLUDED.event_at,
      event_type = EXCLUDED.event_type,
      channel = EXCLUDED.channel,
      actor_role = EXCLUDED.actor_role,
      actor_name = EXCLUDED.actor_name,
      actor_id = EXCLUDED.actor_id,
      text_content = EXCLUDED.text_content,
      raw_json = EXCLUDED.raw_json,
      updated_at = NOW()
    RETURNING id;
    """
    return db_one(
        q,
        (
            entity_type,
            deal_id,
            event.get('event_at'),
            event.get('event_type'),
            event.get('channel'),
            event.get('actor_role'),
            event.get('actor_name'),
            event.get('actor_id'),
            event.get('text_content'),
            event.get('source_type'),
            event.get('source_id'),
            json.dumps(event.get('raw_json') or {}, ensure_ascii=False),
        ),
    )


def upsert_event_media(deal_event_id: int, media: dict):
    q = """
    INSERT INTO event_media(
      deal_event_id, media_type, source_url, mime_type, status, updated_at
    ) VALUES (%s, %s, %s, %s, %s, NOW())
    ON CONFLICT (deal_event_id, source_url)
    DO UPDATE SET
      media_type = EXCLUDED.media_type,
      mime_type = EXCLUDED.mime_type,
      updated_at = NOW()
    RETURNING id, status;
    """
    return db_one(
        q,
        (
            deal_event_id,
            media.get('media_type'),
            media.get('source_url'),
            media.get('mime_type'),
            media.get('status', 'pending'),
        ),
    )


def upsert_media_transcription(event_media_id: int, status: str, request_payload: dict | None = None, response_payload: dict | None = None, provider_job_id: str | None = None, transcript_text: str | None = None, error_text: str | None = None, provider: str | None = None):
    prov = (provider or (response_payload or {}).get('provider') or ACTIVE_TRANSCRIBE_PROVIDER).strip().lower()
    q = """
    INSERT INTO media_transcriptions(
      event_media_id, provider, provider_job_id, status, transcript_text,
      request_payload, response_payload, error_text, updated_at, completed_at
    ) VALUES (
      %s, %s, %s, %s, %s,
      %s::jsonb, %s::jsonb, %s, NOW(),
      CASE WHEN %s IN ('completed', 'done', 'success', 'failed', 'error', 'cancelled', 'canceled') THEN NOW() ELSE NULL END
    )
    ON CONFLICT (event_media_id, provider)
    DO UPDATE SET
      provider_job_id = COALESCE(EXCLUDED.provider_job_id, media_transcriptions.provider_job_id),
      status = EXCLUDED.status,
      transcript_text = COALESCE(EXCLUDED.transcript_text, media_transcriptions.transcript_text),
      request_payload = CASE WHEN EXCLUDED.request_payload <> '{}'::jsonb THEN EXCLUDED.request_payload ELSE media_transcriptions.request_payload END,
      response_payload = CASE WHEN EXCLUDED.response_payload <> '{}'::jsonb THEN EXCLUDED.response_payload ELSE media_transcriptions.response_payload END,
      error_text = COALESCE(EXCLUDED.error_text, media_transcriptions.error_text),
      updated_at = NOW(),
      completed_at = CASE WHEN EXCLUDED.status IN ('completed', 'done', 'success', 'failed', 'error', 'cancelled', 'canceled') THEN NOW() ELSE media_transcriptions.completed_at END
    RETURNING id, provider_job_id, status;
    """
    return db_one(
        q,
        (
            event_media_id,
            prov,
            provider_job_id,
            status,
            transcript_text,
            json.dumps(request_payload or {}, ensure_ascii=False),
            json.dumps(response_payload or {}, ensure_ascii=False),
            error_text,
            status,
        ),
    )


def update_event_media_status(media_id: int, status: str, error_text: str | None = None):
    db_exec(
        "UPDATE event_media SET status=%s, error_text=%s, updated_at=NOW() WHERE id=%s",
        (status, error_text, media_id),
    )


def get_deal_audio_media(deal_id: int, selected_operator_id: int | None = None, selected_operator_name: str = '', entity_type: str = 'deal'):
    # Provider-agnostic: pick the best transcription for each media (completed > latest > newest id),
    # so historical transcriptions from a previous provider keep this worker idempotent.
    q = """
    SELECT em.id, em.source_url, em.status, mt.status AS tr_status, mt.provider, mt.provider_job_id,
           de.actor_id, de.actor_name, de.raw_json
    FROM event_media em
    JOIN deal_events de ON de.id = em.deal_event_id
    LEFT JOIN LATERAL (
      SELECT status, provider, provider_job_id
      FROM media_transcriptions
      WHERE event_media_id = em.id
      ORDER BY (status = 'completed') DESC, completed_at DESC NULLS LAST, id DESC
      LIMIT 1
    ) mt ON TRUE
    WHERE de.deal_id = %s AND de.entity_type = %s AND em.media_type = 'audio'
    ORDER BY em.id ASC
    """
    rows = db_all(q, (deal_id, entity_type))
    uid = safe_int(selected_operator_id)
    selected_name = str(selected_operator_name or '').strip()
    if not uid and not selected_name:
        return rows
    return [row for row in rows if event_matches_selected_operator(row, uid, selected_name)]


STT_FIXED_CONTEXT_TERMS = ['МДС Дорс', 'есік', 'есіктер', 'оцинкованный', 'брашбал', 'тамбур', 'каталог', 'размер']


def gather_stt_context_terms(media_row: dict) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    def add(value):
        v = str(value or '').strip()
        if v and v.casefold() not in seen:
            seen.add(v.casefold())
            terms.append(v)
    deal_event_id = safe_int(media_row.get('deal_event_id'))
    if deal_event_id:
        row = db_one(
            """
            SELECT ae.client_name, ae.selected_operator_name, ae.responsible_name
            FROM deal_events de
            JOIN analysis_exports ae ON ae.deal_id = de.deal_id
            WHERE de.id = %s
            ORDER BY ae.created_at DESC LIMIT 1
            """,
            (deal_event_id,),
        )
        if row:
            add(row.get('client_name'))
            add(row.get('selected_operator_name'))
            add(row.get('responsible_name'))
    for term in STT_FIXED_CONTEXT_TERMS:
        add(term)
    return terms


def submit_media_transcription(media_row: dict):
    """Async submit. POSTs to Soniox and returns immediately. The transcription_poll_worker_loop
    finalizes the result later by polling Soniox and writing transcript_text to the DB."""
    media_id = media_row['id']
    source_url = media_row.get('source_url')
    if not source_url:
        update_event_media_status(media_id, 'failed', 'audio_url_missing')
        upsert_media_transcription(media_id, 'failed', error_text='audio_url_missing')
        return
    try:
        context_terms = gather_stt_context_terms(media_row)
        submit_result = soniox_submit_only(source_url, context_terms=context_terms)
        req_payload = submit_result.get('request_payload') or {}
        resp_payload = submit_result.get('response_payload') or {}
        job_id = submit_result.get('tid') or extract_job_id(resp_payload)
        upsert_media_transcription(media_id, 'submitted', req_payload, resp_payload, job_id, None, None)
        update_event_media_status(media_id, 'processing', None)
    except Exception as exc:
        err = str(exc)
        upsert_media_transcription(media_id, 'failed', error_text=err)
        update_event_media_status(media_id, 'failed', err)


# Parallelism for STT submit. Each job is just a POST + immediate return, so a small pool is fine.
STT_PARALLEL_SUBMITS = int(os.getenv('STT_PARALLEL_SUBMITS', '5'))


def queue_and_process_audio(deal_id: int, selected_operator_id: int | None = None, selected_operator_name: str = '', entity_type: str = 'deal'):
    rows = get_deal_audio_media(deal_id, selected_operator_id, selected_operator_name, entity_type=entity_type)
    to_submit: list[dict] = []
    for row in rows:
        tr_status = (row.get('tr_status') or '').lower()
        media_status = (row.get('status') or '').lower()
        if tr_status and is_terminal_transcription_status(tr_status):
            if is_success_transcription_status(tr_status):
                update_event_media_status(row['id'], 'ready', None)
                continue
            # Retry failed transcriptions on a new export attempt.
            update_event_media_status(row['id'], 'pending', None)
            media_status = 'pending'
        if media_status in ('ready', 'failed'):
            continue
        if tr_status in ('submitted', 'processing', 'queued'):
            # Already in flight — the poll worker will pick it up.
            continue
        to_submit.append(row)

    if not to_submit:
        return

    # Pre-mark every audio as queued so wait_for_audio_completion doesn't return prematurely
    # while the parallel submits are still racing into Soniox.
    for row in to_submit:
        upsert_media_transcription(row['id'], 'queued')

    # Submit in parallel: each call just POSTs to Soniox and returns. Time = max submit, not sum.
    if len(to_submit) == 1:
        submit_media_transcription(to_submit[0])
    else:
        with ThreadPoolExecutor(max_workers=min(STT_PARALLEL_SUBMITS, len(to_submit))) as ex:
            list(ex.map(submit_media_transcription, to_submit))

    # Make sure the background poller is alive — it converts 'submitted' rows to final states.
    ensure_transcription_poll_worker()


# ─── Async transcription polling ─────────────────────────────────────────────
TRANSCRIPTION_POLL_WORKER_LOCK = threading.Lock()
TRANSCRIPTION_POLL_WORKER_STARTED = False
TRANSCRIPTION_POLL_INTERVAL_SEC = float(os.getenv('TRANSCRIPTION_POLL_INTERVAL_SEC', '5'))
TRANSCRIPTION_POLL_PARALLELISM = int(os.getenv('TRANSCRIPTION_POLL_PARALLELISM', '8'))


def _finalize_transcription(tr_row: dict):
    media_id = int(tr_row['event_media_id'])
    tid = str(tr_row.get('provider_job_id') or '').strip()
    if not tid:
        return
    try:
        state = soniox_fetch_state(tid)
    except Exception:
        return  # transient — try next tick
    if not state:
        # Still in flight. Bump updated_at so the row stays "fresh" in the work window.
        try:
            db_exec("UPDATE media_transcriptions SET updated_at=NOW() WHERE id=%s", (tr_row['id'],))
        except Exception:
            pass
        return
    status = state.get('status')
    response_payload = state.get('response_payload') or {}
    if status == 'completed':
        # Pass the raw text up explicitly — format_transcript_for_txt(None, payload) didn't
        # always reach into response_payload['text'] reliably, leading to empty rows even
        # when Soniox actually returned content.
        raw_text = str((response_payload or {}).get('text') or '').strip()
        transcript_text = format_transcript_for_txt(raw_text, response_payload)
        if not (transcript_text or '').strip():
            # Soniox reports completion but the transcript body is empty (we've seen this
            # when the /transcript endpoint timed out during a network flap and we still
            # finalized the row). Treat as failure so a retry can pick it up cleanly.
            upsert_media_transcription(media_id, 'failed', response_payload=response_payload, error_text='empty_transcript_body')
            update_event_media_status(media_id, 'failed', 'empty_transcript_body')
            return
        upsert_media_transcription(media_id, 'completed', response_payload=response_payload, transcript_text=transcript_text)
        update_event_media_status(media_id, 'ready', None)
    else:
        err = state.get('error') or 'transcription_failed'
        upsert_media_transcription(media_id, 'failed', response_payload=response_payload, error_text=err)
        update_event_media_status(media_id, 'failed', err)


def transcription_poll_worker_loop():
    """Background worker. Picks up media_transcriptions in non-terminal states and asks Soniox
    for the result. Uses a persistent pool with a deadline-based wait so a single hung future
    can't freeze the entire loop — abandoned futures keep running in the background while we
    move on to the next tick. TCP_USER_TIMEOUT on HTTP_SESSION ensures they eventually die."""
    pool = ThreadPoolExecutor(max_workers=max(1, TRANSCRIPTION_POLL_PARALLELISM))
    while True:
        try:
            rows = db_all(
                """
                SELECT id, event_media_id, provider_job_id, status
                FROM media_transcriptions
                WHERE status IN ('submitted', 'queued', 'processing')
                  AND provider_job_id IS NOT NULL
                  AND updated_at > NOW() - make_interval(secs => %s)
                ORDER BY updated_at ASC
                LIMIT 50
                """,
                (SONIOX_TIMEOUT_SEC,),
            ) or []
        except Exception as exc:
            db_log('stt', 'poll_worker_query', '', {}, 'error', str(exc))
            time.sleep(10)
            continue

        if rows:
            # Submit polls; wait at most TICK_DEADLINE for them to finish. Anything still in
            # flight after that keeps running, we proceed to the next tick.
            from concurrent.futures import wait, FIRST_EXCEPTION  # local import keeps top tidy
            futures = [pool.submit(_finalize_transcription, r) for r in rows]
            wait(futures, timeout=max(20.0, TRANSCRIPTION_POLL_INTERVAL_SEC * 4))

        time.sleep(max(1.0, TRANSCRIPTION_POLL_INTERVAL_SEC))


def ensure_transcription_poll_worker():
    global TRANSCRIPTION_POLL_WORKER_STARTED
    with TRANSCRIPTION_POLL_WORKER_LOCK:
        if TRANSCRIPTION_POLL_WORKER_STARTED:
            return
        threading.Thread(target=transcription_poll_worker_loop, daemon=True).start()
        TRANSCRIPTION_POLL_WORKER_STARTED = True


def wait_for_audio_completion(deal_id: int, selected_operator_id: int | None = None, selected_operator_name: str = '', entity_type: str = 'deal') -> list[str]:
    errors = []
    deadline = time.time() + EXPORT_AUDIO_WAIT_TIMEOUT_SEC
    while True:
        rows = get_deal_audio_media(deal_id, selected_operator_id, selected_operator_name, entity_type=entity_type)
        pending = []
        for row in rows:
            tr_status = (row.get('tr_status') or '').lower()
            media_status = (row.get('status') or '').lower()
            if media_status == 'ready':
                continue
            if tr_status and is_terminal_transcription_status(tr_status):
                if is_success_transcription_status(tr_status):
                    update_event_media_status(row['id'], 'ready', None)
                else:
                    msg = f"transcription_failed_media:{row['id']}:{tr_status}"
                    update_event_media_status(row['id'], 'failed', msg)
                    errors.append(msg)
                continue
            pending.append(row)
        if not pending:
            return errors
        if time.time() >= deadline:
            for row in pending:
                msg = f"transcription_timeout_media:{row['id']}"
                upsert_media_transcription(row['id'], 'failed', error_text=msg)
                update_event_media_status(row['id'], 'failed', msg)
                errors.append(msg)
            return errors
        time.sleep(max(1, EXPORT_POLL_INTERVAL_SEC))


def persist_communication_bundle(deal_id: int, events: list[dict], entity_type: str = 'deal'):
    for event in events:
        event_row = upsert_deal_event(deal_id, event, entity_type=entity_type)
        current_urls = []
        for media in event.get('media') or []:
            if media.get('source_url'):
                current_urls.append(media.get('source_url'))
            upsert_event_media(event_row['id'], media)
        if current_urls:
            db_exec(
                "DELETE FROM event_media WHERE deal_event_id=%s AND source_url IS NOT NULL AND source_url <> ALL(%s)",
                (event_row['id'], current_urls),
            )
        else:
            db_exec("DELETE FROM event_media WHERE deal_event_id=%s", (event_row['id'],))


def get_deal_events_for_export(deal_id: int, selected_operator_id: int | None = None, selected_operator_name: str = '', entity_type: str = 'deal'):
    # Provider-agnostic transcription read: prefer completed, then latest. Historical transcripts
    # from a previous STT provider remain visible after switching to a new one.
    q = """
    SELECT
      de.id AS event_id, de.event_at, de.event_type, de.channel, de.actor_role, de.actor_name,
      de.actor_id, de.text_content, de.source_type, de.source_id, de.raw_json,
      em.id AS media_id, em.media_type, em.source_url, em.status AS media_status, em.error_text AS media_error,
      mt.status AS tr_status, mt.transcript_text, mt.response_payload AS tr_payload, mt.error_text AS tr_error,
      mt.provider AS tr_provider
    FROM deal_events de
    LEFT JOIN event_media em ON em.deal_event_id = de.id
    LEFT JOIN LATERAL (
      SELECT status, transcript_text, response_payload, error_text, provider
      FROM media_transcriptions
      WHERE event_media_id = em.id
      ORDER BY (status = 'completed') DESC, completed_at DESC NULLS LAST, id DESC
      LIMIT 1
    ) mt ON TRUE
    WHERE de.deal_id = %s AND de.entity_type = %s
    ORDER BY de.event_at ASC NULLS LAST, de.id ASC, em.id ASC
    """
    rows = db_all(q, (deal_id, entity_type))
    uid = safe_int(selected_operator_id)
    selected_name = str(selected_operator_name or '').strip()
    if not uid and not selected_name:
        return rows
    return [row for row in rows if event_matches_selected_operator(row, uid, selected_name)]


def build_export_text_from_db(deal_id: int, ctx: dict, extra_errors: list[str], selected_operator_id: int | None = None, selected_operator_name: str = '', entity_type: str = 'deal'):
    filtered_ctx = apply_selected_operator_context(ctx, selected_operator_id, selected_operator_name)
    rows = get_deal_events_for_export(deal_id, selected_operator_id, selected_operator_name, entity_type=entity_type)
    grouped = {}
    for r in rows:
        eid = r['event_id']
        if eid not in grouped:
            grouped[eid] = {
                'event_at': r['event_at'],
                'event_type': r['event_type'],
                'channel': r['channel'],
                'actor_name': r.get('actor_name'),
                'actor_role': r.get('actor_role'),
                'actor_id': r.get('actor_id'),
                'text_content': r.get('text_content') or '',
                'media': [],
            }
        if r.get('media_id'):
            grouped[eid]['media'].append({
                'media_id': r.get('media_id'),
                'media_type': r.get('media_type'),
                'source_url': r.get('source_url'),
                'media_status': r.get('media_status'),
                'media_error': r.get('media_error'),
                'tr_status': r.get('tr_status'),
                'transcript_text': r.get('transcript_text'),
                'tr_payload': r.get('tr_payload'),
                'tr_error': r.get('tr_error'),
            })

    lines = []
    lines.append(f"ID сделки: {deal_id}")
    lines.append('')
    lines.append('Информация об исполнителе:')
    lines.append(f"- ID: {filtered_ctx.get('responsible_id') or '<не доступно>'}")
    lines.append(f"- Имя: {filtered_ctx.get('responsible_name') or '<не доступно>'}")
    lines.append(f"- Должность: {filtered_ctx.get('executor_position') or '<не доступно>'}")
    lines.append('')
    lines.append('Информация о клиенте:')
    lines.append(f"- Имя: {filtered_ctx.get('client_name') or '<не указан>'}")
    lines.append(f"- Contact ID: {filtered_ctx.get('contact_id') or '<нет>'}")
    lines.append(f"- Company ID: {filtered_ctx.get('company_id') or '<нет>'}")
    call_summary = filtered_ctx.get('call_summary') if isinstance(filtered_ctx.get('call_summary'), dict) else {}
    primary_call_operator = call_summary.get('primary_call_operator') if isinstance(call_summary.get('primary_call_operator'), dict) else None
    participants = call_summary.get('participants') if isinstance(call_summary.get('participants'), list) else []
    lines.append('')
    lines.append('Контекст сотрудников по звонкам:')
    if primary_call_operator and safe_int(primary_call_operator.get('user_id')):
        lines.append(
            f"- Основной сотрудник на созвоне: {primary_call_operator.get('user_name') or '<не доступно>'} "
            f"(ID: {primary_call_operator.get('user_id')}, длительность: {primary_call_operator.get('duration_sec') or 0} сек)"
        )
    else:
        lines.append('- Основной сотрудник на созвоне: <не определён>')
    others = []
    for p in participants:
        if primary_call_operator and safe_int(p.get('user_id')) == safe_int(primary_call_operator.get('user_id')):
            continue
        others.append(
            f"{p.get('user_name') or '<не доступно>'} (ID: {p.get('user_id')}, "
            f"handled: {p.get('handled_calls') or 0}, недозвон: {p.get('ndz_calls') or 0}, пропущено: {p.get('missed_calls') or 0})"
        )
    if others:
        lines.append(f"- Другие участники сделки: {'; '.join(others)}")
    else:
        lines.append('- Другие участники сделки: <нет>')
    cc = filtered_ctx.get('card_completeness') or {}
    lines.append('')
    if int(cc.get('total') or 0) > 0:
        lines.append(f"Заполненность карточки клиента (Bitrix): {cc.get('filled', 0)}/{cc.get('total', 0)} ({cc.get('percent', 0)}%).")
        lines.append('')
    lines.append('Хронология коммуникаций:')
    lines.append('')

    errors = list(extra_errors or [])
    events = list(grouped.values())
    events.sort(key=lambda x: (x['event_at'] is None, x['event_at'] or datetime.now(timezone.utc)))
    for e in events:
        actor = e.get('actor_name') or ('Клиент' if e.get('actor_role') == 'client' else 'Исполнитель')
        ts = fmt_ts(e.get('event_at'))
        text = (e.get('text_content') or '').strip()
        if e.get('channel') == 'call':
            lines.append(f"[{ts}] {actor} -> Звонок: {text or '<без описания>'}")
        elif e.get('event_type') == 'deal_comment':
            lines.append(f"[{ts}] {actor} -> Комментарий в карточке: {text or '<пусто>'}")
        elif e.get('event_type') == 'reminder':
            lines.append(f"[{ts}] {actor} -> Напоминание: {text or '<без описания>'}")
        elif e.get('channel') == 'activity':
            lines.append(f"[{ts}] {actor} -> Активность CRM: {text or '<без описания>'}")
        elif e.get('event_type') == 'whatsapp_audio':
            lines.append(f"[{ts}] {actor} -> WhatsApp аудио: {text or 'Аудиосообщение'}")
        elif e.get('event_type') == 'whatsapp_file':
            lines.append(f"[{ts}] {actor} -> WhatsApp файл: {text or 'Вложение'}")
        elif e.get('channel') == 'timeline':
            lines.append(f"[{ts}] {actor} -> Комментарий таймлайна: {text or '<пусто>'}")
        else:
            lines.append(f"[{ts}] {actor} -> WhatsApp сообщение: {text or '<пусто>'}")

        for media in e.get('media') or []:
            if media.get('media_type') != 'audio':
                continue
            tr_text = format_transcript_for_txt(media.get('transcript_text'), media.get('tr_payload'))
            if tr_text:
                lines.append('Транскрипт:')
                lines.append(tr_text)
            else:
                reason = media.get('tr_error') or media.get('media_error') or media.get('tr_status') or media.get('media_status') or 'нет данных'
                msg = f'audio_missing_transcript_media:{media.get("media_id")}:{reason}'
                lines.append(f"[ERROR] Транскрипция аудио недоступна: {reason}")
                errors.append(msg)
        lines.append('')

    if errors:
        lines.append('Ошибки данных/доступа:')
        for err in errors:
            lines.append(f"- {err}")
        lines.append('')

    export_text = '\n'.join(lines).strip() + '\n'
    snapshot = {
        'deal': ctx.get('deal') or {},
        'responsible': {
            'id': filtered_ctx.get('responsible_id'),
            'name': filtered_ctx.get('responsible_name'),
            'position': filtered_ctx.get('executor_position'),
        },
        'client': {
            'name': filtered_ctx.get('client_name'),
            'contact_id': filtered_ctx.get('contact_id'),
            'company_id': filtered_ctx.get('company_id'),
        },
        'call_summary': call_summary,
        'card_completeness': cc,
        'selected_operator': {
            'id': filtered_ctx.get('selected_operator_id'),
            'name': filtered_ctx.get('selected_operator_name'),
        },
        'events': rows,
        'errors': errors,
    }
    return export_text, snapshot, errors


def process_export_job(export_id: int):
    row = db_one("SELECT * FROM analysis_exports WHERE id=%s", (export_id,))
    if not row:
        return
    deal_id = safe_int(row.get('deal_id'))
    entity_type = str(row.get('entity_type') or 'deal').strip().lower() or 'deal'
    if entity_type not in ('deal', 'lead'):
        entity_type = 'deal'
    batch_id = safe_int(row.get('batch_id'))
    user_id = safe_int(row.get('user_id'))
    bitrix_connection_id = safe_int(row.get('bitrix_connection_id'))
    selected_operator_id = safe_int(row.get('selected_operator_id'))
    selected_operator_name = str(row.get('selected_operator_name') or '').strip()
    if not deal_id or not user_id:
        set_analysis_export_status(export_id, 'failed', 'missing_deal')
        update_export_status_stage(export_id, 'error', 'Ошибка инициализации обработки', 'missing_deal_or_user')
        if batch_id:
            log_batch_progress(batch_id, 'export_invalid')
            finalize_batch_if_ready(batch_id)
        return

    set_analysis_export_status(export_id, 'processing', None)
    if not batch_id:
        entity_label = 'лида' if entity_type == 'lead' else 'сделки'
        update_export_status_stage(export_id, 'bitrix_fetch', f'Получаю данные {entity_label} из Bitrix')
    db_log('web', 'deal_export_started', str(deal_id), {'export_id': export_id, 'batch_id': batch_id, 'entity_type': entity_type}, 'ok', None)
    if batch_id:
        log_batch_progress(batch_id, 'export_started')
    bitrix_ctx = get_user_bitrix_context(user_id, connection_id=bitrix_connection_id)
    standard = get_user_default_standard_version(user_id)
    card_fields = get_standard_card_fields(safe_int((standard or {}).get('id'))) if standard else []
    bundle = collect_communication_events(deal_id, bitrix_ctx=bitrix_ctx, entity_type=entity_type, card_fields=card_fields)
    persist_communication_bundle(deal_id, bundle['events'], entity_type=entity_type)
    if not batch_id:
        update_export_status_stage(export_id, 'bitrix_parsed', 'Данные из Bitrix получены и сохранены')
    selected_ctx = apply_selected_operator_context(bundle['context'], selected_operator_id, selected_operator_name)
    audio_rows = get_deal_audio_media(deal_id, selected_operator_id, selected_operator_name, entity_type=entity_type)
    audio_count = len(audio_rows)
    if not batch_id:
        if audio_count > 0:
            update_export_status_stage(export_id, 'stt_submit', f'Отправляю аудио в Soniox ({audio_count})')
        else:
            update_export_status_stage(export_id, 'stt_skip', 'Аудио не найдено, перехожу к анализу')
    queue_and_process_audio(deal_id, selected_operator_id, selected_operator_name, entity_type=entity_type)
    wait_errors = wait_for_audio_completion(deal_id, selected_operator_id, selected_operator_name, entity_type=entity_type)
    if not batch_id and audio_count > 0:
        if wait_errors:
            update_export_status_stage(export_id, 'stt_done', 'Транскрипция завершена с ошибками', '; '.join(wait_errors[:2]))
        else:
            update_export_status_stage(export_id, 'stt_done', 'Транскрипция из Soniox получена')
    final_errors = list(bundle['errors']) + wait_errors
    export_text, snapshot, text_errors = build_export_text_from_db(
        deal_id,
        bundle['context'],
        final_errors,
        selected_operator_id,
        selected_operator_name,
        entity_type=entity_type,
    )
    has_errors = bool(text_errors)

    filename = f"deal_{deal_id}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.txt"
    final_error_summary = '; '.join(text_errors) if has_errors else None
    update_analysis_export_result(export_id, {
        'deal_id': deal_id,
        'client_name': selected_ctx['client_name'],
        'client_contact_id': selected_ctx['contact_id'],
        'client_company_id': selected_ctx['company_id'],
        'responsible_id': selected_ctx['responsible_id'],
        'responsible_name': selected_ctx['responsible_name'],
        'executor_position': selected_ctx['executor_position'],
        'snapshot': snapshot,
        'export_text': export_text,
        'status': 'completed_with_errors' if has_errors else 'completed',
        'error_summary': final_error_summary,
    })
    if has_errors:
        record_export_failure(export_id, final_error_summary or '')
    else:
        # Successful export — clear any prior retry state from previous attempts.
        db_exec(
            "UPDATE analysis_exports SET error_kind = NULL, retry_after = NULL WHERE id = %s",
            (export_id,),
        )
    upsert_call_text(
        export_id,
        deal_id,
        f'Хронология сделки {deal_id}',
        export_text,
    )
    if batch_id:
        create_analysis_run(export_id, 'queued')
        ensure_qa_worker()
        log_batch_progress(batch_id, 'export_completed')
        finalize_batch_if_ready(batch_id)
    else:
        update_export_status_stage(export_id, 'claude_queue', 'Подготовил данные, отправляю в Claude')
        create_analysis_run(export_id, 'queued')
        ensure_qa_worker()
    db_log('telegram', 'deal_export', str(deal_id), {'export_id': export_id, 'batch_id': batch_id}, 'ok', None)


# Parallelism for export processing (Bitrix fetch + audio submit + Claude wait).
EXPORT_PARALLELISM = int(os.getenv('EXPORT_PARALLELISM', '4'))


def _run_export_with_failure_handling(jid: int):
    try:
        process_export_job(jid)
    except Exception as exc:
        set_analysis_export_status(jid, 'failed', str(exc))
        j = db_one("SELECT deal_id, batch_id FROM analysis_exports WHERE id=%s", (jid,))
        update_export_status_stage(jid, 'error', 'Ошибка на этапе Bitrix/транскрибации', str(exc))
        try:
            record_export_failure(jid, str(exc))
        except Exception:
            pass
        if j and j.get('batch_id'):
            log_batch_progress(int(j['batch_id']), 'export_failed')
            finalize_batch_if_ready(int(j['batch_id']))
        db_log('web', 'deal_export', str(j.get('deal_id') if j else None), {'export_id': jid, 'batch_id': j.get('batch_id') if j else None}, 'error', str(exc))


def export_worker_loop():
    """Picks queued exports and runs them in parallel up to EXPORT_PARALLELISM. Atomically claims
    each job (sets status='processing') so multiple workers / retry loops don't double-process."""
    pool = ThreadPoolExecutor(max_workers=max(1, EXPORT_PARALLELISM))
    in_flight: set[int] = set()
    in_flight_lock = threading.Lock()

    def submit_job(jid: int):
        def runner():
            try:
                _run_export_with_failure_handling(jid)
            finally:
                with in_flight_lock:
                    in_flight.discard(jid)
        with in_flight_lock:
            in_flight.add(jid)
        pool.submit(runner)

    while True:
        with in_flight_lock:
            slots_free = max(0, EXPORT_PARALLELISM - len(in_flight))
            currently_in_flight = list(in_flight)
        if slots_free <= 0:
            time.sleep(max(1, EXPORT_WORKER_INTERVAL_SEC))
            continue

        # Atomic claim: flip status='queued' → 'processing' for the next batch of due rows.
        # Excluding rows already running in this process via NOT IN.
        excl = currently_in_flight or [-1]
        rows = db_all(
            """
            UPDATE analysis_exports
            SET status = 'processing', updated_at = NOW()
            WHERE id IN (
              SELECT id FROM analysis_exports
              WHERE (status = 'queued'
                     OR (status = 'processing' AND updated_at < NOW() - INTERVAL '10 minutes'))
                AND id <> ALL(%s)
              ORDER BY created_at ASC
              LIMIT %s
              FOR UPDATE SKIP LOCKED
            )
            RETURNING id
            """,
            (excl, slots_free),
        ) or []

        if not rows:
            time.sleep(max(1, EXPORT_WORKER_INTERVAL_SEC))
            continue

        for r in rows:
            submit_job(int(r['id']))


def export_retry_worker_loop():
    """Re-runs exports whose `retry_after` is due (billing-class auto-recovery). Resumes via
    the standard export pipeline — `process_export_job` reuses already-completed transcripts
    and only redoes what failed."""
    while True:
        try:
            rows = db_all(
                """
                SELECT id FROM analysis_exports
                WHERE retry_after IS NOT NULL AND retry_after <= NOW()
                ORDER BY retry_after ASC
                LIMIT 5
                """
            ) or []
            for r in rows:
                eid = int(r['id'])
                # Clear schedule first so a long-running retry doesn't fire twice.
                db_exec("UPDATE analysis_exports SET retry_after = NULL WHERE id = %s", (eid,))
                try:
                    process_export_job(eid)
                except Exception as exc:
                    db_log('web', 'auto_retry_export', str(eid), {}, 'error', str(exc))
        except Exception as exc:
            db_log('web', 'auto_retry_loop', '', {}, 'error', str(exc))
        time.sleep(60)


def ensure_export_worker():
    global EXPORT_WORKER_STARTED
    with EXPORT_WORKER_LOCK:
        if EXPORT_WORKER_STARTED:
            return
        threading.Thread(target=export_worker_loop, daemon=True).start()
        threading.Thread(target=export_retry_worker_loop, daemon=True).start()
        EXPORT_WORKER_STARTED = True
    ensure_transcription_poll_worker()


def _do_proactive_token_refresh():
    rows = db_all(
        """
        SELECT id, user_id, bitrix_domain, bitrix_expires_at
        FROM user_bitrix_connections
        WHERE status = 'active'
          AND bitrix_refresh_token IS NOT NULL
          AND bitrix_refresh_token != ''
        """,
        (),
    )
    # Refresh any token expiring within the next 2 hours so the refresh_token
    # never goes stale (Bitrix issues a new refresh_token on every refresh call).
    threshold = now_ts() + 2 * 3600
    refreshed, skipped, errors = 0, 0, 0
    for row in rows:
        raw_exp = row.get('bitrix_expires_at')
        expires_ts = int(raw_exp.timestamp()) if raw_exp else 0
        if expires_ts > threshold:
            skipped += 1
            continue
        try:
            get_user_bitrix_context(int(row['user_id']), connection_id=int(row['id']), force_refresh=True)
            refreshed += 1
        except Exception as exc:
            errors += 1
            print(f"[token_refresh] conn={row['id']} domain={row.get('bitrix_domain')}: {exc}", flush=True)
    if refreshed or errors:
        print(f"[token_refresh] refreshed={refreshed} skipped={skipped} errors={errors}", flush=True)


def _token_refresh_worker_loop():
    # Initial delay so the server is fully up before first network call
    time.sleep(60)
    while True:
        try:
            _do_proactive_token_refresh()
        except Exception as exc:
            print(f"[token_refresh] loop error: {exc}", flush=True)
        time.sleep(30 * 60)  # repeat every 30 minutes


def ensure_token_refresh_worker():
    global TOKEN_REFRESH_STARTED
    with TOKEN_REFRESH_LOCK:
        if TOKEN_REFRESH_STARTED:
            return
        t = threading.Thread(target=_token_refresh_worker_loop, daemon=True)
        t.start()
        TOKEN_REFRESH_STARTED = True


def get_standard_modules(version_id: int):
    return db_all(
        """
        SELECT
          m.id AS standard_module_id,
          b.block_name,
          b.sort_order AS block_sort,
          m.module_name,
          m.module_weight_percent,
          m.module_details,
          m.scoring_rules,
          m.sort_order AS module_sort
        FROM qa_standard_modules m
        JOIN qa_standard_blocks b ON b.id = m.block_id
        WHERE m.standard_version_id = %s AND m.is_scored = TRUE
        ORDER BY b.sort_order ASC, m.sort_order ASC
        """,
        (version_id,),
    )


def create_analysis_run(export_id: int, status: str = 'queued'):
    export_owner = db_one("SELECT user_id FROM analysis_exports WHERE id=%s", (export_id,)) or {}
    standard = get_user_default_standard_version(export_owner.get('user_id'))
    if not standard:
        raise RuntimeError('no_active_standard')
    last = db_one("SELECT COALESCE(MAX(run_version), 0) AS mx FROM qa_analysis_runs WHERE export_id=%s", (export_id,))
    run_version = int(last['mx']) + 1
    return db_one(
        """
        INSERT INTO qa_analysis_runs(export_id, standard_version_id, run_version, status, claude_model, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
        RETURNING id, export_id, standard_version_id, run_version, status
        """,
        (export_id, standard['id'], run_version, status, ANTHROPIC_MODEL),
    )


def build_claude_prompts(export_id: int, standard_version_id: int, export_text: str):
    modules = get_standard_modules(standard_version_id)
    export_row = db_one("SELECT source_snapshot_json FROM analysis_exports WHERE id=%s", (export_id,))
    snapshot = export_row.get('source_snapshot_json') if export_row else {}
    if isinstance(snapshot, str):
        try:
            snapshot = json.loads(snapshot)
        except Exception:
            snapshot = {}
    if not isinstance(snapshot, dict):
        snapshot = {}
    call_context = snapshot.get('call_summary') if isinstance(snapshot.get('call_summary'), dict) else {}
    modules_for_prompt = []
    for m in modules:
        modules_for_prompt.append({
            'standard_module_id': m['standard_module_id'],
            'block_name': m['block_name'],
            'module_name': m['module_name'],
            'module_weight_percent': float(m['module_weight_percent']),
            'module_details': m['module_details'] or '',
            'scoring_rules': m['scoring_rules'] or '',
        })
    system_prompt = load_qa_system_prompt()
    tpl = load_qa_user_prompt_template()
    base = tpl.replace('__EXPORT_ID__', str(export_id)).replace('__STANDARD_VERSION_ID__', str(standard_version_id))
    required_format = {
        'schema_version': 'qa_call_analysis_v1',
        'export_id': export_id,
        'standard_version_id': standard_version_id,
        'overall_score_0_100': 'number(0..100)',
        'modules': [
            {
                'block_name': 'string',
                'module_name': 'string',
                'module_weight_percent': 'number',
                'raw_coef': '0|0.5|1',
                'weighted_points': 'number',
                'evidence': ['string'],
                'comment': 'string (observation)',
            }
        ],
        'final_summary': 'string',
        'touches': {
            'count': 'int',
            'items': [
                {'timestamp_utc': 'string', 'channel': 'call|whatsapp|other', 'direction': 'client_to_operator|operator_to_client|bidirectional|unknown', 'snippet': 'string'}
            ],
            'analysis': {
                'summary': 'string',
                'primary_touch': 'string',
                'preamble_assessment': 'string',
                'delay_findings': ['string'],
                'missed_callback_findings': ['string'],
                'chat_to_call_findings': ['string'],
                'operator_timing_assessment': 'string',
                'recommendations': ['string'],
            },
        },
        'recommendations': ['string'],
        'calculation_check': {
            'sum_weighted_points': 'number',
            'rounded_overall_score_0_100': 'number',
            'formula': 'overall_score_0_100 = round(sum(weighted_points), 2)',
        },
    }
    user_prompt = (
        f"{base}\n\n"
        f"required_format:\n{json.dumps(required_format, ensure_ascii=False, indent=2)}\n\n"
        f"modules_catalog:\n{json.dumps(modules_for_prompt, ensure_ascii=False, indent=2)}\n\n"
        f"call_context:\n{json.dumps(call_context, ensure_ascii=False, indent=2)}\n\n"
        "touch_analysis_rules:\n"
        "- Касанием считать только аудио-звонок (call).\n"
        "- Если звонков несколько, выдели основной диалог как primary_touch и объясни почему.\n"
        "- Все события до основного диалога считать преамбулой (дозвоны, переписка, напоминания).\n"
        "- Отметь несвоевременный ответ/перезвон, если видны большие паузы между входящим и ответом сотрудника.\n"
        "- Если путь был через переписку к звонку, отдельно опиши это в chat_to_call_findings.\n\n"
        f"transcript_text:\n{export_text}\n"
    )
    return system_prompt, user_prompt


def build_claude_translation_prompts(normalized: dict):
    system_prompt = (
        "Ты переводчик JSON-данных для QA-отчета. "
        "Переводи только на казахский язык. "
        "Сохраняй смысл, деловой тон и краткость. "
        "Верни строго один валидный JSON-объект без markdown и без текста вне JSON."
    )
    translation_source = {
        'final_summary': normalized.get('final_summary') or '',
        'modules': [
            {
                'standard_module_id': int(m['standard_module_id']),
                'comment': str(m.get('comment_ru') or ''),
            }
            for m in normalized.get('modules', [])
        ],
        'touches_analysis': {
            'summary': str((normalized.get('touches_analysis') or {}).get('summary') or ''),
            'primary_touch': str((normalized.get('touches_analysis') or {}).get('primary_touch') or ''),
            'preamble_assessment': str((normalized.get('touches_analysis') or {}).get('preamble_assessment') or ''),
            'delay_findings': list((normalized.get('touches_analysis') or {}).get('delay_findings') or []),
            'missed_callback_findings': list((normalized.get('touches_analysis') or {}).get('missed_callback_findings') or []),
            'chat_to_call_findings': list((normalized.get('touches_analysis') or {}).get('chat_to_call_findings') or []),
            'operator_timing_assessment': str((normalized.get('touches_analysis') or {}).get('operator_timing_assessment') or ''),
            'recommendations': list((normalized.get('touches_analysis') or {}).get('recommendations') or []),
        },
        'recommendations': list(normalized.get('recommendations') or []),
    }
    required_format = {
        'final_summary_kk': 'string',
        'modules': [
            {
                'standard_module_id': 'int',
                'comment_kk': 'string',
            }
        ],
        'touches_analysis': {
            'summary_kk': 'string',
            'primary_touch_kk': 'string',
            'preamble_assessment_kk': 'string',
            'delay_findings_kk': ['string'],
            'missed_callback_findings_kk': ['string'],
            'chat_to_call_findings_kk': ['string'],
            'operator_timing_assessment_kk': 'string',
            'recommendations_kk': ['string'],
        },
        'recommendations_kk': ['string'],
    }
    user_prompt = (
        "Переведи поля QA-анализа на казахский язык и верни только JSON.\n"
        "Правила:\n"
        "1. Не меняй структуру и идентификаторы.\n"
        "2. Не добавляй новые поля.\n"
        "3. Переводи кратко, без воды.\n\n"
        f"required_format:\n{json.dumps(required_format, ensure_ascii=False, indent=2)}\n\n"
        f"source:\n{json.dumps(translation_source, ensure_ascii=False, indent=2)}\n"
    )
    return system_prompt, user_prompt


def _str_list_safe(v):
    if not isinstance(v, list):
        return []
    return [str(x).strip() for x in v if str(x).strip()]


def validate_and_apply_kazakh_translation(normalized: dict, raw: dict):
    if not isinstance(raw, dict):
        raise RuntimeError('translation_not_object')
    normalized['final_summary_kk'] = str(raw.get('final_summary_kk') or '').strip()
    modules_raw = raw.get('modules')
    if not isinstance(modules_raw, list):
        modules_raw = []
    by_id = {}
    for item in modules_raw:
        if not isinstance(item, dict):
            continue
        sid = safe_int(item.get('standard_module_id'))
        if not sid:
            continue
        by_id[sid] = item
    for module in normalized.get('modules', []):
        sid = int(module['standard_module_id'])
        translated = by_id.get(sid) or {}
        module['comment_kk'] = str(translated.get('comment_kk') or '').strip()
    ta_raw = raw.get('touches_analysis') if isinstance(raw.get('touches_analysis'), dict) else {}
    touches_analysis = normalized.get('touches_analysis') or {}
    touches_analysis['summary_kk'] = str(ta_raw.get('summary_kk') or '').strip()
    touches_analysis['primary_touch_kk'] = str(ta_raw.get('primary_touch_kk') or '').strip()
    touches_analysis['preamble_assessment_kk'] = str(ta_raw.get('preamble_assessment_kk') or '').strip()
    touches_analysis['delay_findings_kk'] = _str_list_safe(ta_raw.get('delay_findings_kk'))
    touches_analysis['missed_callback_findings_kk'] = _str_list_safe(ta_raw.get('missed_callback_findings_kk'))
    touches_analysis['chat_to_call_findings_kk'] = _str_list_safe(ta_raw.get('chat_to_call_findings_kk'))
    touches_analysis['operator_timing_assessment_kk'] = str(ta_raw.get('operator_timing_assessment_kk') or '').strip()
    touches_analysis['recommendations_kk'] = _str_list_safe(ta_raw.get('recommendations_kk'))
    normalized['touches_analysis'] = touches_analysis
    normalized['recommendations_kk'] = _str_list_safe(raw.get('recommendations_kk'))
    return normalized


def validate_and_normalize_analysis(run: dict, raw: dict, standard_modules: list[dict]):
    if not isinstance(raw, dict):
        raise RuntimeError('analysis_not_object')
    required = ['schema_version', 'export_id', 'standard_version_id', 'modules']
    for key in required:
        if key not in raw:
            raise RuntimeError(f'analysis_missing_field:{key}')
    if raw.get('schema_version') != 'qa_call_analysis_v1':
        raise RuntimeError('analysis_bad_schema_version')
    if int(raw.get('export_id') or 0) != int(run['export_id']):
        raise RuntimeError('analysis_bad_export_id')
    if int(raw.get('standard_version_id') or 0) != int(run['standard_version_id']):
        raise RuntimeError('analysis_bad_standard_version_id')
    modules = raw.get('modules')
    if not isinstance(modules, list) or not modules:
        raise RuntimeError('analysis_modules_empty')

    module_map = {(m['block_name'], m['module_name']): m for m in standard_modules}
    normalized_modules = []
    sum_points = 0.0
    for item in modules:
        if not isinstance(item, dict):
            continue
        block_name = str(item.get('block_name') or '').strip()
        module_name = str(item.get('module_name') or '').strip()
        key = (block_name, module_name)
        std = module_map.get(key)
        if not std:
            continue
        try:
            raw_coef = float(item.get('raw_coef'))
        except Exception:
            raise RuntimeError(f'analysis_bad_raw_coef:{block_name}:{module_name}')
        if raw_coef not in (0.0, 0.5, 1.0):
            raise RuntimeError(f'analysis_bad_raw_coef:{block_name}:{module_name}')
        module_weight = float(std['module_weight_percent'])
        weighted_points = quant2(raw_coef * module_weight)
        evidence = item.get('evidence')
        if not isinstance(evidence, list):
            evidence = []
        raw_comment = str(item.get('comment') or '').strip()
        normalized_modules.append({
            'standard_module_id': std['standard_module_id'],
            'block_name': block_name,
            'module_name': module_name,
            'module_weight_percent': module_weight,
            'raw_coef': raw_coef,
            'weighted_points': weighted_points,
            'comment_ru': raw_comment,
            'comment_kk': '',
            'evidence': [str(x) for x in evidence if str(x).strip()],
        })
        sum_points += weighted_points

    if not normalized_modules:
        raise RuntimeError('analysis_modules_not_matched')
    overall = quant2(sum_points)

    touches = raw.get('touches') if isinstance(raw.get('touches'), dict) else {}
    touch_items = touches.get('items') if isinstance(touches.get('items'), list) else []
    normalized_touches = []
    for ti in touch_items:
        if not isinstance(ti, dict):
            continue
        normalized_touches.append({
            'timestamp_utc': str(ti.get('timestamp_utc') or ''),
            'channel': str(ti.get('channel') or 'other'),
            'direction': str(ti.get('direction') or 'unknown'),
            'snippet': str(ti.get('snippet') or ''),
        })
    touches_count = int(touches.get('count') or len(normalized_touches))
    touches_analysis_raw = touches.get('analysis') if isinstance(touches.get('analysis'), dict) else {}
    def _str_list(v):
        if not isinstance(v, list):
            return []
        return [str(x).strip() for x in v if str(x).strip()]
    normalized_touch_analysis = {
        'summary': str(touches_analysis_raw.get('summary') or ''),
        'primary_touch': str(touches_analysis_raw.get('primary_touch') or ''),
        'preamble_assessment': str(touches_analysis_raw.get('preamble_assessment') or ''),
        'delay_findings': _str_list(touches_analysis_raw.get('delay_findings')),
        'missed_callback_findings': _str_list(touches_analysis_raw.get('missed_callback_findings')),
        'chat_to_call_findings': _str_list(touches_analysis_raw.get('chat_to_call_findings')),
        'operator_timing_assessment': str(touches_analysis_raw.get('operator_timing_assessment') or ''),
        'recommendations': _str_list(touches_analysis_raw.get('recommendations')),
        'summary_kk': '',
        'primary_touch_kk': '',
        'preamble_assessment_kk': '',
        'delay_findings_kk': [],
        'missed_callback_findings_kk': [],
        'chat_to_call_findings_kk': [],
        'operator_timing_assessment_kk': '',
        'recommendations_kk': [],
    }
    recommendations = raw.get('recommendations') if isinstance(raw.get('recommendations'), list) else []
    recommendations = [str(x) for x in recommendations if str(x).strip()]
    if not recommendations:
        recommendations = ['Рекомендации не сформированы моделью.']

    return {
        'schema_version': 'qa_call_analysis_v1',
        'export_id': int(run['export_id']),
        'standard_version_id': int(run['standard_version_id']),
        'modules': normalized_modules,
        'overall_score_0_100': overall,
        'final_summary': str(raw.get('final_summary') or ''),
        'final_summary_kk': '',
        'touches_count': max(0, touches_count),
        'touches_items': normalized_touches,
        'touches_analysis': normalized_touch_analysis,
        'recommendations': recommendations,
        'recommendations_kk': [],
        'calculation_check': {
            'sum_weighted_points': overall,
            'rounded_overall_score_0_100': overall,
            'formula': 'overall_score_0_100 = round(sum(weighted_points), 2)',
        },
    }


def persist_analysis_result(run_id: int, normalized: dict):
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM qa_analysis_module_scores WHERE run_id=%s", (run_id,))
        cur.execute("DELETE FROM qa_analysis_summary WHERE run_id=%s", (run_id,))
        cur.execute("DELETE FROM qa_analysis_touches WHERE run_id=%s", (run_id,))
        cur.execute("DELETE FROM qa_analysis_recommendations WHERE run_id=%s", (run_id,))

        for m in normalized['modules']:
            cur.execute(
                """
                INSERT INTO qa_analysis_module_scores(
                  run_id, standard_module_id, block_name, module_name, module_weight_percent,
                  raw_coef, weighted_points, comment, evidence_json
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    run_id,
                    m['standard_module_id'],
                    m['block_name'],
                    m['module_name'],
                    m['module_weight_percent'],
                    m['raw_coef'],
                    m['weighted_points'],
                    m['comment_ru'],
                    json.dumps({
                        'evidence': m['evidence'],
                        'comment_kk': m.get('comment_kk') or '',
                    }, ensure_ascii=False),
                ),
            )

        cur.execute(
            """
            INSERT INTO qa_analysis_summary(
              run_id, overall_score_0_100, final_summary, final_summary_kk,
              sum_weighted_points, rounded_overall_score_0_100, formula
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                run_id,
                normalized['overall_score_0_100'],
                normalized['final_summary'],
                normalized.get('final_summary_kk') or '',
                normalized['calculation_check']['sum_weighted_points'],
                normalized['calculation_check']['rounded_overall_score_0_100'],
                normalized['calculation_check']['formula'],
            ),
        )
        cur.execute(
            """
            INSERT INTO qa_analysis_touches(run_id, touches_count, items_json)
            VALUES (%s, %s, %s::jsonb)
            """,
            (
                run_id,
                normalized['touches_count'],
                json.dumps(
                    {
                        'version': 'touch_analysis_v1',
                        'items': normalized['touches_items'],
                        'analysis': normalized.get('touches_analysis') or {},
                    },
                    ensure_ascii=False,
                ),
            ),
        )
        for idx, rec in enumerate(normalized['recommendations'], 1):
            cur.execute(
                """
                INSERT INTO qa_analysis_recommendations(run_id, sort_order, recommendation_text, recommendation_text_kk)
                VALUES (%s, %s, %s, %s)
                """,
                (run_id, idx, rec, normalized.get('recommendations_kk', [''])[idx - 1] if idx - 1 < len(normalized.get('recommendations_kk', [])) else ''),
            )


def ensure_report_link(run_id: int, export_id: int):
    existing = db_one("SELECT public_id FROM qa_report_links WHERE run_id=%s", (run_id,))
    if existing:
        # Make sure prior runs for this export are not still flagged active — when an export
        # gets re-run (manual retry, auto-retry after a network blip), only the latest run's
        # link should be the one fetched by aggregate queries. Without this, we'd accidentally
        # show stale reports.
        db_exec(
            "UPDATE qa_report_links SET is_active = FALSE WHERE export_id = %s AND run_id <> %s AND is_active = TRUE",
            (export_id, run_id),
        )
        return existing['public_id']
    for _ in range(10):
        pid = generate_public_id()
        try:
            db_exec(
                "INSERT INTO qa_report_links(run_id, export_id, public_id, is_active, created_at) VALUES (%s, %s, %s, TRUE, NOW())",
                (run_id, export_id, pid),
            )
            # Deactivate any previous active links for this export (older runs).
            db_exec(
                "UPDATE qa_report_links SET is_active = FALSE WHERE export_id = %s AND run_id <> %s AND is_active = TRUE",
                (export_id, run_id),
            )
            return pid
        except Exception:
            continue
    raise RuntimeError('public_id_generation_failed')


def _trigger_employee_cycle(run_id: int, export: dict):
    employee_id = safe_int(export.get('employee_id'))
    user_id = safe_int(export.get('user_id'))
    if employee_id and user_id:
        import threading as _threading
        _threading.Thread(
            target=check_employee_plan_trigger,
            args=(run_id, employee_id, user_id),
            daemon=True,
        ).start()


def process_qa_run(run_id: int):
    run = db_one("SELECT * FROM qa_analysis_runs WHERE id=%s", (run_id,))
    if not run:
        return
    if run['status'] not in ('queued', 'processing'):
        return
    db_exec("UPDATE qa_analysis_runs SET status='processing', started_at=COALESCE(started_at, NOW()), updated_at=NOW() WHERE id=%s", (run_id,))
    export = db_one("SELECT id, export_text, batch_id, deal_id, responsible_id, responsible_name, client_name, user_id, employee_id FROM analysis_exports WHERE id=%s", (run['export_id'],))
    if not export or not export.get('export_text'):
        raise RuntimeError('missing_export_text')
    batch_id = safe_int(export.get('batch_id'))
    if not batch_id or str(export.get('source') or 'telegram') != 'telegram':
        update_export_status_stage(int(run['export_id']), 'claude_processing', 'Данные отправлены в Claude, жду ответ')
    db_log('qa', 'analysis_run_started', str(run_id), {'export_id': run['export_id'], 'batch_id': batch_id, 'deal_id': export.get('deal_id')}, 'ok', None)
    if batch_id:
        log_batch_progress(batch_id, 'qa_started')
    standard_modules = get_standard_modules(run['standard_version_id'])
    if not standard_modules:
        raise RuntimeError('standard_modules_not_found')
    system_prompt, user_prompt = build_claude_prompts(run['export_id'], run['standard_version_id'], export['export_text'])
    parsed, req_payload, resp_payload = call_claude_json(system_prompt, user_prompt, model=ANTHROPIC_MODEL_QA)
    normalized = validate_and_normalize_analysis(run, parsed, standard_modules)
    persist_analysis_result(run_id, normalized)
    public_id = ensure_report_link(run_id, run['export_id'])
    # A successful analysis is the final answer. Clear any stale failure metadata from
    # earlier attempts AND flip the export status back to 'completed' if all audio is now
    # transcribed (re-check media state — what failed on the prior attempt may have since
    # been recovered by the poll worker / retry).
    audio_unfinished = db_one(
        """
        SELECT COUNT(*) AS n
        FROM event_media em
        JOIN deal_events de ON de.id = em.deal_event_id
        JOIN analysis_exports ae ON ae.deal_id = de.deal_id AND ae.id = %s
        WHERE em.media_type = 'audio' AND em.status NOT IN ('ready', 'failed')
        """,
        (run['export_id'],),
    ) or {}
    if int(audio_unfinished.get('n') or 0) == 0:
        db_exec(
            """
            UPDATE analysis_exports
            SET retry_after = NULL, error_kind = NULL, error_summary = NULL,
                status = CASE
                    WHEN EXISTS (
                        SELECT 1 FROM event_media em2
                        JOIN deal_events de2 ON de2.id = em2.deal_event_id
                        WHERE de2.deal_id = analysis_exports.deal_id
                          AND em2.media_type = 'audio' AND em2.status = 'failed'
                    ) THEN 'completed_with_errors'
                    ELSE 'completed'
                END
            WHERE id = %s
            """,
            (run['export_id'],),
        )
    else:
        db_exec(
            "UPDATE analysis_exports SET retry_after = NULL, error_kind = NULL WHERE id = %s",
            (run['export_id'],),
        )
    report_url = f"{REPORT_PUBLIC_BASE_URL.rstrip('/')}{report_path(public_id, safe_int(export.get('responsible_id')))}"
    db_exec(
        """
        UPDATE qa_analysis_runs
        SET status='completed', response_json=%s::jsonb, request_json=%s::jsonb, completed_at=NOW(), updated_at=NOW(), error_text=NULL
        WHERE id=%s
        """,
        (
            json.dumps(to_jsonable({'analysis': parsed}), ensure_ascii=False),
            json.dumps(to_jsonable({'analysis': req_payload}), ensure_ascii=False),
            run_id,
        ),
    )
    if not batch_id:
        update_export_status_stage(int(run['export_id']), 'completed', f'Анализ готов. Ссылка: {report_url}')
    if batch_id:
        log_batch_progress(batch_id, 'qa_completed')
        finalize_batch_if_ready(batch_id)
    db_log('qa', 'analysis_run_completed', str(run_id), {'export_id': run['export_id'], 'batch_id': batch_id, 'report_url': report_url}, 'ok', None)
    _trigger_employee_cycle(run_id, export)


def qa_worker_loop():
    while True:
        run = db_one(
            """
            SELECT id
            FROM qa_analysis_runs
            WHERE status = 'queued'
               OR (status = 'processing' AND updated_at < NOW() - INTERVAL '10 minutes')
            ORDER BY created_at ASC
            LIMIT 1
            """
        )
        if not run:
            time.sleep(max(1, QA_WORKER_INTERVAL_SEC))
            continue
        rid = run['id']
        try:
            process_qa_run(rid)
        except Exception as exc:
            db_exec(
                "UPDATE qa_analysis_runs SET status='failed', error_text=%s, completed_at=NOW(), updated_at=NOW() WHERE id=%s",
                (str(exc), rid),
            )
            export = db_one("SELECT id, batch_id, deal_id FROM analysis_exports WHERE id=(SELECT export_id FROM qa_analysis_runs WHERE id=%s)", (rid,))
            batch_id = safe_int(export.get('batch_id')) if export else None
            if export:
                try:
                    update_export_status_stage(int(export['id']), 'error', 'Ошибка на этапе Claude', str(exc))
                except Exception:
                    pass
                try:
                    record_export_failure(int(export['id']), str(exc))
                except Exception:
                    pass
            if batch_id:
                log_batch_progress(batch_id, 'qa_failed')
                finalize_batch_if_ready(batch_id)
            db_log('qa', 'analysis_run', str(rid), {'batch_id': batch_id, 'deal_id': export.get('deal_id') if export else None}, 'error', str(exc))
        time.sleep(0.2)


def ensure_qa_worker():
    global QA_WORKER_STARTED
    with QA_WORKER_LOCK:
        if QA_WORKER_STARTED:
            return
        t = threading.Thread(target=qa_worker_loop, daemon=True)
        t.start()
        QA_WORKER_STARTED = True
def get_report_payload(public_id: str):
    row = db_one(
        """
        SELECT
          rl.public_id,
          r.id AS run_id,
          r.export_id,
          r.standard_version_id,
          s.overall_score_0_100,
          s.final_summary,
          s.final_summary_kk,
          t.touches_count,
          t.items_json,
          te.deal_id,
          te.entity_type,
          te.responsible_id,
          te.responsible_name,
          te.employee_id,
          te.source_snapshot_json,
          te.user_id,
          te.bitrix_connection_id,
          uc.bitrix_domain
        FROM qa_report_links rl
        JOIN qa_analysis_runs r ON r.id = rl.run_id
        LEFT JOIN qa_analysis_summary s ON s.run_id = r.id
        LEFT JOIN qa_analysis_touches t ON t.run_id = r.id
        LEFT JOIN analysis_exports te ON te.id = r.export_id
        LEFT JOIN user_bitrix_connections uc ON uc.id = te.bitrix_connection_id
        WHERE rl.public_id = %s AND rl.is_active = TRUE
        """,
        (public_id,),
    )
    if not row:
        return None

    modules = db_all(
        """
        SELECT
          COALESCE(sb.block_name, ms.block_name) AS block_name,
          COALESCE(sm.module_name, ms.module_name) AS module_name,
          COALESCE(sm.module_details, '') AS module_details,
          sb.block_weight_percent AS block_weight_percent,
          COALESCE(sm.module_weight_percent, ms.module_weight_percent) AS module_weight_percent,
          COALESCE(sm.scoring_rules, '') AS scoring_rules,
          ms.raw_coef AS raw_coef,
          ms.weighted_points AS weighted_points,
          ms.comment AS comment,
          ms.evidence_json AS evidence_json
        FROM qa_analysis_module_scores ms
        LEFT JOIN qa_standard_modules sm ON sm.id = ms.standard_module_id
        LEFT JOIN qa_standard_blocks sb ON sb.id = sm.block_id
        WHERE ms.run_id=%s
        ORDER BY COALESCE(sb.sort_order, 9999) ASC, COALESCE(sm.sort_order, ms.id) ASC
        """,
        (row['run_id'],),
    )
    recs = db_all(
        "SELECT recommendation_text, recommendation_text_kk FROM qa_analysis_recommendations WHERE run_id=%s ORDER BY sort_order ASC",
        (row['run_id'],),
    )
    touches_raw = row.get('items_json') or []
    touch_analysis = {}
    if isinstance(touches_raw, dict):
        touches = touches_raw.get('items') if isinstance(touches_raw.get('items'), list) else []
        touch_analysis = touches_raw.get('analysis') if isinstance(touches_raw.get('analysis'), dict) else {}
    elif isinstance(touches_raw, list):
        touches = touches_raw
    else:
        touches = []
    snapshot = row.get('source_snapshot_json') or {}
    if isinstance(snapshot, str):
        try:
            snapshot = json.loads(snapshot)
        except Exception:
            snapshot = {}
    if not isinstance(snapshot, dict):
        snapshot = {}
    call_summary = snapshot.get('call_summary') if isinstance(snapshot.get('call_summary'), dict) else {}
    primary_call = call_summary.get('primary_call_operator') if isinstance(call_summary.get('primary_call_operator'), dict) else {}
    primary_call_at = parse_ts(primary_call.get('event_at')) if isinstance(primary_call, dict) else None
    deal_id_num = safe_int(row.get('deal_id'))
    # Frontend uses operator_id to navigate to /dash/operator/<id>; that route is keyed by
    # internal employees.id, not Bitrix responsible_id. Take the canonical name from
    # employees.name (it's the source of truth and won't drift if Bitrix-side renames happen).
    employee_id = safe_int(row.get('employee_id'))
    bitrix_user_id = safe_int(row.get('responsible_id'))
    operator_name = ''
    if employee_id:
        emp_row = db_one("SELECT name FROM employees WHERE id=%s", (employee_id,)) or {}
        operator_name = str(emp_row.get('name') or '').strip()
    if not operator_name:
        operator_name, _ = resolve_user_name_position(bitrix_user_id or 0, str(row.get('responsible_name') or '').strip(), '')
    operator_id = employee_id or bitrix_user_id
    card = snapshot.get('card_completeness') or {}
    details = card.get('details') or []
    if not isinstance(details, list):
        details = []
    missing_fields = [str(d.get('label') or '').strip() for d in details if isinstance(d, dict) and not d.get('filled')]
    missing_fields = [m for m in missing_fields if m]

    block_score_sums = {}
    for m in modules:
        bname = str(m.get('block_name') or '<не доступно>')
        block_score_sums[bname] = quant2(block_score_sums.get(bname, 0.0) + float(m.get('weighted_points') or 0.0))

    def extract_task(evidence_json, raw_coef_val: float) -> str:
        if raw_coef_val == 1.0:
            return '—'
        if isinstance(evidence_json, dict):
            t = str(evidence_json.get('task') or '').strip()
            return t or '—'
        return '—'

    module_payload = []
    for m in modules:
        block_name = m.get('block_name') or '<не доступно>'
        module_title = normalize_module_title(m.get('module_name') or '<не доступно>')
        module_score = quant2(float(m.get('weighted_points') or 0.0))
        raw_coef_val = float(m.get('raw_coef') or 0.0)
        evidence_json = m.get('evidence_json') if isinstance(m.get('evidence_json'), dict) else {}
        observation_text = str(m.get('comment') or '').strip() or '—'
        task_text = extract_task(evidence_json, raw_coef_val)
        module_payload.append({
            'block_name': block_name,
            'module_name': module_title,
            'module_details': m.get('module_details') or '',
            'block_weight_percent': quant2(float(m['block_weight_percent'])) if m.get('block_weight_percent') is not None else None,
            'block_score_percent': quant2(float(block_score_sums.get(str(block_name), 0.0))),
            'module_weight_percent': quant2(float(m.get('module_weight_percent') or 0.0)),
            'module_score_percent': module_score,
            'raw_coef': float(m.get('raw_coef') or 0.0),
            'scoring_rules': m.get('scoring_rules') or '',
            'module_ai_comment': observation_text,
            'module_recommendation': observation_text,
            'module_observation': observation_text,
            'module_observation_kk': str(evidence_json.get('comment_kk') or '').strip(),
            'module_task': task_text,
            'module_task_kk': str(evidence_json.get('task_kk') or '').strip() or '—',
        })

    return {
        'public_id': public_id,
        'run_id': row['run_id'],
        'export_id': row['export_id'],
        'standard_id': safe_int(row.get('standard_version_id')) or None,
        'card_fields_configured': int(card.get('total') or 0) > 0,
        'deal_id': row.get('deal_id'),
        'employee_id': operator_id,
        'employee_name': operator_name,
        'client_name': snapshot.get('client', {}).get('name') if isinstance(snapshot.get('client'), dict) else None,
        'overall_score_percent': quant2(float(row.get('overall_score_0_100') or 0.0)),
        'final_summary': row.get('final_summary') or '',
        'final_summary_kk': row.get('final_summary_kk') or '',
        'touches_count': int(row.get('touches_count') or 0),
        'touches': touches,
        'touches_analysis': touch_analysis,
        'recommendations': [str(r.get('recommendation_text') or '') for r in recs],
        'recommendations_kk': [str(r.get('recommendation_text_kk') or '') for r in recs],
        'observations': [str(r.get('recommendation_text') or '') for r in recs],
        'missing_fields': missing_fields,
        'modules': module_payload,
        'txt_url': chronology_path(public_id, operator_id),
        'report_url': report_path(public_id, operator_id),
        'chronology_url': f"/dash/chronology/{public_id}",
        'employee_url': f"/dash/employee/{operator_id}" if operator_id else '',
        'deal_url': f"https://{row['bitrix_domain']}/crm/{ENTITY_URL_PATH_BY_TYPE.get(str(row.get('entity_type') or 'deal'), 'deal')}/details/{int(row.get('deal_id') or 0)}/" if safe_int(row.get('deal_id')) and row.get('bitrix_domain') else '',
        'bitrix_domain': str(row.get('bitrix_domain') or '').strip(),
        'primary_call_at': primary_call_at,
    }


PDF_TEMPLATE_DIR = Path(os.getenv('PDF_TEMPLATE_DIR', '/root/okosystems/templates'))
OKO_PROJECT_DIR = Path('/root/okosystems')

_PDF_RU_MONTHS = {
    1: 'января', 2: 'февраля', 3: 'марта', 4: 'апреля', 5: 'мая', 6: 'июня',
    7: 'июля', 8: 'августа', 9: 'сентября', 10: 'октября', 11: 'ноября', 12: 'декабря',
}


def _pdf_format_ru_date(dt: datetime | None) -> str:
    if not dt:
        return ''
    return f"{dt.day} {_PDF_RU_MONTHS[dt.month]} {dt.year}"


def _pdf_score_color(ratio_pct: float) -> str:
    if ratio_pct >= 80: return 'green'
    if ratio_pct >= 60: return 'yellow'
    return 'red'


def _pdf_initials(name: str) -> str:
    parts = [p for p in (name or '').split() if p]
    return ''.join(p[0].upper() for p in parts[:2]) or '?'


def _pdf_filename_part(text: str) -> str:
    """Sanitize a single filename component: drop chars forbidden by Win/macOS/Linux,
    collapse whitespace, but keep cyrillic, spaces and em-dash."""
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', '', text or '').strip()
    cleaned = re.sub(r'\s+', ' ', cleaned)
    return cleaned[:60]


def _pdf_build_filename(employee_name: str, client_name: str, deal_id, public_id: str) -> str:
    employee = _pdf_filename_part(employee_name) or 'Сотрудник'
    client = _pdf_filename_part(client_name)
    if not client:
        client = f'Сделка #{deal_id}' if deal_id else ''
    parts = ['OKO Анализ', employee]
    if client:
        parts.append(client)
    return ' — '.join(parts) + '.pdf'


def render_report_pdf(public_id: str) -> tuple[bytes, str] | None:
    """Returns (pdf_bytes, filename) or None if report not found.
    Raises RuntimeError if WeasyPrint isn't available."""
    payload = get_report_payload(public_id)
    if not payload:
        return None

    try:
        from jinja2 import Environment, FileSystemLoader, select_autoescape
        from weasyprint import HTML
    except ImportError as e:
        raise RuntimeError(f'pdf_dependency_missing: {e}')

    modules = payload.get('modules') or []

    block_totals: dict[str, dict] = {}
    for m in modules:
        bn = str(m.get('block_name') or '')
        slot = block_totals.setdefault(bn, {'name': bn, 'score': 0.0, 'weight': 0.0})
        slot['score'] += float(m.get('module_score_percent') or 0.0)
        bw = m.get('block_weight_percent')
        if bw is not None:
            slot['weight'] = float(bw)

    blocks_view = []
    for slot in block_totals.values():
        weight = slot['weight'] or 0.0
        pct = round((slot['score'] / weight) * 100) if weight > 0 else 0
        pct = max(0, min(100, pct))
        blocks_view.append({'name': slot['name'], 'pct': pct, 'color': _pdf_score_color(pct)})

    modules_view = []
    failing = []
    for m in modules:
        weight = float(m.get('module_weight_percent') or 0.0)
        score = float(m.get('module_score_percent') or 0.0)
        ratio = round((score / weight) * 100) if weight > 0 else 0
        ratio = max(0, min(100, ratio))
        item = {
            'block_name': m.get('block_name') or '',
            'module_name': m.get('module_name') or '',
            'module_weight_percent': round(weight),
            'ratio_pct': ratio,
            'color': _pdf_score_color(ratio),
            'observation': m.get('module_observation') or '',
            'task': m.get('module_task') or '',
        }
        modules_view.append(item)
        if ratio < 100:
            failing.append(item)

    failing_by_block: list[dict] = []
    seen: dict[str, dict] = {}
    for it in failing:
        key = it['block_name']
        if key not in seen:
            group = {'block_name': key, 'modules': []}
            seen[key] = group
            failing_by_block.append(group)
        seen[key]['modules'].append(it)

    modules_by_block: list[dict] = []
    seen2: dict[str, dict] = {}
    for it in modules_view:
        key = it['block_name']
        if key not in seen2:
            group = {'block_name': key, 'modules': []}
            seen2[key] = group
            modules_by_block.append(group)
        seen2[key]['modules'].append(it)

    missing_fields = payload.get('missing_fields') or []
    if not isinstance(missing_fields, list):
        missing_fields = []

    overall = int(round(float(payload.get('overall_score_percent') or 0.0)))

    call_dt = payload.get('primary_call_at')
    if isinstance(call_dt, str):
        call_dt = parse_ts(call_dt)
    call_date_str = _pdf_format_ru_date(call_dt) if isinstance(call_dt, datetime) else ''
    generated_at_str = _pdf_format_ru_date(datetime.now(timezone.utc))

    employee_name = str(payload.get('employee_name') or '').strip() or 'Сотрудник'
    client_name = str(payload.get('client_name') or '').strip()
    deal_id = payload.get('deal_id')

    env = Environment(
        loader=FileSystemLoader(str(PDF_TEMPLATE_DIR)),
        autoescape=select_autoescape(['html', 'xml']),
    )
    template = env.get_template('report_pdf.html')
    public_url = f"{REPORT_PUBLIC_BASE_URL.rstrip('/')}/r/{public_id}"
    html_str = template.render(
        title=f"Анализ — {employee_name}",
        bitrix_domain=payload.get('bitrix_domain') or '',
        deal_id=deal_id,
        client_name=client_name,
        employee_name=employee_name,
        employee_initials=_pdf_initials(employee_name),
        call_date_str=call_date_str,
        generated_at_str=generated_at_str,
        overall_score=overall,
        score_class=_pdf_score_color(overall),
        blocks=blocks_view,
        final_summary=payload.get('final_summary') or '',
        failing=failing,
        failing_by_block=failing_by_block,
        modules=modules_view,
        modules_by_block=modules_by_block,
        missing_fields=missing_fields,
        public_url=public_url,
    )

    pdf_bytes = HTML(string=html_str, base_url=str(OKO_PROJECT_DIR)).write_pdf()

    filename = _pdf_build_filename(employee_name, client_name, deal_id, public_id)
    ascii_fallback = f"OKO-Analysis-{deal_id or public_id}.pdf"
    return pdf_bytes, filename, ascii_fallback


def score_ratio_percent(weighted_points, module_weight_percent) -> float:
    weight = float(module_weight_percent or 0.0)
    points = float(weighted_points or 0.0)
    if weight <= 0:
        return 0.0
    return quant2((points / weight) * 100.0)


def get_employee_progress_payload(operator_id: int, user_id: int | None = None):
    """`operator_id` is the internal employees.id. For backward-compat with legacy URLs
    that still carry a Bitrix user_id, we fall back to the employee linked to that
    bitrix_user_id (preferring the most recently active one when there are several)."""
    operator_id = safe_int(operator_id)
    if not operator_id:
        return None
    # Legacy URL fallback: if no exports point at this employee_id, treat it as a
    # bitrix_user_id and find the matching employee.
    has_employee = db_one("SELECT 1 FROM employees WHERE id=%s", (operator_id,))
    if not has_employee:
        legacy = db_one(
            """
            SELECT e.id FROM employees e
            LEFT JOIN analysis_exports ae ON ae.employee_id = e.id
            WHERE e.bitrix_user_id = %s
            GROUP BY e.id
            ORDER BY MAX(ae.created_at) DESC NULLS LAST, e.id DESC
            LIMIT 1
            """,
            (operator_id,),
        )
        if legacy:
            operator_id = int(legacy['id'])
    progress_valid_from = parse_iso_datetime(OPERATOR_PROGRESS_VALID_FROM_UTC, datetime(2026, 3, 14, 0, 0, 0, tzinfo=timezone.utc))
    rows = db_all(
        """
        WITH ranked AS (
          SELECT
            r.id AS run_id,
            r.run_version,
            r.created_at AS run_created_at,
            r.completed_at AS run_completed_at,
            te.id AS export_id,
            te.deal_id,
            te.client_name,
            te.responsible_id,
            te.responsible_name,
            te.source_snapshot_json,
            te.created_at AS export_created_at,
            s.overall_score_0_100,
            s.final_summary,
            rl.public_id,
            ROW_NUMBER() OVER (
              PARTITION BY te.deal_id, te.employee_id
              ORDER BY COALESCE(r.completed_at, r.created_at, te.created_at) DESC, r.id DESC
            ) AS rn
          FROM qa_analysis_runs r
          JOIN analysis_exports te ON te.id = r.export_id
          JOIN qa_analysis_summary s ON s.run_id = r.id
          LEFT JOIN qa_report_links rl ON rl.run_id = r.id AND rl.is_active = TRUE
          WHERE r.status = 'completed'
            AND te.employee_id = %s
            AND (%s IS NULL OR te.user_id = %s)
            AND COALESCE(r.created_at, te.created_at) >= %s
        )
        SELECT
          run_id,
          run_version,
          run_created_at,
          run_completed_at,
          export_id,
          deal_id,
          client_name,
          responsible_id,
          responsible_name,
          source_snapshot_json,
          export_created_at,
          overall_score_0_100,
          final_summary,
          public_id
        FROM ranked
        WHERE rn = 1
        ORDER BY COALESCE(run_completed_at, run_created_at, export_created_at) ASC, run_id ASC
        """,
        (operator_id, user_id, user_id, progress_valid_from),
    )
    if not rows:
        return None

    modules_raw = db_all(
        """
        SELECT
          ms.run_id,
          COALESCE(sb.block_name, ms.block_name) AS block_name,
          COALESCE(sm.module_name, ms.module_name) AS module_name,
          COALESCE(sm.module_weight_percent, ms.module_weight_percent) AS module_weight_percent,
          COALESCE(sb.sort_order, 9999) AS block_sort_order,
          COALESCE(sm.sort_order, ms.id) AS module_sort_order,
          ms.raw_coef,
          ms.weighted_points,
          ms.comment,
          ms.evidence_json
        FROM qa_analysis_module_scores ms
        LEFT JOIN qa_standard_modules sm ON sm.id = ms.standard_module_id
        LEFT JOIN qa_standard_blocks sb ON sb.id = sm.block_id
        WHERE ms.run_id = ANY(%s)
        ORDER BY COALESCE(sb.sort_order, 9999) ASC, COALESCE(sm.sort_order, ms.id) ASC
        """,
        ([int(r['run_id']) for r in rows],),
    )

    modules_by_run = {}
    module_order = {}
    for item in modules_raw:
        rid = int(item['run_id'])
        module_name = normalize_module_title(item.get('module_name') or '<не доступно>')
        module_entry = {
            'block_name': str(item.get('block_name') or '<не доступно>'),
            'module_name': module_name,
            'module_weight_percent': quant2(float(item.get('module_weight_percent') or 0.0)),
            'raw_coef': float(item.get('raw_coef') or 0.0),
            'weighted_points': quant2(float(item.get('weighted_points') or 0.0)),
            'comment': str(item.get('comment') or '').strip(),
            'comment_kk': str((item.get('evidence_json') or {}).get('comment_kk') or '').strip() if isinstance(item.get('evidence_json'), dict) else '',
        }
        modules_by_run.setdefault(rid, []).append(module_entry)
        key = module_name
        if key not in module_order:
            module_order[key] = (
                int(item.get('block_sort_order') or 9999),
                int(item.get('module_sort_order') or 9999),
                str(item.get('block_name') or ''),
            )

    history = []
    score_sum = 0.0
    module_aggregate = {}
    for row in rows:
        snapshot = row.get('source_snapshot_json') or {}
        if isinstance(snapshot, str):
            try:
                snapshot = json.loads(snapshot)
            except Exception:
                snapshot = {}
        if not isinstance(snapshot, dict):
            snapshot = {}
        call_summary = snapshot.get('call_summary') if isinstance(snapshot.get('call_summary'), dict) else {}
        primary_call = call_summary.get('primary_call_operator') if isinstance(call_summary.get('primary_call_operator'), dict) else {}
        primary_call_at = parse_ts(primary_call.get('event_at')) if isinstance(primary_call, dict) else None
        sort_at = primary_call_at or row.get('run_completed_at') or row.get('export_created_at')
        run_modules = modules_by_run.get(int(row['run_id']), [])
        score = quant2(float(row.get('overall_score_0_100') or 0.0))
        score_sum = quant2(score_sum + score)
        for mod in run_modules:
            agg = module_aggregate.setdefault(mod['module_name'], {
                'block_name': mod['block_name'],
                'sum_ratio': 0.0,
                'count': 0,
            })
            agg['sum_ratio'] = quant2(agg['sum_ratio'] + score_ratio_percent(mod['weighted_points'], mod['module_weight_percent']))
            agg['count'] += 1
        history.append({
            'run_id': int(row['run_id']),
            'run_version': int(row.get('run_version') or 0),
            'export_id': int(row['export_id']),
            'public_id': str(row.get('public_id') or '').strip(),
            'deal_id': safe_int(row.get('deal_id')),
            'client_name': str(row.get('client_name') or '').strip() or '<не указан>',
            'employee_id': safe_int(row.get('responsible_id')),
            'employee_name': str(row.get('responsible_name') or '').strip(),
            'overall_score_percent': score,
            'final_summary': str(row.get('final_summary') or '').strip(),
            'primary_call_at': primary_call_at,
            'sort_at': sort_at,
            'modules': run_modules,
        })

    history.sort(key=lambda item: (item['sort_at'] is None, item['sort_at'] or datetime.now(timezone.utc), item['run_id']))
    # operator_id is the internal employees.id. Pull the canonical name from our table (this
    # is the one that won't shift if a Bitrix admin renames the underlying account). Use the
    # linked Bitrix user_id only to enrich position from Bitrix.
    emp_row = db_one("SELECT name, bitrix_user_id FROM employees WHERE id = %s", (operator_id,)) or {}
    operator_name = str(emp_row.get('name') or '').strip()
    if not operator_name:
        stored_names = [str(h.get('operator_name') or '').strip() for h in history if str(h.get('operator_name') or '').strip() and not is_placeholder_text(h.get('operator_name'))]
        operator_name = Counter(stored_names).most_common(1)[0][0] if stored_names else ''
    bitrix_ctx = get_user_bitrix_context(user_id) if user_id else None
    bitrix_user_id_for_lookup = safe_int(emp_row.get('bitrix_user_id'))
    _, operator_position = resolve_user_name_position(bitrix_user_id_for_lookup, operator_name, '', bitrix_ctx=bitrix_ctx)

    best_score = max((float(h['overall_score_percent']) for h in history), default=0.0)
    avg_score = quant2(score_sum / len(history)) if history else 0.0
    latest = history[-1]
    previous = history[-2] if len(history) > 1 else None
    latest_delta = quant2(float(latest['overall_score_percent']) - float(previous['overall_score_percent'])) if previous else None
    first_score = float(history[0]['overall_score_percent']) if history else 0.0
    overall_trend = quant2(float(latest['overall_score_percent']) - first_score) if history else 0.0

    module_keys = sorted(module_order.keys(), key=lambda k: module_order[k])
    module_matrix = []
    for key in module_keys:
        block_name = module_order[key][2]
        values = []
        for h in history:
            found = next((m for m in h['modules'] if m['module_name'] == key), None)
            if found:
                values.append({
                    'weighted_points': found['weighted_points'],
                    'module_weight_percent': found['module_weight_percent'],
                    'ratio_percent': score_ratio_percent(found['weighted_points'], found['module_weight_percent']),
                    'raw_coef': found['raw_coef'],
                    'comment': found['comment'],
                })
            else:
                values.append(None)
        avg_ratio = quant2(sum(v['ratio_percent'] for v in values if v) / max(1, len([v for v in values if v])))
        module_matrix.append({
            'block_name': block_name,
            'module_name': key,
            'avg_ratio_percent': avg_ratio,
            'values': values,
        })

    repeated_problems = []
    for row in module_matrix:
        bad_count = len([v for v in row['values'] if v and float(v['raw_coef']) < 1.0])
        if bad_count >= 2:
            repeated_problems.append({
                'module_name': row['module_name'],
                'block_name': row['block_name'],
                'bad_count': bad_count,
                'avg_ratio_percent': row['avg_ratio_percent'],
            })
    repeated_problems.sort(key=lambda item: (-item['bad_count'], item['avg_ratio_percent'], item['module_name']))

    history_with_diff = []
    followup_summary = {'completed': 0, 'partial': 0, 'not_done': 0, 'items': []}
    for idx, item in enumerate(history):
        prev = history[idx - 1] if idx > 0 else None
        improved = []
        declined = []
        followups = []
        delta = None
        if prev:
            delta = quant2(float(item['overall_score_percent']) - float(prev['overall_score_percent']))
            current_map = {m['module_name']: m for m in item['modules']}
            prev_map = {m['module_name']: m for m in prev['modules']}
            for mname, cur in current_map.items():
                prev_mod = prev_map.get(mname)
                if not prev_mod:
                    continue
                diff = quant2(float(cur['weighted_points']) - float(prev_mod['weighted_points']))
                if diff >= 0.5:
                    improved.append({'module_name': mname, 'diff': diff})
                elif diff <= -0.5:
                    declined.append({'module_name': mname, 'diff': diff})
            for mname, prev_mod in prev_map.items():
                task = str(prev_mod.get('task') or '').strip()
                if not task or float(prev_mod.get('raw_coef') or 0.0) >= 1.0:
                    continue
                cur = current_map.get(mname)
                if not cur:
                    continue
                prev_coef = float(prev_mod.get('raw_coef') or 0.0)
                cur_coef = float(cur.get('raw_coef') or 0.0)
                if cur_coef >= 1.0:
                    status = 'completed'
                    followup_summary['completed'] += 1
                elif cur_coef > prev_coef:
                    status = 'partial'
                    followup_summary['partial'] += 1
                else:
                    status = 'not_done'
                    followup_summary['not_done'] += 1
                entry = {
                    'from_run_id': prev['run_id'],
                    'to_run_id': item['run_id'],
                    'module_name': mname,
                    'status': status,
                    'prev_coef': prev_coef,
                    'current_coef': cur_coef,
                }
                followups.append(entry)
                followup_summary['items'].append(entry)
        history_with_diff.append({
            **item,
            'delta_from_prev': delta,
            'improved_modules': improved,
            'declined_modules': declined,
            'followups': followups,
        })

    def latest_history_match(module_name: str, predicate):
        for h in reversed(history):
            mod = next((m for m in h['modules'] if m['module_name'] == module_name), None)
            if mod and predicate(mod):
                return {
                    'public_id': h.get('public_id'),
                    'deal_id': h.get('deal_id'),
                    'run_id': h.get('run_id'),
                    'overall_score_percent': h.get('overall_score_percent'),
                    'primary_call_at': h.get('primary_call_at'),
                }
        return None

    best_module = None
    worst_module = None
    if module_matrix:
        best_module = max(module_matrix, key=lambda item: float(item['avg_ratio_percent']))
        worst_module = min(module_matrix, key=lambda item: float(item['avg_ratio_percent']))
        if best_module:
            best_module = {
                **best_module,
                'latest_good_example': latest_history_match(
                    best_module['module_name'],
                    lambda mod: float(mod.get('raw_coef') or 0.0) >= 1.0,
                ) or latest_history_match(
                    best_module['module_name'],
                    lambda mod: True,
                ),
            }
        if worst_module:
            worst_module = {
                **worst_module,
                'latest_bad_example': latest_history_match(
                    worst_module['module_name'],
                    lambda mod: float(mod.get('raw_coef') or 0.0) < 1.0,
                ) or latest_history_match(
                    worst_module['module_name'],
                    lambda mod: True,
                ),
            }

    score_series = []
    for item in history:
        dt = item.get('primary_call_at') or item.get('sort_at')
        score_series.append({
            'run_id': item['run_id'],
            'public_id': item.get('public_id') or '',
            'score_percent': quant2(float(item.get('overall_score_percent') or 0.0)),
            'utc_iso': dt.astimezone(timezone.utc).isoformat() if isinstance(dt, datetime) else '',
            'date_label': dt.strftime('%d.%m') if isinstance(dt, datetime) else '—',
        })

    return {
        'employee_id': operator_id,
        'employee_name': operator_name,
        'employee_position': operator_position if not is_placeholder_text(operator_position) else '',
        'analysis_count': len(history),
        'average_score_percent': avg_score,
        'best_score_percent': quant2(best_score),
        'latest_score_percent': latest['overall_score_percent'],
        'latest_delta_percent': latest_delta,
        'overall_trend_percent': overall_trend,
        'history': history_with_diff,
        'score_series': score_series,
        'module_matrix': module_matrix,
        'repeated_problems': repeated_problems,
        'task_followup': followup_summary,
        'best_module': best_module,
        'worst_module': worst_module,
    }


def get_me_payload(user_id: int) -> dict | None:
    uid = safe_int(user_id)
    if not uid:
        return None
    user = db_one("SELECT id, email, first_name, last_name, username, default_standard_id FROM users WHERE id=%s", (uid,))
    if not user:
        return None
    connections = db_all(
        "SELECT id, bitrix_domain, title, is_primary, status FROM user_bitrix_connections WHERE user_id=%s ORDER BY is_primary DESC, id ASC",
        (uid,),
    )
    name_parts = [str(user.get('first_name') or '').strip(), str(user.get('last_name') or '').strip()]
    display_name = ' '.join(p for p in name_parts if p) or str(user.get('username') or user.get('email') or '').strip()
    return {
        'user_id': uid,
        'default_standard_id': safe_int(user.get('default_standard_id')) or None,
        'name': display_name,
        'email': str(user.get('email') or ''),
        'connections': [
            {
                'id': int(c['id']),
                'domain': str(c.get('bitrix_domain') or ''),
                'title': str(c.get('title') or c.get('bitrix_domain') or ''),
                'is_primary': bool(c.get('is_primary')),
                'status': str(c.get('status') or ''),
            }
            for c in (connections or [])
        ],
    }


def get_employees_list(user_id: int, archived: bool = False) -> list:
    """Returns the list of employees with aggregates for the home page.
    archived=False → only status='active' (default). archived=True → only status='archived'.
    'merged' employees are never returned (those are tombstones from manual splits/merges)."""
    uid = safe_int(user_id)
    if not uid:
        return []
    progress_valid_from = parse_iso_datetime(OPERATOR_PROGRESS_VALID_FROM_UTC, datetime(2026, 3, 14, 0, 0, 0, tzinfo=timezone.utc))
    # Group by internal employee_id, not Bitrix responsible_id — when an admin renames
    # a Bitrix account (Фариза → Сара under the same id=35), the resolver creates a new
    # employee row, so histories of two different people don't blend.
    # One export = one analysis from the user's perspective, even if there were multiple
    # qa_runs on the same export (auto-retry after network blips). Take only the latest
    # successful run per export.
    rows = db_all(
        """
        WITH latest_run_per_export AS (
          SELECT DISTINCT ON (te.id)
            te.id AS export_id,
            te.employee_id,
            te.responsible_id,
            r.id AS run_id,
            r.completed_at,
            s.overall_score_0_100
          FROM analysis_exports te
          JOIN qa_analysis_runs r ON r.export_id = te.id AND r.status = 'completed'
          JOIN qa_analysis_summary s ON s.run_id = r.id
          WHERE te.user_id = %s
            AND te.employee_id IS NOT NULL
            AND COALESCE(r.created_at, te.created_at) >= %s
          ORDER BY te.id, r.completed_at DESC NULLS LAST, r.id DESC
        ),
        latest_runs AS (
          SELECT
            employee_id AS operator_id,
            COUNT(*) AS analysis_count,
            ROUND(AVG(overall_score_0_100)::numeric, 1) AS avg_score,
            MAX(completed_at) AS last_at,
            MAX(responsible_id) AS bitrix_user_id
          FROM latest_run_per_export
          GROUP BY employee_id
        ),
        latest_score AS (
          SELECT DISTINCT ON (te.employee_id)
            te.employee_id AS operator_id,
            ROUND(s.overall_score_0_100::numeric, 1) AS latest_score,
            rl.public_id AS latest_public_id
          FROM analysis_exports te
          JOIN qa_analysis_runs r ON r.export_id = te.id AND r.status = 'completed'
          JOIN qa_analysis_summary s ON s.run_id = r.id
          LEFT JOIN qa_report_links rl ON rl.run_id = r.id AND rl.is_active = TRUE
          WHERE te.user_id = %s
            AND te.employee_id IS NOT NULL
            AND COALESCE(r.created_at, te.created_at) >= %s
          ORDER BY te.employee_id, r.completed_at DESC NULLS LAST, r.id DESC
        )
        SELECT
          lr.operator_id,
          e.name AS operator_name,
          lr.analysis_count,
          lr.avg_score,
          lr.last_at,
          lr.bitrix_user_id,
          ls.latest_score,
          ls.latest_public_id
        FROM latest_runs lr
        LEFT JOIN employees e ON e.id = lr.operator_id
        LEFT JOIN latest_score ls ON ls.operator_id = lr.operator_id
        WHERE COALESCE(e.status, 'active') <> 'merged'
          AND COALESCE(e.status, 'active') = %s
        ORDER BY lr.last_at DESC NULLS LAST
        """,
        (uid, progress_valid_from, uid, progress_valid_from, 'archived' if archived else 'active'),
    )

    operator_ids = [int(r['operator_id']) for r in (rows or []) if r.get('operator_id')]
    repeated_counts = {}
    plan_statuses = {}

    if operator_ids:
        # Count problem runs per employee — but only the latest completed run per export,
        # so multiple retries of the same call don't inflate the counter (one bad call = one
        # bad analysis from the user's perspective).
        rp_rows = db_all(
            """
            WITH latest_run_per_export AS (
              SELECT DISTINCT ON (te.id) te.id AS export_id, r.id AS run_id, te.employee_id
              FROM analysis_exports te
              JOIN qa_analysis_runs r ON r.export_id = te.id AND r.status = 'completed'
              WHERE te.user_id = %s AND te.employee_id = ANY(%s)
              ORDER BY te.id, r.completed_at DESC NULLS LAST, r.id DESC
            )
            SELECT lr.run_id, lr.employee_id AS operator_id
            FROM latest_run_per_export lr
            WHERE EXISTS (
              SELECT 1 FROM qa_analysis_module_scores ms
              WHERE ms.run_id = lr.run_id AND ms.raw_coef::float < 1
            )
            """,
            (uid, operator_ids),
        )
        op_bad = {}
        for rp in (rp_rows or []):
            oid = int(rp['operator_id'])
            op_bad.setdefault(oid, set()).add(rp['run_id'])
        for oid, run_set in op_bad.items():
            repeated_counts[oid] = len(run_set)

        plan_rows = db_all(
            """
            SELECT DISTINCT ON (employee_id) employee_id, status
            FROM employee_development_plans
            WHERE employee_id = ANY(%s) AND user_id = %s
            ORDER BY employee_id, created_at DESC
            """,
            (operator_ids, uid),
        )
        for pr in (plan_rows or []):
            plan_statuses[int(pr['employee_id'])] = str(pr.get('status') or 'draft')

    result = []
    for r in (rows or []):
        oid = int(r['operator_id'])
        result.append({
            'employee_id': oid,
            'employee_name': str(r.get('operator_name') or '').strip() or f'Сотрудник {oid}',
            'analysis_count': int(r.get('analysis_count') or 0),
            'avg_score': float(r.get('avg_score') or 0),
            'latest_score': float(r.get('latest_score') or 0),
            'latest_public_id': str(r.get('latest_public_id') or ''),
            'last_at': str(r.get('last_at') or ''),
            'problem_runs': repeated_counts.get(oid, 0),
            'plan_status': plan_statuses.get(oid),
        })
    return result


def get_analyses_list(user_id: int, status_filter: str = 'all', page: int = 1, per_page: int = 20) -> dict:
    uid = safe_int(user_id)
    if not uid:
        return {'items': [], 'total': 0, 'page': 1, 'per_page': per_page}

    status_map = {
        'active': "AND b.status NOT IN ('completed','completed_with_errors','failed')",
        'done': "AND b.status IN ('completed','completed_with_errors')",
        'error': "AND b.status = 'failed'",
    }
    status_clause = status_map.get(status_filter, '')
    offset = (max(1, page) - 1) * per_page

    count_row = db_one(f"SELECT COUNT(*) AS cnt FROM analysis_batches b WHERE b.user_id=%s {status_clause}", (uid,))
    total = safe_int((count_row or {}).get('cnt')) or 0

    rows = db_all(
        f"""
        SELECT b.id AS batch_id, b.status, b.created_at, b.source_text,
               COUNT(e.id) AS export_count,
               COUNT(CASE WHEN e.status IN ('completed','completed_with_errors') THEN 1 END) AS done_count,
               (SELECT ae0.deal_id FROM analysis_exports ae0
                WHERE ae0.batch_id = b.id AND ae0.deal_id IS NOT NULL
                ORDER BY ae0.id ASC LIMIT 1) AS deal_id,
               (SELECT ae0.entity_type FROM analysis_exports ae0
                WHERE ae0.batch_id = b.id AND ae0.deal_id IS NOT NULL
                ORDER BY ae0.id ASC LIMIT 1) AS entity_type,
               (SELECT uc0.bitrix_domain FROM analysis_exports ae0
                LEFT JOIN user_bitrix_connections uc0 ON uc0.id = ae0.bitrix_connection_id
                WHERE ae0.batch_id = b.id ORDER BY ae0.id ASC LIMIT 1) AS bitrix_domain,
               (SELECT qrl.public_id FROM analysis_exports ae2
                LEFT JOIN qa_analysis_runs ar2 ON ar2.export_id = ae2.id
                LEFT JOIN qa_report_links qrl ON qrl.run_id = ar2.id AND qrl.is_active = TRUE
                WHERE ae2.batch_id = b.id AND qrl.public_id IS NOT NULL
                ORDER BY ae2.id DESC LIMIT 1) AS public_id,
               (SELECT ae3.selected_operator_name FROM analysis_exports ae3
                WHERE ae3.batch_id = b.id
                  AND ae3.selected_operator_name IS NOT NULL AND ae3.selected_operator_name <> ''
                LIMIT 1) AS operator_name,
               (SELECT qas.overall_score_0_100 FROM analysis_exports ae4
                JOIN qa_analysis_runs ar4 ON ar4.export_id = ae4.id
                JOIN qa_analysis_summary qas ON qas.run_id = ar4.id
                JOIN qa_report_links qrl4 ON qrl4.run_id = ar4.id AND qrl4.is_active = TRUE
                WHERE ae4.batch_id = b.id
                ORDER BY ar4.completed_at DESC NULLS LAST, ar4.id DESC LIMIT 1) AS score,
               CASE
                 WHEN COUNT(CASE WHEN e.status = 'awaiting_operator' THEN 1 END) > 0 THEN 'awaiting_operator'
                 WHEN COUNT(CASE WHEN e.retry_after IS NOT NULL THEN 1 END) > 0 THEN 'processing'
                 WHEN COUNT(CASE WHEN e.status IN ('completed_with_errors','failed') THEN 1 END) > 0 THEN 'completed_with_errors'
                 -- Atomic transition: don't surface 'completed' until the report link is live.
                 -- Without this, the row could briefly show "Готово" with no public_id (status
                 -- and link sit in different rows; one brief committed before the other).
                 WHEN b.status = 'completed' AND NOT EXISTS (
                   SELECT 1 FROM analysis_exports ae7
                   JOIN qa_analysis_runs ar7 ON ar7.export_id = ae7.id
                   JOIN qa_report_links qrl7 ON qrl7.run_id = ar7.id AND qrl7.is_active = TRUE
                   WHERE ae7.batch_id = b.id
                 ) THEN 'processing'
                 ELSE b.status
               END AS display_status,
               (SELECT ae5.processing_stage FROM analysis_exports ae5
                WHERE ae5.batch_id = b.id AND ae5.status NOT IN ('completed','completed_with_errors','error')
                ORDER BY ae5.updated_at DESC LIMIT 1) AS processing_stage,
               (SELECT ae6.error_kind FROM analysis_exports ae6
                WHERE ae6.batch_id = b.id AND ae6.error_kind IS NOT NULL
                ORDER BY ae6.id DESC LIMIT 1) AS error_kind
        FROM analysis_batches b
        LEFT JOIN analysis_exports e ON e.batch_id = b.id
        WHERE b.user_id = %s {status_clause}
        GROUP BY b.id
        ORDER BY b.id DESC
        LIMIT %s OFFSET %s
        """,
        (uid, per_page, offset),
    ) or []

    items = []
    for r in rows:
        score_val = r.get('score')
        kind = str(r.get('error_kind') or '').strip() or None
        items.append({
            'batch_id': int(r['batch_id']),
            'status': str(r.get('display_status') or r.get('status') or ''),
            'created_at': str(r.get('created_at') or ''),
            'deal_id': safe_int(r.get('deal_id')),
            'entity_type': str(r.get('entity_type') or 'deal'),
            'bitrix_domain': str(r.get('bitrix_domain') or ''),
            'employee_name': str(r.get('operator_name') or ''),
            'score': float(score_val) if score_val is not None else None,
            'public_id': str(r.get('public_id') or ''),
            'export_count': int(r.get('export_count') or 0),
            'done_count': int(r.get('done_count') or 0),
            'processing_stage': str(r.get('processing_stage') or ''),
            'error_kind': kind,
            'error_label': USER_ERROR_LABELS.get(kind) if kind else None,
        })
    return {'items': items, 'total': total, 'page': page, 'per_page': per_page}


def bitrix_api_post(method: str, payload: dict, bitrix_ctx: dict) -> dict:
    access_token = str(bitrix_ctx.get('access_token') or '').strip()
    domain = str(bitrix_ctx.get('domain') or '').strip()
    if not access_token or not domain:
        raise RuntimeError('missing_bitrix_credentials')
    url = f"https://{domain}/rest/{method}.json?auth={access_token}"
    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    resp = requests.post(url, data=body, headers={'Content-Type': 'application/json'}, timeout=30)
    data = resp.json()
    if 'error' in data:
        raise RuntimeError(json.dumps(data, ensure_ascii=False))
    return data


PLAN_SYSTEM_PROMPT = """Ты аналитик отдела продаж. Тебе передаётся статистика работы сотрудника по нескольким звонкам.
Твоя задача — выявить системные проблемы и сформировать конкретный план развития.
В тексте плана и описаниях задач называй человека словом «сотрудник» (а не «оператор» или «менеджер»).
Верни ответ СТРОГО как один JSON-объект. Никакого markdown, кодовых блоков, текста до/после JSON."""

PLAN_USER_PROMPT_TEMPLATE = """Данные по сотруднику ID {operator_id} за последние {calls_count} звонков.

Модули, в которых выявлены проблемы (avg_coef < 1):
{problem_modules_json}

Сформируй план развития. Верни JSON:
{{
  "systemic_problems": [
    {{"module_name": "название модуля", "diagnosis": "одно предложение, почему это системная проблема"}}
  ],
  "tasks": [
    {{"title": "заголовок задачи (до 80 символов)", "description": "подробное описание (до 400 символов), что именно делать и как", "deadline_days": 7}}
  ]
}}

Правила:
- systemic_problems: только модули с avg_coef < 0.6, максимум 4
- tasks: 3–5 задач, каждая — конкретное действие, не общее пожелание
- deadline_days: от 3 до 14
- Никаких имён клиентов, телефонов, персональных данных
"""


def get_employee_plan(employee_id: int, user_id: int | None = None) -> dict | None:
    """`employee_id` is internal employees.id. Plans are scoped per employee, so two
    employees sharing the same Bitrix user_id (rename split) keep separate plans."""
    row = db_one(
        """
        SELECT id, employee_id, user_id, run_ids_json, problem_modules_json, tasks_json,
               bitrix_task_ids_json, status, created_at, updated_at
        FROM employee_development_plans
        WHERE employee_id = %s
          AND (%s IS NULL OR user_id = %s)
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (employee_id, user_id, user_id),
    )
    if not row:
        return None
    return {
        'id': int(row['id']),
        'employee_id': int(row['employee_id']) if row.get('employee_id') else None,
        'run_ids': list(row.get('run_ids_json') or []),
        'problem_modules': list(row.get('problem_modules_json') or []),
        'tasks': list(row.get('tasks_json') or []),
        'bitrix_task_ids': list(row.get('bitrix_task_ids_json') or []),
        'status': str(row.get('status') or 'draft'),
        'created_at': str(row.get('created_at') or ''),
        'updated_at': str(row.get('updated_at') or ''),
    }


def generate_employee_plan(employee_id: int, user_id: int | None = None, calls_count: int = 5, run_ids: list | None = None) -> dict:
    """`employee_id` is the internal employees.id. Plans are per-employee, scoped by run_ids
    that belong to analyses attributed to that employee."""
    employee_id = safe_int(employee_id)
    if not employee_id:
        raise RuntimeError('invalid_employee_id')
    emp_row = db_one("SELECT id, bitrix_user_id FROM employees WHERE id=%s", (employee_id,))
    if not emp_row:
        raise RuntimeError('employee_not_found')
    operator_id = safe_int(emp_row.get('bitrix_user_id'))  # for Bitrix task assignment / legacy column

    if run_ids:
        # Use explicitly provided run_ids (cycle-triggered)
        runs = [{'run_id': rid} for rid in run_ids]
    else:
        progress_valid_from = parse_iso_datetime(OPERATOR_PROGRESS_VALID_FROM_UTC, datetime(2026, 3, 14, 0, 0, 0, tzinfo=timezone.utc))

        # Fetch last N completed runs for this employee (group dedup per deal+employee).
        runs = db_all(
            """
            WITH ranked AS (
              SELECT
                r.id AS run_id,
                te.deal_id,
                COALESCE(r.completed_at, r.created_at, te.created_at) AS sort_at,
                ROW_NUMBER() OVER (
                  PARTITION BY te.deal_id, te.employee_id
                  ORDER BY COALESCE(r.completed_at, r.created_at, te.created_at) DESC, r.id DESC
                ) AS rn
              FROM qa_analysis_runs r
              JOIN analysis_exports te ON te.id = r.export_id
              WHERE r.status = 'completed'
                AND te.employee_id = %s
                AND (%s IS NULL OR te.user_id = %s)
                AND COALESCE(r.created_at, te.created_at) >= %s
            )
            SELECT run_id, deal_id FROM ranked
            WHERE rn = 1
            ORDER BY sort_at DESC
            LIMIT %s
            """,
            (employee_id, user_id, user_id, progress_valid_from, calls_count),
        )
    if not runs:
        raise RuntimeError('no_completed_runs')
    if len(runs) < 2:
        raise RuntimeError('not_enough_runs')

    run_ids = [int(r['run_id']) for r in runs]

    # Aggregate module scores across these runs
    scores = db_all(
        """
        SELECT
          COALESCE(sm.module_name, ms.module_name) AS module_name,
          COALESCE(sb.block_name, ms.block_name) AS block_name,
          AVG(ms.raw_coef::float) AS avg_coef,
          COUNT(*) AS total_calls,
          SUM(CASE WHEN ms.raw_coef::float < 1 THEN 1 ELSE 0 END) AS bad_calls
        FROM qa_analysis_module_scores ms
        LEFT JOIN qa_standard_modules sm ON sm.id = ms.standard_module_id
        LEFT JOIN qa_standard_blocks sb ON sb.id = sm.block_id
        WHERE ms.run_id = ANY(%s)
        GROUP BY COALESCE(sm.module_name, ms.module_name), COALESCE(sb.block_name, ms.block_name)
        HAVING AVG(ms.raw_coef::float) < 1.0 AND SUM(CASE WHEN ms.raw_coef::float < 1 THEN 1 ELSE 0 END) >= 2
        ORDER BY AVG(ms.raw_coef::float) ASC
        LIMIT 10
        """,
        (run_ids,),
    )

    if not scores:
        raise RuntimeError('no_problem_modules')

    problem_modules = [
        {
            'module_name': str(s['module_name'] or ''),
            'block_name': str(s['block_name'] or ''),
            'avg_coef': round(float(s['avg_coef'] or 0), 2),
            'bad_calls': int(s['bad_calls'] or 0),
            'total_calls': int(s['total_calls'] or 0),
        }
        for s in scores
    ]

    problem_modules_text = json.dumps(problem_modules, ensure_ascii=False, indent=2)
    user_prompt = PLAN_USER_PROMPT_TEMPLATE.format(
        operator_id=operator_id,
        calls_count=len(run_ids),
        problem_modules_json=problem_modules_text,
    )

    parsed, req_payload, resp_payload = call_claude_json(PLAN_SYSTEM_PROMPT, user_prompt, model=ANTHROPIC_MODEL_PLAN)

    systemic_problems = []
    if isinstance(parsed.get('systemic_problems'), list):
        for p in parsed['systemic_problems'][:4]:
            if isinstance(p, dict) and p.get('module_name'):
                systemic_problems.append({
                    'module_name': str(p.get('module_name') or '')[:120],
                    'diagnosis': str(p.get('diagnosis') or '')[:300],
                })

    tasks = []
    if isinstance(parsed.get('tasks'), list):
        for t in parsed['tasks'][:5]:
            if isinstance(t, dict) and t.get('title'):
                tasks.append({
                    'title': str(t.get('title') or '')[:80],
                    'description': str(t.get('description') or '')[:400],
                    'deadline_days': max(3, min(14, int(t.get('deadline_days') or 7))),
                })

    if not tasks:
        raise RuntimeError('claude_returned_no_tasks')

    # Get bitrix_connection_id from user
    bitrix_connection_id = None
    if user_id:
        conn = get_primary_bitrix_connection(user_id)
        bitrix_connection_id = safe_int(conn.get('id')) if conn else None

    plan_id = db_one(
        """
        INSERT INTO employee_development_plans(
          employee_id, user_id, bitrix_connection_id,
          run_ids_json, problem_modules_json, tasks_json,
          claude_request_json, claude_response_json, status
        ) VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, 'draft')
        RETURNING id
        """,
        (
            employee_id,
            user_id,
            bitrix_connection_id,
            json.dumps(run_ids, ensure_ascii=False),
            json.dumps(problem_modules, ensure_ascii=False),
            json.dumps(tasks, ensure_ascii=False),
            json.dumps(to_jsonable(req_payload), ensure_ascii=False),
            json.dumps(to_jsonable(resp_payload), ensure_ascii=False),
        ),
    )

    db_log('plan', 'operator_plan_generated', str(employee_id), {
        'employee_id': employee_id, 'employee_id': operator_id, 'plan_id': int(plan_id['id']),
        'run_ids': run_ids, 'tasks_count': len(tasks),
    }, 'ok')

    return {
        'id': int(plan_id['id']),
        'employee_id': operator_id,
        'employee_id': employee_id,
        'run_ids': run_ids,
        'problem_modules': problem_modules,
        'tasks': tasks,
        'bitrix_task_ids': [],
        'status': 'draft',
    }


def send_plan_to_bitrix(plan_id: int, employee_id: int, user_id: int) -> dict:
    """`employee_id` is internal employees.id; we resolve the matching Bitrix user_id from
    employees.bitrix_user_id for task assignment."""
    plan = db_one(
        "SELECT * FROM employee_development_plans WHERE id=%s AND employee_id=%s AND user_id=%s",
        (plan_id, employee_id, user_id),
    )
    if not plan:
        raise RuntimeError('plan_not_found')
    # Bitrix-side assignee is the employee's linked bitrix_user_id (Bitrix tasks need that).
    emp_row = db_one("SELECT bitrix_user_id FROM employees WHERE id=%s", (employee_id,)) or {}
    operator_id = safe_int(emp_row.get('bitrix_user_id'))
    if plan.get('status') == 'sent':
        raise RuntimeError('already_sent')

    tasks = list(plan.get('tasks_json') or [])
    if not tasks:
        raise RuntimeError('no_tasks_in_plan')

    bitrix_ctx = get_user_bitrix_context(user_id, connection_id=safe_int(plan.get('bitrix_connection_id')))

    from datetime import timedelta
    now = datetime.now(timezone.utc)
    created_ids = []
    errors = []

    for task in tasks:
        deadline_days = int(task.get('deadline_days') or 7)
        deadline_dt = now + timedelta(days=deadline_days)
        deadline_str = deadline_dt.strftime('%Y-%m-%dT%H:%M:%S%z')

        fields = {
            'TITLE': str(task.get('title') or 'Задача развития сотрудника'),
            'DESCRIPTION': str(task.get('description') or ''),
            'RESPONSIBLE_ID': operator_id,
            'DEADLINE': deadline_str,
            'PRIORITY': '1',
        }
        try:
            result = bitrix_api_post('tasks.task.add', {'fields': fields}, bitrix_ctx)
            task_result = result.get('result', {})
            task_id = safe_int((task_result.get('task') or {}).get('id') if isinstance(task_result.get('task'), dict) else task_result.get('id'))
            if task_id:
                created_ids.append(task_id)
        except Exception as exc:
            errors.append({'title': fields['TITLE'], 'error': str(exc)})

    db_exec(
        """
        UPDATE employee_development_plans
        SET bitrix_task_ids_json=%s::jsonb,
            status=CASE WHEN %s > 0 THEN 'sent' ELSE 'draft' END,
            updated_at=NOW()
        WHERE id=%s
        """,
        (json.dumps(created_ids, ensure_ascii=False), len(created_ids), plan_id),
    )

    db_log('plan', 'plan_sent_to_bitrix', str(plan_id), {
        'plan_id': plan_id, 'employee_id': operator_id,
        'created_task_ids': created_ids, 'errors': errors,
    }, 'ok' if created_ids else 'error')

    return {
        'created_count': len(created_ids),
        'bitrix_task_ids': created_ids,
        'errors': errors,
        'status': 'sent' if created_ids else 'draft',
    }


# ============================================================
# Notifications
# ============================================================

def create_notification(user_id: int, ntype: str, payload: dict) -> int:
    row = db_one(
        "INSERT INTO user_notifications(user_id, type, payload_json) VALUES (%s, %s, %s::jsonb) RETURNING id",
        (user_id, ntype, json.dumps(payload, ensure_ascii=False)),
    )
    return int(row['id'])


def get_notifications(user_id: int, limit: int = 30) -> list:
    rows = db_all(
        """
        SELECT id, type, payload_json, read_at, created_at
        FROM user_notifications
        WHERE user_id = %s
        ORDER BY created_at DESC
        LIMIT %s
        """,
        (user_id, limit),
    )
    result = []
    for r in rows:
        result.append({
            'id': int(r['id']),
            'type': str(r['type']),
            'payload': dict(r.get('payload_json') or {}),
            'read': r.get('read_at') is not None,
            'created_at': str(r.get('created_at') or ''),
        })
    return result


def mark_notification_read(notif_id: int, user_id: int) -> bool:
    db_exec(
        "UPDATE user_notifications SET read_at=NOW() WHERE id=%s AND user_id=%s AND read_at IS NULL",
        (notif_id, user_id),
    )
    return True


# ============================================================
# Operator plan cycles (auto-triggered)
# ============================================================

def _build_cycle_plan_email_html(operator_name: str, plan: dict, cycle_id: int) -> str:
    tasks = plan.get('tasks') or []
    tasks_html = ''.join(
        f'<li style="margin-bottom:6px"><strong>{t.get("title","")}</strong> — {t.get("description","")}</li>'
        for t in tasks
    )
    problems = plan.get('problem_modules') or []
    problems_html = ''.join(
        f'<li>{p.get("module_name","")} <span style="color:#888">({p.get("block_name","")})</span></li>'
        for p in problems[:5]
    )
    return f"""
<div style="font-family:sans-serif;max-width:600px;margin:0 auto">
<h2 style="color:#111">План развития сотрудника готов</h2>
<p>На основе последних 5 звонков сотрудника <strong>{operator_name}</strong> система сформировала план развития.</p>
<h3 style="color:#333;margin-top:24px">Системные проблемы</h3>
<ul style="color:#444">{problems_html}</ul>
<h3 style="color:#333;margin-top:24px">Задачи</h3>
<ul style="color:#444">{tasks_html}</ul>
<p style="margin-top:24px;color:#666;font-size:13px">
Откройте OKO Systems, чтобы просмотреть план и отправить задачи в Bitrix24.
</p>
</div>
"""


def _build_cycle_report_email_html(operator_name: str, report: dict, cycle_id: int) -> str:
    improved = report.get('improved_modules') or []
    regressed = report.get('regressed_modules') or []
    unchanged = report.get('unchanged_modules') or []
    before_score = report.get('base_avg_score', 0)
    after_score = report.get('check_avg_score', 0)
    delta = round(after_score - before_score, 1)
    delta_str = f'+{delta}%' if delta > 0 else f'{delta}%'
    delta_color = '#16a34a' if delta > 0 else ('#dc2626' if delta < 0 else '#666')

    def module_rows(modules, color):
        return ''.join(
            f'<li style="color:{color}">{m.get("module_name","")} '
            f'<span style="color:#888">{round(m.get("base_coef",0)*100)}% → {round(m.get("check_coef",0)*100)}%</span></li>'
            for m in modules[:5]
        )

    return f"""
<div style="font-family:sans-serif;max-width:600px;margin:0 auto">
<h2 style="color:#111">Отчёт о прогрессе сотрудника</h2>
<p>Сотрудник <strong>{operator_name}</strong>. Сравнение: 5 звонков до и после плана.</p>
<p style="font-size:22px;font-weight:bold;color:{delta_color}">
  Изменение: {delta_str} ({round(before_score,1)}% → {round(after_score,1)}%)
</p>
{'<h3 style="color:#16a34a">Улучшилось</h3><ul>' + module_rows(improved, '#16a34a') + '</ul>' if improved else ''}
{'<h3 style="color:#dc2626">Ухудшилось</h3><ul>' + module_rows(regressed, '#dc2626') + '</ul>' if regressed else ''}
<p style="margin-top:24px;color:#666;font-size:13px">
Откройте OKO Systems для полного отчёта.
</p>
</div>
"""


def _generate_plan_for_cycle(cycle_id: int, employee_id: int, user_id: int):
    try:
        cycle = db_one("SELECT * FROM employee_plan_cycles WHERE id=%s", (cycle_id,))
        if not cycle:
            return
        base_run_ids = list(cycle.get('base_run_ids_json') or [])
        if not base_run_ids:
            raise RuntimeError('no_base_run_ids')

        emp_row = db_one("SELECT name FROM employees WHERE id=%s", (employee_id,)) or {}
        operator_name = str(emp_row.get('name') or f'Сотрудник {employee_id}')

        plan = generate_employee_plan(employee_id, user_id=user_id, run_ids=base_run_ids)
        plan_id = plan['id']

        db_exec(
            "UPDATE employee_plan_cycles SET status='plan_ready', plan_id=%s, updated_at=NOW() WHERE id=%s",
            (plan_id, cycle_id),
        )

        notif_id = create_notification(user_id, 'plan_ready', {
            'cycle_id': cycle_id,
            'plan_id': plan_id,
            'employee_id': employee_id,
            'employee_name': operator_name,
        })

        # Send email notification
        user_row = db_one("SELECT email, first_name FROM users WHERE id=%s", (user_id,))
        if user_row and user_row.get('email'):
            try:
                html = _build_cycle_plan_email_html(operator_name, plan, cycle_id)
                send_mailtrap_email(
                    user_row['email'],
                    f'OKO: план развития — {operator_name}',
                    f'Готов план развития сотрудника {operator_name} на основе последних 5 звонков.',
                    html_body=html,
                    category='plan-ready',
                )
            except Exception as email_exc:
                logging.warning(f'plan email send failed cycle={cycle_id}: {email_exc}')

        db_log('cycle', 'plan_cycle_plan_ready', str(cycle_id), {
            'cycle_id': cycle_id, 'plan_id': plan_id, 'employee_id': employee_id,
        }, 'ok')

    except Exception as exc:
        db_exec(
            "UPDATE employee_plan_cycles SET status='error', error_text=%s, updated_at=NOW() WHERE id=%s",
            (str(exc)[:500], cycle_id),
        )
        db_log('cycle', 'plan_cycle_error', str(cycle_id), {'error': str(exc)}, 'error')


def _generate_report_for_cycle(cycle_id: int, employee_id: int, user_id: int):
    try:
        cycle = db_one("SELECT * FROM employee_plan_cycles WHERE id=%s", (cycle_id,))
        if not cycle:
            return
        base_run_ids = list(cycle.get('base_run_ids_json') or [])
        check_run_ids = list(cycle.get('check_run_ids_json') or [])
        if not base_run_ids or not check_run_ids:
            raise RuntimeError('missing_run_ids')

        emp_row = db_one("SELECT name FROM employees WHERE id=%s", (employee_id,)) or {}
        operator_name = str(emp_row.get('name') or f'Сотрудник {employee_id}')

        def fetch_module_scores(run_ids):
            rows = db_all(
                """
                SELECT
                  COALESCE(sm.module_name, ms.module_name) AS module_name,
                  COALESCE(sb.block_name, ms.block_name) AS block_name,
                  AVG(ms.raw_coef::float) AS avg_coef
                FROM qa_analysis_module_scores ms
                LEFT JOIN qa_standard_modules sm ON sm.id = ms.standard_module_id
                LEFT JOIN qa_standard_blocks sb ON sb.id = sm.block_id
                WHERE ms.run_id = ANY(%s)
                GROUP BY COALESCE(sm.module_name, ms.module_name), COALESCE(sb.block_name, ms.block_name)
                """,
                (run_ids,),
            )
            return {str(r['module_name']): float(r['avg_coef'] or 0) for r in rows}

        def fetch_avg_score(run_ids):
            rows = db_all(
                """
                SELECT overall_score_0_100
                FROM qa_analysis_results
                WHERE run_id = ANY(%s) AND overall_score_0_100 IS NOT NULL
                """,
                (run_ids,),
            )
            if not rows:
                return 0.0
            return round(sum(float(r['overall_score_0_100'] or 0) for r in rows) / len(rows), 1)

        base_scores = fetch_module_scores(base_run_ids)
        check_scores = fetch_module_scores(check_run_ids)
        base_avg = fetch_avg_score(base_run_ids)
        check_avg = fetch_avg_score(check_run_ids)

        all_modules = set(base_scores) | set(check_scores)
        improved, regressed, unchanged = [], [], []
        for mod in all_modules:
            b = base_scores.get(mod, 0.0)
            c = check_scores.get(mod, 0.0)
            entry = {'module_name': mod, 'base_coef': round(b, 2), 'check_coef': round(c, 2)}
            diff = c - b
            if diff >= 0.1:
                improved.append(entry)
            elif diff <= -0.1:
                regressed.append(entry)
            else:
                unchanged.append(entry)

        improved.sort(key=lambda x: x['check_coef'] - x['base_coef'], reverse=True)
        regressed.sort(key=lambda x: x['check_coef'] - x['base_coef'])

        report = {
            'base_avg_score': base_avg,
            'check_avg_score': check_avg,
            'delta': round(check_avg - base_avg, 1),
            'improved_modules': improved[:10],
            'regressed_modules': regressed[:10],
            'unchanged_count': len(unchanged),
        }

        db_exec(
            "UPDATE employee_plan_cycles SET status='report_ready', report_json=%s::jsonb, updated_at=NOW() WHERE id=%s",
            (json.dumps(report, ensure_ascii=False), cycle_id),
        )

        create_notification(user_id, 'report_ready', {
            'cycle_id': cycle_id,
            'plan_id': safe_int(cycle.get('plan_id')),
            'employee_id': employee_id,
            'employee_name': operator_name,
            'delta': report['delta'],
        })

        user_row = db_one("SELECT email, first_name FROM users WHERE id=%s", (user_id,))
        if user_row and user_row.get('email'):
            try:
                html = _build_cycle_report_email_html(operator_name, report, cycle_id)
                send_mailtrap_email(
                    user_row['email'],
                    f'OKO: отчёт о прогрессе — {operator_name}',
                    f'Готов отчёт о прогрессе сотрудника {operator_name}. Изменение: {report["delta"]:+}%',
                    html_body=html,
                    category='report-ready',
                )
            except Exception as email_exc:
                logging.warning(f'report email send failed cycle={cycle_id}: {email_exc}')

        db_log('cycle', 'plan_cycle_report_ready', str(cycle_id), {
            'cycle_id': cycle_id, 'employee_id': employee_id, 'delta': report['delta'],
        }, 'ok')

    except Exception as exc:
        db_exec(
            "UPDATE employee_plan_cycles SET status='error', error_text=%s, updated_at=NOW() WHERE id=%s",
            (str(exc)[:500], cycle_id),
        )
        db_log('cycle', 'plan_cycle_report_error', str(cycle_id), {'error': str(exc)}, 'error')


def check_employee_plan_trigger(run_id: int, employee_id: int, user_id: int):
    """Plan-cycle scheduler. Keys cycles by internal employee_id, so a Bitrix admin renaming
    an account creates a new employee + a new cycle scope — old cycles stay with the prior
    employee, new analyses get their own."""
    try:
        if not employee_id:
            return
        # Linked Bitrix user_id (for legacy operator_id column on cycle row).
        emp_row = db_one("SELECT bitrix_user_id FROM employees WHERE id=%s", (employee_id,)) or {}
        operator_id = safe_int(emp_row.get('bitrix_user_id')) or 0

        last_cycle = db_one(
            """
            SELECT * FROM employee_plan_cycles
            WHERE employee_id=%s AND user_id=%s
            ORDER BY created_at DESC LIMIT 1
            """,
            (employee_id, user_id),
        )

        if last_cycle and last_cycle['status'] in ('plan_generating', 'report_generating'):
            return

        if last_cycle and last_cycle['status'] in ('plan_ready', 'monitoring'):
            if last_cycle['status'] == 'plan_ready':
                db_exec(
                    "UPDATE employee_plan_cycles SET status='monitoring', updated_at=NOW() WHERE id=%s",
                    (last_cycle['id'],),
                )

            # One export = one call from the user's perspective. If we've retried analysis on
            # the same export 5 times due to network blips, that's still 1 call, not 5.
            # DISTINCT ON (export_id) keeps only the latest completed run per export.
            new_runs = db_all(
                """
                SELECT DISTINCT ON (e.id) r.id, r.completed_at
                FROM qa_analysis_runs r
                JOIN analysis_exports e ON e.id = r.export_id
                WHERE r.status='completed'
                  AND e.employee_id=%s AND e.user_id=%s
                  AND r.id > %s
                ORDER BY e.id, r.completed_at DESC NULLS LAST, r.id DESC
                """,
                (employee_id, user_id, max(list(last_cycle.get('base_run_ids_json') or [0]))),
            )
            new_runs = sorted(new_runs, key=lambda x: x['completed_at'] or 0)
            if len(new_runs) >= 5:
                check_run_ids = [int(r['id']) for r in new_runs[:5]]
                db_exec(
                    """
                    UPDATE employee_plan_cycles
                    SET status='report_generating', check_run_ids_json=%s::jsonb, updated_at=NOW()
                    WHERE id=%s
                    """,
                    (json.dumps(check_run_ids, ensure_ascii=False), last_cycle['id']),
                )
                import threading as _threading
                _threading.Thread(
                    target=_generate_report_for_cycle,
                    args=(int(last_cycle['id']), employee_id, user_id),
                    daemon=True,
                ).start()
            return

        used_run_ids = set()
        if last_cycle:
            used_run_ids.update(int(x) for x in (last_cycle.get('base_run_ids_json') or []))
            used_run_ids.update(int(x) for x in (last_cycle.get('check_run_ids_json') or []))

        # DISTINCT ON (export_id) — one analysis = one call, not N retries on the same call.
        all_completed = db_all(
            """
            SELECT DISTINCT ON (e.id) r.id, r.completed_at
            FROM qa_analysis_runs r
            JOIN analysis_exports e ON e.id = r.export_id
            WHERE r.status='completed'
              AND e.employee_id=%s AND e.user_id=%s
            ORDER BY e.id, r.completed_at DESC NULLS LAST, r.id DESC
            LIMIT 50
            """,
            (employee_id, user_id),
        )
        all_completed = sorted(all_completed, key=lambda x: x['completed_at'] or 0, reverse=True)
        new_runs = [r for r in all_completed if int(r['id']) not in used_run_ids]

        if len(new_runs) >= 5:
            base_run_ids = [int(r['id']) for r in new_runs[:5]]
            cycle_row = db_one(
                """
                INSERT INTO employee_plan_cycles(employee_id, user_id, status, base_run_ids_json)
                VALUES (%s, %s, 'plan_generating', %s::jsonb)
                RETURNING id
                """,
                (employee_id, user_id, json.dumps(base_run_ids, ensure_ascii=False)),
            )
            cycle_id = int(cycle_row['id'])
            import threading as _threading
            _threading.Thread(
                target=_generate_plan_for_cycle,
                args=(cycle_id, employee_id, user_id),
                daemon=True,
            ).start()
            db_log('cycle', 'plan_cycle_created', str(cycle_id), {
                'employee_id': employee_id, 'user_id': user_id,
                'base_run_ids': base_run_ids,
            }, 'ok')

    except Exception as exc:
        logging.warning(f'check_employee_plan_trigger error run={run_id}: {exc}')


def get_employee_cycles(employee_id: int, user_id: int) -> list:
    """Cycles are per internal employee, not per Bitrix user_id."""
    rows = db_all(
        """
        SELECT id, status, base_run_ids_json, check_run_ids_json,
               plan_id, report_json, error_text, created_at, updated_at
        FROM employee_plan_cycles
        WHERE employee_id=%s AND user_id=%s
        ORDER BY created_at DESC
        LIMIT 20
        """,
        (employee_id, user_id),
    )
    result = []
    for r in rows:
        result.append({
            'id': int(r['id']),
            'status': str(r['status']),
            'base_run_ids': list(r.get('base_run_ids_json') or []),
            'check_run_ids': list(r.get('check_run_ids_json') or []),
            'plan_id': safe_int(r.get('plan_id')),
            'report': dict(r.get('report_json') or {}),
            'error_text': str(r.get('error_text') or ''),
            'created_at': str(r.get('created_at') or ''),
            'updated_at': str(r.get('updated_at') or ''),
        })
    return result


class Handler(BaseHTTPRequestHandler):
    def _status_only(self, status: int):
        self.send_response(status)
        self.end_headers()

    def _html(self, status: int, html: str, extra_headers: list[tuple[str, str]] | None = None):
        body = html.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        for key, value in (extra_headers or []):
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, location: str, extra_headers: list[tuple[str, str]] | None = None):
        self.send_response(302)
        self.send_header('Location', location)
        for key, value in (extra_headers or []):
            self.send_header(key, value)
        self.end_headers()

    def _json(self, status: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_HEAD(self):
        parsed = urlparse(self.path)
        if parsed.path in (
            '/', '/login', '/register', '/verify-code', '/forgot-password', '/reset-password', '/tenants',
            '/health', '/bitrix/oauth/callback',
            '/transcriptions/submit', '/transcriptions/status',
            '/connect/bitrix', '/legal/license', '/legal/privacy', '/app',
            '/api/notifications', '/api/notifications/read-all',
        ) or parsed.path.startswith('/r/') or parsed.path.startswith('/id/') or parsed.path.startswith('/dash') or parsed.path.startswith('/operator/') or parsed.path.startswith('/api/operator/') or parsed.path.startswith('/api/t/') or parsed.path.startswith('/t/') or parsed.path.startswith('/connect/bitrix/') or parsed.path.startswith('/bitrix/switch/') or parsed.path.startswith('/api/notifications/'):
            self._status_only(200)
            return
        self._status_only(404)

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        lang = detect_ui_lang(params, self.headers.get('Accept-Language', ''))
        auth_session = get_tg_session(self)
        ui_session = bool(auth_session)

        if parsed.path == '/':
            st_token = str((params.get('_st') or [''])[0] or '').strip()
            if st_token and not auth_session:
                row = db_one(
                    "SELECT s.*, u.login, u.email, u.first_name, u.last_name, u.username FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.session_token=%s AND s.expires_at>NOW() AND u.is_active=TRUE",
                    (st_token,),
                )
                if row:
                    self._redirect('/', extra_headers=[('Set-Cookie', f"{TG_SESSION_COOKIE}={st_token}; Max-Age={TG_SESSION_MAX_AGE_SEC}; Path=/; HttpOnly{COOKIE_SESSION_ATTR}")])
                    return
            if auth_session:
                self._redirect('/dash')
                return
            landing_path = Path(__file__).parent / 'landing.html'
            if landing_path.exists():
                self._html(200, landing_path.read_text('utf-8'))
                return
            self._redirect(add_lang_to_href('/login', lang))
            return

        if parsed.path == '/analyses':
            if not auth_session:
                self._redirect(add_lang_to_href('/login', lang) + f'?next=/dash/analyses')
                return
            self._redirect('/dash/analyses')
            return

        if parsed.path == '/logout':
            invalidate_tg_session(self)
            self._redirect('/login', extra_headers=[
                ('Set-Cookie', f"{UI_SESSION_COOKIE}=; Max-Age=0; Path=/; HttpOnly{COOKIE_SESSION_ATTR}"),
                ('Set-Cookie', f"{TG_SESSION_COOKIE}=; Max-Age=0; Path=/; HttpOnly{COOKIE_SESSION_ATTR}"),
            ])
            return

        if parsed.path == '/tenants':
            self._redirect(add_lang_to_href('/' if auth_session else '/login', lang))
            return

        if parsed.path == '/login':
            if auth_session:
                self._redirect(get_post_login_redirect_path(auth_session))
                return
            self._html(200, render_login_page(lang, current_path=parsed.path, query_params=params))
            return

        if parsed.path == '/register':
            if auth_session:
                self._redirect(get_post_login_redirect_path(auth_session))
                return
            self._html(200, render_register_page(lang, current_path=parsed.path, query_params=params))
            return

        if parsed.path == '/verify-code':
            token = str((params.get('token') or [''])[0] or '').strip()
            rec = get_auth_email_code_record(token)
            if not rec:
                self._html(400, render_login_page(lang, t(lang, 'auth_code_invalid'), current_path='/login', query_params=params))
                return
            self._html(
                200,
                render_email_code_page(
                    lang,
                    token=token,
                    email=str(rec.get('email') or ''),
                    current_path=parsed.path,
                    query_params=params,
                ),
            )
            return

        if parsed.path == '/forgot-password':
            if auth_session:
                self._redirect(get_post_login_redirect_path(auth_session))
                return
            self._html(200, render_forgot_password_page(lang, current_path=parsed.path, query_params=params))
            return

        if parsed.path == '/reset-password':
            token = str((params.get('token') or [''])[0] or '').strip()
            if not token:
                self._html(400, render_reset_password_page(lang, '', error_text=t(lang, 'reset_password_invalid'), valid=False, current_path=parsed.path, query_params=params))
                return
            rec = get_password_reset_token_record(token)
            if not rec:
                self._html(400, render_reset_password_page(lang, token, error_text=t(lang, 'reset_password_invalid'), valid=False, current_path=parsed.path, query_params=params))
                return
            self._html(200, render_reset_password_page(lang, token, current_path=parsed.path, query_params=params))
            return

        m_public_connect = PUBLIC_CONNECT_TOKEN_RE.match(parsed.path)
        if m_public_connect:
            connect_token = m_public_connect.group(1)
            rec = get_connect_token_record(connect_token)
            if not rec:
                self._html(400, render_connect_bitrix_page(lang, '', '', 'Ссылка подключения недействительна или уже использована.'))
                return
            self._html(200, render_connect_bitrix_page(lang, connect_token, ''))
            return

        m_legacy_tenant_connect = re.fullmatch(r'^/t/([A-Za-z0-9][A-Za-z0-9_-]{0,63})/connect$', parsed.path)
        if m_legacy_tenant_connect:
            if not auth_session:
                self._redirect(add_lang_to_href('/login', lang))
                return
            self._redirect('/connect/bitrix')
            return

        # Compatibility route: GET /connect/bitrix?id=<slug-or-uuid> -> generate token and redirect.
        if parsed.path == '/connect/bitrix':
            install_token = str((params.get('install_token') or [''])[0] or '').strip()
            if install_token:
                install_event = get_bitrix_install_event(install_token)
                if not install_event:
                    self._html(400, render_login_page(lang, 'Ссылка завершения установки недействительна или устарела.', current_path=parsed.path, query_params=params))
                    return
                if not auth_session:
                    redirect_url = f'/register?install_token={install_token}'
                    self._html(200, f'<!DOCTYPE html><html><head><meta charset="utf-8"><script>try{{window.top.location.href="{redirect_url}"}}catch(e){{window.location.href="{redirect_url}"}}</script></head><body></body></html>')
                    return
                try:
                    finalize_bitrix_install_event(auth_session, install_event)
                except Exception:
                    self._html(400, render_login_page(lang, 'Не удалось автоматически завершить подключение портала. Откройте кабинет и повторите подключение Bitrix24.', current_path=parsed.path, query_params=params))
                    return
                self._redirect('/?bonus=1')
                return
            member_id = str((params.get('member_id') or params.get('MEMBER_ID') or [''])[0] or '').strip()
            domain = str((params.get('DOMAIN') or params.get('domain') or [''])[0] or '').strip()
            if not auth_session:
                self._html(
                    200,
                    render_bitrix_embedded_page(
                        lang,
                        auth_session=auth_session,
                        domain=domain,
                        member_id=member_id,
                        current_path=parsed.path,
                        query_params=params,
                    ),
                )
                return
            connect_token = create_bitrix_connect_token_for_user(int(auth_session['user_id']))
            self._html(200, render_connect_bitrix_page(lang, connect_token, ''))
            return

        if re.fullmatch(r'^/t/([A-Za-z0-9][A-Za-z0-9_-]{0,63})$', parsed.path) or re.fullmatch(r'^/t/([A-Za-z0-9][A-Za-z0-9_-]{0,63})/crm$', parsed.path):
            if not auth_session:
                self._redirect(add_lang_to_href('/login', lang))
                return
            self._redirect('/')
            return

        m_switch_bitrix = re.fullmatch(r'^/bitrix/switch/(\d+)$', parsed.path)
        if m_switch_bitrix:
            if not auth_session:
                self._redirect(add_lang_to_href('/login', lang))
                return
            connection_id = safe_int(m_switch_bitrix.group(1))
            updated = set_primary_bitrix_connection(int(auth_session['user_id']), connection_id)
            if not updated:
                self._status_only(404)
                return
            next_href = str((params.get('next') or ['/'])[0] or '/').strip() or '/'
            if not next_href.startswith('/'):
                next_href = '/'
            self._redirect(next_href)
            return

        m_legacy_tenant_operator = re.fullmatch(r'^/t/([A-Za-z0-9][A-Za-z0-9_-]{0,63})/operators/(\d+)$', parsed.path)
        if m_legacy_tenant_operator:
            if not auth_session:
                self._redirect(f'/login?next=/dash/employee/{m_legacy_tenant_operator.group(2)}')
                return
            self._redirect(f'/dash/employee/{m_legacy_tenant_operator.group(2)}')
            return

        if parsed.path == '/dash':
            self.send_response(302)
            self.send_header('Location', '/dash/')
            self.end_headers()
            return
        if parsed.path == '/dash/' or parsed.path == '/dash/index.html' or (parsed.path.startswith('/dash/') and not parsed.path.startswith('/dash/assets/')):
            index_path = UI_DASH_DIST_PATH / 'index.html'
            if not index_path.exists():
                self._json(503, {'ok': False, 'error': 'dashboard_build_missing'})
                return
            body = index_path.read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path.startswith('/dash/assets/'):
            rel = parsed.path[len('/dash/'):]
            asset_path = (UI_DASH_DIST_PATH / rel).resolve()
            dist_root = UI_DASH_DIST_PATH.resolve()
            if not str(asset_path).startswith(str(dist_root)) or not asset_path.exists() or not asset_path.is_file():
                self._json(404, {'ok': False, 'error': 'dashboard_asset_not_found'})
                return
            body = asset_path.read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', guess_content_type(asset_path))
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        m_analysis_batch_api = re.fullmatch(r'^/api/analysis/batch/(\d+)$', parsed.path)
        if m_analysis_batch_api:
            if not auth_session:
                self._json(401, {'ok': False, 'error': 'unauthorized'})
                return
            bid = safe_int(m_analysis_batch_api.group(1))
            uid = safe_int(auth_session.get('user_id'))
            batch_payload = get_batch_status_payload(bid, uid)
            if not batch_payload:
                self._json(404, {'ok': False, 'error': 'not_found'})
                return
            batch_status = str(batch_payload.get('status') or 'queued')
            item_statuses = [str((item or {}).get('ui_status') or (item or {}).get('status') or '') for item in batch_payload.get('items') or []]
            if any(s == 'awaiting_operator' for s in item_statuses):
                batch_status = 'awaiting_operator'
            elif any(s in ('queued', 'processing') for s in item_statuses):
                batch_status = 'processing' if any(s == 'processing' for s in item_statuses) else 'queued'
            first_public_id = None
            try:
                link_row = db_one(
                    """
                    SELECT qrl.public_id FROM analysis_exports ae
                    LEFT JOIN qa_analysis_runs ar ON ar.export_id = ae.id
                    LEFT JOIN qa_report_links qrl ON qrl.run_id = ar.id AND qrl.is_active = TRUE
                    WHERE ae.batch_id = %s AND qrl.public_id IS NOT NULL
                    ORDER BY ae.id DESC LIMIT 1
                    """,
                    (bid,),
                )
                first_public_id = str(link_row['public_id']) if link_row else None
            except Exception:
                pass
            self._json(200, {'ok': True, 'status': batch_status, 'first_public_id': first_public_id, 'result': to_jsonable(batch_payload)})
            return

        m_report_api = REPORT_API_RE.match(parsed.path)
        if m_report_api:
            payload = get_report_payload(m_report_api.group(1))
            if not payload:
                self._json(404, {'ok': False, 'error': 'report_not_found'})
                return
            self._json(200, {'ok': True, 'result': to_jsonable(payload)})
            return

        m_chronology_api = CHRONOLOGY_API_RE.match(parsed.path)
        if m_chronology_api:
            payload = build_chronology_payload(m_chronology_api.group(1))
            if not payload:
                self._json(404, {'ok': False, 'error': 'chronology_not_found'})
                return
            self._json(200, {'ok': True, 'result': to_jsonable(payload)})
            return

        m_operator_api = EMPLOYEE_API_RE.match(parsed.path)
        if m_operator_api:
            payload = get_employee_progress_payload(safe_int(m_operator_api.group(1)), user_id=safe_int((auth_session or {}).get('user_id')))
            if not payload:
                self._json(404, {'ok': False, 'error': 'operator_not_found'})
                return
            self._json(200, {'ok': True, 'result': to_jsonable(payload)})
            return

        if ME_API_RE.match(parsed.path):
            uid = safe_int((auth_session or {}).get('user_id'))
            if not uid:
                self._json(401, {'ok': False, 'error': 'unauthorized'})
                return
            payload = get_me_payload(uid)
            if not payload:
                self._json(404, {'ok': False, 'error': 'user_not_found'})
                return
            self._json(200, {'ok': True, 'result': to_jsonable(payload)})
            return

        if EMPLOYEES_API_RE.match(parsed.path):
            uid = safe_int((auth_session or {}).get('user_id'))
            if not uid:
                self._json(401, {'ok': False, 'error': 'unauthorized'})
                return
            archived = (params.get('archived') or [''])[0] in ('1', 'true', 'yes')
            operators = get_employees_list(uid, archived=archived)
            self._json(200, {'ok': True, 'result': operators})
            return

        if STANDARDS_API_RE.match(parsed.path):
            uid = safe_int((auth_session or {}).get('user_id'))
            if not uid:
                self._json(401, {'ok': False, 'error': 'unauthorized'})
                return
            self._json(200, {'ok': True, 'result': get_standards_list(user_id=uid)})
            return

        m_standard_api = STANDARD_API_RE.match(parsed.path)
        if m_standard_api:
            uid = safe_int((auth_session or {}).get('user_id'))
            if not uid:
                self._json(401, {'ok': False, 'error': 'unauthorized'})
                return
            payload = get_standard_payload(safe_int(m_standard_api.group(1)), user_id=uid)
            if not payload:
                self._json(404, {'ok': False, 'error': 'standard_not_found'})
                return
            self._json(200, {'ok': True, 'result': payload})
            return

        m_standard_bitrix_fields = STANDARD_BITRIX_FIELDS_API_RE.match(parsed.path)
        if m_standard_bitrix_fields:
            uid = safe_int((auth_session or {}).get('user_id'))
            if not uid:
                self._json(401, {'ok': False, 'error': 'unauthorized'})
                return
            entity_type = (params.get('entity_type') or ['deal'])[0].strip().lower()
            if entity_type not in ('deal', 'lead'):
                entity_type = 'deal'
            try:
                bitrix_ctx = get_user_bitrix_context(uid)
            except Exception as exc:
                self._json(400, {'ok': False, 'error': 'no_bitrix', 'message': str(exc)})
                return
            list_method = 'crm.deal.userfield.list' if entity_type == 'deal' else 'crm.lead.userfield.list'
            get_method = 'crm.deal.userfield.get' if entity_type == 'deal' else 'crm.lead.userfield.get'
            try:
                rows = bitrix_list_all(list_method, {}, bitrix_ctx=bitrix_ctx)
            except Exception as exc:
                self._json(502, {'ok': False, 'error': 'bitrix_fetch_failed', 'message': str(exc)})
                return
            # `userfield.list` strips labels — fetch them via `userfield.get` in batches of 50.
            label_by_id: dict[str, str] = {}
            ids = [str(r.get('ID') or '').strip() for r in rows if isinstance(r, dict) and r.get('ID')]
            for i in range(0, len(ids), 50):
                chunk = ids[i:i + 50]
                cmds = {str(idx): f"{get_method}?ID={fid}" for idx, fid in enumerate(chunk)}
                try:
                    result = bitrix_batch(cmds, bitrix_ctx=bitrix_ctx)
                except Exception:
                    continue
                for idx, fid in enumerate(chunk):
                    item = result.get(str(idx)) or {}
                    if not isinstance(item, dict):
                        continue
                    label = ''
                    for src_key in ('EDIT_FORM_LABEL', 'LIST_COLUMN_LABEL'):
                        src = item.get(src_key) or {}
                        if isinstance(src, dict):
                            for lang_key in ('ru', 'en', 'kk'):
                                v = str(src.get(lang_key) or '').strip()
                                if v:
                                    label = v
                                    break
                        if label:
                            break
                    if label:
                        label_by_id[fid] = label
            fields = []
            for r in rows:
                if not isinstance(r, dict):
                    continue
                field_name = str(r.get('FIELD_NAME') or '').strip()
                if not field_name:
                    continue
                fid = str(r.get('ID') or '').strip()
                label = label_by_id.get(fid) or ''
                fields.append({
                    'field_code': field_name,
                    'label': label or field_name,
                    'user_type_id': str(r.get('USER_TYPE_ID') or '').strip(),
                    'mandatory': str(r.get('MANDATORY') or '').strip() == 'Y',
                    'entity_type': entity_type,
                })
            fields.sort(key=lambda f: f['label'].lower())
            self._json(200, {'ok': True, 'result': {'entity_type': entity_type, 'fields': fields}})
            return

        if ANALYSES_API_RE.match(parsed.path):
            uid = safe_int((auth_session or {}).get('user_id'))
            if not uid:
                self._json(401, {'ok': False, 'error': 'unauthorized'})
                return
            status_filter = (params.get('status') or ['all'])[0]
            page = max(1, safe_int((params.get('page') or ['1'])[0]) or 1)
            result = get_analyses_list(uid, status_filter=status_filter, page=page)
            self._json(200, {'ok': True, 'result': to_jsonable(result)})
            return

        m_operator_plan_api = EMPLOYEE_PLAN_API_RE.match(parsed.path)
        if m_operator_plan_api:
            emp_id = safe_int(m_operator_plan_api.group(1))
            uid = safe_int((auth_session or {}).get('user_id'))
            plan = get_employee_plan(emp_id, user_id=uid)
            if not plan:
                self._json(404, {'ok': False, 'error': 'plan_not_found'})
                return
            self._json(200, {'ok': True, 'result': to_jsonable(plan)})
            return

        if NOTIFICATIONS_API_RE.match(parsed.path):
            uid = safe_int((auth_session or {}).get('user_id'))
            if not uid:
                self._json(401, {'ok': False, 'error': 'unauthorized'})
                return
            notifs = get_notifications(uid)
            unread = sum(1 for n in notifs if not n['read'])
            self._json(200, {'ok': True, 'result': notifs, 'unread_count': unread})
            return

        m_operator_cycles_api = EMPLOYEE_CYCLES_API_RE.match(parsed.path)
        if m_operator_cycles_api:
            uid = safe_int((auth_session or {}).get('user_id'))
            if not uid:
                self._json(401, {'ok': False, 'error': 'unauthorized'})
                return
            emp_id = safe_int(m_operator_cycles_api.group(1))
            cycles = get_employee_cycles(emp_id, uid)
            self._json(200, {'ok': True, 'result': cycles})
            return

        m_legacy_tenant_export_api = re.fullmatch(r'^/api/t/([A-Za-z0-9][A-Za-z0-9_-]{0,63})/analysis/export/(\d+)$', parsed.path)
        if m_legacy_tenant_export_api:
            self._json(404, {'ok': False, 'error': 'deprecated_route'})
            return

        m_legacy_tenant_batch_api = re.fullmatch(r'^/api/t/([A-Za-z0-9][A-Za-z0-9_-]{0,63})/analysis/batch/(\d+)$', parsed.path)
        if m_legacy_tenant_batch_api:
            self._json(404, {'ok': False, 'error': 'deprecated_route'})
            return

        m_legacy_tenant_export_page = re.fullmatch(r'^/t/([A-Za-z0-9][A-Za-z0-9_-]{0,63})/analysis/export/(\d+)$', parsed.path)
        if m_legacy_tenant_export_page:
            self._status_only(404)
            return

        m_legacy_tenant_batch_page = re.fullmatch(r'^/t/([A-Za-z0-9][A-Za-z0-9_-]{0,63})/analysis/batch/(\d+)$', parsed.path)
        if m_legacy_tenant_batch_page:
            self._status_only(404)
            return

        m_report_pdf = REPORT_PDF_LINK_RE.match(parsed.path)
        if m_report_pdf:
            try:
                result = render_report_pdf(m_report_pdf.group(1))
            except RuntimeError as e:
                self._json(503, {'ok': False, 'error': str(e)})
                return
            except Exception as e:
                self._json(500, {'ok': False, 'error': f'pdf_render_failed: {e}'})
                return
            if not result:
                self._json(404, {'ok': False, 'error': 'report_not_found'})
                return
            pdf_bytes, filename, ascii_fallback = result
            disposition = (
                f'attachment; filename="{ascii_fallback}"; '
                f"filename*=UTF-8''{quote(filename)}"
            )
            self.send_response(200)
            self.send_header('Content-Type', 'application/pdf')
            self.send_header('Content-Length', str(len(pdf_bytes)))
            self.send_header('Content-Disposition', disposition)
            self.send_header('Cache-Control', 'private, max-age=0')
            self.end_headers()
            self.wfile.write(pdf_bytes)
            return

        m_report_txt = REPORT_TXT_LINK_RE.match(parsed.path)
        if m_report_txt:
            if not auth_session:
                self._redirect(f'/login?next=/dash/chronology/{m_report_txt.group(1)}')
                return
            self._redirect(f'/dash/chronology/{m_report_txt.group(1)}')
            return

        m_report_pretty_timeline = REPORT_PRETTY_TIMELINE_RE.match(parsed.path)
        if m_report_pretty_timeline:
            if not auth_session:
                self._redirect(f'/login?next=/dash/chronology/{m_report_pretty_timeline.group(1)}')
                return
            self._redirect(f'/dash/chronology/{m_report_pretty_timeline.group(1)}')
            return

        m_operator_report_timeline = OPERATOR_REPORT_TIMELINE_RE.match(parsed.path)
        if m_operator_report_timeline:
            if not auth_session:
                self._redirect(f'/login?next=/dash/chronology/{m_operator_report_timeline.group(2)}')
                return
            self._redirect(f'/dash/chronology/{m_operator_report_timeline.group(2)}')
            return

        m_report = REPORT_LINK_RE.match(parsed.path)
        if m_report:
            if not auth_session:
                self._redirect(f'/login?next=/dash/report/{m_report.group(1)}')
                return
            self._redirect(f'/dash/report/{m_report.group(1)}')
            return

        m_operator_report = OPERATOR_REPORT_RE.match(parsed.path)
        if m_operator_report:
            if not auth_session:
                self._redirect(f'/login?next=/dash/report/{m_operator_report.group(2)}')
                return
            self._redirect(f'/dash/report/{m_operator_report.group(2)}')
            return

        m_report_pretty = REPORT_PRETTY_RE.match(parsed.path)
        if m_report_pretty:
            if not auth_session:
                self._redirect(f'/login?next=/dash/report/{m_report_pretty.group(1)}')
                return
            self._redirect(f'/dash/report/{m_report_pretty.group(1)}')
            return

        m_operator = OPERATOR_DASH_RE.match(parsed.path)
        if m_operator:
            if not auth_session:
                self._redirect(f'/login?next=/dash/operator/{m_operator.group(1)}')
                return
            self._redirect(f'/dash/operator/{m_operator.group(1)}')
            return

        if parsed.path == '/health':
            self._json(200, {'ok': True, 'service': 'okosystems'})
            return

        if parsed.path in ('/readyz', '/readiness'):
            # Liveness says "process is up"; readiness says "can actually serve" — i.e. the DB
            # is reachable. Load balancers / UptimeRobot should probe this, not /health.
            try:
                with db_conn() as _c, _c.cursor() as _cur:
                    _cur.execute('SELECT 1')
                    _cur.fetchone()
                self._json(200, {'ok': True, 'db': 'up'})
            except Exception as exc:
                self._json(503, {'ok': False, 'db': 'down', 'error': str(exc)[:200]})
            return

        if parsed.path in ('/favicon.ico', '/favicon.svg', '/favicon-32.png', '/favicon-192.png', '/apple-touch-icon.png'):
            fname = parsed.path.lstrip('/')
            fpath = Path(__file__).parent / fname
            if fpath.exists():
                if fname.endswith('.ico'): ctype = 'image/x-icon'
                elif fname.endswith('.svg'): ctype = 'image/svg+xml'
                else: ctype = 'image/png'
                body = fpath.read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', ctype)
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'public, max-age=86400')
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()
            return

        if parsed.path in ('/app', '/request-demo', '/legal/license', '/legal/privacy'):
            file_map = {
                '/app': 'app-page.html',
                '/request-demo': 'request-demo.html',
                '/legal/license': 'legal-license.html',
                '/legal/privacy': 'legal-privacy.html',
            }
            fpath = Path(__file__).parent / file_map[parsed.path]
            if fpath.exists():
                self._html(200, fpath.read_text('utf-8'))
            else:
                self._html(404, '<h1>Not found</h1>')
            return

        if parsed.path == '/transcriptions/status':
            ok, err = require_admin_token_from_query(params)
            if not ok:
                self._json(403, {'ok': False, 'error': err})
                return
            activity_id = (params.get('bitrix_activity_id') or [''])[0]
            if not activity_id:
                self._json(400, {'ok': False, 'error': 'missing_bitrix_activity_id'})
                return

            row = db_one(
                """
                SELECT c.bitrix_activity_id, c.audio_url, t.provider_job_id, t.status,
                       t.transcript_text, t.error_text, t.updated_at
                FROM calls c
                LEFT JOIN transcriptions t ON t.call_id = c.id
                WHERE c.bitrix_activity_id = %s
                ORDER BY t.id DESC
                LIMIT 1
                """,
                (int(activity_id),),
            )
            self._json(200, {'ok': True, 'result': row})
            return

        if parsed.path != '/bitrix/oauth/callback':
            self._json(404, {'error': 'not_found'})
            return

        code = (params.get('code') or [''])[0]
        error = (params.get('error') or [''])[0]
        state = (params.get('state') or [''])[0]  # connect_token for multi-tenant flow
        lang = detect_ui_lang(params, self.headers.get('Accept-Language', ''))

        if error:
            self._json(400, {
                'ok': False,
                'error': error,
                'error_description': (params.get('error_description') or [''])[0],
            })
            return

        if not code:
            self._json(400, {'ok': False, 'error': 'missing_code'})
            return

        # OAuth connect flow: state == user connect_token
        if state:
            connect_rec = get_connect_token_record(state)
            if not connect_rec:
                self._html(400, render_connect_bitrix_page(lang, '', '', 'Ссылка подключения недействительна или уже использована.'))
                return
            if not MT_CLIENT_ID or not MT_CLIENT_SECRET:
                self._json(500, {'ok': False, 'error': 'missing_mt_oauth_credentials'})
                return
            try:
                token_data = exchange_code_for_tokens_mt(code)
            except Exception as exc:
                self._json(502, {'ok': False, 'error': 'token_exchange_failed', 'details': str(exc)})
                return
            raw = token_data
            member_id = str(raw.get('member_id') or '')
            domain = str(raw.get('domain') or '')
            access_token = str(raw.get('access_token') or '')
            refresh_token = str(raw.get('refresh_token') or '')
            expires_at = bitrix_token_expires_at(
                expires=raw.get('expires'),
                expires_in=raw.get('expires_in'),
                expires_at=raw.get('expires_at'),
            )
            scope = str(raw.get('scope') or '')
            user_id = safe_int(connect_rec.get('user_id'))
            if not user_id:
                self._json(500, {'ok': False, 'error': 'connect_token_missing_user'})
                return
            activate_user_bitrix_connection(user_id, member_id, domain, access_token, refresh_token, expires_at, scope)
            mark_connect_token_used(state)
            self._html(200, render_oauth_success_page(lang, ''))
            return

        self._json(400, {'ok': False, 'error': 'missing_connect_state'})

    def do_POST(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        lang = detect_ui_lang(params, self.headers.get('Accept-Language', ''))
        auth_session = get_tg_session(self)

        if parsed.path == '/api/support-request':
            try:
                body = parse_body_json(self)
                name = str(body.get('name', '')).strip()[:100]
                company = str(body.get('company', '')).strip()[:100]
                contact = str(body.get('contact', '')).strip()[:100]
                message = str(body.get('message', '')).strip()[:1000]
                if name and TELEGRAM_BOT_TOKEN and DEMO_NOTIFY_CHAT_ID:
                    text = (
                        "\U0001f527 *Технический запрос*\n\n"
                        f"\U0001f464 *Имя:* {name}\n"
                        f"\U0001f3e2 *Компания:* {company or '\u2014'}\n"
                        f"\U0001f4de *Контакт:* {contact or '\u2014'}\n"
                        f"\U0001f4dd *Вопрос:* {message or '\u2014'}"
                    )
                    tg_payload = json.dumps({
                        'chat_id': DEMO_NOTIFY_CHAT_ID,
                        'text': text,
                        'parse_mode': 'Markdown'
                    }).encode('utf-8')
                    tg_req = Request(
                        f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage',
                        data=tg_payload,
                        headers={'Content-Type': 'application/json'},
                        method='POST'
                    )
                    urlopen(tg_req, timeout=10)
                self._json(200, {'ok': True})
            except Exception:
                self._json(500, {'ok': False})
            return

        m_plan_generate = EMPLOYEE_PLAN_GENERATE_RE.match(parsed.path)
        if m_plan_generate:
            if not auth_session:
                self._json(401, {'ok': False, 'error': 'unauthorized'})
                return
            emp_id = safe_int(m_plan_generate.group(1))
            uid = safe_int(auth_session.get('user_id'))
            try:
                body = parse_body_json(self)
            except Exception:
                body = {}
            calls_count = max(2, min(10, int(body.get('calls_count') or 5)))
            try:
                plan = generate_employee_plan(emp_id, user_id=uid, calls_count=calls_count)
                self._json(200, {'ok': True, 'result': to_jsonable(plan)})
            except RuntimeError as exc:
                self._json(400, {'ok': False, 'error': str(exc)})
            except Exception as exc:
                db_log('plan', 'generate_error', str(op_id), {}, 'error', str(exc))
                self._json(500, {'ok': False, 'error': 'internal_error'})
            return

        m_standard_rename = STANDARD_RENAME_API_RE.match(parsed.path)
        if m_standard_rename:
            if not auth_session:
                self._json(401, {'ok': False, 'error': 'unauthorized'})
                return
            try:
                body = parse_body_json(self)
            except Exception:
                body = {}
            try:
                result = rename_standard(safe_int(m_standard_rename.group(1)), str(body.get('name') or ''))
                self._json(200, {'ok': True, 'result': result})
            except RuntimeError as exc:
                self._json(400, {'ok': False, 'error': str(exc)})
            return

        m_standard_set_default = STANDARD_SET_DEFAULT_API_RE.match(parsed.path)
        if m_standard_set_default:
            uid = safe_int((auth_session or {}).get('user_id'))
            if not uid:
                self._json(401, {'ok': False, 'error': 'unauthorized'})
                return
            try:
                result = set_user_default_standard(uid, safe_int(m_standard_set_default.group(1)))
                self._json(200, {'ok': True, 'result': result})
            except RuntimeError as exc:
                self._json(400, {'ok': False, 'error': str(exc)})
            return

        m_standard_card_fields = STANDARD_CARD_FIELDS_API_RE.match(parsed.path)
        if m_standard_card_fields:
            if not auth_session:
                self._json(401, {'ok': False, 'error': 'unauthorized'})
                return
            try:
                body = parse_body_json(self)
            except Exception:
                body = {}
            try:
                result = save_standard_card_fields(safe_int(m_standard_card_fields.group(1)), body.get('fields') or [])
                self._json(200, {'ok': True, 'result': result})
            except RuntimeError as exc:
                self._json(400, {'ok': False, 'error': str(exc)})
            return

        m_emp_archive = EMPLOYEE_ARCHIVE_API_RE.match(parsed.path)
        if m_emp_archive:
            if not auth_session:
                self._json(401, {'ok': False, 'error': 'unauthorized'})
                return
            try:
                result = set_employee_status(safe_int(m_emp_archive.group(1)), safe_int(auth_session.get('user_id')), 'archived')
                self._json(200, {'ok': True, 'result': result})
            except RuntimeError as exc:
                self._json(400, {'ok': False, 'error': str(exc)})
            return

        m_emp_unarchive = EMPLOYEE_UNARCHIVE_API_RE.match(parsed.path)
        if m_emp_unarchive:
            if not auth_session:
                self._json(401, {'ok': False, 'error': 'unauthorized'})
                return
            try:
                result = set_employee_status(safe_int(m_emp_unarchive.group(1)), safe_int(auth_session.get('user_id')), 'active')
                self._json(200, {'ok': True, 'result': result})
            except RuntimeError as exc:
                self._json(400, {'ok': False, 'error': str(exc)})
            return

        m_plan_send = EMPLOYEE_PLAN_SEND_BITRIX_RE.match(parsed.path)
        if m_plan_send:
            if not auth_session:
                self._json(401, {'ok': False, 'error': 'unauthorized'})
                return
            emp_id = safe_int(m_plan_send.group(1))
            plan_id = safe_int(m_plan_send.group(2))
            uid = safe_int(auth_session.get('user_id'))
            try:
                result = send_plan_to_bitrix(plan_id, emp_id, uid)
                self._json(200, {'ok': True, 'result': to_jsonable(result)})
            except RuntimeError as exc:
                self._json(400, {'ok': False, 'error': str(exc)})
            except Exception as exc:
                db_log('plan', 'send_bitrix_error', str(plan_id), {}, 'error', str(exc))
                self._json(500, {'ok': False, 'error': 'internal_error'})
            return

        m_batch_delete = re.fullmatch(r'^/api/analysis/batch/(\d+)/delete$', parsed.path)
        if m_batch_delete:
            if not auth_session:
                self._json(401, {'ok': False, 'error': 'unauthorized'})
                return
            bid = safe_int(m_batch_delete.group(1))
            uid = safe_int(auth_session.get('user_id'))
            ok = delete_analysis_batch(bid, uid)
            self._json(200 if ok else 404, {'ok': ok})
            return

        m_export_operator = re.fullmatch(r'^/api/analysis/export/(\d+)/operator$', parsed.path)
        if m_export_operator:
            if not auth_session:
                self._json(401, {'ok': False, 'error': 'unauthorized'})
                return
            uid = safe_int(auth_session.get('user_id'))
            export_id = safe_int(m_export_operator.group(1))
            try:
                body = parse_body_json(self)
            except Exception:
                self._json(400, {'ok': False, 'error': 'invalid_json'})
                return
            operator_id = safe_int(body.get('operator_id'))
            if not export_id or not operator_id:
                self._json(400, {'ok': False, 'error': 'missing_operator'})
                return
            export = db_one(
                """
                SELECT id, status, selection_options_json, user_id, bitrix_connection_id
                FROM analysis_exports
                WHERE id = %s AND user_id = %s
                """,
                (export_id, uid),
            )
            if not export:
                self._json(404, {'ok': False, 'error': 'not_found'})
                return
            if str(export.get('status') or '') != 'awaiting_operator':
                self._json(409, {'ok': False, 'error': 'not_waiting_for_operator'})
                return
            options = export.get('selection_options_json')
            if isinstance(options, str):
                try:
                    options = json.loads(options)
                except Exception:
                    options = []
            if not isinstance(options, list):
                options = []
            chosen = next((opt for opt in options if safe_int((opt or {}).get('user_id')) == operator_id), None)
            if not chosen:
                self._json(400, {'ok': False, 'error': 'operator_not_in_options'})
                return
            operator_name = str(chosen.get('user_name') or '').strip()
            if is_placeholder_text(operator_name):
                try:
                    bitrix_ctx = get_user_bitrix_context(uid, connection_id=safe_int(export.get('bitrix_connection_id')))
                    operator_name, _ = resolve_user_name_position(operator_id, '', '', bitrix_ctx=bitrix_ctx)
                except Exception:
                    operator_name = ''
            if is_placeholder_text(operator_name):
                operator_name = f'ID {operator_id}'
            queue_export_with_operator(export_id, operator_id, operator_name)
            self._json(200, {'ok': True, 'export_id': export_id, 'employee_id': operator_id, 'employee_name': operator_name})
            return

        m_retry = ANALYSES_RETRY_RE.match(parsed.path)
        if m_retry:
            if not auth_session:
                self._json(401, {'ok': False, 'error': 'unauthorized'})
                return
            uid = safe_int(auth_session.get('user_id'))
            batch_id = safe_int(m_retry.group(1))
            batch = db_one(
                "SELECT id, user_id FROM analysis_batches WHERE id=%s",
                (batch_id,),
            )
            if not batch or safe_int(batch.get('user_id')) != uid:
                self._json(404, {'ok': False, 'error': 'batch_not_found'})
                return
            # Reset retry state on every export in the batch that ended in error, then re-queue.
            # process_export_job preserves successful transcripts (queue_and_process_audio skips
            # media with status='ready'), so this is variant B — only the failed parts redo.
            failed_exports = db_all(
                """
                SELECT id FROM analysis_exports
                WHERE batch_id = %s AND (status IN ('completed_with_errors','failed','error') OR retry_after IS NOT NULL)
                """,
                (batch_id,),
            ) or []
            if not failed_exports:
                self._json(400, {'ok': False, 'error': 'nothing_to_retry'})
                return
            db_exec(
                """
                UPDATE analysis_exports
                SET retry_after = NULL, retry_count = 0, error_kind = NULL,
                    error_summary = NULL, status = 'queued', updated_at = NOW()
                WHERE batch_id = %s AND (status IN ('completed_with_errors','failed','error') OR retry_after IS NOT NULL)
                """,
                (batch_id,),
            )
            # Reset both the status and the finalization markers — without clearing
            # final_message_sent_at, finalize_batch_if_ready early-returns and the batch
            # ends up stuck in 'queued' even after the retried export succeeds.
            db_exec(
                "UPDATE analysis_batches SET status='queued', final_message_sent_at=NULL, completed_at=NULL, updated_at=NOW() WHERE id=%s",
                (batch_id,),
            )
            ensure_export_worker()
            self._json(200, {'ok': True, 'batch_id': batch_id, 'retried': len(failed_exports)})
            return

        m_notif_read = NOTIFICATION_READ_RE.match(parsed.path)
        if m_notif_read:
            if not auth_session:
                self._json(401, {'ok': False, 'error': 'unauthorized'})
                return
            uid = safe_int(auth_session.get('user_id'))
            notif_id = safe_int(m_notif_read.group(1))
            mark_notification_read(notif_id, uid)
            self._json(200, {'ok': True})
            return

        if parsed.path == '/api/notifications/read-all':
            if not auth_session:
                self._json(401, {'ok': False, 'error': 'unauthorized'})
                return
            uid = safe_int(auth_session.get('user_id'))
            db_exec(
                "UPDATE user_notifications SET read_at=NOW() WHERE user_id=%s AND read_at IS NULL",
                (uid,),
            )
            self._json(200, {'ok': True})
            return

        if parsed.path == '/api/analysis/submit':
            if not auth_session:
                self._json(401, {'ok': False, 'error': 'unauthorized'})
                return
            uid = safe_int(auth_session.get('user_id'))
            try:
                body = parse_body_json(self)
            except Exception:
                self._json(400, {'ok': False, 'error': 'invalid_json'})
                return
            url_text = str(body.get('url') or '').strip()
            if not url_text:
                self._json(400, {'ok': False, 'error': 'missing_url'})
                return
            entity_refs = parse_entity_refs_from_text(url_text)
            if not entity_refs:
                self._json(400, {'ok': False, 'error': 'no_entity_link',
                                 'message': 'Не найдена ссылка на сделку или лид Bitrix24. URL должен содержать /crm/deal/details/ID/ или /crm/lead/details/ID/'})
                return
            connections = get_user_bitrix_connections(uid)
            if not connections:
                self._json(400, {'ok': False, 'error': 'no_bitrix',
                                 'message': 'Необходимо подключить Bitrix24 для запуска анализа'})
                return
            primary_conn = next((c for c in connections if c.get('is_primary')), connections[0])
            bitrix_connection_id = safe_int(primary_conn.get('id'))
            try:
                entity_ids_only = [eid for _, eid in entity_refs]
                batch = create_export_batch('web', url_text, entity_ids_only, user_id=uid, bitrix_connection_id=bitrix_connection_id)
                batch_id = safe_int(batch['id'])
                for entity_type, entity_id in entity_refs:
                    export = create_export_record('web', entity_id, batch_id=batch_id, user_id=uid, bitrix_connection_id=bitrix_connection_id, entity_type=entity_type)
                    export_id = safe_int(export['id'])
                    import threading
                    t_thread = threading.Thread(
                        target=initialize_export_selection,
                        args=(export_id, entity_id, uid, bitrix_connection_id),
                        kwargs={'entity_type': entity_type},
                        daemon=True,
                    )
                    t_thread.start()
                self._json(200, {'ok': True, 'batch_id': batch_id, 'deal_count': len(entity_refs)})
            except Exception as exc:
                self._json(500, {'ok': False, 'error': 'internal', 'message': str(exc)})
            return

        if parsed.path == '/api/demo-request':
            try:
                body = parse_body_json(self)
                name = str(body.get('name', '')).strip()[:100]
                company = str(body.get('company', '')).strip()[:100]
                phone = str(body.get('phone', '')).strip()[:50]
                if name and phone and TELEGRAM_BOT_TOKEN and DEMO_NOTIFY_CHAT_ID:
                    text = (
                        "\U0001f514 *Новая заявка на демо*\n\n"
                        f"\U0001f464 *Имя:* {name}\n"
                        f"\U0001f3e2 *Компания:* {company or '\u2014'}\n"
                        f"\U0001f4de *Телефон:* {phone}"
                    )
                    tg_payload = json.dumps({
                        'chat_id': DEMO_NOTIFY_CHAT_ID,
                        'text': text,
                        'parse_mode': 'Markdown'
                    }).encode('utf-8')
                    tg_req = Request(
                        f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage',
                        data=tg_payload,
                        headers={'Content-Type': 'application/json'},
                        method='POST'
                    )
                    urlopen(tg_req, timeout=10)
                self._json(200, {'ok': True})
            except Exception:
                self._json(500, {'ok': False})
            return

        if parsed.path == '/login':
            form = parse_body_form(self)
            login_value = str(form.get('email') or '').strip()
            next_href = str(form.get('next') or '').strip()
            install_token = str(form.get('install_token') or '').strip()
            login_method = str(form.get('method') or 'code').strip()

            if login_method == 'password':
                password_value = str(form.get('password') or '').strip()
                user = get_user_by_email(login_value)
                if not user:
                    self._html(200, render_login_page(lang, t(lang, 'login_error_missing_account'), login_value, current_path=parsed.path, query_params=params, mode='password'))
                    return
                if not str(user.get('password_hash') or '').strip():
                    self._html(200, render_login_page(lang, t(lang, 'login_error_no_password'), login_value, current_path=parsed.path, query_params=params, mode='password'))
                    return
                if not verify_password(password_value, str(user.get('password_hash') or '')):
                    self._html(200, render_login_page(lang, t(lang, 'login_error_wrong_password'), login_value, current_path=parsed.path, query_params=params, mode='password'))
                    return
                session_token = create_tg_session(int(user['id']))
                cookie_header = ('Set-Cookie', f"{TG_SESSION_COOKIE}={session_token}; Max-Age={TG_SESSION_MAX_AGE_SEC}; Path=/; HttpOnly{COOKIE_SESSION_ATTR}")
                if install_token:
                    install_event = get_bitrix_install_event(install_token)
                    if install_event:
                        ensure_user_bitrix_connection(int(user['id']), title='Bitrix24')
                        finalize_bitrix_install_event({'id': int(user['id'])}, install_event)
                    full_url = APP_BASE_URL.rstrip('/') + f'/?_st={session_token}'
                    self._html(200, f'<!DOCTYPE html><html><head><meta charset="utf-8"><script>try{{window.top.location.href="{full_url}"}}catch(e){{window.location.href="{full_url}"}}</script></head><body></body></html>')
                    return
                redirect_target = next_href if next_href.startswith('/') else get_post_login_redirect_path(user)
                self._redirect(redirect_target, extra_headers=[cookie_header])
                return

            user = get_user_by_email(login_value)
            if not user:
                self._html(200, render_login_page(lang, t(lang, 'login_error_missing_account'), login_value, current_path=parsed.path, query_params=params, mode='code'))
                return
            try:
                token, code = create_auth_email_code(
                    login_value,
                    purpose='login',
                    user_id=int(user['id']),
                    install_token=install_token,
                    next_path=next_href,
                )
                send_auth_code_email(login_value, code, lang=lang, purpose='login')
            except Exception:
                self._html(200, render_login_page(lang, 'Не удалось отправить код. Попробуйте ещё раз.', login_value, current_path=parsed.path, query_params=params, mode='code'))
                return
            self._html(
                200,
                render_email_code_page(
                    lang,
                    token=token,
                    email=normalize_email(login_value),
                    notice_text=t(lang, 'auth_code_notice_login'),
                    current_path='/verify-code',
                    query_params={'token': [token]},
                ),
            )
            return

        if parsed.path == '/register':
            form = parse_body_form(self)
            name_value = str(form.get('name') or '').strip()
            email_value = str(form.get('email') or '').strip()
            password_value = str(form.get('password') or '').strip()
            password2_value = str(form.get('password2') or '').strip()
            install_token = str(form.get('install_token') or '').strip()
            next_href = str(form.get('next') or '').strip()
            form_values = {'name': name_value, 'email': email_value}
            if not name_value or not email_value or not password_value:
                self._html(200, render_register_page(lang, 'Заполните все поля.', form_values, current_path=parsed.path, query_params=params))
                return
            if not is_valid_email(email_value):
                self._html(200, render_register_page(lang, t(lang, 'register_error_invalid_email'), form_values, current_path=parsed.path, query_params=params))
                return
            if len(password_value) < 8:
                self._html(200, render_register_page(lang, 'Пароль должен быть не менее 8 символов.', form_values, current_path=parsed.path, query_params=params))
                return
            if password_value != password2_value:
                self._html(200, render_register_page(lang, 'Пароли не совпадают.', form_values, current_path=parsed.path, query_params=params))
                return
            if get_user_by_email(email_value):
                self._html(200, render_register_page(lang, t(lang, 'register_error_email_taken'), form_values, current_path=parsed.path, query_params=params))
                return
            try:
                user = create_local_user(name_value, password_value, email_value, username=normalize_login(name_value))
            except ValueError as exc:
                msg = t(lang, 'register_error_email_taken') if 'email_taken' in str(exc) else 'Ошибка при создании аккаунта.'
                self._html(200, render_register_page(lang, msg, form_values, current_path=parsed.path, query_params=params))
                return
            session_token = create_tg_session(int(user['id']))
            cookie_header = ('Set-Cookie', f"{TG_SESSION_COOKIE}={session_token}; Max-Age={TG_SESSION_MAX_AGE_SEC}; Path=/; HttpOnly{COOKIE_SESSION_ATTR}")
            if install_token:
                install_event = get_bitrix_install_event(install_token)
                if install_event:
                    ensure_user_bitrix_connection(int(user['id']), title='Bitrix24')
                    finalize_bitrix_install_event({'id': int(user['id'])}, install_event)
                full_url = APP_BASE_URL.rstrip('/') + f'/?_st={session_token}'
                self._html(200, f'<!DOCTYPE html><html><head><meta charset="utf-8"><script>try{{window.top.location.href="{full_url}"}}catch(e){{window.location.href="{full_url}"}}</script></head><body></body></html>')
                return
            redirect_target = next_href if next_href.startswith('/') else get_post_login_redirect_path(user)
            self._redirect(redirect_target, extra_headers=[cookie_header])
            return

        if parsed.path == '/verify-code':
            form = parse_body_form(self)
            token = str(form.get('token') or '').strip()
            code = str(form.get('code') or '').strip()
            rec = get_auth_email_code_record(token)
            if not rec:
                self._html(400, render_login_page(lang, t(lang, 'auth_code_invalid'), current_path='/login', query_params=params))
                return
            email_value = str(rec.get('email') or '').strip()
            if hash_auth_email_code(token, code) != str(rec.get('code_hash') or ''):
                self._html(
                    200,
                    render_email_code_page(
                        lang,
                        token=token,
                        email=email_value,
                        error_text=t(lang, 'auth_code_wrong'),
                        current_path='/verify-code',
                        query_params={'token': [token]},
                    ),
                )
                return
            purpose = str(rec.get('purpose') or 'login').strip() or 'login'
            user = None
            if purpose == 'register':
                user = get_user_by_email(email_value)
                if not user:
                    try:
                        user = create_local_user_email_only(
                            str(rec.get('first_name') or '').strip() or email_value.split('@', 1)[0],
                            email_value,
                            username=normalize_login(str(rec.get('first_name') or '').strip() or email_value),
                        )
                    except ValueError:
                        self._html(200, render_register_page(lang, t(lang, 'register_error_email_taken'), {'email': email_value}, current_path='/register', query_params=params))
                        return
            else:
                user_id = safe_int(rec.get('user_id'))
                user = db_one("SELECT * FROM users WHERE id = %s AND is_active = TRUE", (user_id,)) if user_id else get_user_by_email(email_value)
            if not user:
                self._html(200, render_login_page(lang, t(lang, 'login_error_missing_account'), email_value, current_path='/login', query_params=params))
                return
            mark_auth_email_code_used(token)
            install_token_rec = str(rec.get('install_token') or '').strip()
            if install_token_rec:
                install_event = get_bitrix_install_event(install_token_rec)
                if install_event:
                    ensure_user_bitrix_connection(int(user['id']), title='Bitrix24')
                    finalize_bitrix_install_event({'id': int(user['id'])}, install_event)
            session_token = create_tg_session(int(user['id']))
            cookie_header = ('Set-Cookie', f"{TG_SESSION_COOKIE}={session_token}; Max-Age={TG_SESSION_MAX_AGE_SEC}; Path=/; HttpOnly{COOKIE_SESSION_ATTR}")
            if install_token_rec:
                full_url = APP_BASE_URL.rstrip('/') + f'/?_st={session_token}'
                self._html(200, f'<!DOCTYPE html><html><head><meta charset="utf-8"><script>try{{window.top.location.href="{full_url}"}}catch(e){{window.location.href="{full_url}"}}</script></head><body></body></html>')
                return
            redirect_target = str(rec.get('next_path') or '').strip()
            if not redirect_target.startswith('/'):
                redirect_target = get_post_login_redirect_path(user)
            self._redirect(redirect_target, extra_headers=[cookie_header])
            return

        if parsed.path == '/forgot-password':
            form = parse_body_form(self)
            email_value = str(form.get('email') or '').strip()
            if not is_valid_email(email_value):
                self._html(200, render_forgot_password_page(lang, t(lang, 'register_error_invalid_email'), '', email_value, current_path=parsed.path, query_params=params))
                return
            user = get_user_by_email(email_value)
            if user:
                try:
                    token = create_password_reset_token(int(user['id']))
                    send_password_reset_email(user, token, lang=lang)
                except Exception as exc:
                    db_log('auth', 'password_reset_email', str(user.get('id') or ''), {'email': normalize_email(email_value)}, 'error', str(exc))
            self._html(200, render_forgot_password_page(lang, '', t(lang, 'forgot_password_notice'), current_path=parsed.path, query_params=params))
            return

        if parsed.path == '/app/contact':
            form = parse_body_form(self)
            req_lang = str(form.get('lang') or lang or 'ru').strip().lower()
            if req_lang in SUPPORTED_UI_LANGS:
                lang = req_lang
            values = {
                'name': str(form.get('name') or '').strip(),
                'email': str(form.get('email') or '').strip(),
                'company': str(form.get('company') or '').strip(),
                'message': str(form.get('message') or '').strip(),
            }
            if not values['name'] or not values['email'] or not values['message']:
                self._html(200, render_marketplace_app_page(lang, error_text='Заполните имя, email и сообщение.', values=values))
                return
            if not is_valid_email(values['email']):
                self._html(200, render_marketplace_app_page(lang, error_text='Укажите корректный email для обратной связи.', values=values))
                return
            try:
                send_marketplace_contact_email(values['name'], values['email'], values['company'], values['message'])
            except Exception:
                self._html(200, render_marketplace_app_page(lang, error_text='Не удалось отправить запрос. Напишите на support@salmetov.fun.', values=values))
                return
            self._redirect(add_lang_to_href('/app?sent=1', lang))
            return

        if parsed.path == '/reset-password':
            form = parse_body_form(self)
            token = str(form.get('token') or '').strip()
            password = str(form.get('password') or '')
            password_confirm = str(form.get('password_confirm') or '')
            rec = get_password_reset_token_record(token)
            if not rec:
                self._html(400, render_reset_password_page(lang, token, error_text=t(lang, 'reset_password_invalid'), valid=False, current_path=parsed.path, query_params=params))
                return
            if len(password) < 8:
                self._html(200, render_reset_password_page(lang, token, error_text=t(lang, 'register_error_password_short'), current_path=parsed.path, query_params=params))
                return
            if password != password_confirm:
                self._html(200, render_reset_password_page(lang, token, error_text=t(lang, 'register_error_password_mismatch'), current_path=parsed.path, query_params=params))
                return
            update_user_password(int(rec['user_id']), password)
            invalidate_password_reset_tokens_for_user(int(rec['user_id']))
            self._html(200, render_reset_password_page(lang, '', notice_text=t(lang, 'reset_password_success'), valid=False, current_path=parsed.path, query_params=params))
            return

        if parsed.path == '/bitrix/disconnect':
            if not auth_session:
                self._redirect(add_lang_to_href('/login', lang))
                return
            form = parse_body_form(self)
            connection_id = safe_int(form.get('connection_id'))
            if not connection_id:
                self._redirect(add_lang_to_href("/", lang))
                return
            try:
                delete_user_bitrix_connection(int(auth_session['user_id']), connection_id)
            except Exception:
                self._redirect(add_lang_to_href("/?crm_error=disconnect", lang))
                return
            self._redirect(add_lang_to_href("/", lang))
            return

        if parsed.path == '/tenants':
            self._redirect(add_lang_to_href('/' if auth_session else '/login', lang))
            return

        m_legacy_tenant_crm_disconnect = re.fullmatch(r'^/t/([A-Za-z0-9][A-Za-z0-9_-]{0,63})/crm/disconnect$', parsed.path)
        if m_legacy_tenant_crm_disconnect:
            if not auth_session:
                self._redirect(add_lang_to_href('/login', lang))
                return
            try:
                disconnect_user_bitrix_connection(int(auth_session['user_id']))
            except Exception:
                self._redirect(add_lang_to_href("/?crm_error=disconnect", lang))
                return
            self._redirect(add_lang_to_href("/?crm_notice=disconnected", lang))
            return

        if parsed.path == '/connect/bitrix':
            # Bitrix24 marketplace install handler.
            # ONAPPINSTALL payload is application/x-www-form-urlencoded with nested keys.
            # Canonical fields per https://apidocs.bitrix24.com/api-reference/events/index.html:
            #   event=ONAPPINSTALL
            #   auth[access_token], auth[refresh_token], auth[domain],
            #   auth[member_id], auth[expires], auth[expires_in],
            #   auth[scope], auth[application_token]
            form = parse_body_form(self)
            access_token  = str(form.get('auth[access_token]')  or '').strip()
            refresh_token = str(form.get('auth[refresh_token]') or '').strip()
            domain        = normalize_bitrix_domain(str(form.get('auth[domain]') or '').strip())
            member_id     = str(form.get('auth[member_id]')     or '').strip()
            scope         = str(form.get('auth[scope]')         or '').strip()
            expires_at = bitrix_token_expires_at(
                expires=form.get('auth[expires]'),
                expires_in=form.get('auth[expires_in]'),
            )

            if not access_token or not member_id:
                db_log('bitrix', 'install_payload_invalid', member_id or None, {
                    'event': str(form.get('event') or ''),
                    'has_access_token': bool(access_token),
                    'has_member_id': bool(member_id),
                    'keys': sorted(form.keys()),
                }, 'warn', None)
                self._html(
                    200,
                    render_marketplace_install_page(
                        lang,
                        'Установка получена',
                        'Bitrix24 передал событие установки, но токены подключения не были получены. Повторите установку приложения и попробуйте снова.',
                        status='info',
                        action_href='/app',
                        action_label='Открыть Oko Systems',
                    ),
                )
                return

            if not domain:
                db_log('bitrix', 'install_missing_domain', member_id, {
                    'event': str(form.get('event') or ''),
                    'keys': sorted(form.keys()),
                }, 'warn', None)

            existing = get_bitrix_connection_by_member_id_or_domain(member_id=member_id, domain=domain)
            if existing:
                activate_user_bitrix_connection(int(existing['user_id']), member_id, domain, access_token, refresh_token, expires_at, scope)
                self._redirect(add_lang_to_href('/?bonus=1', lang))
                return

            if auth_session:
                activate_user_bitrix_connection(int(auth_session['user_id']), member_id, domain, access_token, refresh_token, expires_at, scope)
                self._redirect(add_lang_to_href('/?bonus=1', lang))
                return

            install_token = create_bitrix_install_event(member_id, domain, access_token, refresh_token, expires_at, scope)
            redirect_url = f'/register?install_token={install_token}'
            self._html(200, f'<!DOCTYPE html><html><head><meta charset="utf-8"><script>try{{window.top.location.href="{redirect_url}"}}catch(e){{window.location.href="{redirect_url}"}}</script></head><body></body></html>')
            return

        if parsed.path == '/logout':
            form = parse_body_form(self)
            next_href = str(form.get('next') or '/login').strip() or '/login'
            if not next_href.startswith('/'):
                next_href = '/login'
            invalidate_tg_session(self)
            self._redirect(next_href, extra_headers=[
                ('Set-Cookie', f"{UI_SESSION_COOKIE}=; Max-Age=0; Path=/; HttpOnly{COOKIE_SESSION_ATTR}"),
                ('Set-Cookie', f"{TG_SESSION_COOKIE}=; Max-Age=0; Path=/; HttpOnly{COOKIE_SESSION_ATTR}"),
            ])
            return

        m_employee_delete = EMPLOYEE_DELETE_RE.match(parsed.path)
        if m_employee_delete:
            if not auth_session:
                self._redirect(add_lang_to_href('/login', lang))
                return
            operator_id = safe_int(m_employee_delete.group(1))
            target_base = add_lang_to_href('/#employees', lang)
            if not operator_id:
                self._redirect(add_query_to_href(target_base, error='employee_delete_missing'))
                return
            try:
                result = delete_employee_data(operator_id)
                if int(result.get('deleted_exports') or 0) <= 0:
                    self._redirect(add_query_to_href(target_base, error='employee_delete_missing'))
                    return
                db_log('ui', 'employee_deleted', str(operator_id), {
                    'employee_id': operator_id,
                    'employee_name': result.get('operator_name') or '',
                    'deleted_exports': int(result.get('deleted_exports') or 0),
                    'deleted_batches': int(result.get('deleted_batches') or 0),
                }, 'ok', None)
                self._redirect(add_query_to_href(target_base, notice='employee_deleted_notice'))
                return
            except Exception as exc:
                db_log('ui', 'employee_deleted', str(operator_id), {'employee_id': operator_id}, 'error', str(exc))
                self._redirect(add_query_to_href(target_base, error='employee_delete_failed'))
                return

        if parsed.path == '/transcriptions/submit':
            try:
                data = parse_body_json(self)
            except Exception:
                self._json(400, {'ok': False, 'error': 'invalid_json'})
                return

            ok, err = require_admin_token_from_body(data)
            if not ok:
                self._json(403, {'ok': False, 'error': err})
                return

            if 'bitrix_activity_id' not in data:
                self._json(400, {'ok': False, 'error': 'missing_bitrix_activity_id'})
                return

            if 'audio_url' in data and data['audio_url']:
                audio_url = data['audio_url']
            else:
                user_id = safe_int(data.get('user_id'))
                bitrix_connection_id = safe_int(data.get('bitrix_connection_id'))
                file_id = data.get('bitrix_file_id')
                owner_id = data.get('owner_id')
                owner_type_id = data.get('owner_type_id', 6)
                if not file_id or not owner_id or not user_id:
                    self._json(400, {'ok': False, 'error': 'missing_audio_url_or_file_context_or_user'})
                    return
                try:
                    bitrix_ctx = get_user_bitrix_context(user_id, connection_id=bitrix_connection_id)
                    audio_url = build_crm_file_url(int(file_id), int(owner_id), int(owner_type_id), bitrix_ctx=bitrix_ctx)
                except Exception as exc:
                    self._json(502, {'ok': False, 'error': 'user_bitrix_context_failed', 'details': str(exc)})
                    return

            try:
                call_row = upsert_call(data, audio_url)
                submit_result = soniox_submit_only(audio_url)
                tr_row = create_transcription(call_row['id'], submit_result['request_payload'], submit_result['response_payload'])
                db_log('api', 'transcription_submitted', str(data['bitrix_activity_id']), submit_result['response_payload'], 'ok', None)
            except Exception as exc:
                db_log('api', 'transcription_submitted', str(data.get('bitrix_activity_id')), {'request': data}, 'error', str(exc))
                self._json(502, {'ok': False, 'error': 'submit_failed', 'details': str(exc)})
                return

            self._json(200, {
                'ok': True,
                'call_id': call_row['id'],
                'bitrix_activity_id': call_row['bitrix_activity_id'],
                'audio_url': audio_url,
                'provider': tr_row.get('provider') or submit_result.get('provider') or ACTIVE_TRANSCRIBE_PROVIDER,
                'provider_job_id': tr_row.get('provider_job_id'),
                'status': tr_row.get('status'),
            })
            return

        self._json(404, {'error': 'not_found'})

    def log_message(self, fmt, *args):
        return


if __name__ == '__main__':
    init_db()
    ensure_fixed_standard_seed()
    ensure_export_worker()
    ensure_qa_worker()
    ensure_token_refresh_worker()
    server = ThreadingHTTPServer((HOST, PORT), Handler)

    def _graceful_shutdown(signum, _frame):
        # serve_forever() runs in this (main) thread, so shutdown() must be invoked from another
        # thread to avoid a self-deadlock. In-flight background analyses are protected separately
        # by the re-queue-on-restart logic in init_db().
        print(f'received signal {signum}; shutting down gracefully...', flush=True)
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, _graceful_shutdown)
    signal.signal(signal.SIGINT, _graceful_shutdown)

    try:
        server.serve_forever()
    finally:
        server.server_close()
        close_db_pool()
        print('shutdown complete', flush=True)
