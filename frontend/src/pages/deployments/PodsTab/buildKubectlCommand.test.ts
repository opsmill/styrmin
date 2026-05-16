import { describe, it, expect } from "vitest";
import { buildKubectlCommand } from "./buildKubectlCommand";

const NS = "styrmin-api-gateway-prod";
const POD = "api-7f9d4-jh2bn";

describe("buildKubectlCommand", () => {
  it("builds logs command", () => {
    expect(buildKubectlCommand("logs", NS, POD)).toBe(
      `kubectl logs --namespace ${NS} ${POD} --all-containers`,
    );
  });

  it("builds describe command", () => {
    expect(buildKubectlCommand("describe", NS, POD)).toBe(
      `kubectl describe pod --namespace ${NS} ${POD}`,
    );
  });

  it("builds events command with field-selector", () => {
    expect(buildKubectlCommand("events", NS, POD)).toBe(
      `kubectl get events --namespace ${NS} --field-selector involvedObject.name=${POD}`,
    );
  });

  it("builds exec command", () => {
    expect(buildKubectlCommand("exec", NS, POD)).toBe(
      `kubectl exec -it --namespace ${NS} ${POD} -- /bin/sh`,
    );
  });
});
