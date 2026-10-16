import { describe, it, expect } from "vitest";
import { render, screen, within } from "@/test/utils";
import { ClusterConfiguration } from "./ClusterConfiguration";

function section(name: string) {
  return screen.getByRole("region", { name });
}

describe("ClusterConfiguration", () => {
  it("shows backend defaults for a dedicated ingress stored as an empty object", async () => {
    await render(
      <ClusterConfiguration
        config={{ dedicated_ingress: {}, ingress_class: "traefik" }}
        capabilities={{}}
      />,
    );

    const ingress = section("Dedicated ingress");
    expect(ingress).toHaveTextContent("traefik (default)");
    expect(ingress).toHaveTextContent("ingress (default)");
    expect(ingress).toHaveTextContent("LoadBalancer (default)");
  });

  it("renders every dedicated ingress service setting", async () => {
    await render(
      <ClusterConfiguration
        config={{
          dedicated_ingress: {
            implementation: "traefik",
            type: "ingress",
            service: {
              type: "NodePort",
              node_port: 30443,
              load_balancer_ip: "10.0.0.5",
              external_traffic_policy: "Local",
              ip_families: ["IPv4", "IPv6"],
              ip_family_policy: "PreferDualStack",
              annotations: { "lb.example.com/id": "abc" },
            },
          },
        }}
        capabilities={{}}
      />,
    );

    const ingress = section("Dedicated ingress");
    expect(ingress).toHaveTextContent("NodePort");
    expect(ingress).toHaveTextContent("30443");
    expect(ingress).toHaveTextContent("10.0.0.5");
    expect(ingress).toHaveTextContent("Local");
    expect(ingress).toHaveTextContent("IPv4, IPv6");
    expect(ingress).toHaveTextContent("PreferDualStack");
    expect(ingress).toHaveTextContent("lb.example.com/id: abc");
    expect(ingress).not.toHaveTextContent("(default)");
  });

  it("says when no dedicated ingress is configured", async () => {
    await render(<ClusterConfiguration config={{}} capabilities={{}} />);

    expect(section("Dedicated ingress")).toHaveTextContent("Not configured");
  });

  it("renders networking, storage, runtime and backup settings", async () => {
    await render(
      <ClusterConfiguration
        config={{
          ingress_class: "nginx",
          fqdn_suffix: "example.com",
          external_url_scheme: "http",
          external_url_port: 8080,
          external_dns_endpoints_type: "NodeExternalIP",
          standard_storage: { storage_class: "csi-hostpath-sc" },
          fast_storage: { storage_class: "local-path" },
          db_size: "10Gi",
          runtime_class: "gvisor",
          backup_ttl: "168h",
        }}
        capabilities={{}}
      />,
    );

    const networking = section("Networking");
    expect(networking).toHaveTextContent("nginx");
    expect(networking).toHaveTextContent("example.com");
    expect(networking).toHaveTextContent("http");
    expect(networking).toHaveTextContent("8080");
    expect(networking).toHaveTextContent("NodeExternalIP");

    const storage = section("Storage");
    expect(storage).toHaveTextContent("csi-hostpath-sc");
    expect(storage).toHaveTextContent("local-path");
    expect(storage).toHaveTextContent("10Gi");

    const runtime = section("Runtime");
    expect(runtime).toHaveTextContent("gvisor");
    expect(
      within(runtime).getByTestId("cluster-scheduling-hint"),
    ).toHaveTextContent("Scheduling is set on each environment or deployment");

    expect(section("Backups")).toHaveTextContent("168h");
  });

  it("shows defaults for unset networking and backup settings", async () => {
    await render(<ClusterConfiguration config={{}} capabilities={{}} />);

    expect(section("Networking")).toHaveTextContent("https (default)");
    expect(section("Backups")).toHaveTextContent("720h (default)");
    expect(section("Storage")).toHaveTextContent("Not configured");
  });

  it("lists derived capabilities", async () => {
    await render(
      <ClusterConfiguration
        config={{}}
        capabilities={{
          storage: { standard: { storage_class: "csi-hostpath-sc" } },
          ingress: {
            traefik: { ingress_class: "traefik", fqdn_suffix: "example.com" },
          },
        }}
      />,
    );

    const table = within(section("Capabilities")).getByTestId(
      "cluster-capabilities",
    );
    expect(table).toHaveTextContent("Storage");
    expect(table).toHaveTextContent("storage_class: csi-hostpath-sc");
    expect(table).toHaveTextContent("Ingress");
    expect(table).toHaveTextContent(
      "ingress_class: traefik, fqdn_suffix: example.com",
    );
  });

  it("renders settings it has no dedicated section for", async () => {
    await render(
      <ClusterConfiguration
        config={{ future_setting: { enabled: true } }}
        capabilities={{}}
      />,
    );

    expect(section("Other settings")).toHaveTextContent(
      'future_setting{"enabled":true}',
    );
  });
});
