import { useEffect, useState } from "react";
import { LoadingBlock, ErrorState } from "@shared/components/States";
import { FormField } from "@shared/components/FormField";
import { useToast } from "@shared/components/Toast";
import { ApiError } from "@shared/api/client";
import type { LdapConfigDto, LdapTestResponseDto, Role } from "@shared/api/types";
import { adminApi } from "../api/adminApi";

const ROLES: Role[] = ["USER", "SECURITY_REVIEWER", "ADMIN"];

interface FormState {
  enabled: boolean;
  server_uri: string;
  use_starttls: boolean;
  bind_dn: string;
  bind_password: string;
  base_dn: string;
  user_search_filter: string;
  group_attribute: string;
}

function formFromConfig(c: LdapConfigDto): FormState {
  return {
    enabled: c.enabled,
    server_uri: c.server_uri,
    use_starttls: c.use_starttls,
    bind_dn: c.bind_dn,
    bind_password: "",
    base_dn: c.base_dn,
    user_search_filter: c.user_search_filter,
    group_attribute: c.group_attribute,
  };
}

/** Roadmap B1.8.3/B1.8.4 — Settings → Authentication → LDAP. Edit → Test →
 * Save → Activate (ADR 0016): "Test connection" always calls the stateless
 * /admin/ldap/test with the form's current values and never touches the
 * saved config; "Save" persists via PUT, which itself re-runs the same
 * test server-side before accepting enabled=true — a broken save can never
 * replace a working saved configuration.
 */
export function LdapSettings() {
  const { notify } = useToast();
  const [config, setConfig] = useState<LdapConfigDto | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState<FormState | null>(null);
  const [mapping, setMapping] = useState<{ dn: string; role: Role }[]>([]);
  const [testUsername, setTestUsername] = useState("");
  const [testResult, setTestResult] = useState<LdapTestResponseDto | null>(null);
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);

  function load() {
    adminApi
      .getLdapConfig()
      .then((c) => {
        setConfig(c);
        setForm(formFromConfig(c));
        setMapping(Object.entries(c.group_role_mapping).map(([dn, role]) => ({ dn, role: role as Role })));
      })
      .catch(() => setError("Could not load LDAP configuration."));
  }
  useEffect(load, []);

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((prev) => (prev ? { ...prev, [key]: value } : prev));
    setTestResult(null);
  }

  function mappingAsObject(): Record<string, string> {
    const obj: Record<string, string> = {};
    for (const row of mapping) {
      if (row.dn.trim()) obj[row.dn.trim()] = row.role;
    }
    return obj;
  }

  async function runTest() {
    if (!form) return;
    if (!form.bind_password) {
      notify("Enter the bind password to test the connection — it is never sent to your browser, so it can't be reused from a prior save.", "error");
      return;
    }
    setTesting(true);
    setTestResult(null);
    try {
      const result = await adminApi.testLdapConfig({
        server_uri: form.server_uri,
        use_starttls: form.use_starttls,
        bind_dn: form.bind_dn,
        bind_password: form.bind_password,
        base_dn: form.base_dn,
        user_search_filter: form.user_search_filter,
        group_attribute: form.group_attribute,
        test_username: testUsername || null,
      });
      setTestResult(result);
    } catch {
      notify("Connection test failed to run", "error");
    } finally {
      setTesting(false);
    }
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!form) return;
    setSaving(true);
    try {
      const payload = {
        enabled: form.enabled,
        server_uri: form.server_uri,
        use_starttls: form.use_starttls,
        bind_dn: form.bind_dn,
        ...(form.bind_password ? { bind_password: form.bind_password } : {}),
        base_dn: form.base_dn,
        user_search_filter: form.user_search_filter,
        group_attribute: form.group_attribute,
        group_role_mapping: mappingAsObject(),
      };
      const updated = await adminApi.updateLdapConfig(payload);
      setConfig(updated);
      setForm(formFromConfig(updated));
      notify(updated.enabled ? "LDAP configuration saved and enabled" : "LDAP configuration saved");
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) {
        notify("Could not enable LDAP: the connection test failed. The previously saved configuration was not changed. Use \"Test connection\" to see details.", "error");
      } else {
        notify("Could not save LDAP configuration", "error");
      }
    } finally {
      setSaving(false);
    }
  }

  if (error) return <div className="page"><ErrorState>{error}</ErrorState></div>;
  if (!config || !form) return <LoadingBlock label="Loading LDAP configuration…" />;

  return (
    <div className="page">
      <h1>Settings — Authentication — LDAP</h1>
      <p className="text-muted">
        Configure external LDAP/Active Directory authentication. Local login always stays available, including during
        an LDAP outage or misconfiguration.
      </p>

      <form onSubmit={save}>
        <div className="card">
          <div className="flex-between" style={{ marginBottom: "8px" }}>
            <h2 style={{ margin: 0, fontSize: "1.1rem" }}>Connection</h2>
            <label style={{ display: "flex", alignItems: "center", gap: "6px", fontWeight: 600 }}>
              <input type="checkbox" checked={form.enabled} onChange={(e) => set("enabled", e.target.checked)} />
              Enabled
            </label>
          </div>

          <FormField label="Server URI" hint="e.g. ldaps://ad.example.org:636">
            <input value={form.server_uri} onChange={(e) => set("server_uri", e.target.value)} required />
          </FormField>

          <label style={{ display: "flex", alignItems: "center", gap: "6px", margin: "8px 0" }}>
            <input type="checkbox" checked={form.use_starttls} onChange={(e) => set("use_starttls", e.target.checked)} />
            Use StartTLS (required for a plain ldap:// URI)
          </label>

          <FormField label="Bind (service account) DN">
            <input value={form.bind_dn} onChange={(e) => set("bind_dn", e.target.value)} required />
          </FormField>

          <FormField
            label="Bind password"
            hint={config.bind_password_configured ? "Bind password: configured. Leave empty to keep the existing password." : "No bind password saved yet."}
          >
            <input
              type="password"
              autoComplete="new-password"
              value={form.bind_password}
              onChange={(e) => set("bind_password", e.target.value)}
              placeholder={config.bind_password_configured ? "Leave empty to keep the existing password" : ""}
            />
          </FormField>

          <FormField label="Base DN">
            <input value={form.base_dn} onChange={(e) => set("base_dn", e.target.value)} required />
          </FormField>

          <FormField label="User search filter" hint="{username} is substituted with the escaped login name">
            <input value={form.user_search_filter} onChange={(e) => set("user_search_filter", e.target.value)} required />
          </FormField>

          <FormField label="Group attribute">
            <input value={form.group_attribute} onChange={(e) => set("group_attribute", e.target.value)} required />
          </FormField>
        </div>

        <div className="card">
          <h2 style={{ margin: "0 0 8px", fontSize: "1.1rem" }}>Test connection</h2>
          <div style={{ display: "flex", gap: "8px", alignItems: "flex-end", marginBottom: "12px" }}>
            <FormField label="Test username (optional)" hint="Probes user search + group resolution for this login name">
              <input value={testUsername} onChange={(e) => setTestUsername(e.target.value)} />
            </FormField>
            <button type="button" className="btn btn-secondary" disabled={testing} onClick={() => void runTest()} style={{ marginBottom: "16px" }}>
              {testing ? "Testing…" : "Test connection"}
            </button>
          </div>

          {testResult && (
            <div>
              <p style={{ fontWeight: 600 }}>
                <span className={`badge ${testResult.success ? "badge-healthy" : "badge-critical"}`}>
                  {testResult.success ? "OK" : "FAILED"}
                </span>
              </p>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Step</th>
                    <th>Result</th>
                    <th>Detail</th>
                  </tr>
                </thead>
                <tbody>
                  {testResult.steps.map((s) => (
                    <tr key={s.name}>
                      <td>{s.name}</td>
                      <td>
                        <span className={`badge ${s.ok ? "badge-healthy" : "badge-critical"}`}>{s.ok ? "OK" : "FAILED"}</span>
                      </td>
                      <td className="text-muted">{s.detail ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {testResult.groups_discovered !== null && (
                <p className="text-muted">{testResult.groups_discovered} group(s) discovered for the test username.</p>
              )}
            </div>
          )}
        </div>

        <div className="card">
          <h2 style={{ margin: "0 0 8px", fontSize: "1.1rem" }}>Group → role mapping</h2>
          <p className="text-muted" style={{ marginTop: 0 }}>
            Exact-match LDAP group DN → OpenRBI role. A login not matching any row here is assigned the USER role. An
            existing local account with a real local password always keeps its admin-configured role, regardless of
            this mapping.
          </p>
          <table className="data-table">
            <thead>
              <tr>
                <th>LDAP group DN</th>
                <th>OpenRBI role</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {mapping.map((row, i) => (
                <tr key={i}>
                  <td>
                    <input
                      style={{ width: "100%" }}
                      value={row.dn}
                      onChange={(e) =>
                        setMapping((prev) => prev.map((r, j) => (j === i ? { ...r, dn: e.target.value } : r)))
                      }
                    />
                  </td>
                  <td>
                    <select
                      value={row.role}
                      onChange={(e) =>
                        setMapping((prev) => prev.map((r, j) => (j === i ? { ...r, role: e.target.value as Role } : r)))
                      }
                    >
                      {ROLES.map((r) => (
                        <option key={r} value={r}>
                          {r}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <button
                      type="button"
                      className="btn btn-danger btn-sm"
                      onClick={() => setMapping((prev) => prev.filter((_, j) => j !== i))}
                    >
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            style={{ marginTop: "8px" }}
            onClick={() => setMapping((prev) => [...prev, { dn: "", role: "USER" }])}
          >
            Add mapping
          </button>
        </div>

        <button type="submit" className="btn btn-primary" disabled={saving}>
          {saving ? "Saving…" : "Save configuration"}
        </button>
      </form>
    </div>
  );
}
