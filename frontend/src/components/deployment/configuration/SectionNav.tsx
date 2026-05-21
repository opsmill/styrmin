import { useEffect, useMemo, useState } from "react";
import {
  DRAWER_SECTION_GROUPS,
  type SectionId,
} from "@/lib/configuration-types";
import { cn } from "@/lib/utils";

import { useDrawerDiff } from "./DrawerDiffContext";

const SECTION_LABELS: Record<SectionId, string> = {
  identity: "Identity",
  driverParameters: "Driver Parameters",
  scheduling: "Scheduling",
  networking: "Networking",
  envVars: "Environment Vars",
  storageRuntime: "Storage & Runtime",
  serviceOverrides: "Services",
  componentOverrides: "Components",
};

interface Props {
  /**
   * Scroll container the section anchors live inside. `IntersectionObserver`
   * uses this as its `root` so scroll-spy semantics match the visible viewport
   * (not the page document, which would be wrong inside a drawer).
   */
  scrollContainerRef: React.RefObject<HTMLElement | null>;
}

/**
 * Left rail rendered inside `ConfigEditDrawer`.
 *
 * Two responsibilities:
 *
 *   1. Scroll-spy — uses `IntersectionObserver` against the drawer's scroll
 *      container to track which `[data-section]` anchor is most visible and
 *      highlight the matching nav row. Native API, no third-party scroll-spy
 *      library (R-006).
 *
 *   2. "Changed" dots — reads the shared drawer diff result and renders a
 *      blue dot next to any section whose `sectionsChanged` set contains it.
 *      The diff is computed once per keystroke in {@link DrawerDiffProvider};
 *      this matches the footer's pending-change count and the Review & apply
 *      dialog via the same helper.
 *
 * Clicking a row calls `scrollIntoView({behavior: 'smooth', block: 'start'})`
 * on the matching anchor element.
 */
export function SectionNav({ scrollContainerRef }: Props) {
  const diffResult = useDrawerDiff();
  const changedSections = useMemo(
    () => new Set(diffResult.sectionsChanged),
    [diffResult.sectionsChanged],
  );

  const [activeSection, setActiveSection] = useState<SectionId>(
    // First section of the first group — drawer always opens with the
    // Identity group at the top, so this resolves to "identity".
    DRAWER_SECTION_GROUPS[0].sectionIds[0],
  );

  useEffect(() => {
    const root = scrollContainerRef.current;
    if (!root) return;

    const observer = new IntersectionObserver(
      (entries) => {
        // Pick the most-visible section. Multiple anchors can intersect
        // simultaneously during scroll; choose the one with the largest
        // intersection ratio so the highlight tracks reading position.
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio);
        const top = visible[0];
        if (!top) return;
        const sectionId = (top.target as HTMLElement).dataset.section as
          | SectionId
          | undefined;
        if (sectionId) {
          setActiveSection(sectionId);
        }
      },
      {
        root,
        // Trip at 50% visibility — Stripe/Linear style scroll-spy.
        threshold: [0, 0.25, 0.5, 0.75, 1],
        rootMargin: "0px 0px -40% 0px",
      },
    );

    const anchors = root.querySelectorAll<HTMLElement>("[data-section]");
    anchors.forEach((el) => observer.observe(el));

    return () => observer.disconnect();
  }, [scrollContainerRef]);

  const handleClick = (sectionId: SectionId) => {
    const root = scrollContainerRef.current;
    if (!root) return;
    const target = root.querySelector<HTMLElement>(
      `[data-section="${sectionId}"]`,
    );
    if (target) {
      target.scrollIntoView({ behavior: "smooth", block: "start" });
      setActiveSection(sectionId);
    }
  };

  return (
    <nav
      aria-label="Configuration sections"
      data-testid="drawer-section-nav"
      className="flex w-[200px] shrink-0 flex-col gap-4 border-r border-border bg-muted px-3 py-4"
    >
      {DRAWER_SECTION_GROUPS.map((group) => (
        <div
          key={group.id}
          className="flex flex-col gap-1"
          data-section-group={group.id}
        >
          {group.label ? (
            <h3
              data-testid={`section-nav-group-label-${group.id}`}
              className="px-2 pb-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground"
            >
              {group.label}
            </h3>
          ) : null}
          {group.sectionIds.map((sectionId) => {
            const isActive = sectionId === activeSection;
            const isChanged = changedSections.has(sectionId);
            return (
              <button
                key={sectionId}
                type="button"
                onClick={() => handleClick(sectionId)}
                aria-current={isActive ? "true" : undefined}
                data-testid={`section-nav-${sectionId}`}
                data-changed={isChanged ? "true" : undefined}
                className={cn(
                  "group flex items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors",
                  isActive
                    ? "bg-background text-foreground shadow-sm ring-1 ring-border"
                    : "text-muted-foreground hover:bg-background/60 hover:text-foreground",
                )}
              >
                <span
                  aria-hidden="true"
                  className={cn(
                    "h-1.5 w-1.5 shrink-0 rounded-full",
                    isChanged ? "bg-blue-500" : "bg-transparent",
                  )}
                  data-testid={
                    isChanged ? `section-changed-dot-${sectionId}` : undefined
                  }
                />
                <span className="truncate">{SECTION_LABELS[sectionId]}</span>
              </button>
            );
          })}
        </div>
      ))}
    </nav>
  );
}
