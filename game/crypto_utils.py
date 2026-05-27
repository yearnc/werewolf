"""Encryption for API keys in .env files.

Uses AES-256-GCM authenticated encryption with PBKDF2 key derivation.
The master key is read from a key file, environment variable, or
derived from machine-specific identifiers as a fallback.

Key file priority:
  1. $WEREWOLF_KEY_FILE  →  read secret from this file
  2. ~/.werewolf-key     →  user home directory
  3. game/.werewolf-key  →  project directory
  4. Machine ID fallback →  derived from hostname + MAC

Format:
  ENC2:<base64(salt[16] + nonce[12] + ciphertext + tag[16])>
  ENC:<base64(xor-encrypted)>  —  legacy format, still supported
  plaintext                     —  backward compatible
"""

import base64
import hashlib
import os
import secrets
import struct
from pathlib import Path

# ── AES-GCM via the cryptography library ──────────────
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# ── Constants ─────────────────────────────────────────

_SALT_LENGTH = 16
_NONCE_LENGTH = 12  # 96 bits — standard for GCM
_TAG_LENGTH = 16    # 128 bits — GCM auth tag
_PBKDF2_ITERATIONS = 600_000
_KEY_LENGTH = 32    # 256-bit AES key

_OLD_PREFIX = "ENC:"
_NEW_PREFIX = "ENC2:"

# Key file paths (tried in order)
_KEY_FILE_PATHS = [
    Path.home() / ".werewolf-key",
    Path(__file__).parent / ".werewolf-key",
]


def _get_machine_id() -> str:
    """Derive a machine-specific identifier string."""
    import platform
    import uuid

    parts = [
        platform.node() or "unknown-host",
        platform.machine() or "unknown-arch",
        str(uuid.getnode()),
        platform.system() or "unknown-os",
    ]
    return "|".join(parts)


def _load_master_secret() -> bytes:
    """Load the master secret.

    Priority:
      1. WEREWOLF_KEY_FILE env var → read file contents
      2. ~/.werewolf-key → read file contents
      3. game/.werewolf-key → read file contents
      4. Machine ID → derive secret (least portable, ok for single machine)
    """
    # 1. Explicit env var
    env_key_file = os.getenv("WEREWOLF_KEY_FILE", "").strip()
    if env_key_file:
        key_path = Path(env_key_file)
        if key_path.is_file():
            return key_path.read_bytes()

    # 2-3. Known file locations
    for path in _KEY_FILE_PATHS:
        if path.is_file():
            return path.read_bytes()

    # 4. Machine fallback
    return _get_machine_id().encode()


def _derive_key(salt: bytes, master_secret: bytes) -> bytes:
    """Derive a 256-bit encryption key from master secret + salt via PBKDF2."""
    return hashlib.pbkdf2_hmac(
        "sha256", master_secret, salt, _PBKDF2_ITERATIONS, dklen=_KEY_LENGTH
    )


# ── Public API ────────────────────────────────────────


def encrypt(plaintext: str) -> str:
    """Encrypt plaintext with AES-256-GCM.

    Returns a base64 string containing salt + nonce + ciphertext + tag.
    """
    master_secret = _load_master_secret()
    salt = secrets.token_bytes(_SALT_LENGTH)
    key = _derive_key(salt, master_secret)
    nonce = secrets.token_bytes(_NONCE_LENGTH)

    aesgcm = AESGCM(key)
    ciphertext_with_tag = aesgcm.encrypt(nonce, plaintext.encode(), None)

    # Pack: salt(16) + nonce(12) + ciphertext + tag(16)
    packed = salt + nonce + ciphertext_with_tag
    return base64.urlsafe_b64encode(packed).decode()


def decrypt(ciphertext: str) -> str:
    """Decrypt a base64-encoded AES-256-GCM ciphertext.

    Expected input format: base64(salt[16] + nonce[12] + ciphertext + tag[16])
    """
    master_secret = _load_master_secret()

    raw = base64.urlsafe_b64decode(ciphertext.encode())
    if len(raw) < _SALT_LENGTH + _NONCE_LENGTH + _TAG_LENGTH:
        raise ValueError(
            f"Ciphertext too short ({len(raw)} bytes), "
            f"expected at least {_SALT_LENGTH + _NONCE_LENGTH + _TAG_LENGTH}"
        )

    salt = raw[:_SALT_LENGTH]
    nonce = raw[_SALT_LENGTH:_SALT_LENGTH + _NONCE_LENGTH]
    encrypted = raw[_SALT_LENGTH + _NONCE_LENGTH:]

    key = _derive_key(salt, master_secret)
    aesgcm = AESGCM(key)
    plaintext = aesgcm.decrypt(nonce, encrypted, None)
    return plaintext.decode()


def encrypt_env_value(plaintext: str) -> str:
    """Wrap encrypted value with ENC2: prefix for .env readability."""
    return f"{_NEW_PREFIX}{encrypt(plaintext)}"


def decrypt_env_value(value: str) -> str:
    """Decrypt a value with ENC2:, ENC:, or no prefix.

    - ENC2:...  → AES-256-GCM (new format)
    - ENC:...   → legacy XOR format
    - plaintext → returned as-is
    """
    value = value.strip()
    if value.startswith(_NEW_PREFIX):
        return decrypt(value[len(_NEW_PREFIX):])
    if value.startswith(_OLD_PREFIX):
        return _decrypt_legacy(value[len(_OLD_PREFIX):])
    return value


# ── Legacy support ────────────────────────────────────


def _decrypt_legacy(ciphertext: str) -> str:
    """Decrypt old ENC: format (XOR + base64)."""
    key = hashlib.sha256(b"werewolf-game-key-2024").digest()
    encrypted = base64.urlsafe_b64decode(ciphertext.encode())
    decrypted = bytes(
        [encrypted[i] ^ key[i % len(key)] for i in range(len(encrypted))]
    )
    return decrypted.decode()


def re_encrypt_env_value(value: str) -> str:
    """Re-encrypt an existing value to the new format.

    Handles ENC2:, ENC:, and plaintext inputs.
    """
    plaintext = decrypt_env_value(value)
    return encrypt_env_value(plaintext)


# ── CLI ───────────────────────────────────────────────


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python crypto_utils.py <command> [text]")
        print()
        print("Commands:")
        print("  encrypt <text>     — encrypt text → ENC2:... for .env")
        print("  decrypt <text>     — decrypt ENC:... or ENC2:... value")
        print("  re-encrypt <text>  — upgrade old ENC: → new ENC2:")
        print("  keygen             — generate a random key file at ~/.werewolf-key")
        sys.exit(1)

    cmd = sys.argv[1]
    text = sys.argv[2] if len(sys.argv) > 2 else ""

    if cmd == "encrypt":
        print(encrypt_env_value(text))
    elif cmd == "decrypt":
        print(decrypt_env_value(text))
    elif cmd == "re-encrypt":
        print(re_encrypt_env_value(text))
    elif cmd == "keygen":
        key_path = Path.home() / ".werewolf-key"
        if key_path.exists():
            overwrite = input(f"{key_path} already exists. Overwrite? (y/n): ")
            if overwrite.strip().lower() not in ("y", "yes"):
                print("Aborted.")
                sys.exit(0)
        random_key = secrets.token_hex(32)
        key_path.write_text(random_key)
        key_path.chmod(0o600)
        print(f"Key file created: {key_path}")
        print("Keep this file secure — anyone with it can decrypt your API keys.")
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
