import { APIError } from "../form/api";

export async function uploadProfilePicture(file: File) {
  const body = new FormData();
  body.append("picture", file);
  const response = await fetch("/api/profile/picture", {
    method: "PUT",
    credentials: "same-origin",
    body
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw new APIError(response.status, result);
  return result as { picture: string };
}
