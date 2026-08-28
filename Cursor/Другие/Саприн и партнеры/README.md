# Саприн и партнеры — мониторинг судебных дел (Битрикс24)

Отдельный контур на VPS `168.222.202.68` (не Анна, не Ноя).

## Состав

| Путь на VPS | Назначение |
|---|---|
| `/opt/saprin/parser` | FastAPI `/delo` + `/court_lookup` (:8081) |
| `/opt/saprin/job` | Job Bitrix → парсер → UF/timeline |
| `/opt/saprin/venv` | Python 3.12 |
| `/opt/saprin/logs` | логи |

## Клиентский маппинг

- Воронка: `CATEGORY_ID=2` (Исполнение)
- Номер дела: `UF_CRM_1741881362933` (берём `2-…/…`)
- Ссылка на суд: `UF_CRM_1747812731315` (+ запасные URL-поля)
- Мировые (`msudrf`) — skip

## Таймеры (МСК)

- Пн **08:00** — этапы до «Вынесено решение»
- Пн–Пт **08:30** — «Вынесено решение» и далее

## Ручной прогон

```bash
sudo systemctl start saprin-job-weekly.service
# или
cd /opt/saprin/job && set -a && source .env && set +a && /opt/saprin/venv/bin/python bitrix.py
```

`DRY_RUN=1` — только лог, без записи в CRM.

## Секреты

Только на VPS в `.env` (mode 600), не в git.
