import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { Buffer } from "node:buffer";

const source = await readFile(new URL("../public/modules/spaces/shared-pointer-renderer.js", import.meta.url), "utf8");
const renderer = await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);

{
  const samples = [];
  for (let index = 0; index < 96; index += 1) {
    renderer.pushSharedPointerSample(samples, { x: index, y: 0, at: index * 16 }, { limit: 12, minDistancePx: 0, minIntervalMs: 0 });
  }
  assert.equal(samples.length, 12, "pointer sample history must stay bounded");
  assert.equal(samples[0].x, 84, "bounded history should keep the newest samples");
  assert.equal(samples.at(-1).x, 95);
}

{
  let visual = { x: 0, y: 0 };
  const target = { x: 100, y: 0 };
  for (let frame = 0; frame < 90; frame += 1) {
    visual = renderer.smoothSharedPointerPosition(visual, target, 1000 / 60, {
      snapDistancePx: 1000,
      maxSpeedPxPerSecond: 10000,
    });
  }
  assert(Math.abs(visual.x - target.x) < 0.25, "time-based interpolation should converge to the target");
  assert.equal(visual.snapped, false, "ordinary cursor motion should not snap");
}

{
  const huge = renderer.smoothSharedPointerPosition({ x: 0, y: 0 }, { x: 1800, y: 0 }, 1000 / 120, { snapDistancePx: 960 });
  assert.equal(huge.mode, "snap", "huge discontinuities should snap instead of smearing across the whole canvas");
  assert.equal(huge.x, 1800);
}

{
  let visual = { x: 0, y: 0 };
  let history = [];
  for (let index = 0; index < 500; index += 1) {
    visual = renderer.smoothSharedPointerPosition(visual, { x: index % 240, y: index % 80 }, 8.33, {
      maxSpeedPxPerSecond: 10000,
    });
    renderer.pushSharedPointerSample(history, { ...visual, at: index * 8.33 }, { limit: 24, minDistancePx: 0, minIntervalMs: 0 });
    history = renderer.pruneSharedPointerSamples(history, index * 8.33, { limit: 24, maxAgeMs: 240 });
  }
  assert(history.length <= 24, "rapid target churn must not grow visual history");
}

assert.equal(renderer.snapSharedPointerPixel(10.24, 2), 10, "pixel snapping should align to the device pixel grid");
assert.equal(renderer.snapSharedPointerPixel(10.26, 2), 10.5);

{
  const midpoint = renderer.sampleSharedPointerPath([
    { x: 0, y: 0 },
    { x: 30, y: 0 },
    { x: 30, y: 30 },
  ], 0.5);
  assert.deepEqual(midpoint, { x: 30, y: 0 }, "path sampling should spend intermediate points instead of collapsing to the endpoint");
  const between = renderer.sampleSharedPointerPath([
    { x: 0, y: 0 },
    { x: 30, y: 0 },
    { x: 30, y: 30 },
  ], 0.75);
  assert.deepEqual(between, { x: 30, y: 15 });
}

{
  const lowLatency = renderer.adaptiveSharedPointerReplayDuration(40, { fps: 60, droppedFrameAgeMs: 1000 });
  assert.equal(lowLatency.mode, "low-latency", "healthy frames should use the shorter replay window");
  assert(lowLatency.durationMs >= 16 && lowLatency.durationMs <= 40, lowLatency);
  const stable = renderer.adaptiveSharedPointerReplayDuration(40, { fps: 60, droppedFrameAgeMs: 12 });
  assert.equal(stable.mode, "stable", "recent dropped frames should temporarily prefer stable replay");
  assert(stable.durationMs >= 32 && stable.durationMs <= 72, stable);
}

{
  const projected = renderer.predictSharedPointerPosition({ x: 10, y: 20 }, { x: 3, y: 4 }, {
    maxLeadMs: 22,
    maxDistancePx: 10,
    staleMs: 140,
    targetAgeMs: 0,
  });
  assert.equal(projected.predicted, true);
  assert(Math.abs(projected.distancePx - 10) < 0.001, "prediction should clamp lead distance");
  const stale = renderer.predictSharedPointerPosition({ x: 10, y: 20 }, { x: 3, y: 4 }, {
    maxLeadMs: 22,
    maxDistancePx: 10,
    staleMs: 140,
    targetAgeMs: 140,
  });
  assert.equal(stale.predicted, false, "stale input should not extrapolate beyond the last target");
  assert.deepEqual({ x: stale.x, y: stale.y }, { x: 10, y: 20 });
}

{
  const compact = renderer.encodeSharedPointerRealtimeSamples([
    { x: 1.234, y: 5.678, at: 96 },
    { x: 8, y: 13, at: 104 },
  ], 108);
  assert.deepEqual(compact, [[-12, 1.23, 5.68], [-4, 8, 13]], "realtime samples should encode as compact deltas");
  const decoded = renderer.decodeSharedPointerRealtimeSamples(compact, 108, 1000);
  assert.deepEqual(decoded.map((sample) => sample.at), [1096, 1104], "receiver should map compact deltas onto its monotonic clock");
}

{
  const buffer = [];
  let result = renderer.appendSharedPointerRealtimeSamples(buffer, Array.from({ length: 90 }, (_, index) => ({
    x: index,
    y: 0,
    at: index * 4,
  })), { limit: 16, maxAgeMs: 120, nowMs: 360 });
  assert.equal(result.samples.length, 16, "realtime netcode sample buffer must stay bounded");
  assert(result.dropped > 0, "old realtime samples should be dropped instead of replayed forever");
  const midpoint = renderer.sampleSharedPointerRealtimeBuffer([
    { x: 0, y: 0, at: 100 },
    { x: 10, y: 0, at: 120 },
  ], 132, { bufferDelayMs: 22 });
  assert.equal(midpoint.mode, "net-buffer");
  assert.equal(midpoint.x, 5);
  const predicted = renderer.sampleSharedPointerRealtimeBuffer([
    { x: 0, y: 0, at: 100 },
    { x: 10, y: 0, at: 110 },
  ], 140, { bufferDelayMs: 12, maxPredictionMs: 30, maxPredictionDistancePx: 12, staleMs: 120 });
  assert.equal(predicted.mode, "net-predict");
  assert(predicted.x > 10, "fresh late samples should predict briefly from velocity");
  assert(predicted.predictionPx <= 12);
}

{
  const offset = renderer.estimateSharedPointerClockOffset({
    senderEpochMs: 1_700_000,
    senderPerfMs: 600,
    receiverEpochMs: 1_701_000,
    receiverPerfMs: 400,
  }, 0);
  assert.equal(offset, -1200, "clock offset maps sender performance time into receiver performance time");
  const smoothed = renderer.estimateSharedPointerClockOffset({
    senderEpochMs: 1_700_000,
    senderPerfMs: 600,
    receiverEpochMs: 1_701_000,
    receiverPerfMs: 400,
  }, -700, { alpha: 0.5 });
  assert.equal(smoothed, -950);
}

{
  const packet = renderer.encodeSharedPointerBinaryPacket({
    userId: "101",
    deviceId: "device-a",
    seq: 42,
    sentPerfMs: 1000,
    sentEpochMs: 1_700_000,
    samples: [
      { x: 12.5, y: 30.25, at: 992 },
      { x: 18.75, y: 31.5, at: 1000 },
    ],
  });
  assert(packet instanceof ArrayBuffer, "binary pointer packet should encode into one ArrayBuffer");
  assert.equal(packet.byteLength, 56, "binary packet should be compact and fixed-size per sample");
  const decoded = renderer.decodeSharedPointerBinaryPacket(packet, {
    receivedAtMs: 1200,
    receiverEpochMs: 1_700_200,
    previousClockOffsetMs: 0,
  });
  assert.equal(decoded.userId, 101);
  assert.equal(decoded.seq, 42);
  assert.equal(decoded.samples.length, 2);
  assert(Math.abs(decoded.samples[1].x - 18.75) < 0.001);
  assert.equal(decoded.clockOffsetMs, 0);
  assert.equal(renderer.hashSharedPointerString("device-a"), decoded.deviceHash);
}

console.log("shared pointer renderer tests passed");
