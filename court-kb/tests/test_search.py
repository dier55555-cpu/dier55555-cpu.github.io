from scraper.case_lookup.captcha import CaptchaSolver
from scraper.case_lookup.search import CaseQuery, search_case, search_case_direct
from scraper.fetch import FetchResult

FORM_URL = "https://example--vrn.sudrf.ru/modules.php?name=sud_delo&name_op=sf&delo_id=1540005&srv_num=1"

FORM_HTML = """
<html><body>
<form name="courtdel" method="get" action="modules.php">
<input type="hidden" name="name" value="sud_delo">
<input type="hidden" name="name_op" value="r">
<input type="hidden" name="delo_id" value="1540005">
<table>
<tr><td>Номер дела (материала)</td><td><input type="text" name="EX_NUM"></td></tr>
<tr>
  <td>Проверочный код</td>
  <td><input type="text" name="captcha_code"><img src="captcha.php?id=42"></td>
</tr>
</table>
</form>
</body></html>
"""

RESULT_HTML_FOUND = """
<html><body>
<table>
<tr><td>ДАННЫЕ ПО ДЕЛУ</td><td></td></tr>
<tr><td>Судья</td><td>Иванов И.И.</td></tr>
<tr><td>Дата рассмотрения</td><td>15.02.2026</td></tr>
</table>
</body></html>
"""

RESULT_HTML_NOT_FOUND = "<html><body>По вашему запросу ничего не найдено</body></html>"
RESULT_HTML_WRONG_CAPTCHA = "<html><body>Неверный код с картинки</body></html>"


class FakeFetcher:
    def __init__(self, form_html, submit_responses):
        self.form_html = form_html
        self.submit_responses = list(submit_responses)
        self.submitted_params = []

    def get(self, url, respect_robots=True):
        return FetchResult(url, ok=True, blocked=False, status_code=200, html=self.form_html)

    def get_bytes(self, url):
        return b"fake-captcha-bytes"

    def post(self, url, data):
        self.submitted_params.append(data)
        return self.submit_responses.pop(0)

    def request(self, method, url, params=None, data=None, **kwargs):
        payload = params if params is not None else data
        self.submitted_params.append(payload)
        return self.submit_responses.pop(0)


class FakeCaptchaSolver(CaptchaSolver):
    def __init__(self, code="ABCD"):
        self.code = code
        self.calls = 0

    def solve(self, image_bytes):
        self.calls += 1
        return self.code


def _ok(html):
    return FetchResult(FORM_URL, ok=True, blocked=False, status_code=200, html=html)


def test_search_case_found_after_captcha_solved():
    fetcher = FakeFetcher(FORM_HTML, [_ok(RESULT_HTML_FOUND)])
    solver = FakeCaptchaSolver()

    result = search_case(
        fetcher, "https://example--vrn.sudrf.ru/", 1540005,
        CaseQuery(case_number="2-123/2026"),
        captcha_solver=solver,
    )

    assert result.status == "found"
    assert len(result.cases) == 1
    assert solver.calls == 1
    assert fetcher.submitted_params[0]["EX_NUM"] == "2-123/2026"
    assert fetcher.submitted_params[0]["captcha_code"] == "ABCD"


def test_search_case_retries_on_wrong_captcha():
    fetcher = FakeFetcher(FORM_HTML, [_ok(RESULT_HTML_WRONG_CAPTCHA), _ok(RESULT_HTML_FOUND)])
    solver = FakeCaptchaSolver()

    result = search_case(
        fetcher, "https://example--vrn.sudrf.ru/", 1540005,
        CaseQuery(case_number="2-123/2026"),
        captcha_solver=solver,
        max_captcha_attempts=2,
    )

    assert result.status == "found"
    assert solver.calls == 2


def test_search_case_not_found():
    fetcher = FakeFetcher(FORM_HTML, [_ok(RESULT_HTML_NOT_FOUND)])
    solver = FakeCaptchaSolver()

    result = search_case(
        fetcher, "https://example--vrn.sudrf.ru/", 1540005,
        CaseQuery(case_number="does-not-exist"),
        captcha_solver=solver,
    )

    assert result.status == "not_found"


def test_search_case_without_solver_reports_captcha_required():
    fetcher = FakeFetcher(FORM_HTML, [])

    result = search_case(
        fetcher, "https://example--vrn.sudrf.ru/", 1540005,
        CaseQuery(case_number="2-123/2026"),
        captcha_solver=None,
    )

    assert result.status == "captcha_required"
    assert result.captcha_image_url == "https://example--vrn.sudrf.ru/captcha.php?id=42"


VORONEZH_TWO_FORMS_HTML = """
<html><body>
<form method="get" action="/modules.php">
<input type="hidden" name="name" value="sud_delo">
<input type="text" name="H_date" value="20.08.2026">
</form>
<form method="get" action="">
<input type="hidden" name="name" value="sud_delo">
<input type="hidden" name="srv_num" value="1">
<input type="hidden" name="name_op" value="r">
<input type="hidden" name="delo_id" value="1540005">
<input type="hidden" name="case_type" value="0">
<input type="hidden" name="new" value="0">
<input type="hidden" name="delo_table" value="g1_case">
<table>
<tr><td>Фамилия</td><td><input type="text" name="G1_PARTS__NAMESS"></td></tr>
<tr><td>Номер дела (материала)</td><td><input type="text" name="g1_case__CASE_NUMBERSS"></td></tr>
</table>
</form>
</body></html>
"""


def test_search_case_picks_second_form_and_works_without_captcha():
    fetcher = FakeFetcher(VORONEZH_TWO_FORMS_HTML, [_ok(RESULT_HTML_FOUND)])

    result = search_case(
        fetcher, "https://sovetsky--vrn.sudrf.ru/", 1540005,
        CaseQuery(case_number="2-123/2026"),
        captcha_solver=None,
    )

    assert result.status == "found"
    submitted = fetcher.submitted_params[0]
    assert submitted["g1_case__CASE_NUMBERSS"] == "2-123/2026"
    assert submitted["name_op"] == "r"
    assert submitted["delo_id"] == "1540005"
    assert "H_date" not in submitted


RESULT_HTML_LIST_PAGE = """
<html><body>
<div id="content">
<p>Всего по запросу найдено — 1.</p>
<table id="tablcont">
<tr><th>№ дела</th><th>Судья</th></tr>
<tr>
  <td><a href="/modules.php?name=sud_delo&name_op=case&case_id=9">2-10/2026</a></td>
  <td>Сидоров С.С.</td>
</tr>
</table>
</div>
</body></html>
"""


class HydratingFetcher(FakeFetcher):
    def get(self, url, respect_robots=True):
        if "name_op=case" in url:
            return _ok(RESULT_HTML_FOUND)
        return super().get(url)


def test_search_case_hydrates_list_hit_into_case_card():
    fetcher = HydratingFetcher(VORONEZH_TWO_FORMS_HTML, [_ok(RESULT_HTML_LIST_PAGE)])
    result = search_case(
        fetcher, "https://sovetsky--vrn.sudrf.ru/", 1540005,
        CaseQuery(case_number="2-10/2026"),
        captcha_solver=None,
    )
    assert result.status == "found"
    assert result.cases[0].case_number == "2-10/2026"
    assert "Судья" in result.as_text() or "Иванов" in result.as_text()


def test_search_case_voronezh_not_found_wording():
    html = "<html><body><p>Данных по запросу не обнаружено.</p><p>Уточните критерии поиска.</p></body></html>"
    fetcher = FakeFetcher(VORONEZH_TWO_FORMS_HTML, [_ok(html)])
    result = search_case(
        fetcher, "https://sovetsky--vrn.sudrf.ru/", 1540005,
        CaseQuery(case_number="2-99999/2099"),
        captcha_solver=None,
    )
    assert result.status == "not_found"


def test_search_case_direct_found_and_hydrates():
    class DirectFetcher(FakeFetcher):
        def request(self, method, url, params=None, data=None, **kwargs):
            assert params["g1_case__CASE_NUMBERSS"] == "2-10/2026"
            return _ok(RESULT_HTML_LIST_PAGE)

        def get(self, url, respect_robots=True):
            assert respect_robots is False
            return _ok(RESULT_HTML_FOUND)

    result = search_case_direct(
        DirectFetcher("", []),
        "sovetsky--vrn.sudrf.ru",
        CaseQuery(case_number="2-10/2026"),
    )
    assert result.status == "found"
    assert "2-10/2026" in result.as_text()
    assert "Иванов" in result.as_text() or "Судья" in result.as_text()


def test_search_case_direct_not_found():
    html = "<html><body><p>Данных по запросу не обнаружено.</p></body></html>"

    class DirectFetcher(FakeFetcher):
        def request(self, method, url, params=None, data=None, **kwargs):
            return _ok(html)

    result = search_case_direct(
        DirectFetcher("", []),
        "sovetsky--vrn.sudrf.ru",
        CaseQuery(case_number="2-99999/2099"),
    )
    assert result.status == "not_found"

