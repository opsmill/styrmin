import { Link } from "@tanstack/react-router";
import { ShieldAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PageLayout } from "@/components/PageLayout";

interface AccessDeniedProps {
  /**
   * Short label identifying the restricted area, e.g. "Users", "Groups".
   * Rendered in the page title and the explanation text so the user can
   * tell at a glance which feature requires elevation.
   */
  area: string;
  /**
   * Role the route requires. Surfaced verbatim to the user.
   */
  requiredRole: string;
}

/**
 * Standardised access-denied page shown when an authenticated user lands on
 * a route they don't have permission for. Replaces the older "silent
 * redirect to /" behaviour which left users confused about why their
 * bookmarked or deep-linked URL appeared not to work.
 */
export function AccessDenied({ area, requiredRole }: AccessDeniedProps) {
  return (
    <PageLayout
      title="Access denied"
      breadcrumbs={[{ label: "Access denied" }]}
    >
      <div
        data-testid="access-denied"
        className="mx-auto flex max-w-xl flex-col items-center gap-4 py-16 text-center"
      >
        <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-destructive/10">
          <ShieldAlert className="h-8 w-8 text-destructive" />
        </div>
        <div className="flex flex-col items-center gap-1.5">
          <h2 className="text-lg font-semibold text-foreground">
            {area} requires the {requiredRole} role
          </h2>
          <p className="max-w-md text-[13px] text-muted-foreground">
            Your account does not have permission to view this page. If you
            think this is a mistake, ask an administrator to update your role.
          </p>
        </div>
        <Button asChild variant="outline">
          <Link to="/">Back to dashboard</Link>
        </Button>
      </div>
    </PageLayout>
  );
}
