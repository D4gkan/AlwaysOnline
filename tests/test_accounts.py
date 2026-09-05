import pytest

from app.accounts.models import Account, AccountValidationError, validate_account_name, validate_url
from app.browser.manager import browser_chromium_launch_options


def test_validate_account_name_accepts_simple_names():
    assert validate_account_name("KnifeAccount") == "KnifeAccount"
    assert validate_account_name("acc_01-b") == "acc_01-b"


@pytest.mark.parametrize("bad", ["", "../etc", "a/b", "a\\b", "..", ".", "a" * 100, "bad name"])
def test_validate_account_name_rejects_unsafe_names(bad):
    with pytest.raises(AccountValidationError):
        validate_account_name(bad)


def test_validate_url_requires_scheme():
    with pytest.raises(AccountValidationError):
        validate_url("csfloat.com/stall/me")


def test_validate_url_requires_expected_host():
    with pytest.raises(AccountValidationError):
        validate_url("https://example.com/stall/me", required_host_suffix="csfloat.com")
    assert validate_url("https://csfloat.com/stall/me", required_host_suffix="csfloat.com")


def test_account_new_defaults_urls():
    account = Account.new("acc1")
    assert account.csfloat_url.startswith("https://csfloat.com")
    assert account.csgoempire_url.startswith("https://csgoempire.com/deposit")
    assert account.enabled is True


def test_browser_uses_sandboxed_chromium_by_default():
    options = browser_chromium_launch_options()
    assert options.get("chromium_sandbox") is True


def test_account_round_trips_through_dict():
    account = Account.new("acc2")
    restored = Account.from_dict(account.to_dict())
    assert restored.name == account.name
    assert restored.csfloat_url == account.csfloat_url
    assert restored.csgoempire_url == account.csgoempire_url
    assert "proxy" not in account.to_dict()


def test_account_new_rejects_proxy_argument():
    with pytest.raises(TypeError):
        Account.new("acc3", proxy="10.0.0.1:8080:user:pass")


def test_browser_only_accounts_do_not_store_proxy_data():
    account = Account.new("acc4")
    payload = account.to_dict()

    assert "proxy" not in payload
    assert payload["csfloat_url"].startswith("https://csfloat.com")
    assert payload["csgoempire_url"].startswith("https://csgoempire.com")
