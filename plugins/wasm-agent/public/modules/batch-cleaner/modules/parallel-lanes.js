export function partitionIntoLanes(items, laneCount) {
  const count = Math.max(1, Math.trunc(Number(laneCount) || 1));
  const lanes = Array.from({ length: Math.min(count, Math.max(1, items.length)) }, () => []);
  items.forEach((item, index) => {
    lanes[index % lanes.length].push({ item, queueIndex: index });
  });
  return lanes;
}

export async function runIndependentLanes(items, laneCount, worker) {
  const lanes = partitionIntoLanes(items, laneCount);
  await Promise.all(lanes.map(async (lane, laneIndex) => {
    for (const assignment of lane) {
      await worker({ ...assignment, laneIndex });
    }
  }));
}
