export type FieldType = "text" | "email" | "tel" | "date" | "currency" | "number" | "select" | "textarea";

export type FieldOption = { value: string; label: string };

export type FormField = {
  key: string;
  label: string;
  type?: FieldType;
  required?: boolean;
  placeholder?: string;
  options?: FieldOption[];
  wide?: boolean;
  help?: string;
};

export type UploadRef = {
  id: string;
  name: string;
  size: number;
  contentType: string;
  url: string;
};

export type ChecklistEntry = {
  status: "pending" | "received" | "validated" | "not_applicable";
  notes: string;
  files: UploadRef[];
};

export type FormPayload = {
  version: 1;
  values: Record<string, string>;
  checklist: Record<string, ChecklistEntry>;
};

export type Submission = {
  id: string;
  status: "draft" | "submitted";
  atendimento: string;
  corretor: string;
  payload: FormPayload;
  createdAt: string;
  updatedAt: string;
  submittedAt?: string;
};

export type SubmissionSummary = Omit<Submission, "payload">;
