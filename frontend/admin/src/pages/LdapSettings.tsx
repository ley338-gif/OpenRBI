import { useEffect, useMemo, useState } from "react";
import { ApiError } from "@shared/api/client";
import type { LdapConfigDto, LdapTestResponseDto, Role } from "@shared/api/types";
import { ConfirmDialog } from "@shared/components/ConfirmDialog";
import { FormField } from "@shared/components/FormField";
import { Icons } from "@shared/components/Icons";
import { ErrorState, LoadingBlock } from "@shared/components/States";
import { useToast } from "@shared/components/Toast";
import { adminApi } from "../api/adminApi";

const ROLES: Role[] = ["USER", "SECURITY_REVIEWER", "ADMIN"];
type Mapping = { dn: string; role: Role };
type FormState = Pick<LdapConfigDto, "enabled" | "server_uri" | "use_starttls" | "bind_dn" | "base_dn" | "user_search_filter" | "group_attribute"> & { bind_password: string };

function formFromConfig(config: LdapConfigDto): FormState {
  return { ...config, bind_password: "" };
}

function validate(form: FormState): Record<string, string> {
  const errors: Record<string, string> = {};
  const uri = form.server_uri.trim().toLowerCase();
  if (!uri) errors.server_uri = "Server URI is required.";
  else if (!uri.startsWith("ldap://") && !uri.startsWith("ldaps://")) errors.server_uri = "Use an ldap:// or ldaps:// server URI.";
  else if (uri.startsWith("ldaps://") && form.use_starttls) errors.use_starttls = "StartTLS cannot be combined with LDAPS.";
  else if (uri.startsWith("ldap://") && !form.use_starttls) errors.use_starttls = "Plain LDAP requires StartTLS. Unencrypted binds are not supported.";
  if (!form.base_dn.trim()) errors.base_dn = "Base DN is required.";
  if (!form.user_search_filter.includes("{username}")) errors.user_search_filter = "User search filter must contain {username}.";
  if (!form.group_attribute.trim()) errors.group_attribute = "Group membership attribute is required.";
  return errors;
}

export function LdapSettings() {
  const { notify } = useToast();
  const [config, setConfig] = useState<LdapConfigDto | null>(null);
  const [form, setForm] = useState<FormState | null>(null);
  const [mapping, setMapping] = useState<Mapping[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [testUsername, setTestUsername] = useState("");
  const [testResult, setTestResult] = useState<LdapTestResponseDto | null>(null);
  const [showDetails, setShowDetails] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [mappingDialog, setMappingDialog] = useState<number | "new" | null>(null);
  const [mappingDraft, setMappingDraft] = useState<Mapping>({ dn: "", role: "USER" });
  const [confirmDisable, setConfirmDisable] = useState(false);

  function applyConfig(next: LdapConfigDto) {
    setConfig(next);
    setForm(formFromConfig(next));
    setMapping(Object.entries(next.group_role_mapping).map(([dn, role]) => ({ dn, role: role as Role })));
  }

  useEffect(() => {
    adminApi.getLdapConfig().then(applyConfig).catch(() => setLoadError("Could not load LDAP configuration."));
  }, []);

  const errors = useMemo(() => form ? validate(form) : {}, [form]);
  const dirty = useMemo(() => {
    if (!config || !form) return false;
    const savedMapping = JSON.stringify(Object.entries(config.group_role_mapping).sort());
    const currentMapping = JSON.stringify(mapping.filter((row) => row.dn.trim()).map((row) => [row.dn.trim(), row.role]).sort());
    return JSON.stringify(formFromConfig(config)) !== JSON.stringify(form) || savedMapping !== currentMapping;
  }, [config, form, mapping]);
  const insecure = !!form?.server_uri.toLowerCase().startsWith("ldap://") && !form.use_starttls;
  const tlsLabel = form?.server_uri.toLowerCase().startsWith("ldaps://") ? "LDAPS" : form?.use_starttls ? "StartTLS" : "Unencrypted";

  function setField<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((current) => current ? { ...current, [key]: value } : current);
    setTestResult(null);
  }

  async function runTest() {
    if (!form || Object.keys(errors).length) return notify("Correct the highlighted fields before testing.", "error");
    if (!form.bind_password) return notify("Enter the bind password to run a stateless connection test.", "error");
    setTesting(true); setTestResult(null); setShowDetails(false);
    try {
      setTestResult(await adminApi.testLdapConfig({ ...form, test_username: testUsername.trim() || null }));
    } catch { notify("Connection test could not be completed.", "error"); }
    finally { setTesting(false); }
  }

  async function persist() {
    if (!form || Object.keys(errors).length) return notify("Correct the highlighted fields before saving.", "error");
    setSaving(true);
    try {
      const group_role_mapping = Object.fromEntries(mapping.filter((row) => row.dn.trim()).map((row) => [row.dn.trim(), row.role]));
      const updated = await adminApi.updateLdapConfig({ ...form, ...(form.bind_password ? {} : { bind_password: undefined }), group_role_mapping });
      applyConfig(updated); setTestResult(null); notify("LDAP configuration saved.");
    } catch (error) {
      notify(error instanceof ApiError && error.status === 422 ? "LDAP validation failed. The active configuration was not changed." : "Could not save LDAP configuration.", "error");
    } finally { setSaving(false); setConfirmDisable(false); }
  }

  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (config?.enabled && form && !form.enabled) setConfirmDisable(true); else void persist();
  }

  function openMapping(index: number | "new") {
    setMappingDraft(index === "new" ? { dn: "", role: "USER" } : { ...mapping[index] });
    setMappingDialog(index);
  }

  function saveMapping() {
    if (!mappingDraft.dn.trim()) return;
    setMapping((rows) => mappingDialog === "new" ? [...rows, { ...mappingDraft, dn: mappingDraft.dn.trim() }] : rows.map((row, index) => index === mappingDialog ? { ...mappingDraft, dn: mappingDraft.dn.trim() } : row));
    setMappingDialog(null);
  }

  if (loadError) return <div className="page"><ErrorState>{loadError}</ErrorState></div>;
  if (!config || !form) return <LoadingBlock label="Loading LDAP configuration…" />;

  return <div className="page ldap-page">
    <header className="page-heading"><div><h1>LDAP / Active Directory</h1><p>Configure external directory authentication. Local OpenRBI accounts remain available during an LDAP outage or misconfiguration.</p></div><a className="btn btn-secondary btn-sm" href="/docs/admin-guide.md">Documentation <Icons.ExternalLink /></a></header>

    <form onSubmit={submit}>
      <div className="ldap-layout">
        <section className="card ldap-connection-card">
          <div className="section-header"><div className="section-title"><span className="section-icon"><Icons.Settings /></span><div><h2>LDAP connection</h2><p>Configure how OpenRBI connects to your LDAP or Active Directory server.</p></div></div><label className="toggle-control"><input type="checkbox" checked={form.enabled} onChange={(event) => setField("enabled", event.target.checked)} /><span /><strong>{form.enabled ? "Enabled" : "Disabled"}</strong></label></div>
          <FormField label="Server URI" hint="LDAP server URI including protocol and optional port."><input value={form.server_uri} placeholder="ldaps://ad.example.org:636" onChange={(e) => setField("server_uri", e.target.value)} aria-invalid={!!errors.server_uri} />{errors.server_uri && <small className="field-error">{errors.server_uri}</small>}</FormField>
          <label className="ldap-check"><input type="checkbox" checked={form.use_starttls} disabled={form.server_uri.toLowerCase().startsWith("ldaps://")} onChange={(e) => setField("use_starttls", e.target.checked)} /><span><strong>Use StartTLS</strong><small>Upgrade a plain LDAP connection to TLS before authentication.</small></span></label>
          {errors.use_starttls && <div className="inline-alert danger">{errors.use_starttls}</div>}
          {insecure && <div className="inline-alert danger"><Icons.Quarantine /><div><strong>Unencrypted LDAP is blocked</strong><p>Enable StartTLS or use an LDAPS server URI before testing or saving.</p></div></div>}
          <FormField label="Bind (service account) DN" hint="Distinguished Name of the service account used for directory searches."><input value={form.bind_dn} placeholder="CN=openrbi-bind,OU=ServiceAccounts,DC=example,DC=org" onChange={(e) => setField("bind_dn", e.target.value)} /></FormField>
          <FormField label="Bind password" hint={config.bind_password_configured ? "Password configured. Leave empty to keep the stored secret." : "No bind password is configured."}><div className="password-field"><input type={showPassword ? "text" : "password"} autoComplete="new-password" value={form.bind_password} placeholder={config.bind_password_configured ? "Password configured" : "Enter bind password"} onChange={(e) => setField("bind_password", e.target.value)} /><button type="button" className="password-toggle" onClick={() => setShowPassword((value) => !value)} aria-label={showPassword ? "Hide password" : "Show password"}>{showPassword ? <Icons.EyeOff /> : <Icons.Eye />}</button></div></FormField>
          <FormField label="Base DN" hint="Base distinguished name used for user and group searches."><input value={form.base_dn} placeholder="DC=example,DC=org" onChange={(e) => setField("base_dn", e.target.value)} aria-invalid={!!errors.base_dn} />{errors.base_dn && <small className="field-error">{errors.base_dn}</small>}</FormField>
          <FormField label="User search filter" hint="{username} is replaced with the escaped login name."><input value={form.user_search_filter} placeholder="(sAMAccountName={username})" onChange={(e) => setField("user_search_filter", e.target.value)} aria-invalid={!!errors.user_search_filter} />{errors.user_search_filter && <small className="field-error">{errors.user_search_filter}</small>}</FormField>
          <details className="ldap-advanced"><summary>Advanced settings</summary><FormField label="Group membership attribute" hint="LDAP attribute used to resolve a user's group memberships."><input value={form.group_attribute} onChange={(e) => setField("group_attribute", e.target.value)} aria-invalid={!!errors.group_attribute} />{errors.group_attribute && <small className="field-error">{errors.group_attribute}</small>}</FormField></details>
        </section>

        <div className="ldap-side">
          <section className="card"><div className="section-title"><span className="section-icon"><Icons.RefreshCw /></span><div><h2>Test connection</h2><p>Verify connectivity, bind, and optionally user and group resolution.</p></div></div><div className="ldap-test-row"><FormField label="Test username (optional)"><input value={testUsername} placeholder="Enter a directory username" onChange={(e) => setTestUsername(e.target.value)} /></FormField><button type="button" className="btn btn-primary" disabled={testing} onClick={() => void runTest()}>{testing && <span className="spinner" />}{testing ? "Testing…" : "Test connection"}</button></div>
            {testResult && <div className={`ldap-test-result ${testResult.success ? "success" : "failure"}`}><div className="ldap-result-heading"><span className="result-icon">{testResult.success ? "✓" : "!"}</span><div><strong>{testResult.success ? "Connection successful" : "Connection failed"}</strong><p>{testResult.success ? "Directory reachable and performed checks succeeded." : "Review the failed step and correct the configuration."}</p></div><button type="button" className="btn btn-secondary btn-sm" onClick={() => setShowDetails((value) => !value)}>{showDetails ? "Hide details" : "View details"}</button></div>{showDetails && <div className="ldap-test-steps">{testResult.steps.map((step) => <div key={step.name}><span className={step.ok ? "ok" : "failed"}>{step.ok ? "✓" : "×"}</span><strong>{step.name}</strong><small>{step.detail || "Completed"}</small></div>)}{testResult.groups_discovered !== null && <p>{testResult.groups_discovered} group(s) resolved for the test user.</p>}</div>}</div>}
          </section>
          <section className="card ldap-status-card"><div className="section-title"><span className="section-icon"><Icons.Shield /></span><div><h2>Status & information</h2><p>Current persisted configuration and authentication behavior.</p></div></div><div className="ldap-status-grid"><div><small>Status</small><strong className={config.enabled ? "positive" : "muted"}>{config.enabled ? "Enabled" : "Disabled"}</strong></div><div><small>Connection security</small><strong className={insecure ? "negative" : "positive"}>{tlsLabel}</strong></div><div><small>Bind secret</small><strong>{config.bind_password_configured ? "Configured" : "Not configured"}</strong></div><div><small>Local login</small><strong className="positive">Available</strong></div></div><p className="status-note">LDAP identities are provisioned just in time at login. OpenRBI does not perform a directory synchronization.</p></section>
        </div>
      </div>

      <section className="card ldap-mapping-card"><div className="section-header"><div className="section-title"><span className="section-icon"><Icons.Groups /></span><div><h2>Group → role mapping</h2><p>Exact-match LDAP group DNs assign an OpenRBI role. Unmatched LDAP users receive USER.</p></div></div><button type="button" className="btn btn-secondary btn-sm" onClick={() => openMapping("new")}>+ Add mapping</button></div>{mapping.length === 0 ? <div className="empty-state"><strong>No group mappings yet</strong><p>Add an LDAP group mapping to assign OpenRBI roles automatically.</p><button type="button" className="btn btn-primary btn-sm" onClick={() => openMapping("new")}>Add mapping</button></div> : <div className="table-wrap"><table className="data-table ldap-mapping-table"><thead><tr><th>LDAP group DN</th><th>OpenRBI role</th><th>Actions</th></tr></thead><tbody>{mapping.map((row, index) => <tr key={`${row.dn}-${index}`}><td><span className="ldap-dn" title={row.dn}>{row.dn}</span></td><td><span className={`role-pill role-${row.role.toLowerCase()}`}>{row.role}</span></td><td><div className="row-actions"><button type="button" className="icon-btn" title="Edit mapping" onClick={() => openMapping(index)}><Icons.Settings /></button><button type="button" className="icon-btn danger" title="Remove mapping" onClick={() => setMapping((rows) => rows.filter((_, itemIndex) => itemIndex !== index))}>×</button></div></td></tr>)}</tbody></table></div>}<p className="mapping-note"><Icons.Help /> Group DN matching is exact and case-sensitive. Local accounts with local passwords keep their configured role.</p></section>

      <div className="ldap-save-bar"><button type="submit" className="btn btn-primary" disabled={saving || !dirty || Object.keys(errors).length > 0}>{saving && <span className="spinner" />}{saving ? "Saving…" : "Save configuration"}</button><span>{dirty ? "You have unsaved changes." : "Configuration is up to date."}</span></div>
    </form>

    {mappingDialog !== null && <div className="modal-overlay" onClick={() => setMappingDialog(null)}><div className="modal" role="dialog" aria-modal="true" onClick={(event) => event.stopPropagation()}><h2>{mappingDialog === "new" ? "Add group mapping" : "Edit group mapping"}</h2><FormField label="LDAP group DN" hint="Use the exact DN returned by your directory."><input autoFocus value={mappingDraft.dn} onChange={(e) => setMappingDraft((draft) => ({ ...draft, dn: e.target.value }))} /></FormField><FormField label="OpenRBI role"><select value={mappingDraft.role} onChange={(e) => setMappingDraft((draft) => ({ ...draft, role: e.target.value as Role }))}>{ROLES.map((role) => <option key={role}>{role}</option>)}</select></FormField><div className="modal-actions"><button type="button" className="btn btn-secondary" onClick={() => setMappingDialog(null)}>Cancel</button><button type="button" className="btn btn-primary" disabled={!mappingDraft.dn.trim()} onClick={saveMapping}>Save mapping</button></div></div></div>}
    {confirmDisable && <ConfirmDialog title="Disable LDAP authentication?" description="LDAP users will no longer be able to sign in. Local OpenRBI accounts remain available." confirmLabel="Disable LDAP" danger busy={saving} onConfirm={() => void persist()} onCancel={() => setConfirmDisable(false)} />}
  </div>;
}
