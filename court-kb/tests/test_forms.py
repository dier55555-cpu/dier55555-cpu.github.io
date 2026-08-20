from scraper.case_lookup.forms import parse_search_form

FORM_HTML_NO_CAPTCHA = """
<html><body>
<form name="courtdel" method="get" action="modules.php">
<input type="hidden" name="name" value="sud_delo">
<input type="hidden" name="name_op" value="r">
<input type="hidden" name="delo_id" value="1540005">
<table>
<tr><td>Фамилия</td><td><input type="text" name="EX_S"></td></tr>
<tr><td>Номер дела (материала)</td><td><input type="text" name="EX_NUM"></td></tr>
<tr><td>Уникальный идентификатор дела</td><td><input type="text" name="EX_UID"></td></tr>
</table>
<input type="submit" value="Найти">
</form>
</body></html>
"""

FORM_HTML_WITH_CAPTCHA = """
<html><body>
<form name="courtdel" method="get" action="modules.php">
<input type="hidden" name="name" value="sud_delo">
<input type="hidden" name="delo_id" value="1540006">
<table>
<tr><td>Фамилия</td><td><input type="text" name="EX_S"></td></tr>
<tr>
  <td>Проверочный код</td>
  <td><input type="text" name="captcha_code"><img src="captcha.php?id=42"></td>
</tr>
</table>
</form>
</body></html>
"""


def test_parses_visible_fields_and_maps_known_labels():
    form = parse_search_form(FORM_HTML_NO_CAPTCHA, "https://example--vrn.sudrf.ru/modules.php")

    assert form.method == "GET"
    assert form.action_url == "https://example--vrn.sudrf.ru/modules.php"

    assert form.field_by_key("last_name").name == "EX_S"
    assert form.field_by_key("case_number").name == "EX_NUM"
    assert form.field_by_key("case_uid").name == "EX_UID"
    assert form.captcha is None
    assert form.unmapped_fields() == []


def test_detects_captcha_image_and_field():
    form = parse_search_form(FORM_HTML_WITH_CAPTCHA, "https://example--vrn.sudrf.ru/modules.php")

    assert form.captcha is not None
    assert form.captcha.field_name == "captcha_code"
    assert form.captcha.image_url == "https://example--vrn.sudrf.ru/captcha.php?id=42"


def test_hidden_fields_are_not_reported_as_unmapped():
    form = parse_search_form(FORM_HTML_NO_CAPTCHA, "https://example--vrn.sudrf.ru/modules.php")
    hidden_names = {f.name for f in form.fields if f.input_type == "hidden"}
    assert hidden_names == {"name", "name_op", "delo_id"}
    assert all(f.mapped_key is None for f in form.fields if f.input_type == "hidden")


TWO_FORMS_HTML = """
<html><body>
<form method="get" action="/modules.php">
<input type="hidden" name="name" value="sud_delo">
<input type="hidden" name="srv_num" value="1">
<tr><td>Вывести список дел, назначенных на дату</td>
<td><input type="text" name="H_date" value="20.08.2026"></td></tr>
</form>
<form method="get" action="">
<input type="hidden" name="name" value="sud_delo">
<input type="hidden" name="name_op" value="r">
<input type="hidden" name="delo_id" value="1540005">
<input type="hidden" name="delo_table" value="g1_case">
<table>
<tr><td>Фамилия</td><td><input type="text" name="G1_PARTS__NAMESS"></td></tr>
<tr><td>Номер дела (материала)</td><td><input type="text" name="g1_case__CASE_NUMBERSS"></td></tr>
<tr><td>Уникальный идентификатор дела</td><td><input type="text" name="g1_case__JUDICIAL_UIDSS"></td></tr>
</table>
</form>
</body></html>
"""


def test_picks_search_form_not_hearing_date_form():
    page = "https://sovetsky--vrn.sudrf.ru/modules.php?name=sud_delo&name_op=sf&delo_id=1540005&srv_num=1"
    form = parse_search_form(TWO_FORMS_HTML, page)
    assert form.field_by_key("last_name").name == "G1_PARTS__NAMESS"
    assert form.field_by_key("case_number").name == "g1_case__CASE_NUMBERSS"
    assert form.field_by_key("case_uid").name == "g1_case__JUDICIAL_UIDSS"
    assert form.action_url == "https://sovetsky--vrn.sudrf.ru/modules.php"
    assert form.captcha is None


def test_maps_gas_field_names_without_labels():
    html = """
    <html><body><form method="get" action="/modules.php">
    <input type="text" name="u1_case__CASE_NUMBERSS">
    <input type="text" name="U1_PARTS__NAMESS">
    </form></body></html>
    """
    form = parse_search_form(html, "https://example--vrn.sudrf.ru/modules.php")
    assert form.field_by_key("case_number").name == "u1_case__CASE_NUMBERSS"
    assert form.field_by_key("last_name").name == "U1_PARTS__NAMESS"
