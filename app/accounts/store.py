"""Local file-backed account storage.

One JSON file per account under `accounts/<name>.json`. No secrets are
ever stored here -- see models.Account for what fields exist.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Iterable, Optional

from app.config import ACCOUNTS_DIR, PROFILES_DIR
from app.accounts.models import Account, AccountValidationError, Site, validate_account_name


class AccountNotFoundError(KeyError):
    pass


class AccountAlreadyExistsError(ValueError):
    pass


def _account_path(name: str) -> Path:
    name = validate_account_name(name)
    path = (ACCOUNTS_DIR / f"{name}.json").resolve()
    # Defense in depth against path traversal even though the name is
    # already restricted to a safe character set.
    if ACCOUNTS_DIR.resolve() not in path.parents:
        raise AccountValidationError("Resolved account path escapes accounts directory.")
    return path


def _atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.remove(tmp_name)


def exists(name: str) -> bool:
    try:
        return _account_path(name).exists()
    except AccountValidationError:
        return False


def save(account: Account) -> None:
    _atomic_write_json(_account_path(account.name), account.to_dict())


def load(name: str) -> Account:
    path = _account_path(name)
    if not path.exists():
        raise AccountNotFoundError(name)
    with open(path) as f:
        return Account.from_dict(json.load(f))


def create(
    name: str,
    csfloat_url: Optional[str] = None,
    csgoempire_url: Optional[str] = None,
) -> Account:
    if exists(name):
        raise AccountAlreadyExistsError(f"Account {name!r} already exists.")
    account = Account.new(name, csfloat_url, csgoempire_url)
    save(account)
    return account


def list_names() -> list[str]:
    if not ACCOUNTS_DIR.exists():
        return []
    return sorted(p.stem for p in ACCOUNTS_DIR.glob("*.json"))


def list_all() -> list[Account]:
    return [load(n) for n in list_names()]


def delete(name: str, *, remove_browser_profiles: bool = True) -> None:
    path = _account_path(name)
    if not path.exists():
        raise AccountNotFoundError(name)
    path.unlink()
    if remove_browser_profiles:
        account = Account.new(name)
        for site in (Site.CSFLOAT, Site.CSGOEMPIRE):
            profile_dir = account.profile_dir(site)
            try:
                if profile_dir.exists():
                    shutil.rmtree(profile_dir, ignore_errors=True)
            except Exception:
                pass

        fallback_root = (PROFILES_DIR / validate_account_name(name)).resolve()
        if PROFILES_DIR.resolve() in fallback_root.parents and fallback_root.exists():
            shutil.rmtree(fallback_root, ignore_errors=True)
