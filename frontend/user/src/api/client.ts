import { ApiClient } from "@shared/api/client";

export const api = new ApiClient(import.meta.env.VITE_API_BASE_URL ?? "/api");
