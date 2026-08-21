# Действие Дело — описание для AI (кабинет)

Два режима одного действия. Клиенту имя действия не пиши.

## Режим А — справка с сайта суда (режим работы, телефоны, структура…)

Когда: клиент спрашивает часы/приёмную/канцелярию/телефон/e-mail/структуру/подсудность/реквизиты госпошлины/как проехать — и в БЗ уже есть «САЙТ» этого суда.

Сначала обязательно найди суд в Базе Знаний и заполни переменные (название, регион, сайт). Потом вызови действие.

Body:
{
  "mode": "info",
  "website": "<САЙТ из строки БЗ, как в таблице>",
  "topic": "<hours|contacts|structure|jurisdiction|duty|visitors|general>"
}

topic:
- hours — режим работы, график приёма, канцелярия
- contacts — телефоны, факс, e-mail, адрес приёма
- structure — организационная структура
- jurisdiction — территориальная подсудность
- duty — реквизиты / госпошлина
- visitors — информация для посетителей / проезд
- general — общая справка «О суде»

Примеры:
1) Часы Октябрьского Ставрополя: {"mode":"info","website":"http://oktyabrsky.stv.sudrf.ru","topic":"hours"}
2) Телефоны: {"mode":"info","website":"https://kominternovsky--vrn.sudrf.ru/","topic":"contacts"}

Ответ клиенту только из result. status not_found/error → не выдумывай часы/телефоны; скажи, что на сайте в типовых разделах не удалось снять данные, и дай САЙТ.

## Режим Б — карточка дела (живой поиск)

Когда: суд из списка ниже И есть номер дела или фамилия участника.

Body:
{
  "mode": "case",
  "court_slug": "<slug>",
  "case_number": "<номер или пустая строка>",
  "last_name": "<фамилия или пустая строка>"
}

court_slug: sovetsky-vrn | kominternovsky-vrn | zheleznodorozhny-vrn | levoberezhny-vrn | centralny-vrn | lensud-vrn (все г. Воронеж).

Примеры:
1) {"mode":"case","court_slug":"sovetsky-vrn","case_number":"2-123/2025","last_name":""}
2) {"mode":"case","court_slug":"kominternovsky-vrn","case_number":"","last_name":"Иванов"}

Суд не из списка → карточку не ищи; для справки используй Режим А с website из БЗ.
status error/not_found → не выдумывай карточку, дай сайт суда.
