const clean = (value = "") => String(value ?? "").trim();

export function masterFrontierRouteProofFromFinal(payload = {}) {
  const diagnostics = payload.diagnostics && typeof payload.diagnostics === "object" ? payload.diagnostics : {};
  const evidence = Array.isArray(payload.evidence) ? payload.evidence : [];
  const routeEvidence = evidence.find((item) => item?.kind === "route.contract") || null;
  const routeId = clean(payload.route_id || diagnostics.route_id || routeEvidence?.subject?.replace(/^route:/, ""));
  if (!routeId) return null;
  return {
    schema: "hermes.wasm_agent.server_route_proof.v1",
    source: "server-final",
    route_id: routeId,
    evidence: routeEvidence ? {
      id: clean(routeEvidence.id),
      kind: "route.contract",
      summary: clean(routeEvidence.summary),
      detail_ref: clean(routeEvidence.detail_ref),
    } : null,
    performance: diagnostics.performance || null,
  };
}
