import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { LoadingBlock, ErrorState } from "@shared/components/States";
import { PageHeader } from "@shared/components/PageHeader";
import { DefinitionList } from "@shared/components/DefinitionList";
import { AttachList, type AttachListItem } from "@shared/components/AttachList";
import { useToast } from "@shared/components/Toast";
import { formatDateTime } from "@shared/format";
import type { GroupDetailDto } from "@shared/api/types";
import { adminApi } from "../api/adminApi";

/**
 * The "search a policy, click to add" side of group<->policy assignment —
 * the reverse direction lives on PolicyDetail.tsx. Both call the same
 * attach/detach endpoints (POST/DELETE /admin/policies/{id}/groups/{id}),
 * which already existed and worked — this and PolicyDetail.tsx's group
 * picker are what was actually missing (there was no UI for either
 * direction before this).
 */
export function GroupDetail() {
  const { id } = useParams<{ id: string }>();
  const { notify } = useToast();
  const [group, setGroup] = useState<GroupDetailDto | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    if (!id) return;
    adminApi.getGroup(id).then(setGroup).catch(() => setError("Could not load this group."));
  }, [id]);
  useEffect(load, [load]);

  if (error) return <div className="page"><ErrorState>{error}</ErrorState></div>;
  if (!group) return <LoadingBlock label="Loading group…" />;

  async function searchPolicies(query: string): Promise<AttachListItem[]> {
    const result = await adminApi.listPolicies({ search: query, limit: 10 });
    return result.items.map((p) => ({ id: p.id, label: p.name, meta: p.policy_type }));
  }

  async function addPolicy(policyId: string) {
    if (!id) return;
    setBusy(true);
    try {
      await adminApi.attachToGroup(policyId, id);
      notify("Policy attached");
      load();
    } catch {
      notify("Could not attach this policy", "error");
    } finally {
      setBusy(false);
    }
  }

  async function removePolicy(policyId: string) {
    if (!id) return;
    setBusy(true);
    try {
      await adminApi.detachFromGroup(policyId, id);
      notify("Policy detached");
      load();
    } catch {
      notify("Could not detach this policy", "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page">
      <p><Link to="/groups">← Groups</Link></p>
      <PageHeader title={group.name} subtitle={group.description || "No description provided."} />

      <div className="card">
        <DefinitionList
          items={[
            { label: "Members", value: String(group.member_count) },
            { label: "Created", value: formatDateTime(group.created_at) },
          ]}
        />
      </div>

      <div className="card">
        <div className="section-header">
          <h2>Assigned policies</h2>
        </div>
        <p className="text-muted" style={{ marginTop: "-8px", marginBottom: "16px" }}>
          Every member of this group is subject to every policy attached here. Search by name to attach a published
          or draft policy; removing one here only unlinks it from this group, it doesn't delete the policy.
        </p>
        <AttachList
          entityLabel="policy"
          entityLabelPlural="policies"
          attached={group.policies.map((p) => ({ id: p.id, label: p.name, meta: p.policy_type }))}
          onSearch={searchPolicies}
          onAdd={addPolicy}
          onRemove={removePolicy}
          busy={busy}
          emptyLabel="No policies attached to this group yet."
        />
      </div>
    </div>
  );
}
