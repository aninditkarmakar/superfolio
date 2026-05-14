from __future__ import annotations

import unittest
from cryptography.fernet import Fernet

from portfolio_engine.automation.credentials import (
    CredentialDecryptionError,
    CredentialMasterKeyError,
    SecretValue,
    decrypt_secret,
    encrypt_secret,
    load_master_key,
)


class SecretValueTests(unittest.TestCase):
    def test_secret_value_redacts_string_forms(self) -> None:
        secret = SecretValue("super-secret")

        self.assertEqual(str(secret), "<redacted>")
        self.assertEqual(repr(secret), "<redacted>")
        self.assertEqual(secret.reveal(), "super-secret")


class CredentialEncryptionTests(unittest.TestCase):
    def test_load_master_key_rejects_missing_value(self) -> None:
        with self.assertRaisesRegex(CredentialMasterKeyError, "missing"):
            load_master_key(None)

    def test_load_master_key_rejects_malformed_value(self) -> None:
        with self.assertRaisesRegex(CredentialMasterKeyError, "invalid"):
            load_master_key("not-a-fernet-key")

    def test_encrypt_decrypt_round_trip(self) -> None:
        key = load_master_key(Fernet.generate_key().decode("ascii"))

        ciphertext = encrypt_secret("ibkr-token", key)
        plaintext = decrypt_secret(ciphertext, key)

        self.assertNotIn(b"ibkr-token", ciphertext)
        self.assertEqual(plaintext.reveal(), "ibkr-token")

    def test_tampered_ciphertext_raises_sanitized_error(self) -> None:
        key = load_master_key(Fernet.generate_key().decode("ascii"))
        ciphertext = bytearray(encrypt_secret("ibkr-token", key))
        # XOR at -7 (within the base64-encoded HMAC, outside the padding region)
        # to guarantee the byte always changes and authentication fails.
        ciphertext[-7] ^= 0xFF

        with self.assertRaisesRegex(CredentialDecryptionError, "credential_decryption_failed"):
            decrypt_secret(bytes(ciphertext), key)


if __name__ == "__main__":
    unittest.main()
