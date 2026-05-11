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
  useCurrentUserQuery,
  type CurrentUserQuery,
  type Role,
} from "@/generated/graphql";
import { setUnauthenticatedHandler } from "@/lib/graphql-fetcher";
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
    // Logout mutation wiring is added in a later task (US1). For now,
    // clear cached queries and navigate to the login page.
    queryClient.clear();
    // The /login route is registered by a later task; use a loose cast so
    // this file compiles independently of that route's registration.
    await router.navigate({ to: "/login" } as Parameters<
      typeof router.navigate
    >[0]);
  }, [queryClient]);

  // Register the UNAUTHENTICATED handler so any subsequent query that gets
  // rejected with code=UNAUTHENTICATED clears the cache and bounces to /login.
  useEffect(() => {
    setUnauthenticatedHandler(() => {
      queryClient.clear();
      void router.navigate({ to: "/login" } as Parameters<
        typeof router.navigate
      >[0]);
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
