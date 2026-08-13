import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import FileAction, FileRuleType, PolicyType, PolicyVersionStatus
from app.models.mixins import CreatedAtMixin, TimestampMixin, UUIDPKMixin


class Policy(UUIDPKMixin, TimestampMixin, Base):
    """A named, versioned policy (see docs/policies.md). The concrete rules
    live on PolicyVersion; a Policy is just the stable identity groups
    attach to.
    """

    __tablename__ = "policies"

    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    policy_type: Mapped[PolicyType] = mapped_column(Enum(PolicyType, name="policy_type"), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1024))
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("policy_versions.id", use_alter=True, name="fk_policy_current_version")
    )


class PolicyVersion(UUIDPKMixin, CreatedAtMixin, Base):
    """A published PolicyVersion is immutable (see docs/policies.md) — an
    edit always creates a new version rather than mutating a published one.
    Every policy decision records which version id was used.
    """

    __tablename__ = "policy_versions"
    __table_args__ = (UniqueConstraint("policy_id", "version_number", name="uq_policy_version_number"),)

    policy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("policies.id"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[PolicyVersionStatus] = mapped_column(
        Enum(PolicyVersionStatus, name="policy_version_status"), nullable=False,
        default=PolicyVersionStatus.DRAFT,
    )
    content: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GroupPolicy(UUIDPKMixin, CreatedAtMixin, Base):
    """Attaches a Policy to a Group. The Policy's current published version
    is what applies; see docs/policies.md for the deterministic conflict
    model used when several of a user's groups disagree.
    """

    __tablename__ = "group_policies"
    __table_args__ = (UniqueConstraint("group_id", "policy_id", name="uq_group_policy"),)

    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("groups.id"), nullable=False, index=True
    )
    policy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("policies.id"), nullable=False, index=True
    )


class FilePolicyRule(UUIDPKMixin, CreatedAtMixin, Base):
    """A single MIME or source-matching rule belonging to a PolicyVersion of
    type MIME/SOURCE. `match_pattern` for SOURCE rules is a normalized host
    pattern (e.g. "*.microsoft.com"), matched structurally against the
    parsed hostname — never via substring containment (see docs/policies.md).
    """

    __tablename__ = "file_policy_rules"

    policy_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("policy_versions.id"), nullable=False, index=True
    )
    rule_type: Mapped[FileRuleType] = mapped_column(Enum(FileRuleType, name="file_rule_type"), nullable=False)
    match_pattern: Mapped[str] = mapped_column(String(512), nullable=False)
    action: Mapped[FileAction] = mapped_column(Enum(FileAction, name="file_action"), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
