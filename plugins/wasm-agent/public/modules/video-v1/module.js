export const moduleDefinition = {
  id: "video-v1",
  title: "Video V1",
  status: "browser-local media editor",
  defaultEnabled: true,
  firmware: "/modules/video-v1/video-v1.entry.js",
  artifact: "/modules/video-v1/artifact.json",
  endpoints: [],
  state: { input: "ephemeral browser file", output: "operator download", networkPolicy: "media-bytes-local" },
};
