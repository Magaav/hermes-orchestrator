const assert = require("assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { pathToFileURL } = require("url");

const pluginRoot = path.resolve(__dirname, "..");
const sourceDir = path.join(pluginRoot, "public", "modules", "wis");
const artifactsDir = path.join(sourceDir, "artifacts");
const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "wasm-agent-wis-engine-"));
const cameraArtifactSource = fs.readFileSync(path.join(artifactsDir, "camera.js"), "utf8");
const engineSource = fs.readFileSync(path.join(sourceDir, "engine.js"), "utf8");
fs.writeFileSync(path.join(tempDir, "camera.mjs"), cameraArtifactSource);
fs.writeFileSync(path.join(tempDir, "engine.mjs"), engineSource);
const cameraArtifactUrl = pathToFileURL(path.join(tempDir, "camera.mjs")).href;
const engineUrl = pathToFileURL(path.join(tempDir, "engine.mjs")).href;

(async () => {
  let createWisSandbox;
  let claimMediaWriter;
  let createCameraArtifactController;
  let createWisCameraArtifactState;
  let createWisFocusedCameraArtifact;
  let focusedWisCameraSlot;
  let isWisFocusedCameraSurface;
  let createWisCameraPushEndpoints;
  let createWisDefaultPushCameraConfigForSlot;
  let normalizeWisCameraConfigForSlot;
  let wisCameraQualityStreamId;
  let wisCameraPushFramePollMs;
  let wisCameraTimelineFrameClosestToTime;
  let wisCameraTimelineFrameAtRatio;
  let wisCameraTimelinePlaybackStartMs;
  let wisCameraTimelineTargetAtRatio;
  let wisCameraTimelineTimeWindow;
  let wisCameraNextTimelineFrame;
  let wisCameraTimelinePlaybackDelayMs;
  let createWisCameraPendingTimelineSeek;
  let resolveWisCameraPendingTimelineSeek;
  let shouldLoadWisCameraTimeline;
  let formatWisCameraTimelineRange;
  let setWisCameraPlaybackBuffering;
  let setWisCameraPlaybackFrame;
  let startWisCameraPlaybackSeek;
  let stopWisCameraPlaybackState;
  let wisCameraPlaybackClockMs;
  let wisCameraPlaybackMatches;
  let wisCameraPlaybackState;
  let wisCameraRecordedSessionMatches;
  let wisCameraRecordedTimelineTitle;
  let isMediaWriterCurrent;
  try {
    ({ createWisSandbox } = await import(engineUrl));
    ({
      claimMediaWriter,
      createCameraArtifactController,
      createWisCameraArtifactState,
      createWisCameraPendingTimelineSeek,
      createWisCameraPushEndpoints,
      createWisDefaultPushCameraConfigForSlot,
      createWisFocusedCameraArtifact,
      focusedWisCameraSlot,
      formatWisCameraTimelineRange,
      isWisFocusedCameraSurface,
      normalizeWisCameraConfigForSlot,
      setWisCameraPlaybackBuffering,
      setWisCameraPlaybackFrame,
      startWisCameraPlaybackSeek,
      stopWisCameraPlaybackState,
      wisCameraPlaybackClockMs,
      wisCameraPlaybackMatches,
      wisCameraPlaybackState,
      wisCameraRecordedSessionMatches,
      wisCameraRecordedTimelineTitle,
      isMediaWriterCurrent,
      resolveWisCameraPendingTimelineSeek,
      shouldLoadWisCameraTimeline,
      wisCameraTimelineFrameClosestToTime,
      wisCameraNextTimelineFrame,
      wisCameraPushFramePollMs,
      wisCameraQualityStreamId,
      wisCameraTimelineFrameAtRatio,
      wisCameraTimelinePlaybackStartMs,
      wisCameraTimelineTargetAtRatio,
      wisCameraTimelineTimeWindow,
      wisCameraTimelinePlaybackDelayMs,
    } = await import(cameraArtifactUrl));
  } finally {
    fs.rmSync(tempDir, { recursive: true, force: true });
  }
  const sandbox = createWisSandbox();

  let surface = sandbox.inspect();
  assert.strictEqual(surface.schema, "hermes.wasm_agent.wis.surface_state.v1");
  assert.strictEqual(surface.document.id, "counter-app");
  assert.strictEqual(surface.sandbox.noBackend, true);
  assert.strictEqual(surface.sandbox.noIframe, true);
  assert.strictEqual(surface.sandbox.wasmEngine.schema, "hermes.wasm_agent.wis.wasm_engine.v1");
  assert.strictEqual(surface.sandbox.wasmEngine.status, "ready");
  assert.strictEqual(surface.sandbox.wasmEngine.version, 1);
  assert.strictEqual(surface.sandbox.wasmEngine.capabilities.artifactRuntime, true);
  assert.strictEqual(surface.wasm.schema, "hermes.wasm_agent.wis.wasm_engine.v1");
  assert(surface.wasm.nodeCost > 0, "WIS WASM engine should score the materialized tree");
  assert(surface.wasm.layoutColumns >= 1, "WIS WASM engine should provide layout columns");
  assert(surface.nodeCount >= 8, "WIS should expose a DOM-like node tree");
  assert(surface.automation.actions.some((action) => action.targetId === "increment"), "increment action is missing");

  const clickResult = sandbox.act({ type: "click", targetId: "increment" });
  assert.strictEqual(clickResult.ok, true);
  surface = sandbox.inspect();
  assert.strictEqual(surface.state.count, 1);
  assert(surface.recentEvents.some((event) => event.type === "wis.state_changed"), "state change event is missing");

  const cameraResult = sandbox.act({
    type: "configureCamera",
    slot: "cam-1",
    config: { kind: "url", mediaMode: "rtsp-relay-required", url: "rtsp://user:***@192.0.2.20/live", clientLocal: true },
  });
  assert.strictEqual(cameraResult.ok, true);
  surface = sandbox.inspect();
  assert.strictEqual(surface.state.cameras["cam-1"].mediaMode, "rtsp-relay-required");
  assert(surface.recentEvents.some((event) => event.type === "wis.camera_configured"), "camera config event is missing");

  const cameraArtifact = createWisFocusedCameraArtifact({
    slot: "1",
    title: "CAM 1",
    camera: { kind: "push", mediaMode: "rtmp-push-ingest", element: "push-frame", streamId: "cam-1" },
  });
  const cameraSandbox = createWisSandbox(cameraArtifact);
  const cameraSurface = cameraSandbox.inspect();
  assert.strictEqual(cameraArtifact.schema, "hermes.wasm_agent.wis.space.v1");
  assert.strictEqual(isWisFocusedCameraSurface(cameraSurface), true);
  assert.strictEqual(focusedWisCameraSlot(cameraSurface), "cam-1");
  assert.strictEqual(cameraSurface.state.cameras["cam-1"].mediaMode, "rtmp-push-ingest");

  const endpoints = createWisCameraPushEndpoints("cam-2");
  assert.strictEqual(endpoints.frameUrl, "/camera/push-frame?stream_id=cam-2");
  assert.strictEqual(endpoints.replayUrl, "/camera/push-replay?stream_id=cam-2&seconds=300");
  assert.strictEqual(
    createWisCameraPushEndpoints("cam-2", {}, { fromMs: 1234, fps: 8, follow: true }).playbackUrl,
    "/camera/push-playback?stream_id=cam-2&from_ms=1234&fps=8&follow=1"
  );
  const defaultPush = createWisDefaultPushCameraConfigForSlot("2");
  assert.strictEqual(defaultPush.streamId, "cam-2");
  assert.strictEqual(defaultPush.frameUrl, "/camera/push-frame?stream_id=cam-2");
  const normalizedPush = normalizeWisCameraConfigForSlot("cam-1", {
    vendor: "intelbras",
    mode: "portal",
    channel: "1",
  });
  assert.strictEqual(normalizedPush.mediaMode, "rtmp-push-ingest");
  assert.strictEqual(normalizedPush.label, "Intelbras CAM 1 RTMP push");
  assert.strictEqual(wisCameraQualityStreamId("cam-1", { extraStreamId: "cam-1-low" }, "extra"), "cam-1-low");
  assert.strictEqual(wisCameraPushFramePollMs({ fps: 10 }), 100);
  assert.strictEqual(wisCameraPushFramePollMs({ fps: 20 }), 67);
  const frames = [
    { id: "old", timestamp_ms: 1000 },
    { id: "middle", timestamp_ms: 2000 },
    { id: "new", timestamp_ms: 32000 },
  ];
  assert.strictEqual(wisCameraTimelineFrameAtRatio(frames, 0.5).id, "middle");
  const timelineWindow = wisCameraTimelineTimeWindow({
    availableRange: { start_ms: 1000, end_ms: 101000 },
    range: { start_ms: 41000, end_ms: 101000 },
  }, frames, { playbackPosition: 80000 });
  assert.deepStrictEqual(timelineWindow, {
    retentionStart: 1000,
    retentionEnd: 101000,
    visibleStart: 41000,
    visibleEnd: 101000,
    playbackPosition: 80000,
  });
  const visibleSeekFrames = [
    { id: "retention-middle", timestamp_ms: 51000 },
    { id: "visible-middle", timestamp_ms: 71000 },
    { id: "visible-end", timestamp_ms: 101000 },
  ];
  const visibleTarget = wisCameraTimelineTargetAtRatio({
    availableRange: { start_ms: 1000, end_ms: 101000 },
    range: { start_ms: 41000, end_ms: 101000 },
  }, visibleSeekFrames, 0.5);
  assert.strictEqual(visibleTarget.targetTime, 71000);
  assert.strictEqual(visibleTarget.snappedFrame.id, "visible-middle");
  assert.strictEqual(wisCameraTimelineTargetAtRatio({
    availableRange: { start_ms: 1000, end_ms: 101000 },
    range: { start_ms: 41000, end_ms: 101000 },
  }, visibleSeekFrames, 0).snappedFrame.id, "retention-middle");
  assert.strictEqual(wisCameraTimelineTargetAtRatio({
    availableRange: { start_ms: 1000, end_ms: 101000 },
    range: { start_ms: 41000, end_ms: 101000 },
  }, visibleSeekFrames, 1).snappedFrame.id, "visible-end");
  assert.strictEqual(wisCameraTimelinePlaybackStartMs({
    timestamp_ms: 51000,
    snapped_timestamp_ms: 71000,
    seek_target_ms: 74000,
  }), 74000);
  assert.strictEqual(wisCameraTimelinePlaybackStartMs({
    timestamp_ms: 51000,
    snapped_timestamp_ms: 71000,
  }), 71000);
  assert.strictEqual(wisCameraTimelinePlaybackStartMs({
    timestamp_ms: 51000,
  }), 51000);
  assert.strictEqual(wisCameraTimelineFrameClosestToTime(visibleSeekFrames, 100000, { visibleStart: 41000, visibleEnd: 101000 }).id, "visible-end");
  assert.strictEqual(wisCameraTimelineTimeWindow({ range: { start_ms: 9000, end_ms: 1000 } }).visibleStart, 1000);
  assert.strictEqual(wisCameraTimelineTargetAtRatio({ range: { start_ms: 1000, end_ms: 61000 } }, frames, 0.25).targetTime, 16000);
  assert.strictEqual(wisCameraTimelineTargetAtRatio({ range: { start_ms: 1000, end_ms: 61000 } }, frames, 0.75).targetTime, 46000);
  assert.strictEqual(wisCameraNextTimelineFrame(frames, { id: "old" }).id, "middle");
  assert.strictEqual(wisCameraNextTimelineFrame(frames, { timestamp_ms: 2500 }).id, "new");
  assert.strictEqual(wisCameraNextTimelineFrame(frames, { id: "new" }), null);
  assert.strictEqual(wisCameraTimelinePlaybackDelayMs(frames[0], frames[1]), 1000);
  assert.strictEqual(wisCameraTimelinePlaybackDelayMs(frames[1], frames[2]), 1200);
  const pendingSeek = createWisCameraPendingTimelineSeek("cam-1", 1, "live", 1000);
  assert.strictEqual(resolveWisCameraPendingTimelineSeek(pendingSeek, frames, "live").id, "new");
  assert.strictEqual(resolveWisCameraPendingTimelineSeek(pendingSeek, frames, "recorded"), null);
  const pendingVisibleSeek = createWisCameraPendingTimelineSeek("cam-1", { ratio: 0.5 }, "live", 1000);
  assert.strictEqual(resolveWisCameraPendingTimelineSeek(pendingVisibleSeek, visibleSeekFrames, "live", {
    availableRange: { start_ms: 1000, end_ms: 101000 },
    range: { start_ms: 41000, end_ms: 101000 },
  }).id, "visible-middle");
  assert.strictEqual(shouldLoadWisCameraTimeline({ streamId: "cam-1", mode: "live", loadedAt: 1000 }, "cam-1", "live", 2000), false);
  assert.strictEqual(shouldLoadWisCameraTimeline({ streamId: "cam-1", mode: "live", loadedAt: 1000 }, "cam-1", "recorded", 2000), true);
  assert.strictEqual(formatWisCameraTimelineRange(null, "recorded"), "No recordings detected");
  assert.strictEqual(wisCameraRecordedSessionMatches({ id: "session-1", mode: "recorded" }, "session-1"), true);
  assert.strictEqual(wisCameraRecordedSessionMatches({ id: "session-1", mode: "live" }, "session-1"), false);
  assert(wisCameraRecordedTimelineTitle({
    id: "session-1",
    mode: "recorded",
    status: "loading",
    frame: { timestamp_ms: 1000 },
  }).startsWith("Syncing recording from "), "recorded loading title should describe pending sync");
  assert(wisCameraRecordedTimelineTitle({
    id: "session-1",
    mode: "recorded",
    status: "playing",
    frame: { timestamp_ms: 1000 },
    currentWallTime: 2000,
  }).startsWith("Viewing recording: "), "recorded playing title should describe rendered playback");
  const playbackRuntime = createWisCameraArtifactState({});
  const firstPlayback = startWisCameraPlaybackSeek(playbackRuntime, "cam-1", {
    id: "frame-a",
    timestamp_ms: 51000,
    seek_target_ms: 74000,
    url: "/camera/push-archive-frame?stream_id=cam-1&frame=frame-a",
  }, { nowMs: 1000, explicitSeek: true, restart: true });
  assert.strictEqual(firstPlayback.state, "seeking");
  assert.strictEqual(firstPlayback.generation, 1);
  assert.strictEqual(wisCameraPlaybackClockMs(firstPlayback, 1400), 74000);
  const displayedPlayback = setWisCameraPlaybackFrame(playbackRuntime, "cam-1", {
    id: "frame-a-stream",
    timestamp_ms: 74200,
  }, { sessionId: firstPlayback.id, generation: firstPlayback.generation, nowMs: 1500 });
  assert.strictEqual(displayedPlayback.state, "recordedPlaying");
  assert.strictEqual(wisCameraPlaybackClockMs(displayedPlayback, 2500), 75200);
  setWisCameraPlaybackBuffering(playbackRuntime, "cam-1", {
    sessionId: firstPlayback.id,
    generation: firstPlayback.generation,
    nowMs: 1550,
  });
  const streamPlayback = setWisCameraPlaybackFrame(playbackRuntime, "cam-1", {
    id: "frame-a-stream-next",
    timestamp_ms: 74600,
  }, {
    sessionId: firstPlayback.id,
    generation: firstPlayback.generation,
    nowMs: 1600,
    updateClockAnchor: false,
  });
  assert.strictEqual(streamPlayback.lastDisplayedFrameTimeMs, 74600);
  assert.strictEqual(wisCameraPlaybackClockMs(streamPlayback, 2500), 75200);
  const mediaImage = { dataset: {} };
  assert.strictEqual(claimMediaWriter(mediaImage, { kind: "recorded-playback", streamId: "cam-1", generation: 2 }), true);
  assert.strictEqual(isMediaWriterCurrent(mediaImage, { kind: "recorded-playback", streamId: "cam-1", generation: 2 }), true);
  assert.strictEqual(claimMediaWriter(mediaImage, { kind: "live", streamId: "cam-1", generation: 1 }), false);
  assert.strictEqual(isMediaWriterCurrent(mediaImage, { kind: "live", streamId: "cam-1", generation: 1 }), false);
  const secondPlayback = startWisCameraPlaybackSeek(playbackRuntime, "cam-1", {
    id: "frame-b",
    timestamp_ms: 90000,
    seek_target_ms: 90500,
    url: "/camera/push-archive-frame?stream_id=cam-1&frame=frame-b",
  }, { nowMs: 3000, explicitSeek: true, restart: true });
  assert.strictEqual(secondPlayback.generation, 2);
  assert.strictEqual(wisCameraPlaybackMatches(playbackRuntime, "cam-1", {
    sessionId: firstPlayback.id,
    generation: firstPlayback.generation,
  }), false);
  assert.strictEqual(setWisCameraPlaybackFrame(playbackRuntime, "cam-1", {
    id: "late-frame",
    timestamp_ms: 76000,
  }, { sessionId: firstPlayback.id, generation: firstPlayback.generation, nowMs: 3200 }), null);
  assert.strictEqual(wisCameraPlaybackState(playbackRuntime, "cam-1").id, secondPlayback.id);
  stopWisCameraPlaybackState(playbackRuntime, "cam-1");
  assert.strictEqual(wisCameraPlaybackState(playbackRuntime, "cam-1"), null);

  const controllerEvents = [];
  const frameCalls = [];
  let renderCallbacks = [];
  const controllerEnv = {
    console,
    AbortController,
    setTimeout,
    clearTimeout,
    requestAnimationFrame(callback) {
      renderCallbacks.push(callback);
      return renderCallbacks.length;
    },
    cancelAnimationFrame(id) {
      renderCallbacks[id - 1] = null;
    },
  };
  const controller = createCameraArtifactController({
    artifactId: "cam-1",
    documentId: "main",
    env: controllerEnv,
    diagnostics: false,
    recordEvent: (type, payload) => controllerEvents.push({ type, payload }),
    getTimelineModel: () => ({
      streamId: "cam-1",
      mode: "recorded",
      frames: [
        { id: "a", timestamp_ms: 1000, url: "/a.jpg" },
        { id: "b", timestamp_ms: 3000, url: "/b.jpg" },
      ],
      range: { start_ms: 1000, end_ms: 3000 },
    }),
    findSegmentForTime: async (targetTimeMs) => ({ id: "b", timestamp_ms: 3000, seek_target_ms: targetTimeMs, url: "/b.jpg" }),
    loadSegment: async (segment, context) => ({ ...segment, loadedGeneration: context.generation }),
    drawFrameAt: (timestampMs, context) => frameCalls.push({ timestampMs, generation: context.generation }),
  });
  const blockedPlaybackSeek = await controller.seekTo(2000, { source: "playback", reason: "render-loop" });
  assert.strictEqual(blockedPlaybackSeek, null);
  assert(controllerEvents.some((event) => event.type === "camera.seek.blocked.playback_source"), "playback-source seeks must be blocked");
  const loadedSegment = await controller.seekTo(2000, { source: "user", reason: "timeline-pointerup" });
  assert.strictEqual(loadedSegment.loadedGeneration, 1);
  assert(controllerEvents.some((event) => event.type === "camera.seek.start"), "controller seek start should be logged");
  assert(controllerEvents.some((event) => event.type === "camera.render.start"), "controller should start one render loop after seek");
  assert.strictEqual(controller.getState().generation, 1);
  assert(controller.getCurrentPlaybackTimeMs(2500) > 2000, "controller playback clock should advance after seek");
  const duplicateRenderStarts = controllerEvents.filter((event) => event.type === "camera.render.start").length;
  controller.startRenderLoop({ generation: 1, reason: "manual-duplicate-check" });
  assert.strictEqual(controllerEvents.filter((event) => event.type === "camera.render.start").length, duplicateRenderStarts + 1);
  const tick = renderCallbacks.find((callback) => typeof callback === "function");
  assert(tick, "controller render loop should schedule a frame");
  tick(16);
  assert(frameCalls.length >= 1, "render loop should draw from playback clock without seeking");
  assert.strictEqual(controllerEvents.filter((event) => event.type === "camera.seek.start").length, 1, "render loop must not start another seek");
  controller.cleanup("test");

  const snapshotResult = sandbox.act({
    type: "configureCamera",
    slot: "cam-2",
    config: {
      kind: "url",
      mediaMode: "jpeg-snapshot-poll",
      element: "snapshot",
      vendor: "intelbras",
      host: "192.168.1.78",
      channel: "2",
      secretPolicy: "per-device-browser-session",
      shareable: true,
      url: "http://user:***@192.168.1.78/cgi-bin/snapshot.cgi?channel=2",
      clientLocal: true,
    },
  });
  assert.strictEqual(snapshotResult.ok, true);
  surface = sandbox.inspect();
  assert.strictEqual(surface.state.cameras["cam-2"].mediaMode, "jpeg-snapshot-poll");
  assert.strictEqual(surface.state.cameras["cam-2"].shareable, true);

  sandbox.act({ type: "input", targetId: "task-input", value: "Export artifact" });
  sandbox.act({ type: "click", targetId: "add-task" });
  surface = sandbox.inspect();
  assert(surface.state.tasks.includes("Export artifact"), "input-driven state change is missing");

  const exported = sandbox.exportSpace();
  assert.strictEqual(exported.schema, "hermes.wasm_agent.wis.export.v1");
  assert.strictEqual(exported.guarantees.backendDependency, false);
  assert.strictEqual(exported.guarantees.iframePrimaryArchitecture, false);
  assert.strictEqual(exported.guarantees.portableArtifactDefinition, true);
  assert.strictEqual(exported.guarantees.wasmEngine, true);
  assert.strictEqual(exported.space.schema, "hermes.wasm_agent.wis.space.v1");

  console.log("wis engine ok");
})();
