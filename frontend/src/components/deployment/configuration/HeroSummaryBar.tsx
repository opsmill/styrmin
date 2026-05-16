import type {
  ParameterDefinition,
  UpdateDeploymentInput,
} from "@/generated/graphql";
import { Button } from "@/components/ui/button";
import type {
  DriverParameterSchema,
  InheritanceState,
  SectionId,
} from "@/lib/configuration-types";

/**
 * Lightweight summary of the most recent successful configuration update,
 * rendered as the "Last changed Xd ago by Y — Z" line in the hero bar.
 *
 * Sourced client-side from the deployment's timeline per research R-009.
 * Optional: when omitted the line is hidden.
 */
export interface LastUpdateEvent {
  /** ISO timestamp of the update task's completion. */
  occurredAt: string;
  /** Display name (or username) of the actor that triggered the update. */
  actor: string;
  /** Short one-line description of what changed (e.g. "scheduling, env_vars"). */
  summary: string;
}

interface Props {
  deployment: {
    id: string;
    name: string;
  };
  environment: {
    id: string;
    name: string;
  };
  driverSchema: DriverParameterSchema;
  /** Per-section inheritance map produced by `computeInheritance()`. */
  inheritance: Map<SectionId, InheritanceState>;
  /** Current deployment input, used to count "configured" fields per section. */
  current: UpdateDeploymentInput;
  /**
   * Whether the viewer can edit this deployment. When `false`, the
   * "Edit configuration" CTA is omitted entirely (FR-030).
   */
  canEdit: boolean;
  lastUpdateEvent?: LastUpdateEvent;
  onEditClick: () => void;
  onViewJsonClick: () => void;
}

/**
 * Dark navy hero strip rendered above the section cards on the Configuration
 * tab (Paper mock `D2 — Configuration Tab (Read)`).
 *
 * Top line: small uppercase eyebrow label "Deployment configuration".
 * Middle line: aggregate field counts (configured / inherited / overridden).
 * Bottom line: optional "Last changed Xd ago by Y — Z" — hidden when no
 * `lastUpdateEvent` is supplied.
 *
 * Right cluster: "View JSON" secondary action + "Edit configuration" primary
 * CTA. The Edit CTA is rendered ONLY when `canEdit === true` per FR-030;
 * a disabled-but-visible state is NOT used because the spec says "hide
 * actions the operator can't perform".
 */
export function HeroSummaryBar({
  environment,
  driverSchema,
  inheritance,
  current,
  canEdit,
  lastUpdateEvent,
  onEditClick,
  onViewJsonClick,
}: Props) {
  const counts = computeFieldCounts(current, driverSchema, inheritance);

  return (
    <header
      data-testid="config-hero"
      className="flex flex-col gap-3 rounded-xl bg-slate-900 px-6 py-5 text-slate-100 shadow-sm md:flex-row md:items-center md:justify-between"
    >
      <div className="flex flex-col gap-1.5">
        <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-400">
          Deployment configuration
        </span>
        <p className="text-[15px] font-medium leading-snug text-slate-100">
          <span data-testid="hero-configured-count">
            {counts.configured} field{counts.configured === 1 ? "" : "s"}{" "}
            configured
          </span>
          <span className="mx-2 text-slate-500">·</span>
          <span data-testid="hero-inherited-count">
            {counts.inherited} inherited from {environment.name}
          </span>
          <span className="mx-2 text-slate-500">·</span>
          <span data-testid="hero-overridden-count">
            {counts.overridden} overridden on this deployment
          </span>
        </p>
        {lastUpdateEvent ? (
          <p className="text-xs text-slate-400" data-testid="hero-last-update">
            Last changed {formatRelative(lastUpdateEvent.occurredAt)} by{" "}
            <span className="font-medium text-slate-200">
              {lastUpdateEvent.actor}
            </span>{" "}
            — {lastUpdateEvent.summary}
          </p>
        ) : null}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={onViewJsonClick}
          data-testid="hero-view-json-button"
          className="border-slate-600 bg-transparent text-slate-100 hover:bg-slate-800 hover:text-slate-100"
        >
          View JSON
        </Button>
        {canEdit ? (
          <Button
            type="button"
            size="sm"
            onClick={onEditClick}
            data-testid="hero-edit-config-button"
          >
            Edit configuration
          </Button>
        ) : null}
      </div>
    </header>
  );
}

interface FieldCounts {
  configured: number;
  inherited: number;
  overridden: number;
}

/**
 * Aggregate field-count metrics for the hero strip.
 *
 * - `overridden`: sum of every `inheritance.overrideCount` across sections.
 * - `configured`: total settable leaf fields visible on the deployment view
 *   (driver parameters + every populated env var + every populated component
 *   block + every populated scheduling/networking/storage scalar). We use a
 *   conservative count by walking the current input — the number is meant to
 *   communicate "scope" rather than be a precise schema-wide cardinality.
 * - `inherited`: configured − overridden.
 */
function computeFieldCounts(
  current: UpdateDeploymentInput,
  driverSchema: DriverParameterSchema,
  inheritance: Map<SectionId, InheritanceState>,
): FieldCounts {
  let overridden = 0;
  for (const state of inheritance.values()) {
    if (state.kind === "overridden") overridden += state.overrideCount;
  }

  const configured =
    countDriverParameters(current, driverSchema) +
    countList(current.envVars) +
    countList(current.components) +
    countList(current.serviceNameOverrides) +
    countList(current.ipWhitelist) +
    countSchedulingFields(current) +
    countScalars(current);

  const inherited = Math.max(0, configured - overridden);

  return { configured, inherited, overridden };
}

function countList<T>(list: readonly T[] | null | undefined): number {
  return list?.length ?? 0;
}

function countDriverParameters(
  current: UpdateDeploymentInput,
  driverSchema: DriverParameterSchema,
): number {
  // Every parameter declared by the driver is a "configured" field on the
  // deployment view, whether it sets an override or inherits the default.
  // Treat the schema length as the canonical count when present; fall back
  // to the override list otherwise.
  return (driverSchema as readonly ParameterDefinition[]).length > 0
    ? driverSchema.length
    : (current.parameters?.length ?? 0);
}

function countSchedulingFields(current: UpdateDeploymentInput): number {
  const s = current.scheduling;
  if (!s) return 0;
  let n = 0;
  if (s.resources) n += 1;
  if (s.runtimeClass) n += 1;
  if (s.tolerations) n += s.tolerations.length;
  if (s.topologySpreadConstraints) n += s.topologySpreadConstraints.length;
  if (s.nodeAffinity) n += 1;
  if (s.podAffinity) n += 1;
  if (s.podAntiAffinity) n += 1;
  return n;
}

function countScalars(current: UpdateDeploymentInput): number {
  let n = 0;
  if (current.fqdnSuffix != null) n += 1;
  if (current.externalUrlScheme != null) n += 1;
  if (current.externalUrlPort != null) n += 1;
  if (current.externalDnsEndpointsType != null) n += 1;
  if (current.ingressClass != null) n += 1;
  if (current.dbSize != null) n += 1;
  if (current.runtimeClass != null) n += 1;
  if (current.nodeSelector != null) n += 1;
  if (current.standardStorage != null) n += 1;
  if (current.dedicatedIngress != null) n += 1;
  return n;
}

/** Compact relative-time formatter — "3d ago", "2h ago", "just now". */
function formatRelative(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return iso;
  const deltaMs = Date.now() - then;
  if (deltaMs < 60_000) return "just now";
  const minutes = Math.floor(deltaMs / 60_000);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}
