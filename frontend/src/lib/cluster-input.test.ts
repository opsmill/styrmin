import { describe, expect, it } from "vitest";

import { clusterConfigToInput } from "./cluster-input";
import fullConfig from "./cluster-input.full-config.json";

describe("clusterConfigToInput", () => {
  // The backend checks that this config sets every ClusterConfig field (#454).
  it("maps every field of a config that sets every field", () => {
    expect(clusterConfigToInput(fullConfig.config)).toEqual(fullConfig.input);
  });

  it("leaves out every field that the config does not set", () => {
    expect(clusterConfigToInput({})).toEqual({});
  });
});
