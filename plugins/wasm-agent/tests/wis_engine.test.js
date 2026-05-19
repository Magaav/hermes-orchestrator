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
  let WIS_CAMERA_TIMELINE_OWNER_STATES;
  let WIS_CAMERA_ARTIFACT_BUILD;
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
  let renderWisCameraPushArchiveFrame;
  let selectWisCameraPlaybackFrame;
  let shouldLoadWisCameraTimeline;
  let formatWisCameraTimelineRange;
  let setWisCameraPlaybackBuffering;
  let setWisCameraPlaybackFrame;
  let pauseWisCameraPlaybackState;
  let resumeWisCameraPlaybackState;
  let startWisCameraPlaybackSeek;
  let stopWisCameraPlaybackState;
  let wisCameraPlaybackClockMs;
  let wisCameraPlaybackMatches;
  let wisCameraPlaybackState;
  let wisCameraRecordedOwnsTimeline;
  let wisCameraTimelineOwnerState;
  let wisCameraActivePlaybackLoop;
  let wisCameraRecordedSessionMatches;
  let wisCameraRecordedTimelineTitle;
  let isMediaWriterCurrent;
  let mediaStreamWriterData;
  let sampleWisCameraPerf;
  let setWisCameraVisibilityState;
  let rememberWisCameraLastGoodFrameFromImage;
  let releaseMediaStreamWriter;
  let wisCameraPerformanceBudget;
  let wisCameraLastGoodFrame;
  try {
    ({ createWisSandbox } = await import(engineUrl));
	    ({
	      WIS_CAMERA_ARTIFACT_BUILD,
	      WIS_CAMERA_TIMELINE_OWNER_STATES,
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
      pauseWisCameraPlaybackState,
      resumeWisCameraPlaybackState,
      setWisCameraPlaybackBuffering,
      setWisCameraPlaybackFrame,
      startWisCameraPlaybackSeek,
      stopWisCameraPlaybackState,
      wisCameraPlaybackClockMs,
      wisCameraPlaybackMatches,
      wisCameraPlaybackState,
      wisCameraRecordedOwnsTimeline,
      wisCameraTimelineOwnerState,
      wisCameraActivePlaybackLoop,
      wisCameraRecordedSessionMatches,
      wisCameraRecordedTimelineTitle,
      isMediaWriterCurrent,
      mediaStreamWriterData,
      sampleWisCameraPerf,
      setWisCameraVisibilityState,
      rememberWisCameraLastGoodFrameFromImage,
      releaseMediaStreamWriter,
      wisCameraPerformanceBudget,
      renderWisCameraPushArchiveFrame,
      selectWisCameraPlaybackFrame,
      wisCameraLastGoodFrame,
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
  const budgetRuntime = createWisCameraArtifactState({});
  setWisCameraVisibilityState(budgetRuntime, "cam-budget", { visible: true, focused: true, ratio: 1 });
  assert.strictEqual(wisCameraPerformanceBudget(budgetRuntime, "cam-budget", { mode: "recorded" }).tier, "focused");
  assert.strictEqual(wisCameraPerformanceBudget(budgetRuntime, "cam-budget", { mode: "recorded" }).recordedVisualFps, 12);
  setWisCameraVisibilityState(budgetRuntime, "cam-budget", { visible: true, focused: false, ratio: 0.5 });
  assert.strictEqual(wisCameraPerformanceBudget(budgetRuntime, "cam-budget", { mode: "recorded" }).tier, "visible");
  assert.strictEqual(wisCameraPerformanceBudget(budgetRuntime, "cam-budget", { mode: "recorded" }).recordedVisualFps, 4);
  setWisCameraVisibilityState(budgetRuntime, "cam-budget", { visible: false, focused: false, ratio: 0 });
  const offscreenBudget = wisCameraPerformanceBudget(budgetRuntime, "cam-budget", { mode: "recorded" });
  assert.strictEqual(offscreenBudget.tier, "offscreen");
  assert.strictEqual(offscreenBudget.allowVisualWork, false);
  setWisCameraVisibilityState(budgetRuntime, "cam-budget", { visible: true, focused: true, ratio: 1, pageHidden: true });
  const backgroundBudget = wisCameraPerformanceBudget(budgetRuntime, "cam-budget", { mode: "recorded" });
  assert.strictEqual(backgroundBudget.tier, "background");
  assert.strictEqual(backgroundBudget.allowNetworkWork, false);
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
  assert.strictEqual(shouldLoadWisCameraTimeline({ streamId: "cam-1", mode: "live", loading: true, loadingStartedAt: 2000 }, "cam-1", "live", 2500), false);
  assert.strictEqual(shouldLoadWisCameraTimeline({ streamId: "cam-1", mode: "live", loading: true, loadingStartedAt: 1000 }, "cam-1", "live", 32000), true);
  assert.strictEqual(shouldLoadWisCameraTimeline({ streamId: "cam-1", mode: "live", loading: true }, "cam-1", "live", 32000), true);
  assert.strictEqual(formatWisCameraTimelineRange(null, "recorded"), "No recordings detected");
  assert.strictEqual(wisCameraRecordedSessionMatches({ id: "session-1", mode: "recorded" }, "session-1"), true);
  assert.strictEqual(wisCameraRecordedSessionMatches({ id: "session-1", mode: "live" }, "session-1"), false);
  assert(wisCameraRecordedTimelineTitle({
    id: "session-1",
    mode: "recorded",
    status: "loading",
    frame: { timestamp_ms: 1000 },
  }).startsWith("Seeking recording: "), "recorded loading title should describe pending seek");
  assert(wisCameraRecordedTimelineTitle({
    id: "session-1",
    mode: "recorded",
    status: "playing",
    frame: { timestamp_ms: 1000 },
    currentWallTime: 2000,
  }).startsWith("Viewing recording: "), "recorded playing title should describe rendered playback");
  assert(wisCameraRecordedTimelineTitle({
    id: "session-1",
    mode: "recorded",
    status: "rebuffering",
    frame: { timestamp_ms: 1000 },
    currentWallTime: 2000,
  }).startsWith("Rebuffering recording from "), "recorded rebuffering title should be honest about stream starvation");
  const playbackRuntime = createWisCameraArtifactState({});
  const firstPlayback = startWisCameraPlaybackSeek(playbackRuntime, "cam-1", {
    id: "frame-a",
    timestamp_ms: 51000,
    seek_target_ms: 74000,
    url: "/camera/push-archive-frame?stream_id=cam-1&frame=frame-a",
  }, { nowMs: 1000, explicitSeek: true, restart: true });
  assert.strictEqual(firstPlayback.state, "seeking");
  assert.strictEqual(firstPlayback.generation, 1);
  assert.strictEqual(firstPlayback.ownerState, WIS_CAMERA_TIMELINE_OWNER_STATES.RECORDED_SEEKING);
  assert.strictEqual(firstPlayback.requestedSeekTimestampMs, 74000, "first live-to-recorded click must persist the clicked timestamp");
  assert.strictEqual(firstPlayback.persistedSeekTimestampMs, 74000, "persisted seek timestamp must not become the nearest/archive frame timestamp");
  assert.notStrictEqual(firstPlayback.persistedSeekTimestampMs, 51000, "first click must not jump back to the archive frame beginning");
  assert.strictEqual(wisCameraTimelineOwnerState(playbackRuntime, "cam-1"), WIS_CAMERA_TIMELINE_OWNER_STATES.RECORDED_SEEKING);
  assert.strictEqual(wisCameraRecordedOwnsTimeline(playbackRuntime, "cam-1"), true);
  assert.strictEqual(firstPlayback.firstRecordedFrameDisplayed, false);
  assert.strictEqual(wisCameraPlaybackClockMs(firstPlayback, 1400), 74000);
  const initialBuffering = setWisCameraPlaybackBuffering(playbackRuntime, "cam-1", {
    sessionId: firstPlayback.id,
    generation: firstPlayback.generation,
    nowMs: 1200,
  });
  assert.strictEqual(initialBuffering.status, "buffering");
  assert.strictEqual(initialBuffering.clockPaused, true);
  assert.strictEqual(wisCameraTimelineOwnerState(playbackRuntime, "cam-1"), WIS_CAMERA_TIMELINE_OWNER_STATES.RECORDED_SEEKING);
  const displayedPlayback = setWisCameraPlaybackFrame(playbackRuntime, "cam-1", {
    id: "frame-a-stream",
    timestamp_ms: 74200,
  }, { sessionId: firstPlayback.id, generation: firstPlayback.generation, nowMs: 1500 });
  assert.strictEqual(displayedPlayback.state, "recordedPlaying");
  assert.strictEqual(displayedPlayback.ownerState, WIS_CAMERA_TIMELINE_OWNER_STATES.RECORDED_PLAYING);
  assert.strictEqual(wisCameraTimelineOwnerState(playbackRuntime, "cam-1"), WIS_CAMERA_TIMELINE_OWNER_STATES.RECORDED_PLAYING);
  assert.strictEqual(displayedPlayback.firstRecordedFrameDisplayed, true);
  assert.strictEqual(displayedPlayback.clockPaused, false);
  assert.strictEqual(wisCameraPlaybackClockMs(displayedPlayback, 2500), 75200);
  assert.strictEqual(displayedPlayback.anchorRecordingTimeMs, 74200, "autoplay timebase must anchor to the first committed frame");
  assert.strictEqual(displayedPlayback.persistedSeekTimestampMs, 74000, "first committed frame must not overwrite the clicked seek timestamp");
  const rebufferingPlayback = setWisCameraPlaybackBuffering(playbackRuntime, "cam-1", {
    sessionId: firstPlayback.id,
    generation: firstPlayback.generation,
    nowMs: 1550,
  });
  assert.strictEqual(rebufferingPlayback.status, "rebuffering");
  assert.strictEqual(rebufferingPlayback.clockPaused, false);
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
  const committedFrameTimes = [74200, 74600];
  [75000, 75400, 75800].forEach((timestampMs, index) => {
    const committed = setWisCameraPlaybackFrame(playbackRuntime, "cam-1", {
      id: `frame-a-stream-${index + 3}`,
      timestamp_ms: timestampMs,
    }, {
      sessionId: firstPlayback.id,
      generation: firstPlayback.generation,
      nowMs: 1700 + (index * 100),
      updateClockAnchor: false,
    });
    committedFrameTimes.push(committed.lastDisplayedFrameTimeMs);
  });
  assert.strictEqual(new Set(committedFrameTimes).size, 5, "recorded playback should commit multiple distinct frame timestamps after autoplay starts");
  assert.strictEqual(wisCameraTimelineOwnerState(playbackRuntime, "cam-1"), WIS_CAMERA_TIMELINE_OWNER_STATES.RECORDED_PLAYING);
  const pausedPlayback = pauseWisCameraPlaybackState(playbackRuntime, "cam-1", {
    sessionId: firstPlayback.id,
    generation: firstPlayback.generation,
    nowMs: 2600,
    reason: "unit-pause",
  });
  const pausedClock = wisCameraPlaybackClockMs(pausedPlayback, 3600);
  assert.strictEqual(pausedPlayback.ownerState, WIS_CAMERA_TIMELINE_OWNER_STATES.RECORDED_PAUSED, "pause should keep recorded ownership but switch owner state to paused");
  assert.strictEqual(pausedClock, pausedPlayback.currentWallTime, "paused playback clock must stop advancing");
  assert.strictEqual(pausedPlayback.lastDisplayedFrameTimeMs, 75800, "pause must not change the visible recorded frame");
  const resumedPlayback = resumeWisCameraPlaybackState(playbackRuntime, "cam-1", {
    sessionId: firstPlayback.id,
    generation: firstPlayback.generation,
    nowMs: 3600,
    reason: "unit-resume",
  });
  assert.strictEqual(resumedPlayback.ownerState, WIS_CAMERA_TIMELINE_OWNER_STATES.RECORDED_PLAYING, "resume should return to recorded playing ownership");
  assert.strictEqual(wisCameraPlaybackClockMs(resumedPlayback, 4600), pausedClock + 1000, "resume should continue at 1x from the paused timestamp");
  assert.notStrictEqual(resumedPlayback.anchorRecordingTimeMs, 51000, "resume must not restart from the beginning");
  const healthySelection = selectWisCameraPlaybackFrame([
    { timestampMs: 99600, packetSeq: 1 },
    { timestampMs: 100100, packetSeq: 2 },
  ], 100000);
  assert.strictEqual(healthySelection.action, "display");
  assert.strictEqual(healthySelection.index, 1, "adaptive playback should choose the closest healthy frame, not the oldest queued frame");
  assert.strictEqual(healthySelection.status, "recordedPlaying");
  const catchUpSelection = selectWisCameraPlaybackFrame([
    { timestampMs: 97000, packetSeq: 1 },
    { timestampMs: 98200, packetSeq: 2 },
    { timestampMs: 99000, packetSeq: 3 },
  ], 100000);
  assert.strictEqual(catchUpSelection.index, 2, "adaptive playback should skip stale backlog when all frames are behind");
  assert.strictEqual(catchUpSelection.status, "catching-up");
  const futureSelection = selectWisCameraPlaybackFrame([
    { timestampMs: 100700, packetSeq: 4 },
  ], 100000);
  assert.strictEqual(futureSelection.action, "hold", "adaptive playback should hold briefly for future-only frames");
  const mediaImage = { dataset: {} };
  assert.strictEqual(claimMediaWriter(mediaImage, { kind: "recorded-playback", streamId: "cam-1", generation: 2 }), true);
  assert.strictEqual(isMediaWriterCurrent(mediaImage, { kind: "recorded-playback", streamId: "cam-1", generation: 2 }), true);
  assert.strictEqual(claimMediaWriter(mediaImage, { kind: "live", streamId: "cam-1", generation: 1 }), false);
  assert.strictEqual(isMediaWriterCurrent(mediaImage, { kind: "live", streamId: "cam-1", generation: 1 }), false);
  const freshLiveImage = { dataset: {} };
  assert.strictEqual(claimMediaWriter(freshLiveImage, { kind: "live", streamId: "cam-1", generation: 0 }), false, "recorded stream owner should fence out newly-created live images");
  assert.strictEqual(mediaStreamWriterData("cam-1").kind, "recorded-playback");
  assert.strictEqual(releaseMediaStreamWriter("cam-1", { kind: "recorded-playback", generation: 2 }), true);
  assert.strictEqual(claimMediaWriter(freshLiveImage, { kind: "live", streamId: "cam-1", generation: 0 }), true);
  assert.strictEqual(releaseMediaStreamWriter("cam-1", { kind: "live", generation: 0 }), true);
	  const makeFakeElement = (tagName) => {
	    const classes = new Set();
	    const element = {
	      tagName: tagName.toUpperCase(),
	      dataset: {},
	      className: "",
	      isConnected: true,
	      children: [],
	      currentSrc: "",
	      alt: "",
	      complete: true,
	      naturalWidth: tagName.toLowerCase() === "img" ? 352 : 0,
	      naturalHeight: tagName.toLowerCase() === "img" ? 240 : 0,
	      style: {
	        setProperty(name, value) { this[name] = value; },
	        getPropertyValue(name) { return this[name] || ""; },
	        removeProperty(name) { delete this[name]; },
	      },
	      classList: {
		add(name) { classes.add(name); },
		remove(name) { classes.delete(name); },
		contains(name) { return classes.has(name); },
	      },
      append(...nodes) {
        nodes.forEach((node) => {
          this.children = this.children.filter((child) => child !== node);
          node.isConnected = true;
          node.parentElement = this;
          this.children.push(node);
        });
      },
      querySelectorAll(selector) {
        if (selector === ".wis-camera-image, .wis-camera-video") {
          return this.children.filter((child) => (
            String(child.className || "").includes("wis-camera-image")
            || String(child.className || "").includes("wis-camera-video")
          ));
        }
        if (selector === ".wis-camera-message, .wis-camera-fallback") {
          return this.children.filter((child) => (
            String(child.className || "").includes("wis-camera-message")
            || String(child.className || "").includes("wis-camera-fallback")
          ));
        }
        return [];
	      },
	      addEventListener() {},
	      decode() { return Promise.resolve(); },
	      remove() {
		this.isConnected = false;
		if (this.parentElement?.children) {
		  this.parentElement.children = this.parentElement.children.filter((child) => child !== this);
		}
	      },
	    };
	    Object.defineProperty(element, "src", {
	      get() { return this._src || ""; },
	      set(value) {
	        this._src = String(value || "");
	        this.currentSrc = this._src;
	        this.complete = Boolean(this._src);
	        if (this._src && this.tagName === "IMG") {
	          this.naturalWidth = this.naturalWidth || 352;
	          this.naturalHeight = this.naturalHeight || 240;
	        }
	      },
		    });
		    return element;
		  };
  const makePlaybackMultipartChunk = (frames, boundary = "frame", options = {}) => {
    const encoder = new TextEncoder();
    const parts = [];
    const includeTerminator = options.includeTerminator !== false;
    const pushText = (text) => parts.push(encoder.encode(text));
    const pushBytes = (bytes) => parts.push(bytes instanceof Uint8Array ? bytes : Uint8Array.from(bytes || []));
    frames.forEach((frame, index) => {
      const bytes = frame.bytes || Uint8Array.from([0xff, 0xd8, index + 1, 0xff, 0xd9]);
      pushText(`--${boundary}\r\nContent-Type: image/jpeg\r\nContent-Length: ${bytes.length}\r\nX-Frame-Timestamp-Ms: ${frame.timestampMs}\r\nX-Frame-Id: ${frame.id || `frame-${index}`}\r\n\r\n`);
      pushBytes(bytes);
      pushText("\r\n");
    });
    if (includeTerminator) pushText(`--${boundary}--\r\n`);
    const totalLength = parts.reduce((total, part) => total + part.length, 0);
    const chunk = new Uint8Array(totalLength);
    let offset = 0;
    parts.forEach((part) => {
      chunk.set(part, offset);
      offset += part.length;
    });
    return chunk;
  };
  const flushMicrotasks = async (count = 8) => {
    for (let index = 0; index < count; index += 1) await Promise.resolve();
  };
  assert.strictEqual(WIS_CAMERA_ARTIFACT_BUILD, "PLAYPAUSE_TRACE_20260519_002", "camera artifact build marker should be exported for browser cache verification");
  const imageRuntime = createWisCameraArtifactState({});
  const imageElement = makeFakeElement("div");
  const imagePipeline = renderWisCameraPushArchiveFrame(imageRuntime, {
    element: imageElement,
    streamId: "cam-1",
    slot: "cam-1",
    camera: { label: "CAM 1" },
    frame: {
      id: "frame-image",
      timestamp_ms: 82000,
      seek_target_ms: 83000,
      url: "/camera/push-archive-frame?stream_id=cam-1&frame=frame-image",
    },
    force: true,
    archiveFrameUrl: "/camera/push-archive-frame?stream_id=cam-1&frame=frame-image&t=1",
    playbackUrl: "/camera/push-playback?stream_id=cam-1&from_ms=83000&fps=15&follow=0",
    document: { createElement: makeFakeElement },
    env: {
      setTimeout() { return 1; },
      clearTimeout() {},
    },
  });
  assert(imagePipeline?.image, "camera.js should own the recorded playback image element");
	  assert.strictEqual(imagePipeline.image.dataset.wisPendingPlaybackFrameMs, "83000");
	  assert.strictEqual(imagePipeline.image.dataset.wisMediaOwner, "recorded-playback");
	  assert.strictEqual(wisCameraPlaybackState(imageRuntime, "cam-1").mode, "recorded");
	  assert(imageElement.children.includes(imagePipeline.image), "image pipeline should attach media inside the camera surface");
	  assert.strictEqual(imageElement.querySelectorAll(".wis-camera-image, .wis-camera-video").length, 2, "recorded playback should keep a front/back image buffer pair");
	  assert(imageElement.querySelectorAll(".wis-camera-image, .wis-camera-video").some((media) => media.dataset.wisBufferRole === "back"), "recorded playback should create a hidden decode buffer");
  releaseMediaStreamWriter("cam-1", { kind: "recorded-playback", generation: imagePipeline.session.generation });
  const frozenRuntime = createWisCameraArtifactState({});
  const frozenLiveImage = makeFakeElement("img");
  frozenLiveImage.className = "wis-camera-image wis-camera-stream wis-camera-push";
  frozenLiveImage.src = "/camera/push-frame?stream_id=cam-freeze&t=1";
  frozenLiveImage.currentSrc = frozenLiveImage.src;
  frozenLiveImage.dataset.wisPlaybackStream = "live";
  frozenLiveImage.dataset.wisMediaOwner = "live";
  rememberWisCameraLastGoodFrameFromImage(frozenRuntime, "cam-freeze", frozenLiveImage);
  assert.strictEqual(wisCameraLastGoodFrame(frozenRuntime, "cam-freeze").src, frozenLiveImage.src);
  const rebuiltElement = makeFakeElement("div");
  const frozenPipeline = renderWisCameraPushArchiveFrame(frozenRuntime, {
    element: rebuiltElement,
    streamId: "cam-freeze",
    slot: "cam-freeze",
    camera: { label: "CAM Freeze" },
    frame: {
      id: "freeze-target",
      timestamp_ms: 120000,
      seek_target_ms: 121000,
      url: "/camera/push-archive-frame?stream_id=cam-freeze&frame=freeze-target",
    },
    force: true,
    document: { createElement: makeFakeElement },
    env: {
      setTimeout() { return 1; },
      clearTimeout() {},
    },
	  });
	  assert.strictEqual(frozenPipeline.image.src, frozenLiveImage.src, "rebuilt recorded surfaces must seed from the last good live frame instead of blanking");
	  assert(!frozenPipeline.image.className.includes("is-buffering"), "pending recorded image must stay visibly frozen, not hidden with opacity");
	  assert.strictEqual(rebuiltElement.querySelectorAll(".wis-camera-image, .wis-camera-video").length, 2, "rebuilt recorded surfaces should keep front/back buffers");
	  releaseMediaStreamWriter("cam-freeze", { kind: "recorded-playback", generation: frozenPipeline.session.generation });
  const reuseRuntime = createWisCameraArtifactState({});
  const reuseElement = makeFakeElement("div");
  const visibleImage = makeFakeElement("img");
  visibleImage.className = "wis-camera-image wis-camera-stream wis-camera-push";
  visibleImage.src = "/camera/push-frame?stream_id=cam-reuse&t=2";
  visibleImage.currentSrc = visibleImage.src;
  reuseElement.append(visibleImage);
  const reusePipeline = renderWisCameraPushArchiveFrame(reuseRuntime, {
    element: reuseElement,
    streamId: "cam-reuse",
    slot: "cam-reuse",
    camera: { label: "CAM Reuse" },
    frame: {
      id: "reuse-target",
      timestamp_ms: 130000,
      seek_target_ms: 131000,
      url: "/camera/push-archive-frame?stream_id=cam-reuse&frame=reuse-target",
    },
    force: true,
    document: { createElement: makeFakeElement },
    env: {
      setTimeout() { return 1; },
      clearTimeout() {},
    },
  });
	  assert.strictEqual(reusePipeline.image, visibleImage, "recorded seek should reuse the existing image node while acquiring ownership");
	  assert.strictEqual(visibleImage.src, "/camera/push-frame?stream_id=cam-reuse&t=2", "reused media node must keep its last visible frame until a decoded replacement is ready");
	  assert.strictEqual(reuseElement.children.filter((child) => child === visibleImage).length, 1, "reusing the media node must not duplicate or remount it");
	  assert.strictEqual(reuseElement.querySelectorAll(".wis-camera-image, .wis-camera-video").length, 2, "reused recorded media should add exactly one back buffer");
	  releaseMediaStreamWriter("cam-reuse", { kind: "recorded-playback", generation: reusePipeline.session.generation });
	  const slowRuntime = createWisCameraArtifactState({});
	  const slowElement = makeFakeElement("div");
	  const slowFront = makeFakeElement("img");
	  slowFront.className = "wis-camera-image wis-camera-stream wis-camera-push";
	  slowFront.src = "/camera/push-frame?stream_id=cam-slow&t=2";
	  slowElement.append(slowFront);
	  const decodeResolvers = [];
	  const slowDocument = {
	    createElement(tagName) {
	      const element = makeFakeElement(tagName);
	      if (tagName === "img") {
	        element.decode = () => new Promise((resolve) => decodeResolvers.push(resolve));
	      }
	      return element;
	    },
	  };
	  const slowPipeline = renderWisCameraPushArchiveFrame(slowRuntime, {
	    element: slowElement,
	    streamId: "cam-slow",
	    slot: "cam-slow",
	    camera: { label: "CAM Slow" },
	    frame: {
	      id: "slow-target",
	      timestamp_ms: 135000,
	      seek_target_ms: 136000,
	      url: "/camera/push-archive-frame?stream_id=cam-slow&frame=slow-target",
	    },
	    force: true,
	    archiveFrameUrl: "/camera/push-archive-frame?stream_id=cam-slow&frame=slow-target&t=1",
	    document: slowDocument,
	    env: {
	      document: slowDocument,
	      setTimeout() { return 1; },
	      clearTimeout() {},
	    },
	  });
	  const slowDisplay = slowPipeline.displayArchiveFrame("unit-test");
	  await Promise.resolve();
	  const slowMediaBeforeDecode = slowElement.querySelectorAll(".wis-camera-image, .wis-camera-video");
	  assert.strictEqual(slowMediaBeforeDecode[0].src, "/camera/push-frame?stream_id=cam-slow&t=2", "front buffer must keep the last good frame while the replacement decodes");
	  assert.strictEqual(slowMediaBeforeDecode[1].src, "/camera/push-archive-frame?stream_id=cam-slow&frame=slow-target&t=1", "back buffer should receive the new source during decode");
	  assert.strictEqual(slowMediaBeforeDecode[0].dataset.wisPlaybackFrameMs || "", "", "visible timestamp must not advance before decode handoff");
	  const slowPendingSample = sampleWisCameraPerf(slowRuntime, "cam-slow", {}, () => {}, { force: true });
	  assert(slowPendingSample.pendingDecodesPerCamera <= 1, "recorded playback should expose at most one pending decode per camera");
	  decodeResolvers.shift()();
	  assert.strictEqual(await slowDisplay, true);
		  const slowMediaAfterDecode = slowElement.querySelectorAll(".wis-camera-image, .wis-camera-video");
		  assert.strictEqual(slowMediaAfterDecode[0].src, "/camera/push-archive-frame?stream_id=cam-slow&frame=slow-target&t=1", "decoded back buffer should be promoted to the visible front");
		  assert.strictEqual(slowMediaAfterDecode[0].dataset.wisPlaybackFrameMs, "136000");
		  releaseMediaStreamWriter("cam-slow", { kind: "recorded-playback", generation: slowPipeline.session.generation });
  const firstFrameRuntime = createWisCameraArtifactState({});
  const firstFrameElement = makeFakeElement("div");
  const requestedSeekMs = 141000;
  const firstStreamFrameMs = requestedSeekMs + 250;
  const heldFutureDecision = selectWisCameraPlaybackFrame([{ timestampMs: firstStreamFrameMs }], requestedSeekMs, {
    targetFrameMs: 67,
    maxFutureWaitMs: 500,
  });
  assert.strictEqual(heldFutureDecision.action, "hold", "the selector should still hold normal future frames outside the first-frame seek handoff");
  const playbackChunk = makePlaybackMultipartChunk([{ id: "first-future", timestampMs: firstStreamFrameMs }]);
  let firstFrameFetchCount = 0;
  let firstFrameReadCount = 0;
  const objectUrls = [];
  const firstFrameEvents = [];
  const firstFramePipeline = renderWisCameraPushArchiveFrame(firstFrameRuntime, {
    element: firstFrameElement,
    streamId: "cam-first",
    slot: "cam-first",
    camera: { label: "CAM First" },
    frame: {
      id: "first-target",
      timestamp_ms: firstStreamFrameMs,
      seek_target_ms: requestedSeekMs,
      url: "/camera/push-archive-frame?stream_id=cam-first&frame=first-target",
    },
    force: true,
    playbackUrl: "/camera/push-playback?stream_id=cam-first&from_ms=141000&fps=15&follow=0",
    document: { createElement: makeFakeElement },
    onMediaEvent: (event, payload) => firstFrameEvents.push({ event, payload }),
    env: {
      AbortController,
      TextEncoder,
      TextDecoder,
      Blob,
      URL: {
        createObjectURL(blob) {
          const url = `blob:first-frame-${objectUrls.length + 1}`;
          objectUrls.push({ url, blob });
          return url;
        },
        revokeObjectURL() {},
      },
      location: { href: "http://localhost/" },
      document: { createElement: makeFakeElement },
      setTimeout() { return 21; },
      clearTimeout() {},
      setInterval() { return 22; },
      clearInterval() {},
      requestAnimationFrame(callback) {
        callback();
        return 23;
      },
      fetch: async () => {
        firstFrameFetchCount += 1;
        return {
          ok: true,
          status: 200,
          headers: { get: () => "multipart/x-mixed-replace; boundary=frame" },
          body: {
            getReader: () => ({
              read: async () => {
                firstFrameReadCount += 1;
                if (firstFrameReadCount === 1) return { value: playbackChunk, done: false };
                return { value: undefined, done: true };
              },
            }),
          },
        };
      },
    },
  });
  firstFramePipeline.startPlaybackStream();
  await flushMicrotasks();
  const firstFrameSession = wisCameraPlaybackState(firstFrameRuntime, "cam-first");
  assert.strictEqual(firstFrameFetchCount, 1, "first recorded seek should start exactly one playback reader");
  assert.strictEqual(firstFrameSession.firstRecordedFrameDisplayed, true, "a slightly-future first recorded frame must be accepted to start the playback clock");
  assert.strictEqual(firstFrameSession.lastDisplayedFrameTimeMs, firstStreamFrameMs, "the first accepted stream frame should be committed as the clock anchor");
  assert(firstFrameEvents.some((entry) => entry.event === "camera.media.best_frame_selected" && entry.payload?.reason === "first-frame-after-seek"), "the recorded scheduler should label the first-frame seek handoff");
  assert(firstFrameEvents.some((entry) => entry.event === "camera.visual.frame_commit" && entry.payload?.decodedOk === true), "the accepted first stream frame should produce a decoded recorded commit");
  assert.strictEqual(wisCameraTimelineOwnerState(firstFrameRuntime, "cam-first"), WIS_CAMERA_TIMELINE_OWNER_STATES.RECORDED_PLAYING, "first decoded playback frame must transition ownership to recorded playing");
	  assert.strictEqual(firstFrameElement.querySelectorAll(".wis-camera-image, .wis-camera-video")[0].dataset.wisMediaOwner, "recorded-playback", "the accepted first frame must commit to the recorded visible layer");
	  const firstFramePerf = sampleWisCameraPerf(firstFrameRuntime, "cam-first", {}, () => {}, { force: true });
	  assert.strictEqual(firstFramePerf.activePlaybackLoops, 1, "first-frame seek playback must keep one active recorded loop");
	  assert.strictEqual(firstFramePerf.playbackReaderCreatedCount, 1, "reader creation should be counted");
	  assert.strictEqual(firstFramePerf.playbackChunksReceived, 1, "stream chunks should be counted");
	  assert.strictEqual(firstFramePerf.playbackFramesParsed, 1, "parsed playback frames should be counted");
	  assert.strictEqual(firstFramePerf.playbackFramesCommitted, 1, "committed playback frames should be counted");
	  assert.strictEqual(firstFramePerf.playbackReaderDoneCount, 1, "clean reader completion should be counted");
	  assert.strictEqual(firstFramePerf.playbackReaderLastDoneReason, "end-of-archive", "finite recorded streams should report an explicit archive end reason");
	  assert(objectUrls.length >= 1, "recorded stream frames should be committed through decoded object URLs");
	  stopWisCameraPlaybackState(firstFrameRuntime, "cam-first");
	  releaseMediaStreamWriter("cam-first", { kind: "recorded-playback", generation: firstFramePipeline.session.generation });
	  const continuityRuntime = createWisCameraArtifactState({});
	  setWisCameraVisibilityState(continuityRuntime, "cam-continuity", { visible: true, focused: true, ratio: 1 });
	  const continuityElement = makeFakeElement("div");
	  const continuityObjectUrls = [];
	  const continuityChunk = makePlaybackMultipartChunk(Array.from({ length: 5 }, (_value, index) => ({
	    id: `continuity-${index + 1}`,
	    timestampMs: 160000 + (index * 80),
	  })));
	  let continuityReadCount = 0;
	  const continuityPipeline = renderWisCameraPushArchiveFrame(continuityRuntime, {
	    element: continuityElement,
	    streamId: "cam-continuity",
	    slot: "cam-continuity",
	    camera: { label: "CAM Continuity" },
	    frame: {
	      id: "continuity-target",
	      timestamp_ms: 160000,
	      seek_target_ms: 160000,
	      url: "/camera/push-archive-frame?stream_id=cam-continuity&frame=continuity-target",
	    },
	    force: true,
	    playbackUrl: "/camera/push-playback?stream_id=cam-continuity&from_ms=160000&fps=15&follow=0",
	    document: { createElement: makeFakeElement },
	    env: {
	      AbortController,
	      TextEncoder,
	      TextDecoder,
	      Blob,
	      URL: {
	        createObjectURL(blob) {
	          const url = `blob:continuity-${continuityObjectUrls.length + 1}`;
	          continuityObjectUrls.push({ url, blob });
	          return url;
	        },
	        revokeObjectURL() {},
	      },
	      location: { href: "http://localhost/" },
	      document: { createElement: makeFakeElement },
	      setTimeout: globalThis.setTimeout.bind(globalThis),
	      clearTimeout: globalThis.clearTimeout.bind(globalThis),
	      setInterval: globalThis.setInterval.bind(globalThis),
	      clearInterval: globalThis.clearInterval.bind(globalThis),
	      requestAnimationFrame(callback) {
	        callback();
	        return 26;
	      },
	      fetch: async () => ({
	        ok: true,
	        status: 200,
	        headers: { get: () => "multipart/x-mixed-replace; boundary=frame" },
	        body: {
	          getReader: () => ({
	            read: async () => {
	              continuityReadCount += 1;
	              if (continuityReadCount === 1) return { value: continuityChunk, done: false };
	              return { value: undefined, done: true };
	            },
	          }),
	        },
	      }),
	    },
	  });
	  continuityPipeline.startPlaybackStream();
	  await flushMicrotasks(40);
	  await new Promise((resolve) => globalThis.setTimeout(resolve, 500));
	  await flushMicrotasks(20);
	  const continuityPerf = sampleWisCameraPerf(continuityRuntime, "cam-continuity", {}, () => {}, { force: true });
	  assert.strictEqual(continuityPerf.playbackReaderCreatedCount, 1, "continuity playback should create one reader");
	  assert.strictEqual(continuityPerf.playbackChunksReceived, 1, "a multipart chunk containing several frames should be counted once as a chunk");
	  assert.strictEqual(continuityPerf.playbackFramesParsed, 5, "the reader loop must parse all frames in a multipart chunk");
	  assert.strictEqual(continuityPerf.playbackFramesCommitted, 5, "the scheduler must continue committing frames after the first stream frame");
	  assert.strictEqual(wisCameraPlaybackState(continuityRuntime, "cam-continuity").lastDisplayedFrameTimeMs, 160320);
	  stopWisCameraPlaybackState(continuityRuntime, "cam-continuity");
	  releaseMediaStreamWriter("cam-continuity", { kind: "recorded-playback", generation: continuityPipeline.session.generation });
	  const chunkedRuntime = createWisCameraArtifactState({});
	  setWisCameraVisibilityState(chunkedRuntime, "cam-chunked", { visible: true, focused: true, ratio: 1 });
	  const chunkedElement = makeFakeElement("div");
	  const chunkedObjectUrls = [];
	  const chunkedChunks = Array.from({ length: 5 }, (_value, index) => makePlaybackMultipartChunk([{
	    id: `chunked-${index + 1}`,
	    timestampMs: 170000 + (index * 80),
	  }], "frame", { includeTerminator: false }));
	  let chunkedReadIndex = 0;
	  const chunkedPipeline = renderWisCameraPushArchiveFrame(chunkedRuntime, {
	    element: chunkedElement,
	    streamId: "cam-chunked",
	    slot: "cam-chunked",
	    camera: { label: "CAM Chunked" },
	    frame: {
	      id: "chunked-target",
	      timestamp_ms: 170000,
	      seek_target_ms: 170000,
	      url: "/camera/push-archive-frame?stream_id=cam-chunked&frame=chunked-target",
	    },
	    force: true,
	    playbackUrl: "/camera/push-playback?stream_id=cam-chunked&from_ms=170000&fps=15&follow=0",
	    document: { createElement: makeFakeElement },
	    env: {
	      AbortController,
	      TextEncoder,
	      TextDecoder,
	      Blob,
	      URL: {
	        createObjectURL(blob) {
	          const url = `blob:chunked-${chunkedObjectUrls.length + 1}`;
	          chunkedObjectUrls.push({ url, blob });
	          return url;
	        },
	        revokeObjectURL() {},
	      },
	      location: { href: "http://localhost/" },
	      document: { createElement: makeFakeElement },
	      setTimeout: globalThis.setTimeout.bind(globalThis),
	      clearTimeout: globalThis.clearTimeout.bind(globalThis),
	      setInterval: globalThis.setInterval.bind(globalThis),
	      clearInterval: globalThis.clearInterval.bind(globalThis),
	      requestAnimationFrame(callback) {
	        callback();
	        return 27;
	      },
	      fetch: async () => ({
	        ok: true,
	        status: 200,
	        headers: { get: () => "multipart/x-mixed-replace; boundary=frame" },
	        body: {
	          getReader: () => ({
	            read: async () => {
	              if (chunkedReadIndex < chunkedChunks.length) {
	                const value = chunkedChunks[chunkedReadIndex];
	                chunkedReadIndex += 1;
	                return { value, done: false };
	              }
	              return { value: undefined, done: true };
	            },
	          }),
	        },
	      }),
	    },
	  });
	  chunkedPipeline.startPlaybackStream();
	  await flushMicrotasks(40);
	  await new Promise((resolve) => globalThis.setTimeout(resolve, 650));
	  await flushMicrotasks(20);
	  const chunkedPerf = sampleWisCameraPerf(chunkedRuntime, "cam-chunked", {}, () => {}, { force: true });
	  const chunkedSession = wisCameraPlaybackState(chunkedRuntime, "cam-chunked");
	  assert.strictEqual(chunkedPerf.playbackReaderCreatedCount, 1, "chunked playback should create one reader");
	  assert.strictEqual(chunkedPerf.playbackChunksReceived, 5, "separate playback stream reads must be counted as five chunks");
	  assert.strictEqual(chunkedPerf.playbackFramesParsed, 5, "the reader loop must parse one frame from each chunk");
	  assert.strictEqual(chunkedPerf.playbackFramesCommitted, 5, "the scheduler must commit separate stream chunks after the first frame");
	  assert.strictEqual(chunkedPerf.playbackReaderDoneCount, 1, "a finite recorded archive stream should report a clean end");
	  assert.strictEqual(chunkedPerf.playbackReaderLastDoneReason, "end-of-archive", "a finite recorded archive stream should report end-of-archive explicitly");
	  assert.strictEqual(chunkedSession.lastDisplayedFrameTimeMs, 170320);
	  assert.strictEqual(chunkedSession.status, "ended", "finite playback must end explicitly instead of remaining recorded-playing with no reader");
	  assert.strictEqual(wisCameraTimelineOwnerState(chunkedRuntime, "cam-chunked"), WIS_CAMERA_TIMELINE_OWNER_STATES.RECORDED_PAUSED);
	  stopWisCameraPlaybackState(chunkedRuntime, "cam-chunked");
	  releaseMediaStreamWriter("cam-chunked", { kind: "recorded-playback", generation: chunkedPipeline.session.generation });
	  const loopRuntime = createWisCameraArtifactState({});
  const loopElement = makeFakeElement("div");
  let playbackFetchCount = 0;
  const loopEnv = {
    AbortController,
    TextEncoder,
    TextDecoder,
    location: { href: "http://localhost/" },
    setTimeout() { return 10; },
    clearTimeout() {},
    setInterval() { return 11; },
    clearInterval() {},
    requestAnimationFrame(callback) {
      callback();
      return 12;
    },
    fetch: async () => {
      playbackFetchCount += 1;
      return {
        ok: true,
        headers: { get: () => "multipart/x-mixed-replace; boundary=frame" },
        body: {
          getReader: () => ({
            read: () => new Promise(() => {}),
          }),
        },
      };
    },
  };
  const loopFrame = {
    id: "loop-target",
    timestamp_ms: 140000,
    seek_target_ms: 141000,
    url: "/camera/push-archive-frame?stream_id=cam-loop&frame=loop-target",
  };
  const loopPipeline = renderWisCameraPushArchiveFrame(loopRuntime, {
    element: loopElement,
    streamId: "cam-loop",
    slot: "cam-loop",
    camera: { label: "CAM Loop" },
    frame: loopFrame,
    force: true,
    playbackUrl: "/camera/push-playback?stream_id=cam-loop&from_ms=141000&fps=15&follow=0",
    document: { createElement: makeFakeElement },
    env: loopEnv,
  });
  loopPipeline.startPlaybackStream();
  await Promise.resolve();
  assert.strictEqual(playbackFetchCount, 1, "first recorded playback render should start one stream reader");
  const duplicateLoopPipeline = renderWisCameraPushArchiveFrame(loopRuntime, {
    element: loopElement,
    streamId: "cam-loop",
    slot: "cam-loop",
    camera: { label: "CAM Loop" },
    frame: loopFrame,
    force: true,
    playbackUrl: "/camera/push-playback?stream_id=cam-loop&from_ms=141000&fps=15&follow=0",
    document: { createElement: makeFakeElement },
    env: loopEnv,
  });
  duplicateLoopPipeline.startPlaybackStream();
  await Promise.resolve();
  assert.strictEqual(playbackFetchCount, 1, "same recorded session render must not start a duplicate stream reader");
  assert.strictEqual(wisCameraActivePlaybackLoop(loopRuntime, "cam-loop").generation, loopPipeline.session.generation);
  const perfSamples = [];
  const perfSample = sampleWisCameraPerf(loopRuntime, "cam-loop", {}, (event, payload) => perfSamples.push({ event, payload }), { force: true });
  assert.strictEqual(perfSample.activePlaybackLoops, 1, "perf sample should expose one active playback loop");
  assert.strictEqual(perfSample.activeReaders, 1, "perf sample should expose one active reader");
  assert.strictEqual(perfSamples[0].event, "camera.perf.sample");
  stopWisCameraPlaybackState(loopRuntime, "cam-loop");
  releaseMediaStreamWriter("cam-loop", { kind: "recorded-playback", generation: loopPipeline.session.generation });
  const rapidRuntime = createWisCameraArtifactState({});
  const rapidElement = makeFakeElement("div");
  let rapidFetchCount = 0;
  let rapidAbortCount = 0;
  class CountingAbortController extends AbortController {
    abort(reason) {
      if (!this.signal.aborted) rapidAbortCount += 1;
      return super.abort(reason);
    }
  }
  const rapidEnv = {
    AbortController: CountingAbortController,
    TextEncoder,
    TextDecoder,
    location: { href: "http://localhost/" },
    setTimeout() { return 20 + rapidFetchCount; },
    clearTimeout() {},
    setInterval() { return 30 + rapidFetchCount; },
    clearInterval() {},
    requestAnimationFrame(callback) {
      callback();
      return 40 + rapidFetchCount;
    },
    fetch: async () => {
      rapidFetchCount += 1;
      return {
        ok: true,
        headers: { get: () => "multipart/x-mixed-replace; boundary=frame" },
        body: {
          getReader: () => ({
            read: () => new Promise(() => {}),
          }),
        },
      };
    },
  };
  let latestRapidPipeline = null;
  for (let index = 0; index < 6; index += 1) {
    const rapidFrame = {
      id: `rapid-${index}`,
      timestamp_ms: 150000 + (index * 1000),
      seek_target_ms: 151000 + (index * 1000),
      url: `/camera/push-archive-frame?stream_id=cam-rapid&frame=rapid-${index}`,
    };
    latestRapidPipeline = renderWisCameraPushArchiveFrame(rapidRuntime, {
      element: rapidElement,
      streamId: "cam-rapid",
      slot: "cam-rapid",
      camera: { label: "CAM Rapid" },
      frame: rapidFrame,
      force: true,
      playbackUrl: `/camera/push-playback?stream_id=cam-rapid&from_ms=${rapidFrame.seek_target_ms}&fps=15&follow=0`,
      document: { createElement: makeFakeElement },
      env: rapidEnv,
    });
    latestRapidPipeline.startPlaybackStream();
    await Promise.resolve();
    const activeLoop = wisCameraActivePlaybackLoop(rapidRuntime, "cam-rapid");
    assert.strictEqual(activeLoop.generation, latestRapidPipeline.session.generation, "rapid seek should leave only the newest playback loop active");
    assert.strictEqual(sampleWisCameraPerf(rapidRuntime, "cam-rapid", {}, () => {}, { force: true }).activePlaybackLoops, 1);
  }
  assert.strictEqual(rapidFetchCount, 6, "six rapid seeks should start six generations, not duplicate the same generation");
  assert(rapidAbortCount >= 5, "starting a new seek generation must abort older playback readers");
	  assert.strictEqual(rapidElement.querySelectorAll(".wis-camera-image, .wis-camera-video").length, 2, "rapid seeks must keep one reusable front/back media buffer pair");
  const rapidActiveSample = sampleWisCameraPerf(rapidRuntime, "cam-rapid", {}, () => {}, { force: true });
  assert.strictEqual(rapidActiveSample.activePlaybackLoops, 1, "six rapid seeks should settle to one active playback loop");
  assert.strictEqual(rapidActiveSample.activeReaders, 1, "six rapid seeks should settle to one active reader");
  stopWisCameraPlaybackState(rapidRuntime, "cam-rapid");
  releaseMediaStreamWriter("cam-rapid", { kind: "recorded-playback", generation: latestRapidPipeline.session.generation });
  assert.strictEqual(wisCameraActivePlaybackLoop(rapidRuntime, "cam-rapid"), null, "returning to live must cancel the recorded playback loop");
  assert.strictEqual(wisCameraTimelineOwnerState(rapidRuntime, "cam-rapid"), WIS_CAMERA_TIMELINE_OWNER_STATES.LIVE, "returning to live should clear recorded timeline ownership");
  const rapidStoppedSample = sampleWisCameraPerf(rapidRuntime, "cam-rapid", {}, () => {}, { force: true });
  assert.strictEqual(rapidStoppedSample.activePlaybackLoops, 0, "live return should report no active playback loops");
  assert.strictEqual(rapidStoppedSample.activeReaders, 0, "live return should report no active playback readers");
  const secondPlayback = startWisCameraPlaybackSeek(playbackRuntime, "cam-1", {
    id: "frame-b",
    timestamp_ms: 90000,
    seek_target_ms: 90500,
    url: "/camera/push-archive-frame?stream_id=cam-1&frame=frame-b",
  }, { nowMs: 3000, explicitSeek: true, restart: true });
  assert.strictEqual(secondPlayback.generation, 2);
  assert.strictEqual(secondPlayback.ownerState, WIS_CAMERA_TIMELINE_OWNER_STATES.RECORDED_SEEKING, "second timeline click should start a fresh recorded seek owner generation");
  assert.strictEqual(wisCameraPlaybackMatches(playbackRuntime, "cam-1", {
    sessionId: firstPlayback.id,
    generation: firstPlayback.generation,
  }), false);
  assert.strictEqual(setWisCameraPlaybackFrame(playbackRuntime, "cam-1", {
    id: "late-frame",
    timestamp_ms: 76000,
  }, { sessionId: firstPlayback.id, generation: firstPlayback.generation, nowMs: 3200 }), null);
  const staleRestart = startWisCameraPlaybackSeek(playbackRuntime, "cam-1", {
    id: "stale-frame",
    timestamp_ms: 70000,
    url: "/camera/push-archive-frame?stream_id=cam-1&frame=stale-frame",
  }, { nowMs: 3300, explicitSeek: true, restart: true, generation: firstPlayback.generation });
  assert.strictEqual(staleRestart.id, secondPlayback.id, "older seek generations must not restore stale playback state");
  assert.strictEqual(wisCameraPlaybackState(playbackRuntime, "cam-1").id, secondPlayback.id);
  const sameFrameRestart = startWisCameraPlaybackSeek(playbackRuntime, "cam-1", {
    id: "frame-b",
    timestamp_ms: 90000,
    seek_target_ms: 90500,
    url: "/camera/push-archive-frame?stream_id=cam-1&frame=frame-b",
  }, { nowMs: 3400, explicitSeek: true, restart: true });
  assert.strictEqual(sameFrameRestart.generation, 3, "explicit second click on the same point must still restart playback generation");
  assert.notStrictEqual(sameFrameRestart.id, secondPlayback.id);
  stopWisCameraPlaybackState(playbackRuntime, "cam-1");
  assert.strictEqual(wisCameraPlaybackState(playbackRuntime, "cam-1"), null);
  assert.strictEqual(wisCameraTimelineOwnerState(playbackRuntime, "cam-1"), WIS_CAMERA_TIMELINE_OWNER_STATES.LIVE);

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

  const mediaClockEvents = [];
  const mediaClockTimelineUpdates = [];
  const mediaClockPendingSeeks = [];
  const mediaClockController = createCameraArtifactController({
    artifactId: "cam-media",
    documentId: "main",
    env: controllerEnv,
    diagnostics: false,
    recordEvent: (type, payload) => mediaClockEvents.push({ type, payload }),
    getTimelineModel: () => ({
      streamId: "cam-media",
      mode: "recorded",
      frames: [
        { id: "a", timestamp_ms: 1000, url: "/a.jpg" },
        { id: "b", timestamp_ms: 3000, url: "/b.jpg" },
      ],
      range: { start_ms: 1000, end_ms: 3000 },
    }),
    findSegmentForTime: async (targetTimeMs) => ({
      id: "b",
      timestamp_ms: 3000,
      seek_target_ms: targetTimeMs,
      url: "/b.jpg",
    }),
    loadSegment: async (segment) => ({ ...segment, playbackClockSource: "media" }),
    onSeekPending: (detail) => mediaClockPendingSeeks.push(detail),
    drawFrameAt: () => {
      throw new Error("media-clocked playback must not use the synthetic render loop");
    },
    updateTimelineVisualOnly: (timestampMs) => {
      mediaClockTimelineUpdates.push(timestampMs);
      return timestampMs;
    },
  });
  const mediaLoadedSegment = await mediaClockController.seekTo(2000, { source: "user", reason: "timeline-click" });
  assert.strictEqual(mediaLoadedSegment.playbackClockSource, "media");
  assert.strictEqual(mediaClockPendingSeeks.length, 1, "timeline seek should enter a recorded pending generation before segment load completes");
  assert.strictEqual(mediaClockPendingSeeks[0].generation, 1);
  assert(mediaClockEvents.some((event) => (
    event.type === "camera.playback.transition"
    && event.payload.fromOwnerState === WIS_CAMERA_TIMELINE_OWNER_STATES.LIVE
    && event.payload.toOwnerState === WIS_CAMERA_TIMELINE_OWNER_STATES.RECORDED_SEEKING
  )), "first timeline click from live must claim recorded seeking ownership");
  assert.strictEqual(mediaClockEvents.some((event) => event.type === "camera.render.start"), false, "media-clocked playback must not start a RAF render loop");
  assert.strictEqual(mediaClockController.getCurrentPlaybackTimeMs(9000), 2000, "media-clocked controller should hold the selected time until a frame displays");
  mediaClockController.markRecordedFrameDisplayed({ id: "b-stream", timestamp_ms: 2500 }, { source: "media", reason: "test-frame" });
  const mediaClockState = mediaClockController.getState().playbackClock;
  assert.strictEqual(mediaClockState.displayedRecordingTimeMs, 2500, "displayed media time should be tracked separately");
  assert(mediaClockEvents.some((event) => (
    event.type === "camera.playback.transition"
    && event.payload.toOwnerState === WIS_CAMERA_TIMELINE_OWNER_STATES.RECORDED_PLAYING
  )), "decoded first recorded frame must transition ownership to recorded playing");
  assert.strictEqual(mediaClockState.anchorRecordingTimeMs, 2500, "desired media clock should anchor to the first committed recorded frame");
  assert.strictEqual(mediaClockState.targetTimeMs, 2000, "clicked seek target should persist separately from the committed frame anchor");
  assert.strictEqual(mediaClockController.getCurrentPlaybackTimeMs(mediaClockState.anchorWallTimeMs + 500), 3000, "desired media clock should advance at 1x from the first displayed frame");
  assert(mediaClockEvents.some((event) => event.type === "camera.clock.loop.start"), "media-clocked playback should start a timeline-only desired clock loop");
  assert(mediaClockTimelineUpdates.some((timestampMs) => timestampMs >= 2000), "displayed frames should wake desired-clock timeline sync");
  const staleMediaSegment = await mediaClockController.seekTo(2600, { source: "user", reason: "timeline-click-latest" });
  assert.strictEqual(staleMediaSegment.playbackClockSource, "media");
  mediaClockController.markRecordedFrameDisplayed({ id: "old-stream-frame", timestamp_ms: 2100 }, { source: "media", reason: "old-stream", generation: 1 });
  assert.notStrictEqual(mediaClockController.getState().playbackClock.displayedRecordingTimeMs, 2100, "old recorded generations must not update the media clock");
  assert.strictEqual(mediaClockController.getState().playbackClock.targetTimeMs, 2600);
  mediaClockController.cleanup("media-clock-test");

  const timelineControllerEvents = [];
  const timelineSegments = [];
  const timelineListeners = new Map();
  const timelineElement = {
    dataset: {},
    isConnected: true,
    style: {
      values: new Map(),
      setProperty(name, value) {
        this.values.set(name, value);
      },
      removeProperty(name) {
        this.values.delete(name);
      },
      getPropertyValue(name) {
        return this.values.get(name) || "";
      },
    },
    classList: { add() {}, remove() {}, contains() { return false; } },
    addEventListener(type, handler) {
      timelineListeners.set(type, handler);
    },
    removeEventListener(type, handler) {
      if (timelineListeners.get(type) === handler) timelineListeners.delete(type);
    },
    getBoundingClientRect() {
      return { left: 0, width: 100 };
    },
    focus() {},
  };
  const timelineController = createCameraArtifactController({
    artifactId: "cam-1",
    documentId: "main",
    env: controllerEnv,
    diagnostics: false,
    recordEvent: (type, payload) => timelineControllerEvents.push({ type, payload }),
    getTimelineModel: () => ({
      streamId: "cam-1",
      mode: "recorded",
      frames: [
        { id: "start", timestamp_ms: 1000, url: "/start.jpg" },
        { id: "middle", timestamp_ms: 2000, url: "/middle.jpg" },
        { id: "end", timestamp_ms: 3000, url: "/end.jpg" },
      ],
      range: { start_ms: 1000, end_ms: 3000 },
    }),
    findSegmentForTime: async (targetTimeMs, context) => ({
      ...context.requestedFrame,
      id: context.requestedFrame?.id || "middle",
      timestamp_ms: 2000,
      seek_target_ms: targetTimeMs,
      url: "/middle.jpg",
    }),
    loadSegment: async (segment) => {
      timelineSegments.push(segment);
      return segment;
    },
  });
  timelineController.configure({ timelineElement });
  assert.strictEqual(typeof timelineListeners.get("click"), "function", "camera.js controller should own timeline click handling");
  timelineListeners.get("click")({
    clientX: 25,
    preventDefault() {},
    stopPropagation() {},
  });
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.strictEqual(timelineSegments.length, 1, "camera.js timeline click should load a playback segment");
  assert.strictEqual(timelineSegments[0].seek_target_ms, 1500);
  assert(timelineControllerEvents.some((event) => event.type === "camera.timeline.user.pointerup" && event.payload.reason === "timeline-click"), "camera.js timeline click should be recorded as the user seek source");
  timelineController.cleanup("timeline-test");

  const liveTimelineEvents = [];
  const liveTimelineSegments = [];
  const liveTimelineListeners = new Map();
  const liveTimelineElement = {
    dataset: {},
    isConnected: true,
    style: {
      values: new Map(),
      setProperty(name, value) {
        this.values.set(name, value);
      },
      removeProperty(name) {
        this.values.delete(name);
      },
    },
    classList: { add() {}, remove() {}, contains() { return false; } },
    addEventListener(type, handler) {
      liveTimelineListeners.set(type, handler);
    },
    removeEventListener(type, handler) {
      if (liveTimelineListeners.get(type) === handler) liveTimelineListeners.delete(type);
    },
    getBoundingClientRect() {
      return { left: 0, width: 100 };
    },
    focus() {},
  };
  const liveTimelineModel = {
    streamId: "cam-live",
    mode: "live",
    frames: [
      { id: "live-start", timestamp_ms: 1000, url: "/live-start.jpg" },
      { id: "live-end", timestamp_ms: 3000, url: "/live-end.jpg" },
    ],
    range: { start_ms: 1000, end_ms: 3000 },
  };
  const liveTimelineController = createCameraArtifactController({
    artifactId: "cam-live",
    documentId: "main",
    env: controllerEnv,
    diagnostics: false,
    recordEvent: (type, payload) => liveTimelineEvents.push({ type, payload }),
    getTimelineModel: () => liveTimelineModel,
    findSegmentForTime: async (targetTimeMs, context) => ({
      ...context.requestedFrame,
      id: context.requestedFrame?.id || "live-end",
      timestamp_ms: 3000,
      seek_target_ms: targetTimeMs,
      url: "/live-end.jpg",
    }),
    loadSegment: async (segment) => {
      liveTimelineSegments.push(segment);
      return segment;
    },
  });
  liveTimelineController.configure({
    timelineElement: liveTimelineElement,
    timeline: liveTimelineModel,
    frames: liveTimelineModel.frames,
    mode: "live",
  });
  liveTimelineListeners.get("click")({
    clientX: 25,
    preventDefault() {},
    stopPropagation() {},
  });
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.strictEqual(liveTimelineSegments.length, 1, "live timeline clicks should immediately start recorded playback");
  assert.strictEqual(liveTimelineSegments[0].seek_target_ms, 1500, "live timeline click should anchor playback at the clicked timestamp");
  assert.strictEqual(liveTimelineController.getState().playbackClock.mode, "recordedPlaying", "live timeline click should leave the controller live mode");
  assert(liveTimelineEvents.some((event) => event.type === "camera.timeline.seek"), "live timeline seek should emit seek diagnostics");
  assert(liveTimelineEvents.some((event) => event.type === "camera.playback.transition" && event.payload.toMode === "seeking"), "live timeline seek should emit a live-to-seeking transition");
  liveTimelineController.cleanup("live-timeline-test");

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
