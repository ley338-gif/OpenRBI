import base64

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


def _fernet() -> Fernet:
    """Derives a Fernet key from OPENRBI_TOTP_SECRET_ENCRYPTION_KEY (a
    64-char hex string, e.g. from `openssl rand -hex 32`). Fails closed: an
    unconfigured key raises rather than silently storing secrets in plaintext
    (see docs/adr/0002-totp-mfa.md).
    """
    settings = get_settings()
    if not settings.totp_secret_encryption_key:
        raise RuntimeError("OPENRBI_TOTP_SECRET_ENCRYPTION_KEY is not configured")
    raw = bytes.fromhex(settings.totp_secret_encryption_key)
    if len(raw) != 32:
        raise RuntimeError("OPENRBI_TOTP_SECRET_ENCRYPTION_KEY must decode to exactly 32 bytes")
    return Fernet(base64.urlsafe_b64encode(raw))


def encrypt_secret(plaintext: str) -> bytes:
    return _fernet().encrypt(plaintext.encode("utf-8"))


def decrypt_secret(ciphertext: bytes) -> str:
    try:
        return _fernet().decrypt(ciphertext).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("could not decrypt stored secret") from exc
