# БитриксЮрист

Ежедневный обход сделок Битрикс24 на VPS `sudrf-parser`.

- `/opt/bitrix-delo` — **копия** рабочего парсера (порт 8081), Аннин `/opt/court-kb:8080` не трогаем  
- `/opt/bitrix-yurist` — Битрикс + `systemd timer` 06:00 МСК  

Ноя/n8n для этого контура не нужны. План: [PLAN.md](PLAN.md).
