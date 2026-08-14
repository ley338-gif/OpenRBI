import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { StatusBadge } from "@shared/components/StatusBadge";
import { LoadingBlock, ErrorState, EmptyState } from "@shared/components/States";
import { ConfirmDialog } from "@shared/components/ConfirmDialog";
import { PageHeader } from "@shared/components/PageHeader";
import { FormField } from "@shared/components/FormField";
import { AttachList, type AttachListItem } from "@shared/components/AttachList";
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

// Matches docker/browser/entrypoint.sh's own fallback defaults — the
// values a session gets when no SESSION policy (or none with valid
// resolution content) applies to a user.
const DEFAULT_SCREEN_WIDTH = 1280;
const DEFAULT_SCREEN_HEIGHT = 800;

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
  const [screenWidth, setScreenWidth] = useState(DEFAULT_SCREEN_WIDTH);
  const [screenHeight, setScreenHeight] = useState(DEFAULT_SCREEN_HEIGHT);
  const [busy, setBusy] = useState(false);
  const [pendingRollback, setPendingRollback] = useState<{ id: string; versionNumber: number } | null>(null);
  const [editingDetails, setEditingDetails] = useState(false);
  const [nameDraft, setNameDraft] = useState("");
  const [descriptionDraft, setDescriptionDraft] = useState("");

  function load() {
    if (!id) return;
    adminApi.getPolicy(id).then(setPolicy).catch(() => setError("Could not load this policy."));
  }
  useEffect(load, [id]);

  if (error) return <div className="page"><ErrorState>{error}</ErrorState></div>;
  if (!policy) return <LoadingBlock label="Loading policy…" />;

  const draft = policy.versions.find((v) => v.status === "DRAFT");
  const currentPublished = policy.versions.find((v) => v.id === policy.current_version_id);
  const sorted = [...policy.versions].sort((a, b) => b.version_number - a.version_number);
  const isSessionPolicy = policy.policy_type === "SESSION";
  // Only these two rule_type values are ever read by
  // app/services/policy_engine.py's evaluate_file_action, but the query
  // that reads them does not filter by the parent Policy's policy_type —
  // so the editor itself must be the thing that keeps a NETWORK/CLIPBOARD/
  // BROWSER/DOWNLOADS/UPLOADS-typed policy from silently acquiring
  // enforced file rules a rule-type badge wouldn't warn about.
  const isFileRulePolicy = policy.policy_type === "MIME" || policy.policy_type === "SOURCE";
  const isNotEnforcedPolicy = !isSessionPolicy && !isFileRulePolicy;

  function startEditing() {
    // A brand-new draft starts from whatever is currently published (not
    // blank) so "New draft version" is really "edit the live rules" — the
    // published version itself stays immutable (app/services/policies.py),
    // this only seeds the new draft's initial rows.
    const source = draft ?? currentPublished;
    setRows(
      source && source.file_rules.length > 0
        ? source.file_rules.map((r) => ({ rule_type: r.rule_type, match_pattern: r.match_pattern, action: r.action, priority: r.priority }))
        : source
          ? []
          : [{ rule_type: "MIME", match_pattern: "", action: "QUARANTINE", priority: 100 }],
    );
    const content = source?.content ?? {};
    setScreenWidth(typeof content.screen_width === "number" ? content.screen_width : DEFAULT_SCREEN_WIDTH);
    setScreenHeight(typeof content.screen_height === "number" ? content.screen_height : DEFAULT_SCREEN_HEIGHT);
    setEditing(true);
  }

  function startEditingDetails() {
    if (!policy) return;
    setNameDraft(policy.name);
    setDescriptionDraft(policy.description ?? "");
    setEditingDetails(true);
  }

  async function saveDetails() {
    if (!id || !nameDraft.trim()) return;
    setBusy(true);
    try {
      await adminApi.updatePolicy(id, nameDraft.trim(), descriptionDraft.trim());
      notify("Policy updated");
      setEditingDetails(false);
      load();
    } catch (err) {
      notify(err instanceof Error ? err.message : "Could not update this policy", "error");
    } finally {
      setBusy(false);
    }
  }

  async function saveDraft() {
    if (!id) return;
    setBusy(true);
    // Every other policy_type's `content` stays {} — resolution is the
    // only field the engine reads today (app/services/policy_engine.py's
    // resolve_session_resolution), and only for SESSION-type policies.
    const content = isSessionPolicy ? { screen_width: screenWidth, screen_height: screenHeight } : {};
    try {
      if (draft) {
        await adminApi.updateVersion(id, draft.id, { content, file_rules: rows });
      } else {
        await adminApi.createVersion(id, { content, file_rules: rows });
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

  async function searchGroups(query: string): Promise<AttachListItem[]> {
    const groups = await adminApi.listGroups();
    const needle = query.toLowerCase();
    return groups
      .filter((g) => g.name.toLowerCase().includes(needle))
      .slice(0, 10)
      .map((g) => ({ id: g.id, label: g.name, meta: `${g.member_count} member${g.member_count === 1 ? "" : "s"}` }));
  }

  async function addGroup(groupId: string) {
    if (!id) return;
    setBusy(true);
    try {
      await adminApi.attachToGroup(id, groupId);
      notify("Group attached");
      load();
    } catch {
      notify("Could not attach this group", "error");
    } finally {
      setBusy(false);
    }
  }

  async function removeGroup(groupId: string) {
    if (!id) return;
    setBusy(true);
    try {
      await adminApi.detachFromGroup(id, groupId);
      notify("Group detached");
      load();
    } catch {
      notify("Could not detach this group", "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page">
      <p><Link to="/policies">← Policies</Link></p>
      {editingDetails ? (
        <div className="card">
          <div className="section-header">
            <h2>Rename policy</h2>
          </div>
          <FormField label="Name">
            <input autoFocus value={nameDraft} onChange={(e) => setNameDraft(e.target.value)} required />
          </FormField>
          <FormField label="Description" hint="Optional context shown in the policy overview.">
            <textarea value={descriptionDraft} onChange={(e) => setDescriptionDraft(e.target.value)} />
          </FormField>
          <div style={{ display: "flex", gap: "8px" }}>
            <button type="button" className="btn btn-primary" disabled={busy || !nameDraft.trim()} onClick={() => void saveDetails()}>
              Save
            </button>
            <button type="button" className="btn btn-secondary" onClick={() => setEditingDetails(false)}>
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <PageHeader
          title={policy.name}
          subtitle={
            isNotEnforcedPolicy ? (
              <>
                Type: {policy.policy_type} <StatusBadge value="NOT ENFORCED" /> · stored for future enforcement, no
                effect on any running or new session today.
                {policy.description && <> · {policy.description}</>}
              </>
            ) : (
              <>
                Type: {policy.policy_type} · Conflict model: <code className="mono">DENY &gt; QUARANTINE &gt; AUTO_RELEASE</code> when
                multiple matching rules apply across a user's groups.
                {policy.description && <> · {policy.description}</>}
              </>
            )
          }
          actions={
            <button type="button" className="btn btn-secondary btn-sm" onClick={startEditingDetails}>
              Rename / edit description
            </button>
          }
        />
      )}

      <div className="card">
        <div className="section-header">
          <h2>Assigned groups</h2>
        </div>
        <p className="text-muted" style={{ marginTop: "-8px", marginBottom: "16px" }}>
          Every member of an attached group is subject to this policy. Search by name to attach a group; removing
          one here only unlinks it, it doesn't delete the group.
        </p>
        <AttachList
          entityLabel="group"
          attached={policy.assigned_groups.map((g) => ({ id: g.id, label: g.name }))}
          onSearch={searchGroups}
          onAdd={addGroup}
          onRemove={removeGroup}
          busy={busy}
          emptyLabel="No groups attached to this policy yet."
        />
      </div>

      <div className="card">
        <div className="section-header">
          <h2>Versions</h2>
          {!editing && (
            <button type="button" className="btn btn-secondary btn-sm" onClick={startEditing}>
              {draft ? "Edit draft" : currentPublished ? "Edit rules (new draft)" : "New draft version"}
            </button>
          )}
        </div>

        {editing && (
          <div style={{ marginTop: "16px" }}>
            {isSessionPolicy && (
              <ResolutionEditor
                width={screenWidth}
                height={screenHeight}
                setWidth={setScreenWidth}
                setHeight={setScreenHeight}
              />
            )}
            {isFileRulePolicy && (
              <p className="hint" style={{ marginBottom: "12px" }}>
                A user can belong to multiple groups. If another group's published policy also matches the same
                file with a more restrictive action, that action wins — DENY beats QUARANTINE beats AUTO_RELEASE —
                regardless of which rule is more specific. See{" "}
                <a href="/docs/policies.md#conflict-model-deterministic">the conflict model</a> before relying on an
                AUTO_RELEASE rule for a user who may be in other groups too.
              </p>
            )}
            {isFileRulePolicy && <RuleEditor rows={rows} setRows={setRows} />}
            {isNotEnforcedPolicy && (
              <EmptyState title="Nothing to configure yet">
                <p>
                  {policy.policy_type} policies are stored but currently have no runtime effect — nothing reads them
                  when a session or file decision is made (docs/policies.md). This version can still be versioned
                  and published for record-keeping, but there is no rule editor here because there is nothing yet
                  for a rule to control.
                </p>
              </EmptyState>
            )}
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
          {isSessionPolicy && (
            <p className="text-muted" style={{ fontSize: "0.85rem", marginBottom: "8px" }}>
              Screen resolution:{" "}
              {typeof v.content.screen_width === "number" && typeof v.content.screen_height === "number" ? (
                <span className="mono">{v.content.screen_width} × {v.content.screen_height}</span>
              ) : (
                <span>not set — sessions fall back to the sandbox default ({DEFAULT_SCREEN_WIDTH} × {DEFAULT_SCREEN_HEIGHT})</span>
              )}
            </p>
          )}
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

/**
 * Only rendered for SESSION-type policies. Sets the Xvfb/noVNC resolution
 * new sessions get when this policy's group applies to a user
 * (app/services/policy_engine.py's resolve_session_resolution) — the only
 * runtime effect a SESSION policy has today.
 */
function ResolutionEditor({
  width,
  height,
  setWidth,
  setHeight,
}: {
  width: number;
  height: number;
  setWidth: (v: number) => void;
  setHeight: (v: number) => void;
}) {
  return (
    <div style={{ marginBottom: "16px" }}>
      <label className="form-field-label" style={{ display: "block", marginBottom: "4px" }}>Screen resolution</label>
      <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
        <input
          type="number"
          min={640}
          max={3840}
          value={width}
          onChange={(e) => setWidth(Number(e.target.value))}
          style={{ width: "90px" }}
          aria-label="Screen width"
        />
        <span>×</span>
        <input
          type="number"
          min={480}
          max={2160}
          value={height}
          onChange={(e) => setHeight(Number(e.target.value))}
          style={{ width: "90px" }}
          aria-label="Screen height"
        />
        <span className="text-muted" style={{ fontSize: "0.85rem" }}>pixels</span>
      </div>
      <p className="hint">
        Applied to every new session started by a user in a group this policy is attached to. Doesn't affect
        sessions already running.
      </p>
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
