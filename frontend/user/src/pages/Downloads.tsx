import { useEffect, useState } from "react";
import { StatusBadge } from "@shared/components/StatusBadge";
import { LoadingBlock, EmptyState, ErrorState } from "@shared/components/States";
import { useToast } from "@shared/components/Toast";
import { formatBytes, formatDateTime } from "@shared/format";
import type { QuarantineFileDto } from "@shared/api/types";
import { userApi } from "../api/userApi";

export function Downloads() {
  const { notify } = useToast();
  const [files, setFiles] = useState<QuarantineFileDto[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);

  useEffect(() => {
    userApi
      .myFiles()
      .then(setFiles)
      .catch(() => setError("Could not load your downloads. The backend may be unavailable."));
  }, []);

  async function handleDownload(file: QuarantineFileDto) {
    setDownloadingId(file.id);
    try {
      // Real single-use token flow (section 17) — never a direct storage
      // path. The token is consumed by the browser navigation itself.
      const { token } = await userApi.requestDownloadToken(file.id);
      window.location.assign(userApi.downloadUrl(token));
    } catch {
      notify("Could not get a download link for this file", "error");
    } finally {
      setDownloadingId(null);
    }
  }

  if (error) return <div className="page"><ErrorState>{error}</ErrorState></div>;
  if (!files) return <LoadingBlock label="Loading downloads…" />;

  return (
    <div className="page">
      <h1>Downloads</h1>
      {files.length === 0 ? (
        <EmptyState>You haven't downloaded any files yet.</EmptyState>
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>File</th>
                <th>Type</th>
                <th>Size</th>
                <th>Scan</th>
                <th>Status</th>
                <th>Received</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {files.map((f) => (
                <tr key={f.id}>
                  <td>{f.original_name}</td>
                  <td className="mono" style={{ fontSize: "0.82rem" }}>{f.detected_mime ?? "—"}</td>
                  <td>{formatBytes(f.size_bytes)}</td>
                  <td><StatusBadge value={f.scanner_status} /></td>
                  <td><StatusBadge value={f.status} /></td>
                  <td>{formatDateTime(f.created_at)}</td>
                  <td>
                    {f.status === "RELEASED" ? (
                      <button
                        type="button"
                        className="btn btn-secondary btn-sm"
                        onClick={() => void handleDownload(f)}
                        disabled={downloadingId === f.id}
                      >
                        {downloadingId === f.id ? <span className="spinner" /> : null} Download
                      </button>
                    ) : (
                      <span className="text-muted" style={{ fontSize: "0.82rem" }}>
                        {f.status === "QUARANTINED" ? "Awaiting review" : "Not available"}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
