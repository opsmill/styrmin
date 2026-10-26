import { useState, type FormEvent } from "react";
import { useNavigate, useSearch } from "@tanstack/react-router";
import { useLoginMutation } from "@/generated/graphql";
import { useAuth } from "@/auth/AuthProvider";
import { safeNext } from "@/lib/safe-next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { StyrminLogo } from "@/components/StyrminLogo";
import { useDocumentTitle } from "@/hooks/use-document-title";

const GENERIC_ERROR = "Invalid username or password.";

export default function LoginPage() {
  useDocumentTitle("Sign in");
  const { refresh } = useAuth();
  const navigate = useNavigate();
  // The /login route's `validateSearch` has already filtered `next` through
  // `safeNext`; we re-validate at submit time to defend against any in-flight
  // change to `location.search`.
  const search = useSearch({ from: "/login" });
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const loginMutation = useLoginMutation({
    onSuccess: async () => {
      setErrorMessage(null);
      // Refetch currentUser so the AuthProvider transitions to the
      // authenticated state, then navigate to the originally requested
      // destination (or '/' if no safe `next` was provided). The /login
      // route's beforeLoad guard only fires on navigation — staying on the
      // same route after refresh() would leave the user stuck on the form.
      await refresh();
      const dest = safeNext(search.next) ?? "/";
      await navigate({ to: dest });
    },
    onError: () => {
      // Surface a single generic message regardless of the server's reason
      // (per FR & spec contract — do not leak whether the username or
      // password was wrong).
      setErrorMessage(GENERIC_ERROR);
    },
  });

  function handleSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    if (loginMutation.isPending) return;
    setErrorMessage(null);
    loginMutation.mutate({ username, password });
  }

  const submitting = loginMutation.isPending;

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <Card className="w-full max-w-sm">
        <CardHeader className="space-y-4">
          <StyrminLogo className="h-10 w-10" />
          <CardTitle>
            <h1>Sign in to Styrmin</h1>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="login-username">Username</Label>
              <Input
                id="login-username"
                type="text"
                autoComplete="username"
                required
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                disabled={submitting}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="login-password">Password</Label>
              <Input
                id="login-password"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                disabled={submitting}
              />
            </div>

            {errorMessage !== null && (
              <p
                role="alert"
                className="text-sm text-destructive"
                data-testid="login-error"
              >
                {errorMessage}
              </p>
            )}

            <Button type="submit" disabled={submitting} className="w-full">
              {submitting ? "Signing in…" : "Sign in"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
