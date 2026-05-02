import {
  canonicalizeHermesFleetSpaceRoute,
  installHermesFleetUi
} from "/mod/hermes/fleet/hermes-fleet-ui.js";

export default async function hermesFleetInitializerEnd() {
  canonicalizeHermesFleetSpaceRoute();
  installHermesFleetUi();
}
