export async function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  try {
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
  } finally {
    setTimeout(() => URL.revokeObjectURL(url), 0);
  }
}

export async function exportApproved(items) {
  const approved = items.filter((item) => item.approved && item.output);
  if (approved.length !== 1) {
    throw new Error("ZIP export requires an installed local ZIP module; export one approved image in this build.");
  }
  return downloadBlob(approved[0].output, `property-cleaned-${approved[0].name}`);
}
