# Архив проекта «Саприн и партнёры» (09.09.2026)

## Куда это лежит на Mac

Репозиторий клонируется как `Projects/Cursor/…`. Эта папка в git:

**`/Users/user/Projects/Cursor/Другие/Саприн и партнеры`**

Вы просили `/Users/user/Projects/Другие/Саприн и партнеры` — в правилах кабинета контур **не Ноя**, только `Cursor/Другие/`. Если нужна копия без `Cursor/`, скопируйте эту папку вручную.

## Что внутри репозитория (можно в git)

| Путь | Содержание |
|---|---|
| `parser/` | код парсера sudrf (API `:8081`) |
| `job/` | Bitrix-джоб, триггеры, тесты, probe, отчёты, откат |
| `deploy/` | systemd timer/service |
| `scripts/deploy.sh` | выкладка на VPS |
| `README.md` | как устроено |
| `_архив/входящие/` | ТЗ разработчика, Excel «Проверка тест 3» |
| `_архив/отчёты-копия/` | DRY_RUN и проверки юриста (август–сентябрь) |
| `_архив/vps/` | маскированные `.env`, копии daily-отчётов 08–09.09 |
| `_архив/systemd-копия/` | те же unit-файлы, что в `deploy/` |

## Секреты (не в git)

Папка **`_архив/secrets/`** — в `.gitignore`. На этой машине агента она заполнена:

- `id_rsa` / `id_rsa.pub` / `id_rsa.zip` — SSH на VPS `root@168.222.202.68`
- `saprin-job.env` — webhook Bitrix, флаги
- `saprin-parser.env` — COURT_KB_PROXY + BACKUP
- `saprin-job.env.proxy` — старый HTTP_PROXY
- `Прокси_для_Саприн.docx` — логины proxy.market

Чтобы секреты оказались на Mac: скопируйте `_архив/secrets/` с облачного агента/архива вручную **или** заберите с VPS (`/opt/saprin/job/.env`, `/opt/saprin/parser/.env`). **Не публикуйте** эту папку в GitHub.

## Боевой контур (VPS)

- Хост: `168.222.202.68` (`parcer555-vps-2`), код: `/opt/saprin/{parser,job,logs,venv}`
- Парсер: `saprin-parser.service` → `127.0.0.1:8081`
- Weekly: Пн **05:00** МСК (`SAPRIN_JOB_KIND=weekly`)
- Daily: Пн–Пт **07:00** МСК (`SAPRIN_JOB_KIND=daily`)
- `DRY_RUN=0`, `APPLY_STAGE_MOVES=1`, `LIMIT_DEALS=0`
- Воронка Bitrix `CATEGORY_ID=2`, ДДУ = `C2:UC_ZLIVI0`
- Отчёты прогонов: `/opt/saprin/logs/runs/{daily,weekly}/` (последние 7)
- Откат: `/opt/saprin/venv/bin/python /opt/saprin/job/rollback_run.py --job daily --stamp YYYYMMDD-HHMM`

## Тесты в коде

`job/test_appeal_v8.py`, `test_appeal_complaint.py`, `test_hearing_no_expertise.py`, `test_run_report.py`

## Последние боевые daily (уже в `_архив/vps/runs-daily/`)

- **08.09** 07:00–07:12: 198 сделок, **3** переноса, 0 ошибок парсера
- **09.09** 07:00–07:14: 197 сделок, **3** переноса, 0 ошибок парсера

Weekly 07.09 05:00–05:27: 207 сделок, 4 переноса (отчёт-файла weekly тогда ещё не писался).
