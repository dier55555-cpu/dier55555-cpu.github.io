# Импорт воркфлоу в n8n НОЕ

В этом каталоге два готовых JSON-файла для импорта в n8n (Workflows → Import from File).

| Файл | Назначение | Как дёргается |
| --- | --- | --- |
| `court-agent-webhook.json` | Вебхук агента: поиск по БЗ, список судов, живой поиск дела | Агент НОЕ → HTTP POST на вебхук |
| `scheduled-crawl.json` | Ночной обход сайтов судов (слой 1) | Расписание 03:00 |

Старый файл `case-lookup-webhook.json` оставлен как узкий вариант только слоя 2; для агента используйте `court-agent-webhook.json`.

## 1. Поднять Python-API на сервере НОЕ

На том же сервере, где крутится n8n (или на соседнем контейнере):

```bash
cd court-kb
cp .env.example .env
# отредактируйте COURT_KB_API_KEY в .env
docker compose up -d --build
curl http://127.0.0.1:8080/health
```

Должно ответить `{"status":"ok"}`.

Проверка, видит ли этот сервер сайты судов (Шаг 0 из корневого README):

```bash
curl -sS -m 15 https://sovetsky--vrn.sudrf.ru/ | head
```

Если в ответе «заблокирован по соображениям безопасности» — заполните `COURT_KB_PROXY` в `.env` российским прокси и перезапустите `docker compose up -d`.

## 2. Переменные окружения n8n

В настройках n8n НОЕ задайте:

- `COURT_KB_API_URL` — `http://127.0.0.1:8080`, если API на том же хосте; если API в Docker-сети n8n — `http://court-kb-api:8080` (имя сервиса из `docker-compose.yml`).
- `COURT_KB_API_KEY` — тот же ключ, что в `.env` API.

## 3. Импорт и активация вебхука

1. n8n → Workflows → Import from File → выберите `court-agent-webhook.json`.
2. Откройте воркфлоу, нажмите **Active**.
3. В ноде Webhook скопируйте Production URL — обычно вида `https://<домен-НОЕ>/webhook/court-agent`.
4. Этот URL подключаете агенту в НОЕ как HTTP-инструмент / webhook-действие.

Тело запроса агента (JSON):

```json
{ "action": "list_courts" }
```

```json
{ "action": "kb_search", "query": "режим работы приёмной", "court_slug": "sovetsky-vrn" }
```

```json
{
  "action": "case_lookup",
  "court_slug": "sovetsky-vrn",
  "case_number": "2-123/2026",
  "production_type": "civil_first_instance"
}
```

Если `action` не указан, воркфлоу угадывает его по полям (`case_number`/`last_name` → поиск дела, `query` → поиск по БЗ).

## 4. Ночной обход

1. Import from File → `scheduled-crawl.json`.
2. Active.
3. После первого успешного прогона в `data/corpus.jsonl` появятся страницы; `GET /corpus/export` отдаёт их для заливки в БЗ агента. Ноду заливки в БЗ НОЕ добавьте сами — эндпоинт загрузки документов зависит от конкретной сборки платформы.

## 5. Что сказать агенту в промпте

- Справочные вопросы (адрес, часы, реквизиты) → `action=kb_search`.
- «Когда заседание / статус дела №… / есть ли дела на фамилию …» → сначала `list_courts`, затем `case_lookup` с `court_slug` и номером или фамилией.
- Не вызывать `case_lookup` «на всякий случай» — это живой запрос к сайту суда, иногда с капчей.
