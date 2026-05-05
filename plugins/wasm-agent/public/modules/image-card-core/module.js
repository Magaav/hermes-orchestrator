export const moduleDefinition = {
  id: "image-card-core",
  title: "Image Card Core",
  status: "browser pixels",
  detail: "Builds compact image-card facts with native decode, Canvas sampling, palette, hash, and layout metrics.",
  defaultEnabled: true,
  firmware: "/modules/image-card-core/module.js",
  analyzer: {
    kind: "image",
    mode: "built-in",
    cache: "always resident with app runtime",
    evidence: "pixel_stats",
  },
};
