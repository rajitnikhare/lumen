import json
import secrets
import sqlite3
import threading
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt


class VaultLocked(Exception):
    pass


class Vault:
    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700)
        self.path = directory / "lumen.sqlite3"
        self._mutex = threading.RLock()
        self._key: bytes | None = None
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self.path.chmod(0o600)
        self._db.execute("PRAGMA journal_mode=DELETE")
        self._db.execute("PRAGMA secure_delete=ON")
        self._db.execute("CREATE TABLE IF NOT EXISTS meta (name TEXT PRIMARY KEY, value BLOB)")
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS records "
            "(id TEXT PRIMARY KEY, kind TEXT NOT NULL, value BLOB NOT NULL)"
        )
        self._db.commit()

    @property
    def initialized(self) -> bool:
        with self._mutex:
            return self._db.execute("SELECT 1 FROM meta WHERE name='salt'").fetchone() is not None

    @property
    def unlocked(self) -> bool:
        with self._mutex:
            return self._key is not None

    def unlock(self, passphrase: str) -> None:
        with self._mutex:
            salt_row = self._db.execute("SELECT value FROM meta WHERE name='salt'").fetchone()
            if not salt_row and len(passphrase) < 12:
                raise ValueError("Choose a passphrase of at least 12 characters.")
            salt = salt_row[0] if salt_row else secrets.token_bytes(16)
            key = Scrypt(salt=salt, length=32, n=2**17, r=8, p=1).derive(passphrase.encode())
            cipher = AESGCM(key)
            if salt_row:
                raw = self._db.execute("SELECT value FROM meta WHERE name='check'").fetchone()[0]
                try:
                    cipher.decrypt(raw[:12], raw[12:], b"lumen-v1")
                except InvalidTag as exc:
                    raise ValueError("Incorrect vault passphrase.") from exc
            else:
                nonce = secrets.token_bytes(12)
                check = nonce + cipher.encrypt(nonce, b"lumen", b"lumen-v1")
                with self._db:
                    self._db.execute("INSERT INTO meta VALUES ('salt', ?)", (salt,))
                    self._db.execute("INSERT INTO meta VALUES ('check', ?)", (check,))
            self._key = key

    def lock(self) -> None:
        with self._mutex:
            self._key = None

    def _cipher(self) -> AESGCM:
        if self._key is None:
            raise VaultLocked("Unlock the vault first.")
        return AESGCM(self._key)

    def put(self, kind: str, record: dict) -> dict:
        identifier = record["id"]
        with self._mutex, self._db:
            nonce = secrets.token_bytes(12)
            aad = f"{kind}:{identifier}".encode()
            raw = nonce + self._cipher().encrypt(nonce, json.dumps(record).encode(), aad)
            self._db.execute(
                "INSERT OR REPLACE INTO records VALUES (?, ?, ?)", (identifier, kind, raw)
            )
        return record

    def get(self, kind: str, identifier: str) -> dict | None:
        with self._mutex:
            self._cipher()
            row = self._db.execute(
                "SELECT value FROM records WHERE id=? AND kind=?", (identifier, kind)
            ).fetchone()
            return self._decode(kind, identifier, row[0]) if row else None

    def update_if_revision(self, kind: str, record: dict, revision: str) -> bool:
        identifier = record["id"]
        with self._mutex, self._db:
            self._cipher()
            row = self._db.execute(
                "SELECT value FROM records WHERE id=? AND kind=?", (identifier, kind)
            ).fetchone()
            if row is None:
                return False
            current = self._decode(kind, identifier, row[0])
            if current["updated_at"] != revision:
                return False
            nonce = secrets.token_bytes(12)
            aad = f"{kind}:{identifier}".encode()
            raw = nonce + self._cipher().encrypt(nonce, json.dumps(record).encode(), aad)
            # Compare ciphertext too, so another connection cannot overwrite a newer revision.
            result = self._db.execute(
                "UPDATE records SET value=? WHERE id=? AND kind=? AND value=?",
                (raw, identifier, kind, row[0]),
            )
            return result.rowcount == 1

    def _decode(self, kind: str, identifier: str, raw: bytes) -> dict:
        return json.loads(
            self._cipher().decrypt(raw[:12], raw[12:], f"{kind}:{identifier}".encode())
        )

    def all(self, kind: str) -> list[dict]:
        with self._mutex:
            self._cipher()
            rows = self._db.execute(
                "SELECT id, value FROM records WHERE kind=?", (kind,)
            ).fetchall()
            return [self._decode(kind, identifier, raw) for identifier, raw in rows]

    def delete(self, kind: str, identifier: str) -> None:
        with self._mutex, self._db:
            self._cipher()
            self._db.execute("DELETE FROM records WHERE kind=? AND id=?", (kind, identifier))

    def close(self) -> None:
        with self._mutex:
            self._key = None
            self._db.close()
