import { useEffect, useState } from "react";
import { LoadingBlock, EmptyState, ErrorState } from "@shared/components/States";
import { FormField } from "@shared/components/FormField";
import { useToast } from "@shared/components/Toast";
import type { GroupSummaryDto } from "@shared/api/types";
import { adminApi } from "../api/adminApi";

export function Groups() {
  const { notify } = useToast();
  const [groups, setGroups] = useState<GroupSummaryDto[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);

  function load() {
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
      notify(`Group "${g.name}" created`);
    } catch {
      notify("Could not create group", "error");
    } finally {
      setBusy(false);
    }
  }

  async function remove(g: GroupSummaryDto) {
    if (!window.confirm(`Delete group "${g.name}"? This cannot be undone.`)) return;
    try {
      await adminApi.deleteGroup(g.id);
      setGroups((prev) => prev!.filter((x) => x.id !== g.id));
      notify(`Group "${g.name}" deleted`);
    } catch {
      notify("Could not delete group", "error");
    }
  }

  if (error) return <div className="page"><ErrorState>{error}</ErrorState></div>;
  if (!groups) return <LoadingBlock label="Loading groups…" />;

  return (
    <div className="page">
      <h1>Groups</h1>

      <div className="card">
        <h2 style={{ margin: "0 0 8px", fontSize: "1.1rem" }}>Create group</h2>
        <form onSubmit={submit} style={{ display: "flex", gap: "8px", alignItems: "flex-end" }}>
          <FormField label="Name">
            <input value={name} onChange={(e) => setName(e.target.value)} required />
          </FormField>
          <FormField label="Description (optional)">
            <input value={description} onChange={(e) => setDescription(e.target.value)} />
          </FormField>
          <button type="submit" className="btn btn-primary" disabled={busy} style={{ marginBottom: "16px" }}>
            Create
          </button>
        </form>
      </div>

      {groups.length === 0 ? (
        <EmptyState>No groups yet.</EmptyState>
      ) : (
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
                  <button type="button" className="btn btn-danger btn-sm" onClick={() => void remove(g)}>
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
