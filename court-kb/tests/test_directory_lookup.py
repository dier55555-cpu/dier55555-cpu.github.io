from scraper.directory.lookup import lookup_courts, tokenize_query
from scraper.directory.normalize import enrich_court


def _records():
    raw = [
        {
            "code": "26RS0002",
            "name": "Ленинский районный суд г. Ставрополя",
            "court_type": "RS",
            "court_type_name": "Районный, городской, межрайонный суд",
            "address": "355017, г Ставрополь, ул Ленина, д 219",
            "website": "http://leninsky.stv.sudrf.ru",
        },
        {
            "code": "36RS0004",
            "name": "Ленинский районный суд г. Воронежа",
            "court_type": "RS",
            "court_type_name": "Районный, городской, межрайонный суд",
            "address": "394018, г Воронеж, ул Володарского, д 42",
            "website": "http://lensud.vrn.sudrf.ru",
        },
        {
            "code": "36RS0005",
            "name": "Советский районный суд г. Воронежа",
            "court_type": "RS",
            "court_type_name": "Районный, городской, межрайонный суд",
            "address": "394030, г Воронеж, ул Плехановская, д 9",
            "website": "http://sovetsky.vrn.sudrf.ru",
        },
        {
            "code": "92RS0003",
            "name": "Ленинский районный суд города Севастополя",
            "court_type": "RS",
            "address": "299011, г Севастополь, ул Ленина, д 3",
            "website": "http://leninsky.sev.sudrf.ru",
        },
    ]
    return [enrich_court(row) for row in raw]


def test_tokenize_drops_stopwords():
    assert tokenize_query("Ленинский район г. Ставрополь") == ["ленинский", "ставрополь"]


def test_lookup_leninsky_stavropol():
    matches = lookup_courts("Ленинский район г. Ставрополь", _records())
    assert matches
    assert matches[0].code == "26RS0002"
    assert matches[0].sudrf_domain == "leninsky--stv.sudrf.ru"


def test_lookup_does_not_confuse_other_leninsky():
    matches = lookup_courts("Ленинский район г. Ставрополь", _records(), limit=3)
    codes = [item.code for item in matches]
    assert codes[0] == "26RS0002"
    assert "36RS0004" not in codes[:1]


def test_lookup_sovietsky_voronezh():
    matches = lookup_courts("Советский Воронеж", _records())
    assert matches[0].code == "36RS0005"


def test_lookup_oblast_court_prefers_os():
    extra = enrich_court({
        "code": "36OS0000",
        "name": "Воронежский областной суд",
        "court_type": "OS",
        "address": "394036, г Воронеж, пр-кт Революции, д 14А",
        "website": "http://oblsud.vrn.sudrf.ru",
    })
    matches = lookup_courts("Воронежский областной", _records() + [extra])
    assert matches[0].code == "36OS0000"


def test_lookup_skips_magistrate_by_default():
    matches = lookup_courts("Ленинский район г. Ставрополь", _records())
    assert all(item.court_type != "MS" for item in matches)
    matches = lookup_courts("Ленинский Норильск", _records())
    assert matches == []
