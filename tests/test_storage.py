import stat

import pytest

from lumen.storage import Vault, VaultLocked


def test_encryption_persistence_permissions_and_wrong_password(tmp_path):
    vault = Vault(tmp_path / "private")
    assert not vault.initialized
    with pytest.raises(ValueError, match="12 characters"):
        vault.unlock("short")
    vault.unlock("a long test passphrase")
    item = {"id": "random-id", "title": "secret-title", "body": "very private information"}
    vault.put("note", item)
    assert vault.get("note", item["id"]) == item
    assert vault.all("note") == [item]
    raw = vault.path.read_bytes()
    assert b"secret-title" not in raw
    assert b"very private information" not in raw
    assert stat.S_IMODE(vault.path.stat().st_mode) == 0o600
    assert stat.S_IMODE(vault.path.parent.stat().st_mode) == 0o700
    vault.lock()
    with pytest.raises(VaultLocked):
        vault.all("note")
    with pytest.raises(ValueError, match="Incorrect"):
        vault.unlock("the wrong passphrase")
    vault.close()
    restored = Vault(tmp_path / "private")
    restored.unlock("a long test passphrase")
    assert restored.get("note", item["id"]) == item
    restored.delete("note", item["id"])
    assert restored.get("note", item["id"]) is None
    restored.close()


def test_conditional_update_never_inserts_or_overwrites_newer_revision(tmp_path):
    vault = Vault(tmp_path / "private")
    vault.unlock("a long test passphrase")
    original = {"id": "research-id", "updated_at": "first", "body": "Original evidence"}
    updated = {**original, "updated_at": "second", "body": "Reviewed evidence"}
    try:
        assert not vault.update_if_revision("research", updated, "first")
        vault.put("research", original)
        assert not vault.update_if_revision("research", updated, "wrong")
        assert vault.get("research", original["id"]) == original
        assert vault.update_if_revision("research", updated, "first")
        assert not vault.update_if_revision("research", original, "first")
        assert vault.get("research", original["id"]) == updated
        assert updated["body"].encode() not in vault.path.read_bytes()
        vault.delete("research", original["id"])
        assert not vault.update_if_revision("research", updated, "second")
        assert vault.get("research", original["id"]) is None
        vault.lock()
        with pytest.raises(VaultLocked):
            vault.update_if_revision("research", updated, "second")
    finally:
        vault.close()
