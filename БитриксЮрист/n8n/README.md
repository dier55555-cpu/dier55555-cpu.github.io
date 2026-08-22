Не импортировать поверх воркфлоу Анны (`court-agent-yurist`).

Этот JSON — **новый** workflow:

- path вебхука: `bitrix-yurist-daily`
- cron 06:00 Europe/Moscow
- один HTTP POST на сервис БитриксЮрист `/run`

Парсер sudrf здесь не вызывается. Его по-прежнему дергает Python через `POST /delo` с теми же URL и ключом, что у Анны.
