import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { StatusBadge } from "@shared/components/StatusBadge";
import { ConfirmDialog } from "@shared/components/ConfirmDialog";
import { LoadingBlock, ErrorState } from "@shared/components/States";
import { FormField } from "@shared/components/FormField";
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
  const navigate = useNavigate();
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
      <h1>{file.original_name}</h1>

      <div className="card">
        <dl className="detail-grid">
          <div><dt>User</dt><dd><Link to={`/users/${file.user_id}`}>{file.user_id.slice(0, 8)}</Link></dd></div>
          <div><dt>Session</dt><dd><Link to={`/sessions/${file.session_id}`} className="mono">{file.session_id.slice(0, 8)}</Link></dd></div>
          <div><dt>Declared MIME</dt><dd>{file.declared_mime ?? "—"}</dd></div>
          <div><dt>Detected MIME</dt><dd>{file.detected_mime ?? "—"}</dd></div>
          <div><dt>Extension</dt><dd>{file.extension ?? "—"}</dd></div>
          <div><dt>Size</dt><dd>{formatBytes(file.size_bytes)}</dd></div>
          <div><dt>SHA-256</dt><dd className="mono" style={{ fontSize: "0.78rem" }}>{file.sha256}</dd></div>
          <div><dt>Initial URL</dt><dd style={{ wordBreak: "break-all" }}>{file.initial_url ?? "—"}</dd></div>
          <div><dt>Final URL</dt><dd style={{ wordBreak: "break-all" }}>{file.final_url ?? "—"}</dd></div>
          <div><dt>Source host</dt><dd>{file.source_host ?? "—"}</dd></div>
          <div><dt>TLS used</dt><dd>{file.tls_used === null ? "—" : file.tls_used ? "Yes" : "No"}</dd></div>
          <div><dt>Scanner status</dt><dd><StatusBadge value={file.scanner_status} /></dd></div>
          <div><dt>Scanner result</dt><dd>{file.scanner_result ?? "—"}</dd></div>
          <div><dt>Policy decision</dt><dd>{file.policy_action ? <StatusBadge value={file.policy_action} /> : "—"}</dd></div>
          <div><dt>Status</dt><dd><StatusBadge value={file.status} /></dd></div>
          <div><dt>Created</dt><dd>{formatDateTime(file.created_at)}</dd></div>
          {file.reviewed_at && (
            <>
              <div><dt>Reviewed</dt><dd>{formatDateTime(file.reviewed_at)}</dd></div>
              <div><dt>Review comment</dt><dd>{file.review_comment ?? "—"}</dd></div>
            </>
          )}
        </dl>

        {reviewable && (
          <>
            <FormField label="Review comment (optional)">
              <input value={comment} onChange={(e) => setComment(e.target.value)} />
            </FormField>
            <div style={{ display: "flex", gap: "8px" }}>
              <button type="button" className="btn btn-primary" onClick={() => setPending("release")}>
                Release
              </button>
              <button type="button" className="btn btn-danger" onClick={() => setPending("reject")}>
                Reject
              </button>
            </div>
          </>
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

      <button type="button" className="btn btn-secondary btn-sm" onClick={() => navigate(-1)} style={{ marginTop: "16px" }}>
        Back
      </button>
    </div>
  );
}
