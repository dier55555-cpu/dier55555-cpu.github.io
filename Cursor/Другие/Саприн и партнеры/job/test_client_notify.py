"""Тексты и телефоны уведомлений клиенту (без сети)."""

from unittest.mock import patch

from client_notify import (
    format_client_message,
    green_chat_id,
    green_send_url,
    mask_phone,
    normalize_phone,
    notify_stage_move,
    phones_from_bitrix_phone_field,
    phones_from_text,
    resolve_client_phone,
)
from triggers import STAGE_DECISION, STAGE_HEARING


def test_normalize_phone_ru():
    assert normalize_phone("+7 (906) 586-18-61") == "79065861861"
    assert normalize_phone("89065861861") == "79065861861"
    assert normalize_phone("9065861861") == "79065861861"
    assert normalize_phone("1") is None


def test_phone_from_title_and_contact():
    assert phones_from_text("Иванов, +79061234567") == ["79061234567"]
    from_crm = phones_from_bitrix_phone_field([
        {"VALUE": "+79061234567", "VALUE_TYPE": "WORK"},
    ])
    assert from_crm == ["79061234567"]
    assert resolve_client_phone(title="без номера", contact_phones=from_crm) == "79061234567"
    assert resolve_client_phone(title="Петров 89201112233", contact_phones=[]) == "79201112233"


def test_decision_message_contains_case_url_lawyer():
    text = format_client_message(
        to_stage=STAGE_DECISION,
        case_number="2-1882/2026",
        case_url="https://kominternovsky--vrn.sudrf.ru/modules.php?name=sud_delo",
        lawyer_phone="79204044433",
    )
    assert "2-1882/2026" in text
    assert "судом вынесено решение" in text
    assert "https://kominternovsky--vrn.sudrf.ru/" in text
    assert "79204044433" in text
    assert "позвонить юристу" in text


def test_other_stage_uses_title():
    text = format_client_message(
        to_stage=STAGE_HEARING,
        case_number="2-1/2026",
        case_url="https://example.sudrf.ru/",
        lawyer_phone=None,
    )
    assert "Назначена дата заседания" in text


def test_green_urls():
    assert green_chat_id("79001112233") == "79001112233@c.us"
    url = green_send_url("https://api.green-api.com", "1100", "tok")
    assert url.endswith("/waInstance1100/sendMessage/tok")


def test_mask_phone():
    assert mask_phone("79065861861").startswith("7906")
    assert "861" not in mask_phone("79065861861") or "***" in mask_phone("79065861861")


def test_notify_disabled_by_default():
    res = notify_stage_move(
        call=lambda *_: {},
        deal_id=1,
        title="x",
        case_number="2-1/2026",
        to_stage=STAGE_DECISION,
        contact_id=1,
        assigned_by_id=1,
        case_url="https://a.sudrf.ru/",
        dry_run=False,
    )
    assert res.sent is False
    assert res.skipped == "disabled"


def test_notify_dry_run_no_http(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIENT_NOTIFY", "1")
    monkeypatch.setenv("CLIENT_NOTIFY_STAGES", STAGE_DECISION)
    monkeypatch.setattr("client_notify.NOTIFY_PATH", str(tmp_path / "sent.json"))

    def call(method, params):
        if method == "crm.contact.get":
            return {"result": {"PHONE": [{"VALUE": "+79061234567"}]}}
        if method == "user.get":
            return {"result": [{"PERSONAL_MOBILE": "+79204044433"}]}
        raise AssertionError(method)

    with patch("client_notify.requests.post") as post:
        res = notify_stage_move(
            call=call,
            deal_id=1276,
            title="test",
            case_number="2-1882/2026",
            to_stage=STAGE_DECISION,
            contact_id=10,
            assigned_by_id=1,
            case_url="https://a.sudrf.ru/card",
            dry_run=True,
        )
        post.assert_not_called()
    assert res.skipped == "dry_run"
    assert res.phone == "79061234567"
    assert "вынесено решение" in res.text
    assert "2-1882/2026" in res.text
