import { api } from "./client";
import type {
  DownloadTokenResponse,
  EnrollConfirmResponse,
  EnrollResponse,
  QuarantineFileDto,
  SessionResponseDto,
  SetupConfirmResponse,
  UserFilePageDto,
} from "@shared/api/types";

// Only endpoints that actually exist on the User listener (section 48) —
// verified against a running `OPENRBI_LISTENER_MODE=user` instance's own
// OpenAPI schema, not assumed from the combined "both" schema.
export const userApi = {
  startSession: () => api.post<SessionResponseDto>("/sessions"),
  mySessions: () => api.get<SessionResponseDto[]>("/sessions/me"),
  getSession: (id: string) => api.get<SessionResponseDto>(`/sessions/${id}`),
  terminateSession: (id: string) => api.post<SessionResponseDto>(`/sessions/${id}/terminate`),
  uploadFile: (sessionId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return api.postForm<{ status: string }>(`/sessions/${sessionId}/uploads`, form);
  },

  myFiles: () => api.get<QuarantineFileDto[]>("/files/me"),
  myFilesPage: (params: URLSearchParams) => api.get<UserFilePageDto>(`/files/me/page?${params.toString()}`),
  requestDownloadToken: (fileId: string) => api.post<DownloadTokenResponse>(`/files/${fileId}/download-token`),
  downloadUrl: (token: string) => `${import.meta.env.VITE_API_BASE_URL ?? "/api"}/files/download/${token}`,

  mfaEnroll: () => api.post<EnrollResponse>("/mfa/enroll"),
  mfaEnrollConfirm: (code: string) => api.post<EnrollConfirmResponse>("/mfa/enroll/confirm", { code }),
  mfaResetSelf: (code: string) => api.post<{ status: string }>("/mfa/reset-self", { code }),
  changePassword: (currentPassword: string, newPassword: string) =>
    api.post<{ status: string; other_sessions_revoked: number }>("/auth/change-password", {
      current_password: currentPassword,
      new_password: newPassword,
    }),
  mfaSetupEnroll: (mfaToken: string) => api.post<EnrollResponse>("/mfa/setup/enroll", { mfa_token: mfaToken }),
  mfaSetupConfirm: (mfaToken: string, code: string) =>
    api.post<SetupConfirmResponse>("/mfa/setup/confirm", { mfa_token: mfaToken, code }),
  mfaVerify: (mfaToken: string, code: string) => api.post("/auth/mfa/verify", { mfa_token: mfaToken, code }),
};

export function displayWebSocketUrl(sessionId: string): string {
  const base = import.meta.env.VITE_API_BASE_URL ?? "/api";
  const absoluteBase = base.startsWith("http") ? new URL(base) : new URL(base, window.location.origin);
  const protocol = absoluteBase.protocol === "https:" ? "wss" : "ws";
  return `${protocol}://${absoluteBase.host}${absoluteBase.pathname.replace(/\/$/, "")}/display/${sessionId}/ws`;
}
