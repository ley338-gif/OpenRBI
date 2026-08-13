import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { StatusBadge } from "@shared/components/StatusBadge";
import { ConfirmDialog } from "@shared/components/ConfirmDialog";
import { LoadingBlock, ErrorState } from "@shared/components/States";
import { FormField } from "@shared/components/FormField";
import { PageHeader } from "@shared/components/PageHeader";
import { DefinitionList } from "@shared/components/DefinitionList";
import { useToast } from "@shared/components/Toast";
import { formatBytes, formatDateTime } from "@shared/format";
import type { QuarantineFileDto } from "@shared/api/types";
import { adminApi } from "../api/adminApi";

/**
 * Metadata only, never a file preview (section 33) — this MVP has no safe
 * file-preview mechanism, so this page only ever shows the captured
 * metadata a reviewer needs, matching app/api/admin_quarantine.py's own
 * response shape exactly.
 */
export function QuarantineDetail() {
  const { id } = useParams<{ id: string }>();
  const { notify } = useToast();
  const [file, setFile] = useState<QuarantineFileDto | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [comment, setComment] = useState("");
  const [pending, setPending] = useState<"release" | "reject" | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!id) return;
    adminApi.getQuarantineFile(id).then(setFile).catch(() => setError("Could not load this file."));
  }, [id]);

  async function confirm() {
    if (!pending || !id) return;
    setBusy(true);
    try {
      const updated = pending === "release" ? await adminApi.releaseFile(id, comment) : await adminApi.rejectFile(id, comment);
      setFile(updated);
      notify(pending === "release" ? "File released" : "File rejected");
    } catch {
      notify("Could not complete this review", "error");
    } finally {
      setBusy(false);
      setPending(null);
    }
  }

  if (error) return <div className="page"><ErrorState>{error}</ErrorState></div>;
  if (!file) return <LoadingBlock label="Loading file…" />;

  const reviewable = file.status === "QUARANTINED";

  return (
    <div className="page">
      <p><Link to="/quarantine">← Quarantine</Link></p>
      <PageHeader
        title={file.original_name}
        meta={<StatusBadge value={file.status} />}
        actions={
          reviewable && (
            <>
              <button type="button" className="btn btn-primary" onClick={() => setPending("release")}>
                Release
              </button>
              <button type="button" className="btn btn-danger" onClick={() => setPending("reject")}>
                Reject
              </button>
            </>
          )
        }
      />

      <div className="card">
        <div className="section-header"><h2>File information</h2></div>
        <DefinitionList
          items={[
            { label: "Declared MIME", value: file.declared_mime ?? "—" },
            { label: "Detected MIME", value: file.detected_mime ?? "—" },
            { label: "Extension", value: file.extension ?? "—" },
            { label: "Size", value: formatBytes(file.size_bytes) },
            { label: "SHA-256", value: <span className="mono" style={{ fontSize: "0.78rem" }}>{file.sha256}</span> },
            { label: "Created", value: formatDateTime(file.created_at) },
          ]}
        />
      </div>

      <div className="card">
        <div className="section-header"><h2>Source</h2></div>
        <DefinitionList
          items={[
            { label: "User", value: <Link to={`/users/${file.user_id}`}>{file.user_id.slice(0, 8)}</Link> },
            { label: "Session", value: <Link to={`/sessions/${file.session_id}`} className="mono">{file.session_id.slice(0, 8)}</Link> },
            { label: "Initial URL", value: <span style={{ wordBreak: "break-all" }}>{file.initial_url ?? "—"}</span> },
            { label: "Final URL", value: <span style={{ wordBreak: "break-all" }}>{file.final_url ?? "—"}</span> },
            { label: "Source host", value: file.source_host ?? "—" },
            { label: "TLS used", value: file.tls_used === null ? "—" : file.tls_used ? "Yes" : "No" },
          ]}
        />
      </div>

      <div className="card">
        <div className="section-header"><h2>Security scan</h2></div>
        <DefinitionList
          items={[
            { label: "Scanner status", value: <StatusBadge value={file.scanner_status} /> },
            { label: "Scanner result", value: file.scanner_result ?? "—" },
          ]}
        />
      </div>

      <div className="card">
        <div className="section-header"><h2>Policy decision</h2></div>
        <DefinitionList
          items={[{ label: "Decision", value: file.policy_action ? <StatusBadge value={file.policy_action} /> : "—" }]}
        />
      </div>

      <div className="card">
        <div className="section-header"><h2>Review</h2></div>
        {file.reviewed_at ? (
          <DefinitionList
            items={[
              { label: "Reviewed", value: formatDateTime(file.reviewed_at) },
              { label: "Review comment", value: file.review_comment ?? "—" },
            ]}
          />
        ) : reviewable ? (
          <FormField label="Review comment (optional)">
            <input value={comment} onChange={(e) => setComment(e.target.value)} />
          </FormField>
        ) : (
          <p className="text-muted">This file has not been reviewed.</p>
        )}
      </div>

      {pending && (
        <ConfirmDialog
          title={pending === "release" ? `Release "${file.original_name}"?` : `Reject "${file.original_name}"?`}
          description={
            pending === "release"
              ? "The user will be able to retrieve this file with a single-use download link."
              : "The file will never be released to the user. This cannot be undone."
          }
          confirmLabel={pending === "release" ? "Release" : "Reject"}
          danger={pending === "reject"}
          busy={busy}
          onConfirm={() => void confirm()}
          onCancel={() => setPending(null)}
        />
      )}
    </div>
  );
}
