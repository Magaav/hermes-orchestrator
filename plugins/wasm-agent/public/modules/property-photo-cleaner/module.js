export const moduleDefinition = {
  id: "property-photo-cleaner",
  title: "Property Photo Cleaner",
  status: "browser-local detection + generative cleaning",
  detail: "Finds and reconstructs selected cleanup regions entirely in the browser.",
  defaultEnabled: true,
  firmware: "/modules/property-photo-cleaner/property-photo-cleaner.entry.js",
  endpoints: [],
  state: {
    browserStorage: "hermes.property-photo-cleaner.models",
    networkPolicy: "photo-bytes-local",
  },
};
