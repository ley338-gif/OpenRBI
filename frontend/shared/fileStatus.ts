// User-facing wording for file states. OpenRBI never claims a file is safe:
// labels describe only what was actually verified or done (README "Security",
// docs/quarantine.md#no-safe-claims) — "No threat detected", never "clean",
// "safe" or "approved".

const FILE_STATUS_LABELS: Record<string, string> = {
  PENDING_SCAN: "Scanning",
  SCANNING: "Scanning",
  QUARANTINED: "Quarantined",
  RELEASED: "Released",
  REJECTED: "Blocked",
  DELETED: "Deleted",
};

const SCAN_RESULT_LABELS: Record<string, string> = {
  PENDING: "Scan pending",
  SCANNING: "Scanning",
  CLEAN: "No threat detected",
  INFECTED: "Threat detected",
  ERROR: "Scan failed",
};

/** QuarantineFile.status → label (Downloads, Quarantine review). */
export function fileStatusLabel(status: string): string {
  return FILE_STATUS_LABELS[status] ?? status;
}

/** QuarantineFile.scanner_status → label. */
export function scanResultLabel(scannerStatus: string): string {
  return SCAN_RESULT_LABELS[scannerStatus] ?? scannerStatus;
}
