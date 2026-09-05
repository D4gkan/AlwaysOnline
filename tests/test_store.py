import pytest

from app.accounts import store
from app.accounts.store import AccountAlreadyExistsError, AccountNotFoundError
from app.accounts.models import AccountValidationError, Site


@pytest.fixture(autouse=True)
def isolate_accounts_dir(tmp_path, monkeypatch):
    """Point account storage at a temp directory for every test."""
    accounts_dir = tmp_path / "accounts"
    profiles_dir = tmp_path / "browser_profiles"
    accounts_dir.mkdir()
    profiles_dir.mkdir()
    monkeypatch.setattr(store, "ACCOUNTS_DIR", accounts_dir)
    monkeypatch.setattr(store, "PROFILES_DIR", profiles_dir)
    yield


def test_create_and_load_round_trip():
    account = store.create("testacc")
    loaded = store.load("testacc")
    assert loaded.name == account.name
    assert loaded.csfloat_url == account.csfloat_url


def test_create_duplicate_raises():
    store.create("dupe")
    with pytest.raises(AccountAlreadyExistsError):
        store.create("dupe")


def test_load_missing_raises():
    with pytest.raises(AccountNotFoundError):
        store.load("does-not-exist")


def test_list_names_and_all():
    store.create("a1")
    store.create("a2")
    names = store.list_names()
    assert names == ["a1", "a2"]
    accounts = store.list_all()
    assert {a.name for a in accounts} == {"a1", "a2"}


def test_delete_removes_record_and_profiles():
    store.create("todelete")
    # Build the profile path against the same (monkeypatched) PROFILES_DIR
    # that store.delete() uses, since Account.profile_dir() reads the
    # real app.config.PROFILES_DIR directly rather than store's copy.
    prof_path = store.PROFILES_DIR / "todelete" / Site.CSFLOAT.value
    prof_path.mkdir(parents=True, exist_ok=True)
    (prof_path / "marker.txt").write_text("x")

    store.delete("todelete")

    with pytest.raises(AccountNotFoundError):
        store.load("todelete")
    assert not prof_path.exists()


def test_path_traversal_rejected():
    with pytest.raises(AccountValidationError):
        store.create("../evil")
