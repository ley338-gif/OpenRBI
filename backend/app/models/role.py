from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import CreatedAtMixin, UUIDPKMixin


class Role(UUIDPKMixin, CreatedAtMixin, Base):
    """One of the MVP roles (USER, SECURITY_REVIEWER, ADMIN), seeded by
    migration. Roles grant product capabilities; they are deliberately
    separate from Groups, which drive security policy (see docs/policies.md).
    """

    __tablename__ = "roles"

    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))
