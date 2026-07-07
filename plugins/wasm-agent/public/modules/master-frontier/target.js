export function isMasterFrontierTarget(value, { masterTargetId, frontierNodeId, isAdmin }) {
  const target = String(value || "").trim();
  return Boolean(isAdmin) && (target === masterTargetId || target === frontierNodeId);
}

export function masterFrontierNodeId(value, { masterTargetId, frontierNodeId, fallback, isAdmin }) {
  return isMasterFrontierTarget(value, { masterTargetId, frontierNodeId, isAdmin })
    ? frontierNodeId
    : fallback;
}

export function masterFrontierSelectionTarget({ masterTargetId }) {
  return masterTargetId;
}
