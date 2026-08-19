from sudrf_kb.parse import classify_page, extract_links, parse_page

SAMPLE_HTML = """
<html>
<head><title>Контакты - Советский районный суд г. Воронежа</title></head>
<body>
  <header>Шапка сайта, меню, логотип</header>
  <nav><a href="/modules.php?name=Home">Главная</a></nav>
  <div id="content">
    <h1>Контактная информация</h1>
    <p>Адрес: г. Воронеж, ул. Театральная, д. 30</p>
    <p>Телефон: (473) 255-05-55</p>
    <a href="/modules.php?name=News">Новости</a>
    <a href="https://another-domain.example/page">Внешняя ссылка</a>
    <a href="/files/report.pdf">Документ PDF</a>
  </div>
  <footer>Подвал сайта</footer>
  <script>console.log('should be removed')</script>
</body>
</html>
"""


def test_parse_page_strips_noise_and_keeps_content():
    page = parse_page("https://sovetsky--vrn.sudrf.ru/contacts", SAMPLE_HTML)

    assert "Театральная" in page.text
    assert "Шапка сайта" not in page.text
    assert "Подвал сайта" not in page.text
    assert "console.log" not in page.text
    assert page.title.startswith("Контакты")


def test_classify_page_by_keywords():
    assert classify_page("/contacts", "Контакты суда") == "contacts"
    assert classify_page("/news/1", "Новости суда") == "news"
    assert classify_page("/modules.php?name=sud_delo", "Движение дела") == "case_lookup"
    assert classify_page("/random", "Просто страница") == "other"


def test_extract_links_stays_within_domain_and_skips_binaries():
    links = extract_links(SAMPLE_HTML, "https://sovetsky--vrn.sudrf.ru/contacts")

    assert "https://sovetsky--vrn.sudrf.ru/modules.php?name=News" in links
    assert not any("another-domain.example" in link for link in links)
    assert not any(link.endswith(".pdf") for link in links)
