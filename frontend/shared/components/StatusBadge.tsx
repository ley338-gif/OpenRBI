// Status is always conveyed by the label text, not color alone (section
// 6/43) — the badge classes add color as a supporting signal only.

// "No threat detected" is deliberately neutral, not green: a scan finding
// nothing is not a statement that a file is safe (shared/fileStatus.ts).
const HEALTHY = new Set(["ACTIVE", "READY", "CONNECTED", "HEALTHY", "ONLINE", "RELEASED", "RESOLVED", "PUBLISHED", "SUCCESS"]);
const CRITICAL = new Set([
  "FAILED",
  "UNAVAILABLE",
  "ISOLATED",
  "ISOLATING",
  "QUARANTINED",
  "INFECTED",
  "THREAT DETECTED",
  "CRITICAL",
  "REJECTED",
  "OFFLINE",
  "LOCKED",
  "BLOCKED",
  "DENIED",
  "REVOKED",
]);
const WARNING = new Set([
  "DEGRADED",
  "NOT_CONFIGURED",
  "TERMINATING",
  "SCANNING",
  "PENDING_SCAN",
  "HIGH",
  "MEDIUM",
  "DRAINING",
  "MAINTENANCE",
  "INVESTIGATING",
  "SCAN FAILED",
  "WAITING",
  "WARNING",
  "NOT ENFORCED",
]);
const INFO = new Set(["QUEUED", "STARTING", "NEW", "PENDING", "SCAN PENDING", "DRAFT"]);

function variantFor(value: string): string {
  const v = value.toUpperCase();
  if (HEALTHY.has(v)) return "badge-healthy";
  if (CRITICAL.has(v)) return "badge-critical";
  if (WARNING.has(v)) return "badge-warning";
  if (INFO.has(v)) return "badge-info";
  return "badge-neutral";
}

export function StatusBadge({ value }: { value: string }) {
  return <span className={`badge ${variantFor(value)}`}>{value.replace(/_/g, " ")}</span>;
}
