import enum


class RoleName(str, enum.Enum):
    USER = "USER"
    SECURITY_REVIEWER = "SECURITY_REVIEWER"
    ADMIN = "ADMIN"


class PolicyType(str, enum.Enum):
    NETWORK = "NETWORK"
    DOWNLOADS = "DOWNLOADS"
    UPLOADS = "UPLOADS"
    CLIPBOARD = "CLIPBOARD"
    BROWSER = "BROWSER"
    SESSION = "SESSION"
    MIME = "MIME"
    SOURCE = "SOURCE"


class PolicyVersionStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class FileRuleType(str, enum.Enum):
    MIME = "MIME"
    SOURCE = "SOURCE"


class FileAction(str, enum.Enum):
    """Precedence when multiple rules match (see docs/policies.md conflict
    model): DENY > QUARANTINE > AUTO_RELEASE > default policy.
    """

    AUTO_RELEASE = "AUTO_RELEASE"
    QUARANTINE = "QUARANTINE"
    DENY = "DENY"


class BrowserNodeStatus(str, enum.Enum):
    ONLINE = "ONLINE"
    DRAINING = "DRAINING"
    OFFLINE = "OFFLINE"
    DEGRADED = "DEGRADED"
    # Roadmap B1.10.1 — admin-set, like DRAINING: unlike DRAINING (which
    # still counts toward "the scheduler could use this node once it's
    # done draining"), MAINTENANCE means "don't consider this node at all,
    # an admin took it out of service on purpose." See
    # app/services/worker_health.py for the full Healthy/Degraded/
    # Draining/Maintenance/Offline definitions this feeds into.
    MAINTENANCE = "MAINTENANCE"


class SessionStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    STARTING = "STARTING"
    ACTIVE = "ACTIVE"
    DISCONNECTED = "DISCONNECTED"
    ISOLATING = "ISOLATING"
    ISOLATED = "ISOLATED"
    TERMINATING = "TERMINATING"
    TERMINATED = "TERMINATED"
    FAILED = "FAILED"


class QuarantineStatus(str, enum.Enum):
    PENDING_SCAN = "PENDING_SCAN"
    SCANNING = "SCANNING"
    QUARANTINED = "QUARANTINED"
    RELEASED = "RELEASED"
    REJECTED = "REJECTED"
    DELETED = "DELETED"


class ScannerStatus(str, enum.Enum):
    PENDING = "PENDING"
    SCANNING = "SCANNING"
    CLEAN = "CLEAN"
    INFECTED = "INFECTED"
    ERROR = "ERROR"


class IncidentSeverity(str, enum.Enum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class IncidentStatus(str, enum.Enum):
    NEW = "NEW"
    INVESTIGATING = "INVESTIGATING"
    RESOLVED = "RESOLVED"
    FALSE_POSITIVE = "FALSE_POSITIVE"


class SecurityEventType(str, enum.Enum):
    USER_CREATED = "USER_CREATED"
    USER_DISABLED = "USER_DISABLED"
    USER_ENABLED = "USER_ENABLED"
    USER_LOGIN = "USER_LOGIN"
    USER_LOGIN_FAILED = "USER_LOGIN_FAILED"
    LOGIN_LOCKED = "LOGIN_LOCKED"
    MFA_ENROLLED = "MFA_ENROLLED"
    MFA_FAILED = "MFA_FAILED"
    MFA_RESET = "MFA_RESET"
    RECOVERY_CODE_USED = "RECOVERY_CODE_USED"
    SESSION_STARTED = "SESSION_STARTED"
    SESSION_DISCONNECTED = "SESSION_DISCONNECTED"
    SESSION_ISOLATED = "SESSION_ISOLATED"
    SESSION_RESTORED = "SESSION_RESTORED"
    SESSION_TERMINATED = "SESSION_TERMINATED"
    NETWORK_ACCESS_BLOCKED = "NETWORK_ACCESS_BLOCKED"
    DOWNLOAD_REQUESTED = "DOWNLOAD_REQUESTED"
    DOWNLOAD_BLOCKED = "DOWNLOAD_BLOCKED"
    FILE_QUARANTINED = "FILE_QUARANTINED"
    FILE_RELEASED = "FILE_RELEASED"
    FILE_REJECTED = "FILE_REJECTED"
    MALWARE_DETECTED = "MALWARE_DETECTED"
    POLICY_CHANGED = "POLICY_CHANGED"
    POLICY_PUBLISHED = "POLICY_PUBLISHED"
    NODE_DRAINED = "NODE_DRAINED"

    # Extensions beyond the project brief's minimum event list (§22 says "at
    # least" these) — admin user/group management is security-relevant and
    # must be auditable just like the enumerated events.
    USER_ROLE_CHANGED = "USER_ROLE_CHANGED"
    USER_GROUPS_CHANGED = "USER_GROUPS_CHANGED"
    PASSWORD_RESET_BY_ADMIN = "PASSWORD_RESET_BY_ADMIN"
    GROUP_CREATED = "GROUP_CREATED"
    GROUP_DELETED = "GROUP_DELETED"
    UPLOAD_REQUESTED = "UPLOAD_REQUESTED"
    UPLOAD_BLOCKED = "UPLOAD_BLOCKED"

    # Roadmap Phase B / B1.3 — a just-in-time-provisioned LDAP account is a
    # real account-creation event, distinct from an admin-issued
    # USER_CREATED (see backend/migrations/versions/b3d8f1a29c47_*).
    USER_PROVISIONED_VIA_LDAP = "USER_PROVISIONED_VIA_LDAP"

    # Roadmap Phase B / B1.8 — LDAP is now configurable through the admin
    # portal instead of only .env; these mirror POLICY_CHANGED/PUBLISHED's
    # separation of "content changed" from "the thing actually took
    # effect" for the same reason (a reviewer needs to see both, not infer
    # one from the other).
    LDAP_CONFIG_CHANGED = "LDAP_CONFIG_CHANGED"
    LDAP_ENABLED = "LDAP_ENABLED"
    LDAP_DISABLED = "LDAP_DISABLED"
    LDAP_CONNECTION_TESTED = "LDAP_CONNECTION_TESTED"

    # Roadmap Phase B / B1.9 — first-run bootstrap of the initial local
    # administrator. INITIAL_ADMIN_CREATED fires when the bootstrap admin
    # row is created (password set, MFA not yet enrolled); SYSTEM_INITIALIZED
    # fires once, when the mandatory MFA enrollment for that same account
    # completes and the installation becomes permanently closed to further
    # bootstrap attempts — mirrors POLICY_CHANGED vs. POLICY_PUBLISHED's
    # "content changed" vs. "the thing actually took effect" split.
    INITIAL_ADMIN_CREATED = "INITIAL_ADMIN_CREATED"
    SYSTEM_INITIALIZED = "SYSTEM_INITIALIZED"

    # Roadmap Phase B / B1.10 — worker/session operations. WORKER_DRAINED
    # was NODE_DRAINED before this (kept, still a valid historical value —
    # Postgres enums can't drop values); WORKER_DRAIN_DISABLED is the
    # previously-missing complement (undrain_node() never audited before).
    WORKER_DRAIN_ENABLED = "WORKER_DRAIN_ENABLED"
    WORKER_DRAIN_DISABLED = "WORKER_DRAIN_DISABLED"
    WORKER_MAINTENANCE_ENABLED = "WORKER_MAINTENANCE_ENABLED"
    WORKER_MAINTENANCE_DISABLED = "WORKER_MAINTENANCE_DISABLED"

    # Roadmap Phase B / B1.10.4 — bulk termination of every live session a
    # user has, from the User Detail page. Distinct from SESSION_TERMINATED
    # (still emitted once per session terminated this way, same as a single
    # Kill) so a reviewer can see both "this session ended" and "an admin
    # revoked this user's sessions as one action" without inferring one
    # from a run of several SESSION_TERMINATED events with the same actor.
    USER_SESSIONS_REVOKED = "USER_SESSIONS_REVOKED"

    # Roadmap Phase B / B1.10.5 — Account Lock/Unlock: an admin-triggered
    # equivalent of the automatic brute-force login lockout (same Redis
    # mechanism and window, see app/core/sessions.py's force_login_lock()),
    # not a second, DB-persisted "disabled" concept — that's USER_DISABLED,
    # unchanged and distinct.
    ACCOUNT_LOCKED = "ACCOUNT_LOCKED"
    ACCOUNT_UNLOCKED = "ACCOUNT_UNLOCKED"
