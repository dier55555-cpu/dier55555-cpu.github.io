# БитриксЮрист

Ежедневный обход сделок Битрикс24 на VPS `sudrf-parser`.

- `/opt/bitrix-delo:8081` — копия парсера + справочник судов РФ (~10k), SSL для `msudrf`
- `/opt/bitrix-yurist` — job: Битрикс → БЗ (регион/город/район/суд → сайт) → `/delo` → лента карточки
- Аннин `/opt/court-kb:8080` не трогаем

## Справочник судов

Источник — Google Sheets (не DaData):

- [Суды РФ](https://docs.google.com/spreadsheets/d/19sxmrNDDHu0u-g4y3987g5hMMSdFh5VkKKmRRH-v2VU)
- [Мировые суды](https://docs.google.com/spreadsheets/d/109ThgsNtz_pyaLu0RZonEqh0oN1ntS5OCbJAfH_M6HQ)

CSV-снимки: `parser-src/directory/sheets/`. Сборка JSON:

```bash
cd parser-src
python -m scraper.directory.from_sheets            # из локальных CSV
python -m scraper.directory.from_sheets --download # свежая выгрузка Sheets → CSV → JSON
```

На VPS: скопировать `directory/courts-ru.json` в `/opt/bitrix-delo/directory/` и `systemctl restart bitrix-delo`.

## Капча мировых (2captcha)

В `/opt/bitrix-delo/.env`:

```bash
TWOCAPTCHA_API_KEY=...
```

Пакет: `pip install 2captcha-python` в venv bitrix-delo. Gate `kcaptchaForm` решается автоматически; ответ POST в windows-1251.

План: [PLAN.md](PLAN.md)  
ТЗ для долгого подключения клиента: [TZ-CLIENT.md](TZ-CLIENT.md)
