export function homeCleanWidgetLayout(layout = {}, panel = "home") {
  if (panel !== "home") return layout;
  const timeline = layout.timeline && typeof layout.timeline === "object" ? layout.timeline : {};
  return {
    ...layout,
    timeline: { ...timeline, minimized: true, maximized: false },
  };
}

export function initialVisibleWidgetPosition({ visibleRect, boardRect, widgetRect, distance = 1, inset = 0 } = {}) {
  const scale = Math.max(Number(distance) || 1, 0.01);
  const width = Math.max(0, Number(widgetRect?.width) || 0) / scale;
  const height = Math.max(0, Number(widgetRect?.height) || 0) / scale;
  const visibleLeft = (Number(visibleRect?.left) - Number(boardRect?.left)) / scale;
  const visibleTop = (Number(visibleRect?.top) - Number(boardRect?.top)) / scale;
  const visibleWidth = Math.max(0, Number(visibleRect?.width) || 0) / scale;
  const visibleHeight = Math.max(0, Number(visibleRect?.height) || 0) / scale;
  const boardWidth = Math.max(width, Number(boardRect?.width) / scale || 0);
  const boardHeight = Math.max(height, Number(boardRect?.height) / scale || 0);
  const edge = Math.max(0, Number(inset) || 0);
  return {
    left: Math.round(Math.min(Math.max(edge, visibleLeft + (visibleWidth - width) / 2), Math.max(edge, boardWidth - width - edge))),
    top: Math.round(Math.min(Math.max(edge, visibleTop + (visibleHeight - height) / 2), Math.max(edge, boardHeight - height - edge))),
  };
}
