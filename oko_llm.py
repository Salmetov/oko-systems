"""Claude (Anthropic) client for OKO — the transport layer for LLM calls.

Streaming JSON call to the Anthropic messages API plus a tolerant JSON extractor. Domain
prompt construction stays in app.py; this module only knows *how* to talk to Claude. Depends
only on oko_config + oko_http + stdlib (no app imports -> no cycles).
"""
import json
import time

import requests

from oko_config import (
    ANTHROPIC_API_KEY,
    ANTHROPIC_MODEL,
    ANTHROPIC_MAX_TOKENS,
    ANTHROPIC_ENDPOINT,
    ANTHROPIC_CONNECT_TIMEOUT_SEC,
)
from oko_http import HTTP_SESSION


def extract_json_object(text: str):
    if not text:
        return None
    raw = text.strip()
    if raw.startswith('```'):
        parts = raw.split('```')
        for p in parts:
            p2 = p.strip()
            if p2.startswith('{') and p2.endswith('}'):
                raw = p2
                break
            if '\n' in p2:
                body = p2.split('\n', 1)[1].strip()
                if body.startswith('{') and body.endswith('}'):
                    raw = body
                    break
    try:
        return json.loads(raw)
    except Exception:
        start = raw.find('{')
        end = raw.rfind('}')
        if start >= 0 and end > start:
            try:
                return json.loads(raw[start:end + 1])
            except Exception:
                return None
    return None


def call_claude_json(system_prompt: str, user_prompt: str, model: str | None = None):
    """Streaming Claude call. Reads SSE events as they arrive — keeps the TCP socket flowing
    constantly so flaky KZ→AWS routes can't develop a zombie connection. Read timeout is
    per-chunk, not per-response: if no bytes for N seconds we abort fast. Same return shape
    as the non-streaming version: (parsed_json, request_payload, response_metadata)."""
    if not ANTHROPIC_API_KEY:
        raise RuntimeError('missing_anthropic_api_key')
    payload = {
        'model': model or ANTHROPIC_MODEL,
        'max_tokens': ANTHROPIC_MAX_TOKENS,
        'temperature': 0,
        'system': system_prompt,
        'messages': [
            {'role': 'user', 'content': [{'type': 'text', 'text': user_prompt}]}
        ],
        'stream': True,
    }

    # Retry the connect/initial-response phase only — once the stream is flowing, a tight
    # per-chunk timeout already protects us. KZ→us-east-1 connect handshake is what most
    # commonly drops; 3 attempts with jitter cover ~30s of network flap.
    import random as _rnd
    body_bytes = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    last_exc: Exception | None = None
    resp = None
    for attempt in range(3):
        try:
            resp = HTTP_SESSION.post(
                ANTHROPIC_ENDPOINT,
                headers={
                    'x-api-key': ANTHROPIC_API_KEY,
                    'anthropic-version': '2023-06-01',
                    'content-type': 'application/json',
                    'accept': 'text/event-stream',
                },
                data=body_bytes,
                timeout=(ANTHROPIC_CONNECT_TIMEOUT_SEC, 30),  # (connect, read-per-chunk)
                stream=True,
            )
            break
        except (requests.exceptions.ConnectTimeout,
                requests.exceptions.ConnectionError) as exc:
            last_exc = exc
            if attempt >= 2:
                raise
            time.sleep((1.5 ** attempt) + _rnd.uniform(0, 0.7))
    if resp is None:
        raise RuntimeError(f'anthropic_connect_failed: {last_exc}')
    if resp.status_code >= 400:
        body = ''
        try:
            body = resp.text[:1000]
        except Exception:
            pass
        raise RuntimeError(f'anthropic_http_{resp.status_code}: {body}')

    text_parts: list[str] = []
    usage: dict = {}
    stop_reason: str | None = None
    message_id: str | None = None
    model_used: str | None = None

    try:
        for raw_line in resp.iter_lines(decode_unicode=True, chunk_size=1024):
            if not raw_line:
                continue
            if not raw_line.startswith('data:'):
                continue
            data_str = raw_line[5:].lstrip()
            if not data_str or data_str == '[DONE]':
                continue
            try:
                event = json.loads(data_str)
            except Exception:
                continue
            etype = event.get('type')
            if etype == 'message_start':
                msg = event.get('message') or {}
                message_id = msg.get('id') or message_id
                model_used = msg.get('model') or model_used
                usage.update(msg.get('usage') or {})
            elif etype == 'content_block_delta':
                delta = event.get('delta') or {}
                if delta.get('type') == 'text_delta':
                    text_parts.append(delta.get('text') or '')
            elif etype == 'message_delta':
                d = event.get('delta') or {}
                if d.get('stop_reason'):
                    stop_reason = d['stop_reason']
                if event.get('usage'):
                    usage.update(event['usage'])
            elif etype == 'error':
                err = event.get('error') or {}
                raise RuntimeError(f"anthropic_stream_error: {err.get('type')}: {err.get('message')}")
            elif etype == 'message_stop':
                break
    finally:
        try:
            resp.close()
        except Exception:
            pass

    text = ''.join(text_parts).strip()
    parsed = extract_json_object(text)
    if not parsed:
        snippet = text[:1200] if text else ''
        raise RuntimeError(f'anthropic_invalid_json_response: {snippet}')
    response_meta = {
        'id': message_id,
        'model': model_used,
        'stop_reason': stop_reason,
        'usage': usage,
        'text': text,
        'streamed': True,
    }
    return parsed, payload, response_meta
