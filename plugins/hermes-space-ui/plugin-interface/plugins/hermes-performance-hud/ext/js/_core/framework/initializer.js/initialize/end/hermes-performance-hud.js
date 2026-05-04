import { installHermesPerformanceHud } from "/mod/hermes/performance-hud/performance-hud.js";

export default async function hermesPerformanceHudInitializerEnd() {
  installHermesPerformanceHud();
}
