import { describe, it, expect } from "vitest";
import {
  clusterConfigChanges,
  configToFormValues,
  mergeFormValuesIntoConfig,
  nothingToSave,
  sameJson,
} from "./ClusterConfigFields.helpers";

/** Saving the form unchanged must submit the stored config as it is. */
function roundTrip(stored: Record<string, unknown>) {
  return mergeFormValuesIntoConfig(stored, configToFormValues(stored));
}

describe("mergeFormValuesIntoConfig(stored, configToFormValues(stored))", () => {
  it.each([
    [
      "values the form does not list",
      {
        ingress_class: "traefik",
        runtime_class: "default",
        dedicated_ingress: {
          implementation: "nginx",
          type: "gateway-api",
          service: {
            type: "ExternalName",
            external_traffic_policy: "Hybrid",
          },
        },
      },
    ],
    [
      "service annotations and the load balancer IP",
      {
        ingress_class: "traefik",
        dedicated_ingress: {
          service: {
            type: "LoadBalancer",
            annotations: { "lb.example.com/id": "abc" },
            load_balancer_ip: "10.0.0.5",
            ip_families: ["IPv6", "IPv4"],
            ip_family_policy: "PreferDualStack",
          },
        },
      },
    ],
    [
      "a scheduling value that refers to another deployment",
      {
        ingress_class: "traefik",
        scheduling: {
          pod_affinity: {
            required: [
              {
                topology_key: "kubernetes.io/hostname",
                deployment_ref: { deployment_name: "db", components: ["db"] },
              },
            ],
          },
        },
        node_selector: "pool=apps",
        db_size: "10Gi",
        backup_ttl: "720h",
      },
    ],
    [
      "a dedicated ingress with an empty service",
      { dedicated_ingress: { service: {} } },
    ],
    [
      "a dedicated ingress stored as an empty object",
      { dedicated_ingress: {} },
    ],
    [
      "every value the form shows",
      {
        ingress_class: "nginx",
        runtime_class: "gvisor",
        fqdn_suffix: "apps.example.com",
        external_url_scheme: "http",
        external_url_port: 8443,
        external_dns_endpoints_type: "NodeExternalIP",
        dedicated_ingress: {
          implementation: "traefik",
          type: "ingress",
          service: { type: "NodePort", node_port: 30443 },
        },
        standard_storage: { storage_class: "ebs-gp3" },
        fast_storage: { storage_class: "nvme-local" },
      },
    ],
  ])("keeps %s", (_name, stored) => {
    expect(roundTrip(stored)).toEqual(stored);
  });
});

describe("clusterConfigChanges", () => {
  it("lists each changed value with the form's label", () => {
    expect(
      clusterConfigChanges(
        {
          fqdn_suffix: "old.example.com",
          dedicated_ingress: { service: { load_balancer_ip: "10.0.0.5" } },
        },
        { fqdn_suffix: "new.example.com" },
      ),
    ).toEqual([
      {
        label: "FQDN suffix",
        before: "old.example.com",
        after: "new.example.com",
      },
      { label: "Dedicated ingress", before: "On", after: "Off" },
      { label: "Load balancer IP", before: "10.0.0.5", after: "Not set" },
    ]);
  });

  it("finds no change between equal configs", () => {
    expect(
      clusterConfigChanges(
        { ingress_class: "traefik", scheduling: { runtime_class: "kata" } },
        { scheduling: { runtime_class: "kata" }, ingress_class: "traefik" },
      ),
    ).toEqual([]);
  });
});

describe("nothingToSave", () => {
  const config = { ingress_class: "traefik" };

  it("is true when nothing changes and nothing is redeployed", () => {
    expect(
      nothingToSave(config, config, { redeployed: [], ingressControllers: [] }),
    ).toBe(true);
  });

  it("is false when saving again redeploys a deployment", () => {
    expect(
      nothingToSave(config, config, {
        redeployed: [{}],
        ingressControllers: [],
      }),
    ).toBe(false);
  });

  it("is false when saving again redeploys a controller", () => {
    expect(
      nothingToSave(config, config, {
        redeployed: [],
        ingressControllers: [{ action: "REDEPLOY" }],
      }),
    ).toBe(false);
  });
});

describe("sameJson", () => {
  it("ignores the key order and compares arrays in order", () => {
    expect(sameJson({ a: 1, b: [1, 2] }, { b: [1, 2], a: 1 })).toBe(true);
    expect(sameJson({ a: [1, 2] }, { a: [2, 1] })).toBe(false);
    expect(sameJson({ a: 1 }, { a: 1, b: 2 })).toBe(false);
  });
});
