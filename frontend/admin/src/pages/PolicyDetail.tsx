import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { StatusBadge } from "@shared/components/StatusBadge";
import { LoadingBlock, ErrorState, EmptyState } from "@shared/components/States";
import { ConfirmDialog } from "@shared/components/ConfirmDialog";
import { PageHeader } from "@shared/components/PageHeader";
import { useToast } from "@shared/components/Toast";
import { formatDateTime } from "@shared/format";
import type { FileAction, FileRuleType, PolicyDetailDto } from "@shared/api/types";
import { adminApi } from "../api/adminApi";

interface RuleRow {
  rule_type: FileRuleType;
  match_pattern: string;
  action: FileAction;
  priority: number;
}

/**
 * The primary UX for the existing policy engine (section 28) — a
 * structured rule builder, not a JSON textbox. Only MIME/SOURCE rules are
 * offered because those are the only ones app/services/policy_engine.py
 * actually evaluates (docs/policies.md) — the editor doesn't pretend
 * NETWORK/CLIPBOARD/etc. rules do anything at runtime.
 */
export function PolicyDetail() {
  const { id } = useParams<{ id: string }>();
  const { notify } = useToast();
  const [policy, setPolicy] = useState<PolicyDetailDto | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [rows, setRows] = useState<RuleRow[]>([]);
  const [busy, setBusy] = useState(false);
  const [pendingRollback, setPendingRollback] = useState<{ id: string; versionNumber: number } | null>(null);

  function load() {
    if (!id) return;
    adminApi.getPolicy(id).then(setPolicy).catch(() => setError("Could not load this policy."));
  }
  useEffect(load, [id]);

  if (error) return <div className="page"><ErrorState>{error}</ErrorState></div>;
  if (!policy) return <LoadingBlock label="Loading policy…" />;

  const draft = policy.versions.find((v) => v.status === "DRAFT");
  const sorted = [...policy.versions].sort((a, b) => b.version_number - a.version_number);

  function startEditing() {
    setRows(
      draft
        ? draft.file_rules.map((r) => ({ rule_type: r.rule_type, match_pattern: r.match_pattern, action: r.action, priority: r.priority }))
        : [{ rule_type: "MIME", match_pattern: "", action: "QUARANTINE", priority: 100 }],
    );
    setEditing(true);
  }

  async function saveDraft() {
    if (!id) return;
    setBusy(true);
    try {
      if (draft) {
        await adminApi.updateVersion(id, draft.id, { content: {}, file_rules: rows });
      } else {
        await adminApi.createVersion(id, { content: {}, file_rules: rows });
      }
      notify("Draft saved");
      setEditing(false);
      load();
    } catch {
      notify("Could not save draft", "error");
    } finally {
      setBusy(false);
    }
  }

  async function publish(versionId: string) {
    if (!id) return;
    setBusy(true);
    try {
      await adminApi.publishVersion(id, versionId);
      notify("Policy version published");
      load();
    } catch {
      notify("Could not publish this version", "error");
    } finally {
      setBusy(false);
    }
  }

  async function confirmRollback() {
    if (!id || !pendingRollback) return;
    setBusy(true);
    try {
      await adminApi.rollback(id, pendingRollback.id);
      notify("Rolled back");
      load();
    } catch {
      notify("Could not roll back", "error");
    } finally {
      setBusy(false);
      setPendingRollback(null);
    }
  }

  return (
    <div className="page">
      <p><Link to="/policies">← Policies</Link></p>
      <PageHeader
        title={policy.name}
        subtitle={
          <>
            Type: {policy.policy_type} · Conflict model: <code className="mono">DENY &gt; QUARANTINE &gt; AUTO_RELEASE</code> when
            multiple matching rules apply across a user's groups.
          </>
        }
      />

      <div className="card">
        <div className="section-header">
          <h2>Versions</h2>
          {!editing && (
            <button type="button" className="btn btn-secondary btn-sm" onClick={startEditing}>
              {draft ? "Edit draft" : "New draft version"}
            </button>
          )}
        </div>

        {editing && (
          <div style={{ marginTop: "16px" }}>
            <RuleEditor rows={rows} setRows={setRows} />
            <div style={{ display: "flex", gap: "8px", marginTop: "8px" }}>
              <button type="button" className="btn btn-primary" onClick={() => void saveDraft()} disabled={busy}>
                Save draft
              </button>
              <button type="button" className="btn btn-secondary" onClick={() => setEditing(false)}>
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>

      {sorted.map((v) => (
        <div className="card" key={v.id}>
          <div className="flex-between" style={{ marginBottom: "8px" }}>
            <div>
              v{v.version_number} · <StatusBadge value={v.status} />{" "}
              <span className="text-muted" style={{ fontSize: "0.82rem" }}>
                {v.published_at ? `published ${formatDateTime(v.published_at)}` : `created ${formatDateTime(v.created_at)}`}
              </span>
            </div>
            <div style={{ display: "flex", gap: "8px" }}>
              {v.status === "DRAFT" && (
                <button type="button" className="btn btn-primary btn-sm" onClick={() => void publish(v.id)} disabled={busy}>
                  Publish
                </button>
              )}
              {v.status === "SUPERSEDED" && (
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={() => setPendingRollback({ id: v.id, versionNumber: v.version_number })}
                  disabled={busy}
                >
                  Roll back to this version
                </button>
              )}
            </div>
          </div>
          {v.file_rules.length === 0 ? (
            <EmptyState title="No file rules in this version" />
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th>Rule type</th>
                  <th>Pattern</th>
                  <th>Action</th>
                  <th>Priority</th>
                </tr>
              </thead>
              <tbody>
                {v.file_rules.map((r) => (
                  <tr key={r.id}>
                    <td>{r.rule_type}</td>
                    <td className="mono">{r.match_pattern}</td>
                    <td><StatusBadge value={r.action} /></td>
                    <td>{r.priority}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      ))}

      {pendingRollback && (
        <ConfirmDialog
          title={`Roll back to v${pendingRollback.versionNumber}?`}
          description="This version becomes the current published version immediately, replacing whatever is published now."
          confirmLabel="Roll back"
          busy={busy}
          onConfirm={() => void confirmRollback()}
          onCancel={() => setPendingRollback(null)}
        />
      )}
    </div>
  );
}

function RuleEditor({ rows, setRows }: { rows: RuleRow[]; setRows: (rows: RuleRow[]) => void }) {
  function update(i: number, patch: Partial<RuleRow>) {
    setRows(rows.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));
  }
  return (
    <div>
      {rows.map((row, i) => (
        <div key={i} style={{ display: "flex", gap: "8px", marginBottom: "8px", alignItems: "center" }}>
          <select value={row.rule_type} onChange={(e) => update(i, { rule_type: e.target.value as FileRuleType })}>
            <option value="MIME">MIME</option>
            <option value="SOURCE">SOURCE</option>
          </select>
          <input
            placeholder={row.rule_type === "MIME" ? "e.g. application/pdf" : "e.g. *.microsoft.com"}
            value={row.match_pattern}
            onChange={(e) => update(i, { match_pattern: e.target.value })}
            style={{ flex: 1 }}
          />
          <select value={row.action} onChange={(e) => update(i, { action: e.target.value as FileAction })}>
            <option value="AUTO_RELEASE">AUTO_RELEASE</option>
            <option value="QUARANTINE">QUARANTINE</option>
            <option value="DENY">DENY</option>
          </select>
          <input
            type="number"
            value={row.priority}
            onChange={(e) => update(i, { priority: Number(e.target.value) })}
            style={{ width: "70px" }}
          />
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => setRows(rows.filter((_, idx) => idx !== i))}>
            Remove
          </button>
        </div>
      ))}
      <button
        type="button"
        className="btn btn-secondary btn-sm"
        onClick={() => setRows([...rows, { rule_type: "MIME", match_pattern: "", action: "QUARANTINE", priority: 100 }])}
      >
        Add rule
      </button>
    </div>
  );
}
