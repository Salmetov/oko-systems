# DESIGN_SYSTEM.md — Oko Systems UI v2

Этот документ — источник правды для всего визуального языка продукта.
Перед добавлением любого нового экрана или блока — прочитай его целиком.
Если UI-решение меняет систему — обнови этот документ в том же цикле работ.

---

## 1. Общая концепция

Продукт состоит из двух визуальных зон с разными задачами:

**Публичная зона** (лендинг, логин, legal): продаёт идею, создаёт доверие.
Тёмная, плотная, кинетическая. Задача — конвертировать.

**Кабинет** (дашборд, отчёты, аналитика): инструмент для работы с данными.
Светлая, чистая, минималистичная. Задача — читаться быстро и без шума.

Общее между зонами: шрифт Manrope, акцентный синий #5B6AF9, Manrope — единственный шрифт во всём продукте.

---

## 2. Цветовая система

### Публичная зона (лендинг, логин)
```
--bg-hero:       #08080E        /* фон страниц, почти чёрный */
--bg-section:    #0E0E18        /* чуть светлее для чередующихся секций */
--bg-card:       #FFFFFF        /* белая карточка поверх тёмного фона */
--accent:        #5B6AF9        /* основной синий, кнопки, акценты */
--accent-hover:  #7B87FF        /* hover-состояние синего */
--text-white:    #FFFFFF
--text-muted:    rgba(255,255,255,0.55)
--text-faint:    rgba(255,255,255,0.28)
--border-dark:   rgba(255,255,255,0.08)
--border-dark-hover: rgba(255,255,255,0.18)
--glow:          radial-gradient(ellipse, rgba(91,106,249,.22) 0%, transparent 70%)
```

### Кабинет (дашборд, отчёты)
```
--bg:            #F3F4F8        /* страница */
--surface:       #FFFFFF        /* панели, карточки */
--surface-muted: #F9FAFB        /* приглушённый фон внутри панелей */
--border:        #E5E7EB
--border-strong: #D1D5DB
--ink:           #0C0C14        /* основной текст */
--ink-soft:      #6B7280        /* вторичный текст */
--ink-faint:     #9CA3AF        /* подписи, eyebrow */
--accent:        #5B6AF9
--accent-soft:   #EEF0FE        /* фон под синий тег/badge */
```

### Семантические цвета (одинаковы в обеих зонах)
```
--good:          #2f8a57    good-soft: #edf8f1
--warn:          #9b6a19    warn-soft: #fff7ea
--bad:           #b3473f    bad-soft:  #fff1ef
```

### Сайдбар кабинета (всегда тёмный)
```
background:      #0C0C14
border-right:    1px solid rgba(255,255,255,0.07)
active link bg:  #5B6AF9
hover link bg:   rgba(255,255,255,0.07)
text:            rgba(255,255,255,0.55)
text active:     #FFFFFF
```

---

## 3. Типографика

Единственный шрифт: **Manrope** (Google Fonts, weights 400–900).
Подключать через:
```html
<link href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
```

### Публичная зона
| Элемент | Размер | Weight | Доп. |
|---|---|---|---|
| eyebrow | 11px | 800 | uppercase, letter-spacing: 0.12em, color: #5B6AF9 |
| h1 hero | clamp(42px, 6vw, 72px) | 900 | letter-spacing: -0.04em, line-height: 1.02 |
| h2 section | clamp(28px, 4vw, 42px) | 900 | letter-spacing: -0.03em |
| card title | 18–22px | 800 | letter-spacing: -0.02em |
| body | 15–16px | 500 | line-height: 1.6 |
| secondary | 13–14px | 500 | color: rgba(255,255,255,0.55) |
| button | 14–15px | 800 | |

### Кабинет
| Элемент | Размер | Weight | Доп. |
|---|---|---|---|
| eyebrow | 11–12px | 800–900 | uppercase, letter-spacing: 0.12em, color: var(--ink-faint) |
| page-title | clamp(22px, 3vw, 28px) | 900 | letter-spacing: -0.03em |
| panel-title | 20–24px | 800 | letter-spacing: -0.02em |
| body | 14–15px | 500 | line-height: 1.55 |
| table cell | 14px | 500 | |
| secondary | 12–13px | 500–600 | color: var(--ink-soft) |
| KPI value | clamp(34px, 3vw, 40px) | 900 | letter-spacing: -0.05em, line-height: 0.95 |
| label/eyebrow | 11–12px | 800 | uppercase |

---

## 4. Лендинг — структура и паттерны

### Общий layout
- Тёмный фон `#08080E`, фиксированный nav сверху.
- Секции чередуются: `#08080E` → `#0E0E18` → `#08080E`.
- Максимальная ширина контента: `1200px`, `margin: 0 auto`, `padding: 0 24px`.

### Nav
```
height: 60px
background: rgba(8,8,14,0.9) + backdrop-filter: blur(12px)
border-bottom: 1px solid rgba(255,255,255,0.08)
logo: белый текст + синяя квадратная плашка с буквой «О» (28×28px, radius 6-7px, bg #5B6AF9)
кнопка CTA справа: синяя, radius 12px, height 40px
на mobile: скрывать второстепенные ссылки, оставлять логотип + главную CTA
```

### Hero-секция
```
padding: 120px 0 100px
центрированная вёрстка
eyebrow сверху
h1 огромный, две строки, с переносом
subtitle 18–20px, max-width ~600px, цвет rgba(255,255,255,0.6)
две кнопки: primary (синяя) + secondary (прозрачная с белой рамкой)
анимированный демо-блок ниже кнопок — живой пример работы продукта
```

### Trust bar / логотипы клиентов
```
padding: 20px 0
border-top + border-bottom: 1px solid rgba(255,255,255,0.08)
текст: rgba(255,255,255,0.3), uppercase, letter-spacing
логотипы: rgba(255,255,255,0.25), grayscale
```

### Карточки фич/преимуществ
```
background: rgba(255,255,255,0.04)
border: 1px solid rgba(255,255,255,0.08)
border-radius: 20px
padding: 28–32px
иконка/эмодзи в цветной плашке 44×44px, radius 12px
hover: border-color: rgba(255,255,255,0.16), translateY(-3px)
```

### Кнопки (публичная зона)
```
primary:
  background: #5B6AF9, color: #fff, border: none
  height: 48–52px, padding: 0 24px, border-radius: 14px
  font-weight: 800, font-size: 15px
  hover: background #7B87FF, translateY(-1px)

secondary (outline):
  background: transparent
  border: 1px solid rgba(255,255,255,0.18)
  color: rgba(255,255,255,0.75)
  hover: border-color rgba(255,255,255,0.4), color #fff

ghost (nav):
  height: 30–36px, padding: 0 14px, border-radius: 8–10px
  border: 1px solid rgba(255,255,255,0.12)
  color: rgba(255,255,255,0.55)
  hover: background rgba(255,255,255,0.08), color #fff
```

### Анимации (лендинг)
```
IntersectionObserver: элементы появляются fadeInUp при входе в viewport
  opacity: 0 → 1, translateY(24px) → 0
  duration: 0.6s, ease: cubic-bezier(0.2, 0.7, 0.2, 1)
  stagger между элементами: 80–100ms через CSS --delay

счётчики: анимировать цифры при первом появлении (requestAnimationFrame)
marquee: бесконечная горизонтальная прокрутка через CSS animation
```

### Footer (лендинг)
```
background: #08080E
border-top: 1px solid rgba(255,255,255,0.08)
две колонки: лого+копирайт слева, ссылки справа
текст: rgba(255,255,255,0.25–0.35)
```

---

## 5. Логин / Auth-страницы

```
background: #08080E + radial-gradient glow (#5B6AF9, opacity ~0.22) сверху по центру
fixed topbar: лого слева, кнопки языка справа
контент: вертикально центрирован, белая карточка max-width 400px
```

### Auth-карточка
```
background: #fff
border-radius: 24px
padding: 36px
box-shadow: 0 0 0 1px rgba(91,106,249,.15), 0 24px 64px rgba(0,0,0,.45)
анимация появления: cardIn (opacity 0→1, translateY 16px→0, 0.5s ease)
```

### Форма внутри карточки
```
eyebrow: синий, uppercase, 11px
h1: 26px, font-weight 900, color #0C0C14
tabs: серый фон #F3F4F6, активный таб белый с тенью
input: height 46px, border-radius 11px, border 1.5px #E5E7EB
  focus: border-color #5B6AF9, box-shadow 0 0 0 3px rgba(91,106,249,.1)
submit: width 100%, height 48px, background #5B6AF9, border-radius 12px, font-weight 800
error: background #FEF2F2, border #FECACA, color #DC2626
```

---

## 6. Кабинет — layout и сайдбар

### Общий layout
```
display: flex, min-height: 100vh
sidebar фиксирован слева, content-wrap занимает остаток
content-inner padding: 28px 28px 48px
```

### Сайдбар
```
width: 248px
background: #0C0C14
border-right: 1px solid rgba(255,255,255,0.07)
position: sticky, top: 0, height: 100vh, overflow-y: auto
padding: 20px 16px 24px
display: flex, flex-direction: column

Лого-блок:
  синяя плашка 30×30px radius 8px с буквой «О» + название «Oko Systems»
  подзаголовок rgba(255,255,255,0.35)

Навигационные ссылки:
  height: 38px, padding: 0 10px, border-radius: 10px
  color: rgba(255,255,255,0.55)
  hover: background rgba(255,255,255,0.07), color rgba(255,255,255,0.85)
  active: background #5B6AF9, color #fff

Logout-кнопка:
  margin-top: auto (прижата к низу)
  border: 1px solid rgba(255,255,255,0.1)
  background: transparent
  hover: background rgba(255,255,255,0.08)

На мобайле (< 1040px): sidebar скрыт
```

### Панели кабинета
```
background: #FFFFFF
border: 1px solid #E5E7EB
border-radius: 16–18px
box-shadow: 0 4px 16px rgba(12,12,20,.05)
padding: 18–20px
```

### Primary button (кабинет)
```
background: #5B6AF9
border-color: #5B6AF9
color: #fff
hover: background #7B87FF
height: 40px, padding: 0 16px, border-radius: 11px, font-weight: 700
```

---

## 7. Компоненты

### Badge / статус
```
display: inline-flex, height: 30px, padding: 0 10px, border-radius: 999px
border: 1px, font-size: 12px, font-weight: 800

good:  background #edf8f1, border #cde7d7, color #2f8a57
warn:  background #fff7ea, border #f1dfbb, color #9b6a19
bad:   background #fff1ef, border #f0d2ce, color #b3473f
```

### Eyebrow
```
font-size: 11px, font-weight: 800, letter-spacing: 0.12em, text-transform: uppercase
публичная зона: color #5B6AF9
кабинет: color var(--ink-faint) #9CA3AF
```

### Score-pill (оценки в таблицах)
```
min-width: 76px, height: 32px, border-radius: 999px, font-size: 12px, font-weight: 900
те же цвета good/warn/bad что у badge
```

### Action-карточки (home dashboard)
```
display: flex, gap: 14px, padding: 18px
background: #fff, border: 1px solid #E5E7EB, border-radius: 16px
icon-плашка: 38×38px, border-radius 10px
  blue:   background #EEF0FE, color #5B6AF9
  green:  background #ECFDF5, color #059669
  orange: background #FFF7ED, color #D97706
  purple: background #F5F3FF, color #7C3AED
title: 13px, font-weight 800, color #0C0C14
sub: 12px, color #6B7280
hover (если ссылка): translateY(-2px), shadow
```

### Modal
```
backdrop: rgba(20,25,34,.34) + backdrop-filter blur(10px)
карточка: white, border-radius 18px, padding 22px, max-width 460px
```

### Таблицы
```
border-collapse: separate
th: 12px, font-weight 800, uppercase, letter-spacing 0.10em, color var(--ink-faint)
    background rgba(249,250,251,.92)
td: 14px, color var(--ink-soft)
hover строки: background rgba(249,250,251,.82)
border-bottom: 1px solid #ebe6de
широкие таблицы: внутри .hscroll
```

---

## 8. Responsive

```
< 1040px: sidebar скрыт, двухколоночные грид → 1 колонка
< 860px:  action-cards → 1 колонка
< 720px:  content-inner padding → 16px, page-title уменьшается
< 480px:  auth-карточка padding → 28px 20px
```

Обязательно для каждого нового блока:
- `min-width: 0` на grid-items
- проверить overflow на 390px
- длинные казахские/русские слова должны переноситься

---

## 9. Анимации

```
Лендинг: IntersectionObserver fadeInUp, stagger через --delay, duration 0.6s
  @keyframes fadeInUp { from { opacity:0; transform:translateY(24px) } to { opacity:1; transform:none } }

Кабинет: pageReveal — то же самое, но без stagger
  animation-delay: calc(var(--reveal, 0) * 70ms)

Hover: translateY(-1px) до translateY(-3px) в зависимости от размера блока
Модальные окна: opacity 0→1, pointer-events none→auto

@media (prefers-reduced-motion: reduce): все анимации отключить
```

---

## 10. Правила написания кода

```
Все базовые токены — в render_dashboard_base_styles() в app.py.
Специфические стили страницы — передавать через extra_style= в render_page_frame().
Лендинг, логин, legal — standalone HTML-файлы (/root/okosystems/*.html).
Новые standalone-страницы должны копировать CSS-переменные из секции 2 этого документа.

CSS-классы:
  публичная зона: без prefix или .landing-* 
  кабинет-специфика: без prefix (исторически)
  логин: .a-* (изолированное пространство имён)

Не дублировать переменные — использовать var().
Не хардкодить цвета вне :root если они уже есть как переменные.
```

---

## 11. Запреты

- Не добавлять второй шрифт (только Manrope).
- Не использовать тёплые бежевые тона (#f6f4f0 и подобные) — это устаревшая палитра.
- Не делать светлый сайдбар в кабинете.
- Не делать primary-кнопки тёмно-серыми — только синий #5B6AF9.
- Не добавлять loop-анимации ради декора.
- Не дублировать один смысл в заголовке и chips одновременно.
- Не добавлять длинные абзацы внутри KPI-карточек.
- Не вжимать таблицы на мобайле до нечитаемости — использовать hscroll.
- Не упоминать публично: Soniox, Claude, Anthropic (внутренние технологии).

---

## 12. Source of truth в коде

| Что | Где |
|---|---|
| CSS-токены и базовые стили кабинета | `render_dashboard_base_styles()` в `app.py` |
| Shell/layout кабинета | `render_page_frame()`, `render_sidebar_html()` |
| Лендинг | `/root/okosystems/landing.html` |
| Логин | `render_login_page()` в `app.py` |
| Legal-страницы | `/root/okosystems/legal-*.html` |
| Роуты и серверная логика | `app.py`, класс `OkoHandler` |
| Telegram-уведомления | `DEMO_NOTIFY_CHAT_ID` в `.env` |
