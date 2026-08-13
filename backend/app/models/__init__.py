"""Import every model so app.db.base.Base.metadata is complete for Alembic
autogenerate and for app startup. Do not import from app.models.<module>
directly elsewhere except via this package, to keep this the single place
that guarantees full metadata registration.
"""

from app.models.browser_node import BrowserNode
from app.models.browser_session import BrowserSession
from app.models.group import Group, UserGroup
from app.models.incident import Incident
from app.models.ldap_config import LdapConfig
from app.models.mfa import RecoveryCode
from app.models.policy import FilePolicyRule, GroupPolicy, Policy, PolicyVersion
from app.models.quarantine import QuarantineFile
from app.models.role import Role
from app.models.security_event import SecurityEvent
from app.models.system_state import SystemState
from app.models.user import User
from app.models.worker_metric_sample import WorkerMetricSample

__all__ = [
    "BrowserNode",
    "BrowserSession",
    "FilePolicyRule",
    "Group",
    "GroupPolicy",
    "Incident",
    "LdapConfig",
    "Policy",
    "PolicyVersion",
    "QuarantineFile",
    "RecoveryCode",
    "Role",
    "SecurityEvent",
    "SystemState",
    "User",
    "UserGroup",
    "WorkerMetricSample",
]
