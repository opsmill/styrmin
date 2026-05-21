import type { GetDriverQuery } from "@/generated/graphql";

/**
 * Identifier for the active tab in the driver detail right pane.
 */
export type TabId =
  | "overview"
  | "parameters"
  | "components"
  | "actions"
  | "source";

/**
 * Narrowed shape of an `ApplicationDriver` as returned by `useGetDriverQuery`.
 *
 * Lifted from the generated GraphQL types so consumers can reuse the exact
 * shape the query actually selects (including `createdOn`).
 */
export type DriverDetail = NonNullable<GetDriverQuery["applicationDriver"]>;

/**
 * Narrowed shape of a single `ApplicationDriverVersion` entry as returned by
 * `useGetDriverQuery`.
 */
export type DriverVersionDetail = DriverDetail["versions"][number];

/**
 * Narrowed shape of a single declared parameter on a driver version.
 */
export type DriverParameter = DriverVersionDetail["parameters"][number];

/**
 * Narrowed shape of a single declared action on a driver version.
 */
export type DriverAction = DriverVersionDetail["actions"][number];

/**
 * Narrowed shape of the helm chart reference on a driver version.
 */
export type DriverHelmChart = DriverVersionDetail["helmChart"];
