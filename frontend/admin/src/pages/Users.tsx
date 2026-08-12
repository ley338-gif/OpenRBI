import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { StatusBadge } from "@shared/components/StatusBadge";
import { LoadingBlock, EmptyState, ErrorState } from "@shared/components/States";
import { ErrorBanner, FormField } from "@shared/components/FormField";
import { PageHeader } from "@shared/components/PageHeader";
import { TableToolbar } from "@shared/components/TableToolbar";
import { useToast } from "@shared/components/Toast";
import { ApiError } from "@shared/api/client";
import type { GroupSummaryDto, Role, UserSummaryDto } from "@shared/api/types";
import { adminApi } from "../api/adminApi";

export function Users() {
  const { notify } = useToast();
  const [users, setUsers] = useState<UserSummaryDto[] | null>(null);
  const [groups, setGroups] = useState<GroupSummaryDto[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [search, setSearch] = useState("");
  const [roleFilter, setRoleFilter] = useState("");

  function load() {
    setError(null);
    Promise.all([adminApi.listUsers(), adminApi.listGroups()])
      .then(([u, g]) => {
        setUsers(u);
        setGroups(g);
      })
      .catch(() => setError("Could not load users. The backend may be unavailable."));
  }

  useEffect(load, []);

  async function toggleActive(user: UserSummaryDto) {
    try {
      const updated = user.is_active ? await adminApi.disableUser(user.id) : await adminApi.enableUser(user.id);
      setUsers((prev) => prev!.map((u) => (u.id === updated.id ? updated : u)));
      notify(`${updated.username} ${updated.is_active ? "enabled" : "disabled"}`);
    } catch {
      notify("Could not update this user", "error");
    }
  }

  // Client-side only — GET /admin/users has no search/filter params today
  // (a documented gap, same as Sessions' filter bar).
  const filtered = useMemo(() => {
    if (!users) return [];
    return users.filter((u) => {
      if (roleFilter && u.role !== roleFilter) return false;
      if (search && !u.username.toLowerCase().includes(search.toLowerCase())) return false;
      return true;
    });
  }, [users, search, roleFilter]);

  if (error) {
    return (
      <div className="page">
        <ErrorState action={<button type="button" className="btn btn-secondary btn-sm" onClick={load}>Try again</button>}>
          {error}
        </ErrorState>
      </div>
    );
  }
  if (!users) return <LoadingBlock label="Loading users…" />;

  return (
    <div className="page">
      <PageHeader
        title="Users"
        subtitle="Manage accounts, roles, and MFA across the organization."
        actions={
          <button type="button" className="btn btn-primary" onClick={() => setShowCreate(true)}>
            Create User
          </button>
        }
      />

      {showCreate && (
        <CreateUserForm
          groups={groups}
          onClose={() => setShowCreate(false)}
          onCreated={(u) => {
            setUsers((prev) => [...(prev ?? []), u]);
            setShowCreate(false);
            notify(`User "${u.username}" created`);
          }}
        />
      )}

      {users.length === 0 ? (
        <EmptyState title="No users yet">Create the first account to get started.</EmptyState>
      ) : (
        <>
          <TableToolbar
            search={search}
            onSearchChange={setSearch}
            searchPlaceholder="Search by username…"
            filters={
              <select value={roleFilter} onChange={(e) => setRoleFilter(e.target.value)} aria-label="Filter by role">
                <option value="">All roles</option>
                <option value="USER">USER</option>
                <option value="SECURITY_REVIEWER">SECURITY_REVIEWER</option>
                <option value="ADMIN">ADMIN</option>
              </select>
            }
            onRefresh={load}
          />
          {filtered.length === 0 ? (
            <EmptyState title="No matching users">Try a different search or filter.</EmptyState>
          ) : (
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Username</th>
                    <th>Role</th>
                    <th>Status</th>
                    <th>Groups</th>
                    <th>MFA</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((u) => (
                    <tr key={u.id}>
                      <td>
                        <Link to={`/users/${u.id}`}>{u.username}</Link>
                      </td>
                      <td>{u.role}</td>
                      <td><StatusBadge value={u.is_active ? "ACTIVE" : "DISABLED"} /></td>
                      <td>{u.groups.join(", ") || "—"}</td>
                      <td><StatusBadge value={u.mfa_enabled ? "ENABLED" : "NOT ENABLED"} /></td>
                      <td>
                        <button type="button" className="btn btn-secondary btn-sm" onClick={() => void toggleActive(u)}>
                          {u.is_active ? "Disable" : "Enable"}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function CreateUserForm({
  groups,
  onClose,
  onCreated,
}: {
  groups: GroupSummaryDto[];
  onClose: () => void;
  onCreated: (u: UserSummaryDto) => void;
}) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>("USER");
  const [groupIds, setGroupIds] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (username.trim().length === 0) {
      setError("Username is required.");
      return;
    }
    if (password.length < 8) {
      setError("Password must be at least 8 characters — the backend enforces its own rules regardless.");
      return;
    }
    setBusy(true);
    try {
      const u = await adminApi.createUser({ username, password, role, group_ids: groupIds });
      onCreated(u);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Could not create user.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <h2 style={{ margin: "0 0 8px", fontSize: "1.1rem" }}>Create user</h2>
      {error && <ErrorBanner>{error}</ErrorBanner>}
      <form onSubmit={submit}>
        <FormField label="Username">
          <input value={username} onChange={(e) => setUsername(e.target.value)} required autoFocus />
        </FormField>
        <FormField label="Initial password" hint="The backend, not this form, is authoritative on password rules.">
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        </FormField>
        <FormField label="Role">
          <select value={role} onChange={(e) => setRole(e.target.value as Role)}>
            <option value="USER">USER</option>
            <option value="SECURITY_REVIEWER">SECURITY_REVIEWER</option>
            <option value="ADMIN">ADMIN</option>
          </select>
        </FormField>
        <FormField label="Groups">
          <select
            multiple
            value={groupIds}
            onChange={(e) => setGroupIds(Array.from(e.target.selectedOptions, (o) => o.value))}
          >
            {groups.map((g) => (
              <option key={g.id} value={g.id}>
                {g.name}
              </option>
            ))}
          </select>
        </FormField>
        <div style={{ display: "flex", gap: "8px" }}>
          <button type="submit" className="btn btn-primary" disabled={busy}>
            {busy ? <span className="spinner" /> : null} Create
          </button>
          <button type="button" className="btn btn-secondary" onClick={onClose} disabled={busy}>
            Cancel
          </button>
        </div>
      </form>
    </div>
  );
}
