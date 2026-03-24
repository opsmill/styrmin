import { Link } from "react-router";
import { ChevronRight } from "lucide-react";
import { Separator } from "@/components/ui/separator";
import type { ReactNode } from "react";

interface Breadcrumb {
  label: string;
  href?: string;
}

interface PageLayoutProps {
  title: string;
  breadcrumbs?: Breadcrumb[];
  actions?: ReactNode;
  children: ReactNode;
}

export function PageLayout({
  title,
  breadcrumbs,
  actions,
  children,
}: PageLayoutProps) {
  return (
    <div>
      <header className="border-b bg-background">
        <div className="container mx-auto px-6 py-4">
          {breadcrumbs && breadcrumbs.length > 0 && (
            <nav className="flex items-center gap-1 text-sm text-muted-foreground mb-2">
              <Link to="/" className="hover:text-foreground">
                Styrmin
              </Link>
              {breadcrumbs.map((crumb, i) => (
                <span key={i} className="flex items-center gap-1">
                  <ChevronRight className="h-3 w-3" />
                  {crumb.href ? (
                    <Link to={crumb.href} className="hover:text-foreground">
                      {crumb.label}
                    </Link>
                  ) : (
                    <span className="text-foreground">{crumb.label}</span>
                  )}
                </span>
              ))}
            </nav>
          )}
          <div className="flex items-center justify-between">
            <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
            {actions && (
              <div className="flex items-center gap-2">{actions}</div>
            )}
          </div>
        </div>
      </header>
      <Separator />
      <main className="container mx-auto px-6 py-6">{children}</main>
    </div>
  );
}
