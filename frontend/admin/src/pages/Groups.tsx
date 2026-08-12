import { useEffect, useState } from "react";
import { LoadingBlock, EmptyState, ErrorState } from "@shared/components/States";
import { ConfirmDialog } from "@shared/components/ConfirmDialog";
import { PageHeader } from "@shared/components/PageHeader";
import { FormField } from "@shared/components/FormField";
import { useToast } from "@shared/components/Toast";
import type { GroupSummaryDto } from "@shared/api/types";
import { adminApi } from "../api/adminApi";

export function Groups() {
  const { notify } = useToast();
  const [groups, setGroups] = useState<GroupSummaryDto[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<GroupSummaryDto | null>(null);

  function load() {
    setError(null);
    adminApi.listGroups().then(setGroups).catch(() => setError("Could not load groups."));
  }
  useEffect(load, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    try {
      const g = await adminApi.createGroup(name, description || null);
      setGroups((prev) => [...(prev ?? []), g]);
      setName("");
      setDescription("");
      setShowCreate(false);
      notify(`Group "${g.name}" created`);
    } catch {
      notify("Could not create group", "error");
    } finally {
      setBusy(false);
    }
  }

  async function confirmDelete() {
    if (!pendingDelete) return;
    setBusy(true);
    try {
      await adminApi.deleteGroup(pendingDelete.id);
      setGroups((prev) => prev!.filter((x) => x.id !== pendingDelete.id));
      notify(`Group "${pendingDelete.name}" deleted`);
    } catch {
      notify("Could not delete group", "error");
    } finally {
      setBusy(false);
      setPendingDelete(null);
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
  if (!groups) return <LoadingBlock label="Loading groups…" />;

  return (
    <div className="page">
      <PageHeader
        title="Groups"
        subtitle="Group users together to apply the same policies and roles."
        actions={
          <button type="button" className="btn btn-primary" onClick={() => setShowCreate(true)}>
            Create Group
          </button>
        }
      />

      {showCreate && (
        <div className="card">
          <div className="section-header"><h2>Create group</h2></div>
          <form onSubmit={submit} style={{ display: "flex", gap: "8px", alignItems: "flex-end" }}>
            <FormField label="Name">
              <input value={name} onChange={(e) => setName(e.target.value)} required autoFocus />
            </FormField>
            <FormField label="Description (optional)">
              <input value={description} onChange={(e) => setDescription(e.target.value)} />
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

      {groups.length === 0 ? (
        <EmptyState title="No groups yet">Create a group to organize users under shared policies.</EmptyState>
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Description</th>
                <th>Members</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {groups.map((g) => (
                <tr key={g.id}>
                  <td>{g.name}</td>
                  <td>{g.description || "—"}</td>
                  <td>{g.member_count}</td>
                  <td>
                    <button type="button" className="btn btn-danger btn-sm" onClick={() => setPendingDelete(g)}>
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {pendingDelete && (
        <ConfirmDialog
          title={`Delete group "${pendingDelete.name}"?`}
          description={`Removes the group and its ${pendingDelete.member_count} membership link${pendingDelete.member_count === 1 ? "" : "s"}. This cannot be undone.`}
          confirmLabel="Delete"
          danger
          busy={busy}
          onConfirm={() => void confirmDelete()}
          onCancel={() => setPendingDelete(null)}
        />
      )}
    </div>
  );
}
