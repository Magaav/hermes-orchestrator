import { APIError } from "../form/api";

export type Preferences = {
  theme: "day" | "night";
  touchEnabled: boolean;
  notifications: boolean;
};

export type Inventory = {
  generatedAt: string;
  database: {
    path: string;
    bytes: number;
    tables: Array<{ name: string; rows: number; columns: number }>;
  };
  storage: Array<{
    id: string;
    label: string;
    path: string;
    files: number;
    bytes: number;
    available: boolean;
  }>;
};

export type AuditEntry = {
  id: number;
  date: string;
  user: string;
  type: "create" | "update" | "delete";
  table: string;
  recordId: string;
  reason: string;
  json: unknown;
};

export type Capability = { id: string; label: string; group: string };
export type Role = {
  id: string;
  name: string;
  color: string;
  priority: number;
  system: boolean;
  permissions: string[];
};
export type ManagedUser = {
  email: string;
  enabled: boolean;
  name: string;
  picture?: string;
  lastLogin?: string;
  roles: string[];
};
export type AdminData = { capabilities: Capability[]; roles: Role[]; users: ManagedUser[] };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: "same-origin",
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers }
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new APIError(response.status, body);
  return body as T;
}

export function applyPreferences(value: Preferences) {
  document.documentElement.dataset.theme = value.theme;
  document.documentElement.dataset.touch = value.touchEnabled ? "enabled" : "disabled";
}

export const settingsAPI = {
  preferences: () => request<Preferences>("/api/settings/preferences"),
  savePreferences: (value: Preferences) => request<Preferences>("/api/settings/preferences", {
    method: "PUT", body: JSON.stringify(value)
  }),
  inventory: () => request<Inventory>("/api/settings/inventory"),
  audit: () => request<{ items: AuditEntry[]; count: number }>("/api/settings/audit?limit=250"),
  admin: () => request<AdminData>("/api/settings/admin"),
  createRole: (value: Omit<Role, "id" | "system">) => request<Role>("/api/settings/admin/roles", {
    method: "POST", body: JSON.stringify(value)
  }),
  updateRole: (id: string, value: Omit<Role, "id" | "system">) => request<Role>(`/api/settings/admin/roles/${encodeURIComponent(id)}`, {
    method: "PUT", body: JSON.stringify(value)
  }),
  updateRoleActions: (id: string, permissions: string[]) => request<Role>(`/api/settings/admin/roles/${encodeURIComponent(id)}/actions`, {
    method: "PUT", body: JSON.stringify({ permissions })
  }),
  deleteRole: (id: string) => request<{ deleted: boolean }>(`/api/settings/admin/roles/${encodeURIComponent(id)}`, {
    method: "DELETE"
  }),
  saveUser: (email: string, roles: string[]) => request<ManagedUser>("/api/settings/admin/users", {
    method: "POST", body: JSON.stringify({ email, roles })
  }),
  updateUser: (email: string, roles: string[]) => request<ManagedUser>(`/api/settings/admin/users/${encodeURIComponent(email)}`, {
    method: "PUT", body: JSON.stringify({ email, roles })
  }),
  deleteUser: (email: string) => request<{ deleted: boolean }>(`/api/settings/admin/users/${encodeURIComponent(email)}`, {
    method: "DELETE"
  })
};
