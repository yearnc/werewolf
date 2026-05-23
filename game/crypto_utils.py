"""Simple encryption for API keys in .env files.

Uses XOR + base64 — prevents casual reading of plaintext keys.
Not cryptographically secure against a determined attacker with source access.
"""

import base64
import hashlib

_SEED = "werewolf-game-key-2024"


def _derive_key() -> bytes:
    return hashlib.sha256(_SEED.encode()).digest()


def encrypt(plaintext: str) -> str:
    """Encrypt a plaintext string, returning a base64-encoded ciphertext."""
    key = _derive_key()
    data = plaintext.encode()
    encrypted = bytes([data[i] ^ key[i % len(key)] for i in range(len(data))])
    return base64.urlsafe_b64encode(encrypted).decode()


def decrypt(ciphertext: str) -> str:
    """Decrypt a base64-encoded ciphertext back to plaintext."""
    key = _derive_key()
    encrypted = base64.urlsafe_b64decode(ciphertext.encode())
    decrypted = bytes([encrypted[i] ^ key[i % len(key)] for i in range(len(encrypted))])
    return decrypted.decode()


def encrypt_env_value(plaintext: str) -> str:
    """Wrap encrypted value with ENC: prefix for .env readability."""
    return f"ENC:{encrypt(plaintext)}"


def decrypt_env_value(value: str) -> str:
    """Decrypt a value that may or may not have the ENC: prefix."""
    if value.startswith("ENC:"):
        return decrypt(value[4:])
    return value  # Plaintext fallback for backward compatibility


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python crypto_utils.py <encrypt|decrypt> <text>")
        print("  encrypt  — encrypt text and print ENC:... value for .env")
        print("  decrypt  — decrypt an ENC:... value")
        sys.exit(1)

    cmd = sys.argv[1]
    text = sys.argv[2] if len(sys.argv) > 2 else ""

    if cmd == "encrypt":
        print(encrypt_env_value(text))
    elif cmd == "decrypt":
        print(decrypt_env_value(text))
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
