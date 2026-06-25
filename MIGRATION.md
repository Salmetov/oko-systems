# OKO Systems — Migration Runbook

Миграция сервера `ai.salmetov.fun` со старого хоста (Нью-Джерси) на новый (Алматы) **без снимка диска**, через rsync + pg_dump по SSH.

**Контекст:** проект в стадии MVP, пользуются только основатель и партнёр. Окно простоя не критично. Главное — чтобы после миграции всё работало.

**Кто исполнитель:** Claude Code, запущенный пользователем на **новом** сервере. Все команды ниже по умолчанию выполняются именно там, со SSH-доступом к старому. Если ты — Claude и читаешь этот файл, веди пользователя пошагово, не делай деструктивного без подтверждения.

---

## Раскладка

- **OLD = старый сервер** (Нью-Джерси): IP `78.111.88.140`, всё работает прямо сейчас
- **NEW = новый сервер** (Алматы): чистая Ubuntu 24.04, IP — узнать у пользователя в начале миграции

Все `OLD_IP` ниже — это `78.111.88.140`. Все команды выполняются на NEW, если не сказано иное.

## Что переносим / не переносим

**Переносим:**
- `/root/okosystems/` — код приложения, `.env`, `prompts/`, `schema.sql`, `tokens.json`, `admin_token.txt`
- `/etc/caddy/Caddyfile` — конфиг reverse-proxy (с правкой `bind`)
- `/etc/systemd/system/okosystems.service` — systemd-юнит
- `bitrix_ai` — БД PostgreSQL через `pg_dump`/`pg_restore`
- `/root/.claude/projects/-root/memory/` — память Claude (для контекста в будущих сессиях)

**Не переносим (соберём/настроим заново):**
- `/var/lib/caddy/` — старые сертификаты не подойдут (новый IP, Let's Encrypt выдаст свежий)
- `/root/.npm`, `/root/.cache` — кэши, ненужны
- `/root/.vscode-server`, `/root/.claude.json`, остальное `~/.claude/` — это твоя локальная сессия Claude/IDE; на новом сервере уже свежая
- `/root/okosystems/ui-dashboard/dist/` — пересоберём из исходников через `npm run build`
- `/root/okosystems/ui-dashboard/node_modules/` — поставим через `npm install`

---

## Шаг 1. Подготовить NEW: установить пакеты

```bash
apt update
apt install -y python3 python3-psycopg2 python3-requests \
                postgresql-16 \
                caddy \
                rsync \
                nodejs npm \
                curl
```

**Caddy** — официальный репозиторий: если в Ubuntu 24.04 нет свежего пакета, добавить репозиторий https://caddyserver.com/docs/install#debian-ubuntu-raspbian.

**Node.js** — для сборки фронта. Если в Ubuntu-репах слишком старая версия, поставить из NodeSource (нужна Node 20+, потому что Vite 7 требует).

Проверка:
```bash
python3 --version          # 3.10+
psql --version             # 16.x
caddy version              # 2.x
node --version             # 20+
```

## Шаг 2. Настроить SSH-доступ NEW → OLD

На NEW сгенерировать ключ и добавить публичную часть в `authorized_keys` на OLD:

```bash
ssh-keygen -t ed25519 -N "" -f /root/.ssh/migration_key
cat /root/.ssh/migration_key.pub
# скопировать вывод
```

На OLD (через старую SSH-сессию пользователя):

```bash
echo "<публичный ключ из вывода выше>" >> /root/.ssh/authorized_keys
```

Проверка с NEW:

```bash
ssh -i /root/.ssh/migration_key root@78.111.88.140 "hostname && whoami"
```

Должно вернуть имя старого сервера и `root`. Дальше для удобства добавь в `~/.ssh/config` на NEW:

```bash
cat >> /root/.ssh/config <<'EOF'
Host old
    HostName 78.111.88.140
    User root
    IdentityFile /root/.ssh/migration_key
EOF
chmod 600 /root/.ssh/config
ssh old "echo OK"
```

## Шаг 3. Перенести код приложения

```bash
rsync -av --progress \
  --exclude='ui-dashboard/node_modules' \
  --exclude='ui-dashboard/dist' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  old:/root/okosystems/ /root/okosystems/
```

Проверка:
```bash
ls -la /root/okosystems/
cat /root/okosystems/.env | head -5      # должны быть переменные
chmod 600 /root/okosystems/.env          # права на секреты
```

## Шаг 4. Перенести конфиги системы

### 4.1. Caddy

```bash
ssh old cat /etc/caddy/Caddyfile > /etc/caddy/Caddyfile
# на старом уже была убрана строка bind, но если вдруг вернулась — снести:
sed -i '/^    bind 78\.111\.88\.140$/d' /etc/caddy/Caddyfile
caddy validate --config /etc/caddy/Caddyfile
```

### 4.2. systemd-юнит okosystems

```bash
ssh old cat /etc/systemd/system/okosystems.service > /etc/systemd/system/okosystems.service
systemctl daemon-reload
```

## Шаг 5. Перенести БД

### 5.1. Создать роль и БД на NEW

```bash
sudo -u postgres psql <<'EOF'
CREATE ROLE bitrix_app WITH LOGIN;
CREATE DATABASE bitrix_ai OWNER bitrix_app;
EOF
```

(Пароль не нужен — приложение ходит через unix-сокет с peer/scram-аутентификацией. Если в `.env` `DATABASE_URL` указывает на пользователя/пароль — задать `ALTER ROLE bitrix_app WITH PASSWORD '...';` соответствующий значению из `.env`.)

### 5.2. Перелить дамп через SSH-пайп

```bash
ssh old "sudo -u postgres pg_dump -Fc bitrix_ai" \
  | sudo -u postgres pg_restore -d bitrix_ai --no-owner --role=bitrix_app
```

(`--no-owner --role=bitrix_app` — на случай, если на NEW нет точно тех же ролей, что и на OLD.)

Проверка:
```bash
sudo -u postgres psql -d bitrix_ai -c "\dt"
sudo -u postgres psql -d bitrix_ai -c "SELECT count(*) FROM users;"
```

## Шаг 6. Перенести память Claude (для непрерывности контекста)

```bash
mkdir -p /root/.claude/projects/-root/memory
rsync -av old:/root/.claude/projects/-root/memory/ \
            /root/.claude/projects/-root/memory/
ls /root/.claude/projects/-root/memory/
```

Должны появиться `MEMORY.md`, `project_okosystems.md`, `migration_runbook.md` и др. После этого Claude в новых сессиях на NEW будет автоматически подгружать этот контекст.

## Шаг 7. Собрать фронт

```bash
cd /root/okosystems/ui-dashboard
npm install
npm run build
ls dist/index.html      # должен существовать
```

## Шаг 8. Остановить OLD, запустить NEW, локальная проверка

### 8.1. Остановить приложение на OLD

```bash
ssh old "systemctl stop okosystems"
```

(Caddy на OLD можно не трогать — он перестанет получать трафик, как только переключим DNS.)

### 8.2. Запустить на NEW

```bash
systemctl enable --now okosystems
systemctl reload caddy
systemctl status okosystems caddy postgresql@16-main --no-pager
ss -tulnp | grep -E ':(80|443|18080|5432)'
```

### 8.3. Проверка приложения локально (без DNS)

```bash
curl -H "Host: ai.salmetov.fun" http://127.0.0.1/health
```

Должен вернуть 200. Если нет — смотреть `journalctl -u okosystems -n 100 --no-pager`.

## Шаг 9. Переключить DNS

В панели регистратора `salmetov.fun`:
- A-запись `ai` → IP нового сервера в Алматы

Проверка пропагации:
```bash
dig +short ai.salmetov.fun
```

Должен вернуть новый IP (1–10 минут).

## Шаг 10. Дождаться TLS-сертификата

Caddy сам запросит сертификат у Let's Encrypt после того, как DNS укажет на NEW и Let's Encrypt сможет достучаться по `:80`:

```bash
journalctl -u caddy -f | grep -iE "certificate|obtained"
```

Ждать `certificate obtained successfully`. Обычно — пара минут.

Финальная проверка:
```bash
curl -I https://ai.salmetov.fun/
```

В браузере: `https://ai.salmetov.fun/dash`, залогиниться.

## Шаг 11. Smoke-test интеграций

Все внешние интеграции работают через домен — должны работать сразу. Просто проверить:

- **Bitrix24:** действие, требующее OAuth-refresh, → `journalctl -u okosystems -f | grep -i bitrix`
- **ElevenLabs:** запустить тестовую транскрипцию, проверить, что webhook прилетает обратно
- **Telegram bot:** `curl https://api.telegram.org/bot<TOKEN>/getWebhookInfo` (взять токен из `.env`) — URL должен указывать на домен
- **Anthropic, Mailtrap:** только исходящий трафик — проверяется через UI (запустить анализ, отправить тестовое письмо)

## Шаг 12. Удалить OLD

- В панели хостера в Нью-Джерси удалить старую VM
- На NEW: убрать ключ миграции, если больше не нужен:
  ```bash
  rm -f /root/.ssh/migration_key /root/.ssh/migration_key.pub
  # и убрать секцию `Host old` из /root/.ssh/config
  ```
- Обновить этот runbook: новый IP, можно зафиксировать дату миграции

---

## Если что-то пошло не так

- **rsync падает по разрешениям** — на старом сервере `chmod 600 /root/.ssh/authorized_keys`, проверить SELinux/AppArmor (обычно неактуально для Ubuntu)
- **`pg_restore` ругается на роль** — `CREATE ROLE <missing_role>;` на NEW и повторить с `--no-owner`
- **Caddy падает** — проверить, что `bind 78.111.88.140` точно убран; смотреть `journalctl -u caddy -n 50`
- **Сертификат не выдаётся** — DNS ещё не пропагировал, или фаервол хостера блокирует `:80`. Проверить `curl http://ai.salmetov.fun/.well-known/acme-challenge/test` снаружи, должен попадать на NEW
- **Совсем плохо** — OLD ещё жив (Шаг 12 не делал) → откатить DNS на OLD_IP, разбираться без давления

---

## Чек-лист

- [ ] **Шаг 1.** Установить пакеты на NEW
- [ ] **Шаг 2.** SSH-доступ NEW → OLD, алиас `ssh old`
- [ ] **Шаг 3.** rsync кода `/root/okosystems/`
- [ ] **Шаг 4.** Скопировать Caddyfile и systemd-юнит
- [ ] **Шаг 5.** Создать БД `bitrix_ai`, перелить дамп через SSH-пайп
- [ ] **Шаг 6.** Перенести `/root/.claude/projects/-root/memory/`
- [ ] **Шаг 7.** `npm install && npm run build` в `ui-dashboard/`
- [ ] **Шаг 8.** Остановить OLD, запустить NEW, `curl -H "Host: ..." http://127.0.0.1/health` → 200
- [ ] **Шаг 9.** Переключить A-запись DNS
- [ ] **Шаг 10.** Дождаться TLS, открыть `/dash` в браузере
- [ ] **Шаг 11.** Smoke-test: Bitrix, ElevenLabs, Telegram
- [ ] **Шаг 12.** Удалить OLD, почистить ключи на NEW
