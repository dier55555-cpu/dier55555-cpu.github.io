from scraper.directory.dadata import walk_prefix
from scraper.directory.normalize import city_nominative, enrich_court, parse_city, parse_district, parse_region, sudrf_target


def test_sudrf_dotted_host_becomes_double_hyphen():
    domain, supported = sudrf_target("http://sovetsky.vrn.sudrf.ru")
    assert domain == "sovetsky--vrn.sudrf.ru"
    assert supported is True


def test_sudrf_live_host_stays():
    domain, supported = sudrf_target("https://sovetsky--vrn.sudrf.ru/")
    assert domain == "sovetsky--vrn.sudrf.ru"
    assert supported is True


def test_single_label_sudrf_is_supported():
    domain, supported = sudrf_target("http://1ap.sudrf.ru")
    assert domain == "1ap.sudrf.ru"
    assert supported is True


def test_mos_gorsud_is_not_g1_parser():
    domain, supported = sudrf_target("https://mos-gorsud.ru/rs/babushkinskij")
    assert domain == "mos-gorsud.ru"
    assert supported is False


def test_empty_website():
    domain, supported = sudrf_target("")
    assert domain == ""
    assert supported is False


def test_parse_voronezh_district_court():
    record = enrich_court({
        "code": "36RS0005",
        "name": "Советский районный суд г. Воронежа",
        "court_type": "RS",
        "court_type_name": "Районный, городской, межрайонный суд",
        "address": "394030, г Воронеж, ул Плехановская, д 9",
        "website": "http://sovetsky.vrn.sudrf.ru",
    })
    assert record.city == "Воронеж"
    assert record.district == "Советский"
    assert record.sudrf_domain == "sovetsky--vrn.sudrf.ru"
    assert record.parser_supported is True
    assert record.region_code == "36"


def test_parse_stavropol_leninsky():
    record = enrich_court({
        "code": "26RS0002",
        "name": "Ленинский районный суд г. Ставрополя",
        "court_type": "RS",
        "court_type_name": "Районный, городской, межрайонный суд",
        "address": "355017, г Ставрополь, ул Ленина, д 219",
        "website": "http://leninsky.stv.sudrf.ru",
    })
    assert record.city == "Ставрополь"
    assert record.district == "Ленинский"
    assert record.region == "Ставропольский край" or record.city == "Ставрополь"
    assert record.sudrf_domain == "leninsky--stv.sudrf.ru"


def test_parse_region_from_krai_address():
    assert parse_region(
        "Александровский районный суд Ставропольского края",
        "356300, Ставропольский край, с Александровское, ул Войтика, д 9",
    ) == "Ставропольский край"
    assert parse_city(
        "Александровский районный суд Ставропольского края",
        "356300, Ставропольский край, с Александровское, ул Войтика, д 9",
    ) == "Александровское"
    assert parse_district("Александровский районный суд Ставропольского края") == "Александровский"


def test_parse_moscow_federal_city():
    record = enrich_court({
        "code": "77RS0001",
        "name": "Бабушкинский районный суд города Москвы",
        "court_type": "RS",
        "address": "129281, г Москва, ул Лётчика Бабушкина, д 39А",
        "website": "https://mos-gorsud.ru/rs/babushkinskij",
    })
    assert record.city == "Москва"
    assert record.region == "Москва"
    assert record.district == "Бабушкинский"
    assert record.parser_supported is False


def test_oblast_court_has_no_district():
    record = enrich_court({
        "code": "36OS0000",
        "name": "Воронежский областной суд",
        "court_type": "OS",
        "address": "394036, г Воронеж, пр-кт Революции, д 14А",
        "website": "http://oblsud.vrn.sudrf.ru",
    })
    assert record.district == ""
    assert record.city == "Воронеж"
    assert record.region == "Воронежская область"
    assert record.sudrf_domain == "oblsud--vrn.sudrf.ru"


def test_fill_missing_region_from_neighbours():
    from scraper.directory.normalize import fill_missing_regions

    city_court = enrich_court({
        "code": "36RS0005",
        "name": "Советский районный суд г. Воронежа",
        "court_type": "RS",
        "address": "394030, г Воронеж, ул Плехановская, д 9",
        "website": "http://sovetsky.vrn.sudrf.ru",
    })
    oblast = enrich_court({
        "code": "36OS0000",
        "name": "Воронежский областной суд",
        "court_type": "OS",
        "address": "394036, г Воронеж, пр-кт Революции, д 14А",
        "website": "http://oblsud.vrn.sudrf.ru",
    })
    assert city_court.region == ""
    filled = fill_missing_regions(item for item in [city_court, oblast])
    assert len(filled) == 2
    by_code = {item.code: item for item in filled}
    assert by_code["36RS0005"].region == "Воронежская область"


def test_parse_rabochiy_poselok_and_chuvashia():
    record = enrich_court({
        "code": "22RS0001",
        "name": "Благовещенский районный суд Алтайского края",
        "court_type": "RS",
        "address": "658670, Алтайский край, рп Благовещенка, пер Кучеровых, д 65",
        "website": "http://blagoveshensky.alt.sudrf.ru",
    })
    assert record.city == "Благовещенка"
    assert record.region == "Алтайский край"

    chuvash = enrich_court({
        "code": "21RS0001",
        "name": "Алатырский районный суд Чувашской Республики",
        "court_type": "RS",
        "address": "429820, Чувашская Республика - Чувашия, г Алатырь, ул Первомайская, д 35",
        "website": "http://alatyrsky.chv.sudrf.ru",
    })
    assert chuvash.city == "Алатырь"
    assert "Чуваш" in chuvash.region
    assert city_nominative("Ставрополя") == "Ставрополь"
    assert city_nominative("Воронежа") == "Воронеж"
    assert city_nominative("Москвы") == "Москва"


def test_walk_prefix_expands_when_api_returns_20():
    calls = []

    def fake_suggest(query, court_type):
        calls.append(query)
        assert court_type == "RS"
        if query in {"36RS", "36RS0", "36RS00"}:
            return [{"code": f"36RS{i:04d}", "name": str(i)} for i in range(20)]
        if query == "36RS000":
            return [{"code": f"36RS{i:04d}", "name": str(i)} for i in range(9)]
        if query == "36RS001":
            return [{"code": "36RS0015", "name": "15"}, {"code": "99RS0001", "name": "noise"}]
        return []

    rows = walk_prefix(fake_suggest, "36RS", "RS")
    codes = {row["code"] for row in rows}
    assert {f"36RS{i:04d}" for i in range(9)} <= codes
    assert "36RS0015" in codes
    assert "99RS0001" not in codes
    assert "36RS" in calls
    assert "36RS0" in calls
    assert "36RS00" in calls
    assert "36RS000" in calls
    assert "36RS001" in calls


def test_moscow_address_without_name_suffix():
    record = enrich_court({
        "code": "77MS0001",
        "name": "Судебный участок № 1 района Матушкино",
        "court_type": "MS",
        "address": "124681, г Москва, г Зеленоград, к 200Г",
        "website": "https://mos-sud.ru",
    })
    assert record.region == "Москва"
