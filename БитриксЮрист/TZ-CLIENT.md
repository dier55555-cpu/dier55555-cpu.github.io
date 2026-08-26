# ТЗ: БитриксЮрист — долгое подключение клиенту

Документ для передачи клиенту и для вашей внутренней настройки.  
Цель: ежедневная проверка дел по сайтам судов РФ и запись результата в сделки Битрикс24 **без** Нои/n8n и **без** пересечения с Анной / Нейроагентс.

**Статус проверки пилота (VPS `sudrf-parser`, 26.08.2026):**

| Компонент | Результат |
| --- | --- |
| `bitrix-delo` (:8081) | `active`, `/health` = ok |
| `bitrix-yurist.timer` | `active`, следующий запуск 06:00 МСК |
| `POST /court_lookup` | ok (районный + мировой) |
| `POST /delo` мировой | `found` (капча + `op=sf`) |
| `POST /delo` районный sudrf | `found` (сайт снова отдаёт поиск) |
| Запись в Битрикс | `DRY_RUN=0`, входящий вебхук настроен |

---

## 0. Что это за продукт (границы)

### Делает
1. Раз в сутки (по умолчанию 06:00 Europe/Moscow) читает сделки Битрикс24 с номером дела.
2. По региону/городу/району/названию суда находит официальный сайт в справочнике (~10k судов).
3. Запрашивает карточку дела на сайте суда (`sudrf.ru` / `msudrf.ru`).
4. Если статус изменился — обновляет UF-поля сделки и пишет комментарий в ленту:  
   **«Обновление дела произведено»** + дата/время МСК + краткий diff.

### Не делает
- Не чат-бот и не агент Нои.
- Не трогает Анну (`/opt/court-kb:8080`, n8n `court-agent-yurist`, её MCP/промпт/БЗ).
- Не шлёт WhatsApp/Telegram клиенту в MVP (только лента CRM). Мессенджер — отдельный этап.

### Изоляция аккаунтов (Анна / Нейроагентс / БитриксЮрист)

| Контур | Платформа | Ключи | Где живут |
| --- | --- | --- | --- |
| Анна | Ноя + VPS `:8080` | свои MCP/API Нои | не трогаем |
| Нейроагентс | отдельный аккаунт Нои | **свои** ключи MCP/API | отдельный кабинет Нои, отдельные секреты |
| БитриксЮрист | VPS + Битрикс REST | webhook Bitrix, `COURT_KB_API_KEY`, `TWOCAPTCHA_API_KEY`, прокси | только `.env` на VPS клиента |

**Правило:** один продукт = один набор секретов = один VPS-каталог / один Bitrix-портал.  
Нейроагентс подключаете в Cursor/Ное как **отдельный MCP-сервер/аккаунт** с другими ключами; в БитриксЮрист Ноя не входит.

---

## 1. Архитектура на стороне клиента

```
VPS клиента (RU IP, Ubuntu 22.04+)

  /opt/bitrix-delo       :127.0.0.1:8081
       ├── uvicorn api.delo_app
       ├── directory/courts-ru.json
       └── .env  (API_KEY, PROXY, TWOCAPTCHA)

  /opt/bitrix-yurist
       ├── bitrix.py
       ├── systemd timer 06:00 MSK
       └── .env  (BITRIX_WEBHOOK_URL, UF_*, COURT_KB_*)

  Битрикс24 облако клиента
       └── входящий вебхук (crm) + UF-поля сделок
```

Внешние сервисы (оплата отдельно):

1. **Битрикс24** — портал клиента.  
2. **VPS в РФ** — хостинг парсера.  
3. **RU-прокси** — обход WAF судов (обязательно, даже с RU VPS желательно иметь пул).  
4. **2captcha / rucaptcha** — капча мировых судей.  
5. **Google Sheets** (ваши таблицы судов) — источник справочника; на VPS кладётся JSON-снимок.

---

## 2. Ресурсы: где брать, где платить, какие тарифы

Цены — ориентиры на момент составления ТЗ; перед оплатой сверяйте сайт провайдера.

### 2.1. VPS (обязательно)

| Параметр | Рекомендация для продакшена |
| --- | --- |
| Где | SpaceWeb / Beget / Timeweb / Selectel — **дата-центр РФ** |
| ОС | Ubuntu 22.04 LTS |
| CPU | 2 vCPU |
| RAM | **от 2 ГБ** (1 ГБ на пилоте тесно: uvicorn + job) |
| Диск | от 20 ГБ NVMe |
| Сеть | белый IPv4, без зарубежного IP |
| Доступ | root SSH-ключ (не пароль в чатах) |

**Ориентир оплаты:** рабочий VPS 2 ГБ ≈ **700–1500 ₽/мес** (зависит от провайдера).  
Пилотный сейчас: ~1 ГБ RAM — для клиента поднимать конфиг.

**Что купить у хостера:** только VPS. Отдельный «хостинг сайта» не нужен: API слушает `127.0.0.1`, снаружи не публикуем.

### 2.2. Прокси РФ (обязательно для стабильности)

Суды режут «подозрительные» IP. Нужен пул **российских** HTTP(S)-прокси (sticky-порты).

| Параметр | Рекомендация |
| --- | --- |
| Тип | IPv4 RU, лучше **резидентские** или ISP; датацентровые — дешевле, чаще 503 |
| Где | Proxy.Market / аналоги с RU-гео |
| Формат в `.env` | `COURT_KB_PROXY=http://user:pass@host:port` + список портов `COURT_KB_PROXY_PORTS=10001,10002,...` |
| Объём | для 50–200 сделок/сутки трафика мало; старт **10 ГБ** пакета |

**Ориентир Proxy.Market (резидентские):** тест 100 МБ ~49 ₽; 10 ГБ ~245 ₽/ГБ → пакет ~2450 ₽; pay-as-you-go ~345 ₽/ГБ.  
Для долгой работы: пакет **10–50 ГБ**, автопополнение баланса, гео **Россия**.

### 2.3. 2captcha / RuCaptcha (обязательно для мировых)

| Параметр | Значение |
| --- | --- |
| Сайт | [rucaptcha.com](https://rucaptcha.com) или [2captcha.com](https://2captcha.com) |
| Что купить | баланс API, ключ `TWOCAPTCHA_API_KEY` |
| Тип капчи | обычная картинка (kcaptcha), не reCAPTCHA |
| Расход | ~1–3 решения на проверку мирового участка |

**Ориентир:** старт **$5–10** на баланс; при десятках мировых дел в день — мониторить баланс раз в неделю.  
Ключ класть **только** в `/opt/bitrix-delo/.env` (и при желании дублировать в bitrix-yurist, но использует delo).

### 2.4. Битрикс24 клиента

| Параметр | Рекомендация |
| --- | --- |
| Тариф | любой с CRM и REST (облако или коробка с входящими вебхуками) |
| Что создать | входящий вебхук пользователя с правом **CRM** |
| Воронка | отдельная категория сделок «Судебные дела» (или согласованная) |
| Стадии | список `STAGE_ID`, которые мониторим |

Оплата — на стороне клиента (его портал). Вам нужен только URL вебхука вида  
`https://PORTAL.bitrix24.ru/rest/USER_ID/CODE/`.

### 2.5. Справочник судов (ваши Sheets)

| Ресурс | URL |
| --- | --- |
| Суды РФ | https://docs.google.com/spreadsheets/d/19sxmrNDDHu0u-g4y3987g5hMMSdFh5VkKKmRRH-v2VU |
| Мировые | https://docs.google.com/spreadsheets/d/109ThgsNtz_pyaLu0RZonEqh0oN1ntS5OCbJAfH_M6HQ |

На VPS кладётся `courts-ru.json` (~10k записей). Пересборка:

```bash
cd /opt/bitrix-delo   # или из репо parser-src
python -m scraper.directory.from_sheets --download
# скопировать directory/courts-ru.json → /opt/bitrix-delo/directory/
systemctl restart bitrix-delo
```

Отдельная оплата не нужна (Google-аккаунт с доступом к таблицам).

### 2.6. Что НЕ покупать для БитриксЮрист

- Отдельный аккаунт Нои / n8n «под мониторинг».  
- Отдельный MCP для БитриксЮрист.  
- Публичный домен/SSL на API (слушаем localhost).  
- DaData (справочник уже из Sheets).

---

## 3. Пошаговый путь настройки (клиент, вдолгую)

### Шаг A. Подготовка у клиента (до доступа на сервер)

1. Согласовать воронку и стадии сделок.  
2. Создать UF-поля сделки (имена можно свои — прописать в `.env`):

| Назначение | Пример кода поля |
| --- | --- |
| Номер дела | `UF_CRM_CASE_NUMBER` |
| Название суда | `UF_CRM_COURT_NAME` |
| Регион | `UF_CRM_REGION` |
| Город | `UF_CRM_CITY` |
| Район | `UF_CRM_DISTRICT` |
| Сайт суда (заполняет job) | `UF_CRM_COURT_WEBSITE` |
| Slug (опционально) | `UF_CRM_COURT_SLUG` |
| Последний статус | `UF_CRM_LAST_STATUS` |
| Время проверки | `UF_CRM_LAST_CHECK_AT` |
| Hash снимка | `UF_CRM_SNAPSHOT_HASH` |

3. Создать **входящий вебхук** Bitrix24 → права CRM.  
4. Заполнить в 1–2 тестовых сделках: номер дела + регион/город/район/название суда.  
5. Выдать вам: URL вебхука, `CATEGORY_ID`, список `STAGE_ID`, коды UF.

### Шаг B. Инфраструктура

1. Арендовать VPS РФ (2 ГБ+).  
2. Завести аккаунт прокси РФ, выписать login/pass + порты.  
3. Завести RuCaptcha/2captcha, пополнить, скопировать API key.  
4. Добавить SSH-ключ на VPS (отдельный ключ «битрикс-юрист-клиент-X»).

### Шаг C. Установка ПО на VPS

```bash
# 1) каталоги
mkdir -p /opt/bitrix-delo /opt/bitrix-yurist

# 2) залить код парсера (копия, НЕ Анна) + courts-ru.json в /opt/bitrix-delo
# 3) venv
cd /opt/bitrix-delo
python3 -m venv venv
./venv/bin/pip install -r requirements-delo.txt 2captcha-python

# 4) bitrix job
cp bitrix.py /opt/bitrix-yurist/
# pip/system python3 с requests достаточно

# 5) .env — см. шаблон ниже (секреты НЕ в git)

# 6) systemd
cp deploy/bitrix-delo.service /etc/systemd/system/
cp deploy/bitrix-yurist.service /etc/systemd/system/
cp deploy/bitrix-yurist.timer /etc/systemd/system/
# в timer задать TZ=Europe/Moscow и OnCalendar=06:00
systemctl daemon-reload
systemctl enable --now bitrix-delo
systemctl enable --now bitrix-yurist.timer
```

**Важно:** `bitrix-yurist.service` должен иметь `After=` / `Wants=` на `bitrix-delo.service`, иначе утренний прогон поймает `Connection refused` на :8081.

### Шаг D. Секреты `.env`

**`/opt/bitrix-delo/.env`**

```bash
COURT_KB_API_KEY=<длинный случайный>
COURT_KB_PROXY=http://USER:PASS@pool.proxy.market:10001
COURT_KB_PROXY_PORTS=10001,10002,10003,10004,10005
TWOCAPTCHA_API_KEY=<ключ с rucaptcha/2captcha>
```

**`/opt/bitrix-yurist/.env`**

```bash
BITRIX_WEBHOOK_URL=https://CLIENT.bitrix24.ru/rest/ID/CODE/
BITRIX_CATEGORY_ID=0
BITRIX_STAGE_IDS=NEW,PREPARATION,EXECUTING
UF_CASE_NUMBER=UF_CRM_CASE_NUMBER
UF_COURT_NAME=UF_CRM_COURT_NAME
UF_REGION=UF_CRM_REGION
UF_CITY=UF_CRM_CITY
UF_DISTRICT=UF_CRM_DISTRICT
UF_COURT_WEBSITE=UF_CRM_COURT_WEBSITE
UF_COURT_SLUG=UF_CRM_COURT_SLUG
UF_LAST_STATUS=UF_CRM_LAST_STATUS
UF_LAST_CHECK_AT=UF_CRM_LAST_CHECK_AT
UF_SNAPSHOT_HASH=UF_CRM_SNAPSHOT_HASH
COURT_KB_API_URL=http://127.0.0.1:8081
COURT_KB_API_KEY=<тот же, что в bitrix-delo>
DRY_RUN=1
COMMENT_ONLY_ON_CHANGE=1
PAUSE_BETWEEN_DEALS_SEC=5
TZ=Europe/Moscow
```

### Шаг E. Приёмочные тесты (чек-лист)

1. `curl http://127.0.0.1:8081/health` → `{"status":"ok"}`  
2. `POST /court_lookup` с регионом/судом клиента → `found` + website  
3. `POST /delo` на мировой участок клиента → `found` или честный `not_found`  
4. `POST /delo` на районный sudrf → `found` / `not_found` / явная ошибка сайта  
5. `DRY_RUN=1` → `python3 /opt/bitrix-yurist/bitrix.py` → в логе сделки без записи  
6. `DRY_RUN=0` на 1 тестовой сделке → UF обновились, в ленте комментарий с датой МСК  
7. `systemctl list-timers bitrix-yurist.timer` → следующий запуск виден  
8. На следующий день — `journalctl -u bitrix-yurist.service -u bitrix-delo`

### Шаг F. Передача клиенту (handoff)

Передать папку/архив:

- код `/opt/bitrix-delo`, `/opt/bitrix-yurist`  
- unit-файлы systemd  
- это ТЗ  
- **не** передавать чужие ключи Анны/Нейроагентс/вашего пилота  

Клиент (или вы по договору) оплачивает VPS/прокси/2captcha на **своих** кабинетах.  
Доступ SSH — отдельный ключ; вебхук Bitrix — только их портал.

---

## 4. Ежедневная эксплуатация

| Действие | Как |
| --- | --- |
| Логи job | `journalctl -u bitrix-yurist.service -n 100` |
| Логи API | `journalctl -u bitrix-delo -n 100` |
| Ручной прогон | `systemctl start bitrix-yurist.service` |
| Баланс капчи | кабинет rucaptcha / `res.php?action=getbalance` |
| Баланс прокси | кабинет Proxy.Market |
| Обновить справочник | `from_sheets --download` → restart `bitrix-delo` |
| Смена воронки | правки `BITRIX_CATEGORY_ID` / `BITRIX_STAGE_IDS` + restart не нужен (читается на запуске job) |

Алерты (рекомендуется на долгосрок): раз в день скрипт/почта если `errors > 0` в итоге job или баланс 2captcha < $1.

---

## 5. Оценка расходов клиента (порядок)

| Статья | Старт / мес (ориентир) |
| --- | --- |
| VPS 2 ГБ РФ | 700–1500 ₽ |
| Прокси RU 10 ГБ | ~2000–3500 ₽ (зависит от типа) |
| 2captcha | 300–1500 ₽ (от доли мировых) |
| Битрикс24 | по тарифу клиента (уже есть) |
| **Итого инфраструктура** | **~3–6 тыс. ₽/мес** при умеренной нагрузке |

При росте сделок (>500/сутки) — больше sticky-портов прокси и RAM VPS.

---

## 6. Риски и правила работы с судами

1. Сайты sudrf периодически отдают «Информация временно недоступна» — это не баг Bitrix; job пишет ошибку в лог/поле, не «обновление произведено».  
2. Мировые почти всегда с капчей — без 2captcha не будет стабильного `found`.  
3. Не публиковать `:8081` в интернет.  
4. Не смешивать `.env` Анны и БитриксЮрист.  
5. Не коммитить вебхуки и API-ключи в git.

---

## 7. Отдельный аккаунт «Нейроагентс» (Ноя / MCP)

БитриксЮрист **не использует** Ною. Если параллельно ведёте Нейроагентс:

1. Создайте **отдельный** аккаунт/проект в Ное (не Анна).  
2. Выпустите **отдельные** MCP/API-ключи только для Нейроагентс.  
3. В Cursor подключайте MCP Нейроагентс как второй сервер с другим именем.  
4. Секреты храните в другом `.env` / другом секрет-хранилище.  
5. Не давайте Нейроагентс доступ к webhook БитриксЮрист и наоборот.

Так аккаунты и ключи не пересекутся.

---

## 8. Критерии готовности «клиент в проде»

- [ ] VPS РФ 2 ГБ+, systemd оба сервиса `enabled`  
- [ ] Прокси RU + 2captcha с положительным балансом  
- [ ] Webhook Bitrix CRM, UF-поля, воронка  
- [ ] `/health`, `/court_lookup`, `/delo` (MS + RS) проходят  
- [ ] Тестовая сделка: лента «Обновление дела произведено»  
- [ ] `DRY_RUN=0`, timer 06:00 МСК  
- [ ] Документы handoff + отдельные ключи от Анны/Нейроагентс  
- [ ] Понятен владелец оплаты VPS/прокси/капчи (клиент)

---

## 9. Состав поставки (файлы в репозитории)

| Путь | Назначение |
| --- | --- |
| `БитриксЮрист/bitrix.py` | ежедневный job |
| `БитриксЮрист/deploy/*.service\|timer` | systemd |
| `БитриксЮрист/parser-src/` | код/патчи парсера + справочник |
| `БитриксЮрист/.env.example` | шаблон секретов |
| `БитриксЮрист/TZ-CLIENT.md` | этот документ |
| `БитриксЮрист/PLAN.md` | продуктовый план |

---

*Версия ТЗ: 26.08.2026. Пилот проверен на живых sudrf/msudrf.*
