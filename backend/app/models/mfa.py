import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import CreatedAtMixin, UUIDPKMixin


class RecoveryCode(UUIDPKMixin, CreatedAtMixin, Base):
    """MFA recovery codes. Only the hash is ever stored; the plaintext code
    is shown to the user exactly once at generation time and is not
    recoverable afterwards. `used_at` being set makes the code permanently
    invalid (see docs/adr/0002-totp-mfa.md).
    """

    __tablename__ = "recovery_codes"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    code_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column()
