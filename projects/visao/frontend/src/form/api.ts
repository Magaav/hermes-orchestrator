import type { FormPayload, Submission, SubmissionSummary, UploadRef } from "./types";

export type SessionUser = {
  id: number;
  email: string;
  name: string;
  picture?: string;
  createdAt: string;
  lastLogin: string;
  roles?: string[];
  capabilities?: string[];
};

type APIErrorBody = { error?: string; message?: string; fields?: string[] };

export class APIError extends Error {
  fields: string[];
  status: number;

  constructor(status: number, body: APIErrorBody) {
    super(body.message || "Não foi possível concluir a operação.");
    this.name = "APIError";
    this.status = status;
    this.fields = body.fields || [];
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: "same-origin",
    ...init,
    headers: init?.body instanceof FormData ? init.headers : { "Content-Type": "application/json", ...init?.headers }
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new APIError(response.status, body);
  return body as T;
}

export const api = {
  session: () => request<{ authenticated: boolean; user: SessionUser | null }>("/api/session"),
  logout: () => request<{ authenticated: boolean }>("/api/session", { method: "DELETE" }),
  list: () => request<{ items: SubmissionSummary[]; count: number }>("/api/submissions"),
  get: (id: string) => request<Submission>(`/api/submissions/${id}`),
  save: (id: string | undefined, status: "draft" | "submitted", payload: FormPayload) => request<Submission>("/api/submissions", {
    method: "POST", body: JSON.stringify({ id: id || "", status, payload })
  }),
  upload: async (file: File) => {
    const data = new FormData();
    data.append("file", file);
    return request<UploadRef>("/api/uploads", { method: "POST", body: data });
  }
};
