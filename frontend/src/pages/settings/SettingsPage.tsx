import { Link } from "@tanstack/react-router";
import { PageLayout } from "@/components/PageLayout";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Users, UsersRound } from "lucide-react";
import { IfRole } from "@/auth/IfRole";
import { useDocumentTitle } from "@/hooks/use-document-title";

export default function SettingsPage() {
  useDocumentTitle("Settings");
  return (
    <PageLayout title="Settings" breadcrumbs={[{ label: "Settings" }]}>
      <IfRole minimum="ADMIN">
        <section>
          <h2 className="text-lg font-semibold mb-4">Access</h2>
          <div className="grid gap-4 sm:grid-cols-2 max-w-xl">
            <Link to="/users" className="block" data-testid="users-card">
              <Card className="cursor-pointer hover:border-primary/50 transition-colors">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <Users className="h-4 w-4" />
                    Users
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="text-xs text-muted-foreground">
                    Manage user accounts, roles, and activation status.
                  </p>
                </CardContent>
              </Card>
            </Link>
            <Link to="/groups" className="block" data-testid="groups-card">
              <Card className="cursor-pointer hover:border-primary/50 transition-colors">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <UsersRound className="h-4 w-4" />
                    Groups
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="text-xs text-muted-foreground">
                    Group memberships confer effective roles to users.
                  </p>
                </CardContent>
              </Card>
            </Link>
          </div>
        </section>
      </IfRole>
    </PageLayout>
  );
}
