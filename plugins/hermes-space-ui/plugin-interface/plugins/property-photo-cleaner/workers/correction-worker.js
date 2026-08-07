self.onmessage = async ({ data }) => {
  if (data?.type === "dispose") return self.close();
  self.postMessage({ id: data.id, error: "Correction worker adapter is not active in this MVP." });
};
