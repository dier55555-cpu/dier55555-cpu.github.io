# Саприн и партнёры — парсер судов + Bitrix job

Контур: **`Cursor/Другие/Саприн и партнеры/`** (не Ноя, отдельно от Анны).  
На Mac: `/Users/user/Projects/Cursor/Другие/Саприн и партнеры`.  
Сводка архива ТЗ/тестов/VPS: `_архив/README.md`.  
VPS: `168.222.202.68` (`parcer555-vps-2`) → `/opt/saprin/{parser,job,data,logs,venv}`.

## Архитектура

```
Bitrix24 (CATEGORY_ID=2 «Исполнение»)
        │  crm.deal.list
        ▼
/opt/saprin/job/bitrix.py  + triggers.py
        │  POST http://127.0.0.1:8081/delo
        ▼
saprin-parser.service  (api.delo_app, :8081, sync-handlers в threadpool)
        │  до 6 одновременных /delo на РАЗНЫЕ суды
        │  COURT_KB_PROXY (residential RU)
        ▼
*.sudrf.ru   (msudrf — skipped, без 2captcha)
```

Секреты (webhook, proxy) **только на VPS**, `chmod 600`, не в git.

## Клиентские UF

| Назначение | Код |
|---|---|
| № дела | `UF_CRM_1741881362933` |
| Ссылка на дело (приоритет) | `UF_CRM_1747812731315` → `UF_CRM_1742479380838` → `UF_CRM_1739466337400` (+ запасные url UF) |

## Служебные UF (на портале)

Префикс `UF_CRM_SAPRIN_*` (см. `job/.env.example` и `job/create_uf_fields.py`):  
`LAST_STATUS`, `LAST_CHECK`, `SNAP_HASH`, `KNOWN_STAGE`, `COURT_SITE`, `DECISION_DATE`, `DECISION_PUB`, `DEADLINE_40D`, `STAGE_ENTER`, `APPEAL_RESULT`.

## Расписание (МСК)

| Unit | Когда | Этапы |
|---|---|---|
| `saprin-job-weekly.timer` | Пн **05:00** | до «Вынесено решение» |
| `saprin-job-daily.timer` | Пн–Пт **07:00** | с «Вынесено решение» и далее |

## Уведомления клиенту (MAX и Telegram)

При **автопереходе** этапа (по умолчанию только «Вынесено решение», `C2:UC_GZ6RL3`) джоб берёт телефон из контакта сделки (если нет — из названия) и шлёт текст в MAX и Telegram **по номеру**.

Шаблон для «Вынесено решение»:

```
Сообщаем вам, что по вашему делу {номер} судом вынесено решение. Для ознакомления можете перейти по ссылке:
{ссылка на sudrf}

Также можете позвонить юристу, ведущему ваше дело: {телефон ответственного}.
```

Официальные боты MAX/Telegram **не умеют** писать «на любой номер» без диалога. Поэтому транспорт — **Green-API**: два инстанса (мессенджер MAX и Telegram), в кабинете сканируется QR **рабочими** аккаунтами фирмы.

```bash
# в /opt/saprin/job/.env
CLIENT_NOTIFY=1
CLIENT_NOTIFY_STAGES=C2:UC_GZ6RL3
CLIENT_NOTIFY_CHANNELS=max,telegram
GREEN_API_MAX_URL=https://api.green-api.com
GREEN_API_MAX_ID=...
GREEN_API_MAX_TOKEN=...
GREEN_API_TG_URL=https://api.green-api.com
GREEN_API_TG_ID=...
GREEN_API_TG_TOKEN=...
```

Другие этапы: допишите ID через запятую в `CLIENT_NOTIFY_STAGES`. Повтор на ту же сделку+этап не шлётся (`job/data/client_notify.json`). `DRY_RUN=1` — только лог, без отправки.

Проверка шаблона и телефонов без рассылки:

```bash
/opt/saprin/venv/bin/python /opt/saprin/job/probe_notify.py
```

## Отчёты и откат

После каждого прогона на VPS: `/opt/saprin/logs/runs/weekly/` и `.../daily/` (хранятся **последние 7**).

```bash
ls -lt /opt/saprin/logs/runs/daily/
# 20260908-0700.md  +  -moves.jsonl  +  -errors.jsonl
```

Откат **только переносов из выбранного отчёта**, если этап в CRM всё ещё «стало»:

```bash
# сначала посмотреть
/opt/saprin/venv/bin/python /opt/saprin/job/rollback_run.py --job daily --stamp 20260908-0700
# применить
/opt/saprin/venv/bin/python /opt/saprin/job/rollback_run.py --job daily --stamp 20260908-0700 --apply
```

Сделки, которые юрист уже сдвинул дальше, скрипт **пропустит**.

## Деплой

```bash
export SAPRIN_SSH_KEY=~/.ssh/saprin_id_rsa
bash scripts/deploy.sh
```

На VPS: `/opt/saprin/parser/.env` (`COURT_KB_PROXY=…`), `/opt/saprin/job/.env` (webhook, `DRY_RUN=1`), `/opt/saprin/job/.env.proxy`.

**Источник истины для sudrf — `COURT_KB_PROXY` в `parser/.env`.**  
`job/.env.proxy` (`HTTP_PROXY` / `PROXY_USER`) не должен расходиться по логину: иначе легко получить 407 и тихий уход в `port=direct`.

```bash
systemctl restart saprin-parser
systemctl enable --now saprin-job-weekly.timer saprin-job-daily.timer
```

## Прокси: как проверить

```bash
# на VPS — до DRY_RUN / прод-джоба
/opt/saprin/venv/bin/python /opt/saprin/job/probe_proxy.py
# OK: auth_ok>0 и sudrf_ok>0
# FAIL 407: неверный логин/пароль в кабинете proxy.market → поправить COURT_KB_PROXY, restart parser
journalctl -u saprin-parser -n 50 | grep -E 'port=|channels exhausted|407'
```

Признаки поломки: в логах массово `port=direct` / `channels exhausted`, в job — таймауты «Судебное делопроизводство».  
Парсер пробует до 3 sticky-портов; `direct` с IP VPS по умолчанию **выключен**, если пул прокси непустой (`COURT_KB_ALLOW_DIRECT=1` — вернуть старое поведение).

## Ручной прогон

```bash
curl -sS http://127.0.0.1:8081/health
/opt/saprin/venv/bin/python /opt/saprin/job/probe_proxy.py
curl -sS http://127.0.0.1:8081/delo -H 'Content-Type: application/json' \
  -d '{"case_number":"2-6302/2024","website":"https://kominternovsky--vrn.sudrf.ru/"}'

cd /opt/saprin/job
set -a && source .env && set +a
LIMIT_DEALS=3 DRY_RUN=1 /opt/saprin/venv/bin/python bitrix.py
```

## Вкладки / столбцы сайтов судов (райсуд)

Точные названия со скринов клиента и пометки «что берём для триггеров»:

- `job/sudrf_tabs_rayon.md` — райсуд
- `job/sudrf_tabs_oblsud.md` — облсуд (апелляция)
- `job/sudrf_labels.py` — константы для матчинга

Райсуд, вкладка апелляции: **`ОБЖАЛОВАНИЕ РЕШЕНИЙ, ОПРЕДЕЛЕНИЙ (ПОСТ.)`**.  
Облсуд: **`РАССМОТРЕНИЕ В НИЖЕСТОЯЩЕМ СУДЕ`**, **`УЧАСТНИКИ`** (не «СТОРОНЫ…»).

## Ограничения

- Нет ссылки на sudrf и нет сохранённого `COURT_SITE` → **не** перебираем суды области; один комментарий в ленту: указать ссылку на дело или название суда.
- **В8** (апелляция отменила/изменила): автопереход в «Решение вступило в законную силу».
- **Апелляция**: только событие «Направлено в вышестоящую инстанцию» в «ДВИЖЕНИЕ ЖАЛОБЫ». Вкладка без этого события — не триггер. Возврат жалобы (несоответствие требованиям) — остаёмся на «Вынесено решение»; назад с апелляции не откатываем (календарь-алерт).
- **«ДДУ 2025 год»**: СЗ + «без рассмотрения» + неявка сторон (как Шайкин).
- Ошибки этапа A/B/C → разовое событие в календарь компании (+ attendees всем активным).
- Пока `DRY_RUN=1` — в Bitrix ничего не пишется; `APPLY_STAGE_MOVES` сработает только после снятия DRY_RUN.
- Парсинг: **до 6 разных судов сразу** (`PARSE_CONCURRENCY=6`); один и тот же hostname — очередь + пауза `PARSE_HOST_PAUSE_SEC`. VPS 2 CPU / 2 ГБ для этого хватает (ожидание сети).
- Мировые суды / 2captcha / Ноя / n8n / Анна (`/opt/court-kb`) — вне контура.
