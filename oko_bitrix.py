"""Bitrix24 transport layer for OKO.

OAuth token exchange/refresh, a per-domain token-bucket rate limiter, and the raw REST call
primitives (bitrix_api / bitrix_batch / bitrix_list_all). Every call takes an explicit
bitrix_ctx (access_token + domain), so this stays pure transport: it depends only on
oko_config + stdlib + requests, never on app-level domain helpers — no import cycles.
"""
import json
import os
import threading
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

import requests

from oko_config import MT_CLIENT_ID, MT_CLIENT_SECRET, MT_REDIRECT_URI


def exchange_code_for_tokens_mt(code: str) -> dict:
    """Exchange Bitrix OAuth code using app credentials."""
    form = urlencode({
        'grant_type': 'authorization_code',
        'client_id': MT_CLIENT_ID,
        'client_secret': MT_CLIENT_SECRET,
        'code': code,
        'redirect_uri': MT_REDIRECT_URI,
    }).encode('utf-8')
    req = Request("https://oauth.bitrix.info/oauth/token/", data=form, method='POST')
    req.add_header('Content-Type', 'application/x-www-form-urlencoded')
    try:
        with urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except HTTPError as exc:
        raw = exc.read().decode('utf-8', errors='replace')
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {'error': 'http_error', 'status': exc.code, 'body': raw}
        raise RuntimeError(json.dumps(payload, ensure_ascii=False)) from exc
    except URLError as exc:
        raise RuntimeError(f'network_error: {exc}') from exc


def refresh_tokens_central(refresh_token: str, client_id: str, client_secret: str) -> dict:
    """Refresh OAuth tokens via Bitrix's central endpoint (oauth.bitrix.info).
    Works when the portal domain is unknown — the JSON response includes `domain`.
    """
    form = urlencode({
        'grant_type': 'refresh_token',
        'client_id': client_id,
        'client_secret': client_secret,
        'refresh_token': refresh_token,
    }).encode('utf-8')
    req = Request("https://oauth.bitrix.info/oauth/token/", data=form, method='POST')
    req.add_header('Content-Type', 'application/x-www-form-urlencoded')
    try:
        with urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except HTTPError as exc:
        raw = exc.read().decode('utf-8', errors='replace')
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {'error': 'http_error', 'status': exc.code, 'body': raw}
        raise RuntimeError(json.dumps(payload, ensure_ascii=False)) from exc
    except URLError as exc:
        raise RuntimeError(f'network_error: {exc}') from exc


def refresh_tokens_for_domain(refresh_token: str, domain: str, client_id: str, client_secret: str) -> dict:
    domain_value = str(domain or '').strip()
    if not domain_value:
        raise RuntimeError('missing_bitrix_domain')
    endpoint = f"https://{domain_value}/oauth/token/"
    form = urlencode({
        'grant_type': 'refresh_token',
        'client_id': client_id,
        'client_secret': client_secret,
        'refresh_token': refresh_token,
    }).encode('utf-8')
    req = Request(endpoint, data=form, method='POST')
    req.add_header('Content-Type', 'application/x-www-form-urlencoded')
    try:
        with urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except HTTPError as exc:
        raw = exc.read().decode('utf-8', errors='replace')
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {'error': 'http_error', 'status': exc.code, 'body': raw}
        raise RuntimeError(json.dumps(payload, ensure_ascii=False)) from exc
    except URLError as exc:
        raise RuntimeError(f'network_error: {exc}') from exc


# Per-domain rate limiter for Bitrix24 cloud (~2 req/sec sustained, ~30 req/30s burst).
# Token-bucket style: each domain has its own bucket; refilled at BITRIX_RPS_LIMIT/sec up to
# BITRIX_BURST_LIMIT tokens. acquire() blocks the caller if the bucket is empty.
BITRIX_RPS_LIMIT = float(os.getenv('BITRIX_RPS_LIMIT', '2.0'))
BITRIX_BURST_LIMIT = float(os.getenv('BITRIX_BURST_LIMIT', '25'))
_BITRIX_BUCKETS: dict[str, dict] = {}
_BITRIX_BUCKETS_LOCK = threading.Lock()


def _bitrix_rate_acquire(domain: str):
    """Block until at least 1 token is available in this domain's bucket. Token-bucket."""
    if not domain:
        return
    now = time.monotonic()
    with _BITRIX_BUCKETS_LOCK:
        bucket = _BITRIX_BUCKETS.get(domain)
        if bucket is None:
            bucket = {'tokens': BITRIX_BURST_LIMIT, 'last': now}
            _BITRIX_BUCKETS[domain] = bucket
        # Refill based on time since last update.
        elapsed = max(0.0, now - bucket['last'])
        bucket['tokens'] = min(BITRIX_BURST_LIMIT, bucket['tokens'] + elapsed * BITRIX_RPS_LIMIT)
        bucket['last'] = now
        if bucket['tokens'] >= 1.0:
            bucket['tokens'] -= 1.0
            return
        wait = (1.0 - bucket['tokens']) / BITRIX_RPS_LIMIT
    # Wait outside the lock so other threads aren't blocked.
    time.sleep(wait)
    # Recursive single retry — bucket should now have ≥1 token.
    _bitrix_rate_acquire(domain)


def bitrix_api(method: str, params: dict | None = None, bitrix_ctx: dict | None = None) -> dict:
    access_token = str((bitrix_ctx or {}).get('access_token') or '').strip()
    domain = str((bitrix_ctx or {}).get('domain') or '').strip()
    if not access_token:
        raise RuntimeError('missing_access_token')
    if not domain:
        raise RuntimeError('missing_bitrix_domain')

    q = dict(params or {})
    q['auth'] = access_token
    query = urlencode(q, doseq=True)
    url = f"https://{domain}/rest/{method}.json?{query}"

    # Token-bucket gate: if we're hammering this portal, slow down before sending.
    _bitrix_rate_acquire(domain)
    resp = requests.get(url, timeout=30)
    data = resp.json()
    if 'error' in data:
        # If Bitrix returned QUERY_LIMIT_EXCEEDED despite our throttler (e.g. another app on
        # the same portal also burned tokens), back off and retry once.
        err_code = str(data.get('error') or '')
        if err_code == 'QUERY_LIMIT_EXCEEDED':
            time.sleep(2.0)
            _bitrix_rate_acquire(domain)
            resp = requests.get(url, timeout=30)
            data = resp.json()
            if 'error' not in data:
                return data
        raise RuntimeError(json.dumps(data, ensure_ascii=False))
    return data


def bitrix_batch(commands: dict, bitrix_ctx: dict | None = None) -> dict:
    """Execute up to 50 Bitrix REST commands in a single HTTP call.
    `commands` maps label → "method?param1=value1&param2=value2". Returns the nested 'result.result' map."""
    access_token = str((bitrix_ctx or {}).get('access_token') or '').strip()
    domain = str((bitrix_ctx or {}).get('domain') or '').strip()
    if not access_token:
        raise RuntimeError('missing_access_token')
    if not domain:
        raise RuntimeError('missing_bitrix_domain')
    form = [('auth', access_token), ('halt', '0')]
    for label, cmd in commands.items():
        form.append((f'cmd[{label}]', cmd))
    _bitrix_rate_acquire(domain)
    resp = requests.post(f"https://{domain}/rest/batch.json", data=form, timeout=60)
    data = resp.json()
    if 'error' in data:
        raise RuntimeError(json.dumps(data, ensure_ascii=False))
    outer = data.get('result') or {}
    inner = outer.get('result')
    if isinstance(inner, list):
        return {str(i): v for i, v in enumerate(inner)}
    if isinstance(inner, dict):
        return inner
    return {}


def bitrix_list_all(method: str, params: dict, bitrix_ctx: dict | None = None) -> list:
    rows = []
    start = 0
    while True:
        p = dict(params)
        p['start'] = start
        data = bitrix_api(method, p, bitrix_ctx=bitrix_ctx)
        chunk = data.get('result', [])
        if isinstance(chunk, list):
            rows.extend(chunk)
        else:
            break
        if 'next' not in data:
            break
        start = data.get('next')
        if start is None:
            break
    return rows
