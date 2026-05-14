from __future__ import annotations

from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken


class CredentialMasterKeyError(RuntimeError):
    """Raised when the credential master key is missing or malformed."""


class CredentialDecryptionError(RuntimeError):
    """Raised when encrypted credential material cannot be authenticated."""


@dataclass(frozen=True)
class MasterKey:
    key_id: str
    fernet: Fernet


@dataclass(frozen=True)
class SecretValue:
    _value: str

    def reveal(self) -> str:
        return self._value

    def __str__(self) -> str:
        return "<redacted>"

    def __repr__(self) -> str:
        return "<redacted>"


def load_master_key(value: str | None, *, key_id: str = "v1") -> MasterKey:
    if value is None or value.strip() == "":
        raise CredentialMasterKeyError("missing credential master key")
    try:
        return MasterKey(key_id=key_id, fernet=Fernet(value.strip().encode("ascii")))
    except (ValueError, TypeError) as error:
        raise CredentialMasterKeyError("invalid credential master key") from error


def encrypt_secret(plaintext: str, master_key: MasterKey) -> bytes:
    return master_key.fernet.encrypt(plaintext.encode("utf-8"))


def decrypt_secret(ciphertext: bytes, master_key: MasterKey) -> SecretValue:
    try:
        plaintext = master_key.fernet.decrypt(ciphertext).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError) as error:
        raise CredentialDecryptionError("credential_decryption_failed") from error
    return SecretValue(plaintext)
