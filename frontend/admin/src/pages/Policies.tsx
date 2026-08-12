import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { LoadingBlock, EmptyState, ErrorState } from "@shared/components/States";
import { FormField } from "@shared/components/FormField";
import { useToast } from "@shared/components/Toast";
import type { PolicySummaryDto, PolicyType } from "@shared/api/types";
import { adminApi } from "../api/adminApi";

const POLICY_TYPES: PolicyType[] = ["MIME", "SOURCE", "NETWORK", "DOWNLOADS", "UPLOADS", "CLIPBOARD", "BROWSER", "SESSION"];

export function Policies() {
  const { notify } = useToast();
  const [policies, setPolicies] = useState<PolicySummaryDto[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [policyType, setPolicyType] = useState<PolicyType>("MIME");
  const [busy, setBusy] = useState(false);

  function load() {
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
      notify(`Policy "${p.name}" created as a draft`);
    } catch {
      notify("Could not create policy", "error");
    } finally {
      setBusy(false);
    }
  }

  if (error) return <div className="page"><ErrorState>{error}</ErrorState></div>;
  if (!policies) return <LoadingBlock label="Loading policies…" />;

  return (
    <div className="page">
      <h1>Policies</h1>

      <div className="card">
        <h2 style={{ margin: "0 0 8px", fontSize: "1.1rem" }}>Create policy</h2>
        <form onSubmit={submit} style={{ display: "flex", gap: "8px", alignItems: "flex-end" }}>
          <FormField label="Name">
            <input value={name} onChange={(e) => setName(e.target.value)} required />
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
        </form>
      </div>

      {policies.length === 0 ? (
        <EmptyState>No policies yet.</EmptyState>
      ) : (
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
      )}
    </div>
  );
}
