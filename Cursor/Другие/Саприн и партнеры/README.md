# Саприн и партнёры — парсер судов + Bitrix job

Контур: **`Cursor/Другие/Саприн и партнеры/`** (не Ноя, отдельно от Анны).  
VPS: `168.222.202.68` (`parcer555-vps-2`) → `/opt/saprin/{parser,job,data,logs,venv}`.

## Архитектура

```
Bitrix24 (CATEGORY_ID=2 «Исполнение»)
        │  crm.deal.list
        ▼
/opt/saprin/job/bitrix.py  + triggers.py
        │  POST http://127.0.0.1:8081/delo
        ▼
saprin-parser.service  (api.delo_app, :8081)
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
| `saprin-job-weekly.timer` | Пн 08:00 | до «Вынесено решение» |
| `saprin-job-daily.timer` | Пн–Пт 08:30 | с «Вынесено решение» и далее |

## Деплой

```bash
export SAPRIN_SSH_KEY=~/.ssh/saprin_id_rsa
bash scripts/deploy.sh
```

На VPS: `/opt/saprin/parser/.env` (`COURT_KB_PROXY=…`), `/opt/saprin/job/.env` (webhook, `DRY_RUN=1`), `/opt/saprin/job/.env.proxy`.

```bash
systemctl restart saprin-parser
systemctl enable --now saprin-job-weekly.timer saprin-job-daily.timer
```

## Ручной прогон

```bash
curl -sS http://127.0.0.1:8081/health
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
- **В8** (апелляция отменила/изменила): `stop_manual` + комментарий, без автоперехода.
- Пока `DRY_RUN=1` — в Bitrix ничего не пишется; `APPLY_STAGE_MOVES` сработает только после снятия DRY_RUN.
- Мировые суды / 2captcha / Ноя / n8n / Анна (`/opt/court-kb`) — вне контура.
