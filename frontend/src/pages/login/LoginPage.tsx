import { useState, type FormEvent } from "react";
import { useNavigate } from "@tanstack/react-router";
import { useLoginMutation } from "@/generated/graphql";
import { useAuth } from "@/auth/AuthProvider";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const GENERIC_ERROR = "Invalid username or password.";

export default function LoginPage() {
  const { refresh } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const loginMutation = useLoginMutation({
    onSuccess: async () => {
      setErrorMessage(null);
      // Refetch currentUser so the AuthProvider transitions to the
      // authenticated state, then navigate to '/'. The /login route's
      // beforeLoad guard only fires on navigation — staying on the same
      // route after refresh() would leave the user stuck on the form.
      await refresh();
      await navigate({ to: "/" });
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
        <CardHeader>
          <CardTitle>Sign in to Styrmin</CardTitle>
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
