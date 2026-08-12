import pyotp

ISSUER_NAME = "OpenRBI"


def generate_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(secret: str, username: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name=ISSUER_NAME)


def verify_code(secret: str, code: str) -> bool:
    """valid_window=1 tolerates one 30s step of clock drift either side —
    intentionally narrow, not a permissive fallback (RFC 6238 default is 0).
    """
    if not code:
        return False
    return pyotp.TOTP(secret).verify(code, valid_window=1)
