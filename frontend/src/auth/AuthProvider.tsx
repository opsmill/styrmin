import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  type ReactNode,
} from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  LogoutDocument,
  useCurrentUserQuery,
  type CurrentUserQuery,
  type LogoutMutation,
  type LogoutMutationVariables,
  type Role,
} from "@/generated/graphql";
import {
  graphqlFetcher,
  setUnauthenticatedHandler,
} from "@/lib/graphql-fetcher";
import { router } from "@/router";
import { LoadingState } from "@/components/LoadingState";

export type CurrentUser = NonNullable<CurrentUserQuery["currentUser"]>;
export type { Role };

export interface AuthContextValue {
  currentUser: CurrentUser | null;
  loading: boolean;
  refresh: () => Promise<void>;
  logout: () => Promise<void>;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

interface AuthProviderProps {
  children: ReactNode;
}

export function AuthProvider({ children }: AuthProviderProps) {
  const queryClient = useQueryClient();
  const query = useCurrentUserQuery(undefined, {
    staleTime: Infinity,
    retry: false,
  });

  const currentUser: CurrentUser | null = query.data?.currentUser ?? null;
  // Loading only on first response: once we have data (or an error), we are not loading.
  const loading = query.isPending && !query.isError;

  const refresh = useCallback(async () => {
    await queryClient.invalidateQueries({
      queryKey: useCurrentUserQuery.getKey(),
    });
  }, [queryClient]);

  const logout = useCallback(async () => {
    // Best-effort: tell the server to invalidate the session cookie. We always
    // proceed to clear the local cache and redirect even if the request fails
    // (network down, already unauthenticated, etc.) so the user is not stuck.
    try {
      await graphqlFetcher<LogoutMutation, LogoutMutationVariables>(
        LogoutDocument,
      )();
    } catch {
      // Swallow — the local cleanup below is what matters for the UX.
    }
    queryClient.clear();
    await router.navigate({ to: "/login" });
  }, [queryClient]);

  // Register the UNAUTHENTICATED handler so any subsequent query that gets
  // rejected with code=UNAUTHENTICATED clears the cache and bounces to /login.
  useEffect(() => {
    setUnauthenticatedHandler(() => {
      queryClient.clear();
      void router.navigate({ to: "/login" });
    });
    return () => {
      setUnauthenticatedHandler(null);
    };
  }, [queryClient]);

  const value = useMemo<AuthContextValue>(
    () => ({ currentUser, loading, refresh, logout }),
    [currentUser, loading, refresh, logout],
  );

  // Push the auth context into the router so route `beforeLoad` guards see
  // a fresh value synchronously.
  useEffect(() => {
    router.update({
      context: { ...router.options.context, auth: value },
    });
  }, [value]);

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <LoadingState message="Loading..." />
      </div>
    );
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (ctx === null) {
    throw new Error("useAuth must be used inside an <AuthProvider>");
  }
  return ctx;
}
