import { useState, type FormEvent } from "react";
import { AlertCircle, KeyRound, Save } from "lucide-react";

import {
  useUpdateUserMutation,
  useChangePasswordMutation,
} from "@/generated/graphql";
import { GraphQLOperationError } from "@/lib/graphql-fetcher";
import { useAuth } from "@/auth/AuthProvider";
import { PASSWORD_REQUIREMENTS_SUMMARY } from "@/auth/password-policy";
import { PageLayout } from "@/components/PageLayout";
import { LoadingState } from "@/components/LoadingState";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { useDocumentTitle } from "@/hooks/use-document-title";

interface CodeError extends Error {
  code?: string;
}

function extractCode(err: unknown): string | null {
  if (err instanceof GraphQLOperationError) {
    return err.code;
  }
  if (err instanceof Error) {
    const code = (err as CodeError).code;
    return typeof code === "string" ? code : null;
  }
  return null;
}

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : "Unknown error";
}

export default function ProfilePage() {
  useDocumentTitle("Profile");
  const { currentUser, refresh } = useAuth();

  // ----- Display name form state -----
  const [displayName, setDisplayName] = useState(
    currentUser?.displayName ?? "",
  );
  const [displayNameSeededFor, setDisplayNameSeededFor] = useState<
    string | null
  >(currentUser?.id ?? null);
  const [displayNameSuccess, setDisplayNameSuccess] = useState<string | null>(
    null,
  );
  const [displayNameError, setDisplayNameError] = useState<string | null>(null);

  // Re-seed the display-name field if the caller switches identity mid-flight
  // (e.g. the auth context refreshes with a different user). We avoid an
  // effect-based reset to keep the seeding synchronous.
  if (currentUser !== null && displayNameSeededFor !== currentUser.id) {
    setDisplayNameSeededFor(currentUser.id);
    setDisplayName(currentUser.displayName);
  }

  // ----- Change-password form state -----
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newPasswordConfirm, setNewPasswordConfirm] = useState("");
  const [currentPasswordError, setCurrentPasswordError] = useState<
    string | null
  >(null);
  const [newPasswordConfirmError, setNewPasswordConfirmError] = useState<
    string | null
  >(null);
  const [passwordChangeSuccess, setPasswordChangeSuccess] = useState<
    string | null
  >(null);
  const [passwordChangeError, setPasswordChangeError] = useState<string | null>(
    null,
  );

  const updateUserMutation = useUpdateUserMutation({
    onSuccess: async () => {
      setDisplayNameError(null);
      setDisplayNameSuccess("Display name updated.");
      // Re-issue the currentUser query so the header reflects the new name.
      await refresh();
    },
    onError: (err) => {
      setDisplayNameSuccess(null);
      setDisplayNameError(errorMessage(err));
    },
  });

  const changePasswordMutation = useChangePasswordMutation({
    onSuccess: () => {
      setCurrentPasswordError(null);
      setPasswordChangeError(null);
      setPasswordChangeSuccess(
        "Password changed. Other sessions have been signed out.",
      );
      setCurrentPassword("");
      setNewPassword("");
      setNewPasswordConfirm("");
    },
    onError: (err) => {
      setPasswordChangeSuccess(null);
      const code = extractCode(err);
      const msg = errorMessage(err);
      if (code === "INVALID_CREDENTIALS") {
        // Surface as an inline error on the current-password field rather than
        // a top-level alert — that matches the spec's "wrong-current-password
        // renders inline error" acceptance.
        setCurrentPasswordError("Current password is incorrect.");
        setPasswordChangeError(null);
      } else {
        setCurrentPasswordError(null);
        setPasswordChangeError(msg);
      }
    },
  });

  if (currentUser === null) {
    // Root-level `requireAuth` should have redirected to /login long before
    // this component mounts; the null branch only exists to satisfy types.
    return (
      <PageLayout title="Profile">
        <LoadingState message="Loading profile..." />
      </PageLayout>
    );
  }

  function handleDisplayNameSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    if (currentUser === null) return;
    setDisplayNameSuccess(null);
    setDisplayNameError(null);
    // Skip the round-trip if the value is unchanged.
    if (displayName === currentUser.displayName) {
      return;
    }
    updateUserMutation.mutate({
      id: currentUser.id,
      input: {
        displayName,
        role: null,
        active: null,
        groupIds: null,
      },
    });
  }

  function handleChangePasswordSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    setPasswordChangeSuccess(null);
    setPasswordChangeError(null);
    setCurrentPasswordError(null);
    setNewPasswordConfirmError(null);

    // Client-side check only — the server takes only `newPassword`.
    if (newPassword !== newPasswordConfirm) {
      setNewPasswordConfirmError("Passwords do not match.");
      return;
    }

    changePasswordMutation.mutate({
      currentPassword,
      newPassword,
    });
  }

  const displayNameSubmitting = updateUserMutation.isPending;
  const passwordSubmitting = changePasswordMutation.isPending;

  return (
    <PageLayout title="Profile" breadcrumbs={[{ label: "Profile" }]}>
      <div className="flex flex-col gap-6 max-w-2xl">
        <Card data-testid="profile-display-name-card">
          <CardHeader>
            <CardTitle>Account</CardTitle>
            <CardDescription>
              Your username identifies you to the system; only the display name
              can be edited here.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form
              onSubmit={handleDisplayNameSubmit}
              className="flex flex-col gap-4"
              data-testid="profile-display-name-form"
            >
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="profile-username">Username</Label>
                <Input
                  id="profile-username"
                  type="text"
                  value={currentUser.username}
                  readOnly
                  disabled
                  data-testid="profile-username"
                />
                <p className="text-xs text-muted-foreground">
                  Username cannot be changed — contact an admin.
                </p>
              </div>

              <div className="flex flex-col gap-1.5">
                <Label htmlFor="profile-display-name">Display name</Label>
                <Input
                  id="profile-display-name"
                  type="text"
                  value={displayName}
                  onChange={(event) => setDisplayName(event.target.value)}
                  disabled={displayNameSubmitting}
                  data-testid="profile-display-name"
                  required
                />
              </div>

              {displayNameError !== null && (
                <Alert
                  variant="destructive"
                  data-testid="profile-display-name-error"
                >
                  <AlertCircle className="h-4 w-4" />
                  <AlertTitle>Error</AlertTitle>
                  <AlertDescription>{displayNameError}</AlertDescription>
                </Alert>
              )}
              {displayNameSuccess !== null && (
                <Alert data-testid="profile-display-name-success">
                  <AlertTitle>Saved</AlertTitle>
                  <AlertDescription>{displayNameSuccess}</AlertDescription>
                </Alert>
              )}

              <div className="flex justify-end">
                <Button
                  type="submit"
                  disabled={
                    displayNameSubmitting ||
                    displayName === currentUser.displayName
                  }
                  data-testid="profile-display-name-save"
                >
                  <Save className="h-4 w-4 mr-1" />
                  {displayNameSubmitting ? "Saving…" : "Save display name"}
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>

        <Card data-testid="profile-change-password-card">
          <CardHeader>
            <CardTitle>Change password</CardTitle>
            <CardDescription>
              Changing your password will sign out your other active sessions.
              This session will stay signed in.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form
              onSubmit={handleChangePasswordSubmit}
              className="flex flex-col gap-4"
              data-testid="profile-change-password-form"
            >
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="profile-current-password">
                  Current password
                </Label>
                <Input
                  id="profile-current-password"
                  type="password"
                  autoComplete="current-password"
                  value={currentPassword}
                  onChange={(event) => setCurrentPassword(event.target.value)}
                  disabled={passwordSubmitting}
                  required
                  data-testid="profile-current-password"
                />
                {currentPasswordError !== null && (
                  <p
                    className="text-sm text-destructive"
                    role="alert"
                    data-testid="profile-current-password-error"
                  >
                    {currentPasswordError}
                  </p>
                )}
              </div>

              <div className="flex flex-col gap-1.5">
                <Label htmlFor="profile-new-password">New password</Label>
                <Input
                  id="profile-new-password"
                  type="password"
                  autoComplete="new-password"
                  value={newPassword}
                  onChange={(event) => setNewPassword(event.target.value)}
                  disabled={passwordSubmitting}
                  required
                  aria-describedby="profile-new-password-policy"
                  data-testid="profile-new-password"
                />
                <p
                  id="profile-new-password-policy"
                  className="text-xs text-muted-foreground"
                  data-testid="profile-new-password-policy"
                >
                  {PASSWORD_REQUIREMENTS_SUMMARY}
                </p>
              </div>

              <div className="flex flex-col gap-1.5">
                <Label htmlFor="profile-new-password-confirm">
                  Confirm new password
                </Label>
                <Input
                  id="profile-new-password-confirm"
                  type="password"
                  autoComplete="new-password"
                  value={newPasswordConfirm}
                  onChange={(event) =>
                    setNewPasswordConfirm(event.target.value)
                  }
                  disabled={passwordSubmitting}
                  required
                  data-testid="profile-new-password-confirm"
                />
                {newPasswordConfirmError !== null && (
                  <p
                    className="text-sm text-destructive"
                    role="alert"
                    data-testid="profile-new-password-confirm-error"
                  >
                    {newPasswordConfirmError}
                  </p>
                )}
              </div>

              {passwordChangeError !== null && (
                <Alert
                  variant="destructive"
                  data-testid="profile-change-password-error"
                >
                  <AlertCircle className="h-4 w-4" />
                  <AlertTitle>Error</AlertTitle>
                  <AlertDescription>{passwordChangeError}</AlertDescription>
                </Alert>
              )}
              {passwordChangeSuccess !== null && (
                <Alert data-testid="profile-change-password-success">
                  <AlertTitle>Saved</AlertTitle>
                  <AlertDescription>{passwordChangeSuccess}</AlertDescription>
                </Alert>
              )}

              <div className="flex justify-end">
                <Button
                  type="submit"
                  disabled={passwordSubmitting}
                  data-testid="profile-change-password-save"
                >
                  <KeyRound className="h-4 w-4 mr-1" />
                  {passwordSubmitting ? "Saving…" : "Change password"}
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>
      </div>
    </PageLayout>
  );
}
