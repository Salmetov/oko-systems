# OKO Systems

**An LLM-powered call-analysis platform that turns raw sales calls into measurable coaching.**

OKO connects to a company's [Bitrix24](https://www.bitrix24.com/) CRM, transcribes its sales calls, scores them against a quality rubric with an LLM, and — instead of stopping at a one-off score — drives a closed coaching loop: it generates a personalized development plan per sales rep, pushes the action items back into Bitrix24 as tasks, and then measures whether the next batch of calls actually improved.

> Built solo, end-to-end, as a production SaaS for B2B sales teams in the CIS market. It is currently open-sourced as an engineering case study (no longer in active commercial use).

---

## The idea

Most call-QA tools give you a score and a transcript. That's a report, not an outcome. OKO is built around the observation that the value isn't in *grading* a call — it's in **changing what the rep does next week**. So the core unit of the product is a coaching *cycle*, not a single analysis:

```
   Mon: analyze 5 calls ──► LLM QA scoring ──► development plan ──► tasks pushed to Bitrix24
                                                                          │
                                                                          ▼
   Fri: analyze 5 more calls ──► before/after comparison ──► did the rep improve? ──► notify manager
```

The trigger is **count-based, not time-based** (it fires on N completed analyses, default 5), so the loop adapts naturally to however fast a given team actually uploads calls — a one-week rhythm is just the typical case, not a hardcoded schedule.

## What it does

- **Call ingestion** from Bitrix24 deals (activities, attached media) with idempotent de-duplication.
- **Speech-to-text** via [Soniox](https://soniox.com/), behind a provider-agnostic transcription layer (the STT vendor can be swapped without losing historical data).
- **LLM QA analysis** against a configurable rubric of scored modules. The report deliberately surfaces **only the failing modules** as action cards and collapses everything that passed — the manager sees what to fix, not a wall of green.
- **Per-rep development plans** generated from the aggregate of recent calls, then pushed into Bitrix24 as concrete tasks (`tasks.task.add`).
- **Before/after measurement** — once a rep accumulates a fresh batch of calls, OKO compares module scores against the pre-plan baseline and reports the delta.
- **Manager notifications** — in-app bell + email (Mailtrap), so the loop closes without anyone babysitting a dashboard.
- **Lead capture** — marketing/demo/support flows route to Telegram and email.

## Architecture

```
                         ┌──────────────────────────────────────────┐
   Bitrix24 CRM ◄──OAuth──┤  Python backend (single stdlib HTTP svc) │
   (calls, tasks)         │                                          │
                          │   • server-rendered public/legal pages   │
   Soniox  ◄──STT────────►│   • REST API for the SPA                 │──► PostgreSQL (29 tables)
                          │   • Bitrix integration + token refresh   │
   Claude  ◄──LLM────────►│   • background workers (plan/report gen)  │
   (Haiku QA / Sonnet     │                                          │
    plans & reports)      └───────────────────┬──────────────────────┘
                                              │ serves built assets
   Mailtrap ◄──email                          ▼
   Telegram ◄──alerts             React + Vite SPA  (the /dash dashboard)
```

### Stack

| Layer | Choice | Notes |
|---|---|---|
| Backend | Python 3, **stdlib `http.server` only** | No web framework — deliberately dependency-light |
| LLM | Anthropic **Claude** | Haiku for high-volume QA scoring, Sonnet for plan/report generation |
| STT | **Soniox** | Behind a provider-agnostic read layer |
| DB | **PostgreSQL** | 29 tables; domain-level idempotency via unique keys |
| Frontend | **React 19 + Vite 7 + TypeScript** | SPA served from `ui-dashboard/dist` |
| Reverse proxy / TLS | Caddy | Automatic certs |
| CRM | **Bitrix24** | OAuth, both site flow and embedded-app (marketplace) flow |

## Engineering notes worth a look

A few decisions that reflect how this was built rather than just what it does:

- **Cost-aware model routing.** QA scoring (the highest-volume call) runs on the cheaper Claude Haiku; the lower-volume, higher-stakes plan/report generation runs on Sonnet. Per-call LLM *output* was cut by roughly 60% through iterative prompt redesign — dropping evidence/recommendation fields from per-call output and returning nothing for modules that pass. This optimization was evaluated **manually** against real calls, not via an automated A/B harness — it's an honest, hands-on tuning process, and the prompts live in [`prompts/`](prompts/).
- **Resilience against slow external services.** A custom `requests` adapter sets Linux `TCP_USER_TIMEOUT` so the kernel kills dead connections that keep-alive ACKs would otherwise hide; failed exports auto-retry with exponential backoff on billing/network/rate-limit errors.
- **Idempotency at the domain layer.** Unique constraints on Bitrix activity IDs, deal events, media, and transcription jobs mean a noisy CRM retry never produces a duplicate analysis.
- **Production-readiness, honestly scoped.** See [`PRODUCTION_ROADMAP.md`](PRODUCTION_ROADMAP.md) for the deliberate split: ship product features lean, but treat infra (backups, connection pooling, a durable job queue, graceful shutdown, per-tenant fairness) as production-grade from the start — with a clear-eyed list of what's done and what's deferred.

## Honest status & caveats

This is a real product built under real constraints by one person, not a reference architecture:

- The backend is a **single ~11k-line `app.py`**. It's cohesive and documented, but the obvious next refactor is modularization — and `PRODUCTION_ROADMAP.md` reflects that I know it.
- Background jobs run in in-process threads (fine at the target load of ~10 accounts × 10 analyses/day; a durable Postgres-backed queue is the planned upgrade).
- HTML for the public/legal pages is server-rendered straight from Python — pragmatic for an MVP, not how I'd start a greenfield project today.

## Repository layout

```
app.py                  backend: HTTP server, Bitrix/LLM/STT integration, rendering
schema.sql              PostgreSQL schema (29 tables)
prompts/                LLM prompts for QA analysis
templates/              PDF report template
ui-dashboard/           React + Vite SPA (the /dash app)
landing.html, ...       static marketing & legal pages
AGENTS.md               architecture & route-family reference
PRODUCTION_ROADMAP.md   production-readiness plan (done vs. deferred)
API_CONTRACT.md         (historical) transcription API contract
DESIGN_SYSTEM.md        UI design system
.env.example            required configuration
```

## Running it

```bash
cp .env.example .env        # fill in DB URL + API keys
psql "$DATABASE_URL" -f schema.sql
cd ui-dashboard && npm install && npm run build && cd ..
python3 app.py              # serves on $CALLBACK_HOST:$CALLBACK_PORT
```

Secrets are never committed — see [`.env.example`](.env.example) for the full list of required environment variables.

---

*OKO Systems — built by [@Salmetov](https://github.com/Salmetov).*
