# Bitrix -> ElevenLabs Transcription API

> **Внимание: документ устарел.** Описывает архитектуру времён ElevenLabs (до 2026-05-04).
> Текущий STT-провайдер — **Soniox** (`api.soniox.com`, модель `stt-async-v4`),
> работает по схеме async submit + poll, без webhook'а. Эндпоинт `/elevenlabs/webhook`
> и переменные окружения `ELEVENLABS_*` удалены из `app.py`. Таблицы и провайдеро-нейтральный
> слой чтений описаны в актуальной схеме `schema.sql` и в коде (`soniox_submit`,
> `_soniox_tokens_to_words`, `ACTIVE_TRANSCRIBE_PROVIDER`).
> Этот файл сохранён как исторический контекст и подлежит переписыванию отдельной задачей.

## Database schema
- File: `/root/okosystems/schema.sql`
- Tables:
  - `calls`
  - `transcriptions`
  - `sync_log`

## Auth
- Internal endpoints are protected with `admin_token`.
- `admin_token` file: `/root/okosystems/admin_token.txt`

## Endpoints

### 1) Submit transcription job
`POST /transcriptions/submit`

Body (JSON):
```json
{
  "admin_token": "...",
  "bitrix_activity_id": 584043,
  "bitrix_file_id": 13423,
  "owner_type_id": 6,
  "owner_id": 584043,
  "deal_id": 103079,
  "contact_id": 132025,
  "phone": "+77474668793",
  "direction": "2",
  "started_at": "2026-01-17T14:16:53+03:00",
  "ended_at": "2026-01-17T14:21:16+03:00",
  "duration_seconds": 263
}
```

Alternative:
- You can pass `audio_url` directly instead of `bitrix_file_id/owner_*`.

Response (success):
```json
{
  "ok": true,
  "call_id": 1,
  "bitrix_activity_id": 584043,
  "audio_url": "https://...",
  "provider": "elevenlabs",
  "provider_job_id": "...",
  "status": "submitted"
}
```

### 2) Receive ElevenLabs webhook
`POST /elevenlabs/webhook`

- Accepts raw JSON from ElevenLabs.
- If `ELEVENLABS_WEBHOOK_TOKEN` is set, request must include header:
  - `X-Webhook-Token: <same token>`

Response:
- `200` when transcription row updated
- `202` when payload saved to log but matching job not found

### 3) Get transcription status
`GET /transcriptions/status?admin_token=...&bitrix_activity_id=584043`

Response:
```json
{
  "ok": true,
  "result": {
    "bitrix_activity_id": 584043,
    "audio_url": "https://...",
    "provider_job_id": "...",
    "status": "completed",
    "transcript_text": "...",
    "error_text": null,
    "updated_at": "..."
  }
}
```

## Required environment variables
In `/root/okosystems/.env`:
- `DATABASE_URL`
- `ELEVENLABS_API_KEY`
- `ELEVENLABS_STT_ENDPOINT` (default: `https://api.elevenlabs.io/v1/speech-to-text`)
- `ELEVENLABS_MODEL_ID` (default: `scribe_v1`)
- `APP_BASE_URL` (used to form webhook URL)
- `ELEVENLABS_WEBHOOK_TOKEN` (optional)

## Service management
- Restart app: `systemctl restart okosystems`
- Logs: `journalctl -u okosystems -f`
- Caddy config: `/etc/caddy/Caddyfile`
