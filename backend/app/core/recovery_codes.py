import secrets

_GROUP_LEN = 5
_GROUPS = 3


def generate_recovery_codes(count: int = 10) -> list[str]:
    """Human-typeable, high-entropy codes (~25 alphanumeric chars each,
    well beyond brute-force range) shown to the user exactly once.
    """
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I ambiguity
    codes = []
    for _ in range(count):
        raw = "".join(secrets.choice(alphabet) for _ in range(_GROUP_LEN * _GROUPS))
        groups = [raw[i : i + _GROUP_LEN] for i in range(0, len(raw), _GROUP_LEN)]
        codes.append("-".join(groups))
    return codes
