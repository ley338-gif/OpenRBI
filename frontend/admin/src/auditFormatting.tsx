import type { ReactNode } from "react";
import { Icons } from "@shared/components/Icons";
import type { SecurityEventDto } from "@shared/api/types";

export type AuditCategory = "Authentication" | "User management" | "Sessions" | "Policies" | "Security" | "Quarantine" | "System" | "Administration";
export type AuditOutcome = "Success" | "Failed" | "Warning" | "Denied";

const CATEGORY_RULES: Array<[AuditCategory, RegExp]> = [
  ["Authentication", /(LOGIN|MFA|PASSWORD|RECOVERY|ACCOUNT_LOCK)/],
  ["User management", /^(USER_|GROUP_)/],
  ["Sessions", /SESSION_/],
  ["Policies", /POLICY_/],
  ["Quarantine", /(QUARANTINE|FILE_RELEASED|FILE_REJECTED|MALWARE)/],
  ["Security", /(BLOCKED|MALWARE|SECURITY)/],
  ["System", /(WORKER|NODE|SYSTEM_)/],
  ["Administration", /^(LDAP_|INITIAL_ADMIN)/],
];

export const AUDIT_CATEGORIES: AuditCategory[] = ["Authentication", "User management", "Sessions", "Policies", "Security", "Quarantine", "System", "Administration"];
export const AUDIT_OUTCOMES: AuditOutcome[] = ["Success", "Failed", "Warning", "Denied"];

export function eventLabel(value: string) {
  const text = value.replaceAll("_", " ").toLowerCase();
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function eventCategory(value: string): AuditCategory {
  return CATEGORY_RULES.find(([, pattern]) => pattern.test(value))?.[0] ?? "Security";
}

export function eventOutcome(value: string): AuditOutcome {
  if (/(LOGIN_FAILED|MFA_FAILED)/.test(value)) return "Failed";
  if (/(BLOCKED|REJECTED|LOCKED)/.test(value)) return "Denied";
  if (/(MALWARE|QUARANTINED|DISCONNECTED|ISOLATED|DRAIN|MAINTENANCE)/.test(value)) return "Warning";
  return "Success";
}

export function categoryIcon(category: AuditCategory): ReactNode {
  if (category === "Authentication" || category === "Policies" || category === "Security") return <Icons.Shield />;
  if (category === "User management") return <Icons.Users />;
  if (category === "Sessions") return <Icons.Sessions />;
  if (category === "Quarantine") return <Icons.Quarantine />;
  if (category === "System") return <Icons.System />;
  return <Icons.Audit />;
}

export function auditActor(event: SecurityEventDto) {
  const metadata = event.metadata_json ?? {};
  const actor = metadata.actor ?? metadata.actor_id ?? metadata.admin_id ?? metadata.created_by ?? metadata.reset_by ?? metadata.reviewed_by;
  if (typeof actor === "string" && actor) return { label: "Administrator", id: actor };
  if (event.user_id && /^(USER_LOGIN|MFA_|RECOVERY_|SESSION_|DOWNLOAD_|UPLOAD_|PASSWORD_CHANGED)/.test(event.event_type)) return { label: "User", id: event.user_id };
  return { label: "System", id: null };
}

export function auditTarget(event: SecurityEventDto) {
  if (event.quarantine_file_id) return { label: "Quarantine file", id: event.quarantine_file_id, href: `/quarantine/${event.quarantine_file_id}` };
  if (event.session_id) return { label: "Session", id: event.session_id, href: `/sessions/${event.session_id}` };
  if (event.user_id) return { label: "User", id: event.user_id, href: `/users/${event.user_id}` };
  const metadata = event.metadata_json ?? {};
  for (const [key, value] of Object.entries(metadata)) {
    if (typeof value === "string" && key.endsWith("_id") && value) return { label: eventLabel(key.slice(0, -3)), id: value, href: null };
  }
  return { label: "System", id: null, href: null };
}

export function searchableEvent(event: SecurityEventDto) {
  return [event.id, event.event_type, eventLabel(event.event_type), eventCategory(event.event_type), eventOutcome(event.event_type), event.user_id, event.session_id, event.quarantine_file_id, JSON.stringify(event.metadata_json ?? {})].filter(Boolean).join(" ").toLowerCase();
}
