from scraper.case_lookup.captcha import CaptchaSolver
from scraper.case_lookup.search import CaseQuery, search_case
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

    def get(self, url):
        return FetchResult(url, ok=True, blocked=False, status_code=200, html=self.form_html)

    def get_bytes(self, url):
        return b"fake-captcha-bytes"

    def post(self, url, data):
        self.submitted_params.append(data)
        return self.submit_responses.pop(0)

    def request(self, method, url, params=None, data=None):
        self.submitted_params.append(params)
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
