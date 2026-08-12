import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { LoadingBlock, EmptyState, ErrorState } from "@shared/components/States";
import { FormField } from "@shared/components/FormField";
import { PageHeader } from "@shared/components/PageHeader";
import { useToast } from "@shared/components/Toast";
import type { PolicySummaryDto, PolicyType } from "@shared/api/types";
import { adminApi } from "../api/adminApi";

const POLICY_TYPES: PolicyType[] = ["MIME", "SOURCE", "NETWORK", "DOWNLOADS", "UPLOADS", "CLIPBOARD", "BROWSER", "SESSION"];

export function Policies() {
  const { notify } = useToast();
  const [policies, setPolicies] = useState<PolicySummaryDto[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [name, setName] = useState("");
  const [policyType, setPolicyType] = useState<PolicyType>("MIME");
  const [busy, setBusy] = useState(false);

  function load() {
    setError(null);
    adminApi.listPolicies().then(setPolicies).catch(() => setError("Could not load policies."));
  }
  useEffect(load, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    try {
      const p = await adminApi.createPolicy(name, policyType);
      setPolicies((prev) => [...(prev ?? []), p]);
      setName("");
      setShowCreate(false);
      notify(`Policy "${p.name}" created as a draft`);
    } catch {
      notify("Could not create policy", "error");
    } finally {
      setBusy(false);
    }
  }

  if (error) {
    return (
      <div className="page">
        <ErrorState action={<button type="button" className="btn btn-secondary btn-sm" onClick={load}>Try again</button>}>
          {error}
        </ErrorState>
      </div>
    );
  }
  if (!policies) return <LoadingBlock label="Loading policies…" />;

  return (
    <div className="page">
      <PageHeader
        title="Policies"
        subtitle="Versioned rules controlling downloads, uploads, and file types."
        actions={
          <button type="button" className="btn btn-primary" onClick={() => setShowCreate(true)}>
            Create Policy
          </button>
        }
      />

      {showCreate && (
        <div className="card">
          <div className="section-header"><h2>Create policy</h2></div>
          <form onSubmit={submit} style={{ display: "flex", gap: "8px", alignItems: "flex-end" }}>
            <FormField label="Name">
              <input value={name} onChange={(e) => setName(e.target.value)} required autoFocus />
            </FormField>
            <FormField
              label="Type"
              hint={
                policyType === "MIME" || policyType === "SOURCE"
                  ? undefined
                  : "Only MIME/SOURCE file rules are actually enforced today — see docs/policies.md."
              }
            >
              <select value={policyType} onChange={(e) => setPolicyType(e.target.value as PolicyType)}>
                {POLICY_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </FormField>
            <button type="submit" className="btn btn-primary" disabled={busy} style={{ marginBottom: "16px" }}>
              Create
            </button>
            <button
              type="button"
              className="btn btn-secondary"
              disabled={busy}
              style={{ marginBottom: "16px" }}
              onClick={() => setShowCreate(false)}
            >
              Cancel
            </button>
          </form>
        </div>
      )}

      {policies.length === 0 ? (
        <EmptyState title="No policies yet">Create the first policy to start controlling file transfers.</EmptyState>
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Type</th>
                <th>Current version</th>
              </tr>
            </thead>
            <tbody>
              {policies.map((p) => (
                <tr key={p.id}>
                  <td>
                    <Link to={`/policies/${p.id}`}>{p.name}</Link>
                  </td>
                  <td>{p.policy_type}</td>
                  <td>{p.current_version_number ?? "— (no published version)"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
