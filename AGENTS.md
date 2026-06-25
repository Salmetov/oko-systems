# Oko Systems

## Product Model

Сервис строится как `user-oriented` продукт для РОПа.

- основной пользователь: руководитель отдела продаж
- основная ценность: быстрый доступ к кабинету и анализу качества звонков
- основной источник данных: Bitrix24
- базовая модель доступа: `user -> user_bitrix_connections -> analysis`

## Runtime Shape

Текущий backend собран вокруг одного Python runtime в `app.py`.

- серверный HTML по-прежнему рендерится прямо из `app.py`
- публичные marketing/legal страницы лежат в отдельных статических файлах в корне проекта:
  `landing.html`, `app-page.html`, `request-demo.html`, `legal-license.html`, `legal-privacy.html`
- отдельный frontend на React/Vite существует в `ui-dashboard/`
- runtime раздаёт уже собранный `/dash` из `ui-dashboard/dist`, а не `src`

Если меняется поведение `/dash`, нужно думать в терминах `build output + serving`, а не только серверного Python-кода.

## Current Auth

Auth в системе — только по паролю.

- `/login` поддерживает один сценарий: вход по паролю
- вкладка "Код на почту" удалена из UI; `auth_email_codes` и `/verify-code` остались в backend, но entry point из login-страницы убран
- `/register` создаёт аккаунт с паролем
- `/forgot-password` и `/reset-password` — рабочие public routes для восстановления пароля
- `password_reset_tokens` и `password_hash` — активный контур, не трогать

Если идёт рефакторинг auth, целевой вектор — упрощение первого входа через пароль, не возвращать email-code tab без явной необходимости.

## Bitrix Flow

Bitrix24 остаётся главным входом интеграции.

- `POST /connect/bitrix` принимает install event / данные подключения от Bitrix24
- `GET /connect/bitrix` обслуживает user-facing flow подключения
- `bitrix_install_events` используются для незавершённой установки и последующего завершения после auth
- `bitrix_connect_tokens` используются для явного подключения портала уже авторизованным пользователем
- embedded flow внутри Bitrix должен оставаться коротким и вести к привязке портала без лишних промежуточных экранов

Новый код не должен возвращать multi-tenant мышление в Bitrix flow.

## Route Families

Важнее мыслить не по одиночным URL, а по семействам маршрутов.

Public auth and onboarding:
- `/login`
- `/register`
- `/verify-code`
- `/forgot-password`
- `/reset-password`
- `/connect/bitrix`
- `/connect/bitrix/<token>`

Public marketing and static pages:
- `/` -> `landing.html` для неавторизованных
- `/app`
- `/request-demo`
- `/legal/license`
- `/legal/privacy`

Public report/read-only routes:
- `/r/<public_id>`
- `/r/<public_id>/txt`
- `/id/<public_id>`
- `/id/<public_id>/timeline`
- `/operator/<id>`
- `/operator/<id>/report/<public_id>`
- `/operator/<id>/report/<public_id>/timeline`
- `/api/report/<public_id>`
- `/api/chronology/<public_id>`
- `/api/operator/<id>`

Authenticated app routes (API и действия):
- `/api/analysis/submit`
- `/api/analysis/batch/<id>`
- `/api/analysis/batch/<id>/delete`
- `/api/analysis/export/<id>/operator`
- `/api/operator/<id>/plan`
- `/api/operator/<id>/plan/generate`
- `/api/operator/<id>/plan/<plan_id>/send-bitrix`
- `/api/operator/<id>/cycles`
- `/api/notifications` (GET)
- `/api/notifications/<id>/read` (POST)
- `/api/notifications/read-all` (POST)
- `/bitrix/switch/<id>`
- `/bitrix/disconnect`
- `/logout` (GET и POST)

Authenticated UI routes (все редиректят на `/dash`):
- `/` -> redirect `/dash` для авторизованных
- `/analyses` -> redirect `/dash`
- старые серверные dashboard-страницы -> redirect `/dash`

React SPA (основной authenticated UI):
- `/dash` и все под-роуты (роутинг внутри SPA)
- `/dash/assets/*` — статика билда
- собирается из `ui-dashboard/src`, раздаётся из `ui-dashboard/dist`
- после изменений в React всегда нужен `npm run build` перед деплоем

Если меняются маршруты, сначала проверять фактический `do_GET` / `do_POST` в `app.py`, а не полагаться на исторические URL из старых обсуждений.

## Data Model Boundaries

Ключевые таблицы, которые отражают текущую архитектуру:

- `users`
- `sessions`
- `auth_email_codes`
- `password_reset_tokens`
- `user_bitrix_connections`
- `bitrix_connect_tokens`
- `bitrix_install_events`
- `analysis_exports`
- `analysis_batches`
- `qa_analysis_*`
- `qa_report_links`
- `qa_call_texts`
- `deal_events`
- `event_media`
- `media_transcriptions`
- `operator_development_plans`
- `operator_plan_cycles`
- `user_notifications`

Для анализа звонков привязка должна идти через `user_id` и `bitrix_connection_id`, а не через возвращение tenant-layer.

## Integration Rules

- все обращения к Bitrix должны идти через user-scoped context helpers, прежде всего `get_user_bitrix_context(...)`
- токены Bitrix хранятся в `user_bitrix_connections`
- один пользователь уже может иметь несколько Bitrix connections; текущий UX просто выбирает один `primary`
- вход через сайт и через Bitrix24 app должен приводить к одному и тому же user profile
- публичные report-ссылки и operator/report views нельзя случайно завязать на обязательную UI-сессию

## Contact Flows

Сейчас в системе есть несколько разных внешних contact-entry сценариев.

- `POST /api/demo-request` -> demo lead в Telegram
- `POST /api/support-request` -> support/contact lead в Telegram
- `POST /app/contact` -> contact flow marketplace-страницы через email

Если меняется contact UX, важно не смешивать marketing/demo/support сценарии с auth и Bitrix onboarding.

## Operator Plan Cycles (автоматический цикл развития)

Система автоматически запускает цикл развития оператора после накопления 5 завершённых анализов.

Триггер **счётный, не временной**: ориентируется на количество завершённых runs, а не на день недели.

Реальный продуктовый кейс — недельный цикл на одного сотрудника:
- понедельник: РОП анализирует 5 звонков → система генерирует план → задачи в Bitrix24
- пятница: РОП анализирует ещё 5 звонков → система генерирует отчёт сравнения «до/после»

То есть полный цикл «план → задачи → замер прогресса» укладывается в **одну рабочую неделю**. Если клиент загружает звонки в другом ритме, цикл просто подстраивается естественным образом — счётный триггер в коде ничего не привязывает к дням недели.

Дедлайны задач плана (`deadline_days`, дефолт 7) совпадают с длиной цикла — задача в понедельник со сроком неделя замеряется к следующему понедельнику, а промежуточный замер в пятницу даёт ранний сигнал о прогрессе.

### Жизненный цикл `operator_plan_cycles.status`:

```
plan_generating  →  plan_ready  →  monitoring  →  report_generating  →  report_ready
                                                        (5 новых звонков)
```

- `plan_generating` — создан цикл, фоновый поток генерирует план через Claude
- `plan_ready` — план готов, уведомление отправлено, задачи можно отправить в Bitrix24
- `monitoring` — план отправлен / ждём накопления ещё 5 звонков
- `report_generating` — накопилось 5 новых звонков, генерируется отчёт сравнения
- `report_ready` — отчёт готов, уведомление отправлено

### Точка входа триггера:

`_trigger_operator_cycle(run_id, export)` вызывается в конце `process_qa_run` после строки `db_log('qa', 'analysis_run_completed', ...)`.
Запускает `check_operator_plan_trigger` в отдельном daemon-потоке.

### Ключевые функции:

- `check_operator_plan_trigger(run_id, operator_id, user_id)` — логика проверки, нужно ли стартовать цикл
- `_generate_plan_for_cycle(cycle_id, operator_id, user_id)` — фоновый поток: план + уведомление + email
- `_generate_report_for_cycle(cycle_id, operator_id, user_id)` — фоновый поток: сравнение до/после + уведомление + email
- `generate_operator_plan(..., run_ids=None)` — принимает опциональный список run_ids для фиксации конкретных звонков цикла

### Email:

Уведомления отправляются через Mailtrap (`send_mailtrap_email`).
Категории: `plan-ready`, `report-ready`.

### Notifications:

`user_notifications` хранит все уведомления пользователя.
В React UI — колокольчик в top bar, polling раз в 30 секунд.
Клик по уведомлению навигирует на страницу оператора и помечает как прочитанное.

## Cleanup Direction

Если меняется архитектура, держим курс на упрощение:

- не возвращать tenant runtime как основную модель
- не возвращать Telegram-specific auth/onboarding как продуктовую ось
- не плодить новые intermediate screens в Bitrix embedded flow
- новые приватные сценарии добавлять в user-oriented маршруты, а не в `/t/...`
- при расхождении между legacy runtime и целевым продуктовым направлением выбирать упрощение и user-oriented flow, но сначала проверять, не используется ли legacy в production
