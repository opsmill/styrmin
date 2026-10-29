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

// Write the user into router.options.context right away, without waiting for
// AuthProvider's next render, so that a navigate() call made just after sees
// it in the route guards.
function setRouterUser(currentUser: CurrentUser | null): void {
  router.options.context = {
    ...router.options.context,
    auth: {
      ...router.options.context?.auth,
      currentUser,
    } as AuthContextValue,
  };
}

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
    // After the refetch the cache holds fresh data, but React's automatic
    // batching defers AuthProvider's re-render (and its synchronous
    // router.options.context assignment below) until after the current
    // microtask chain. Eagerly propagate the new currentUser into
    // router.options.context here so that any navigate() call made
    // immediately after refresh() sees the authenticated state.
    const data = queryClient.getQueryData<CurrentUserQuery>(
      useCurrentUserQuery.getKey(),
    );
    setRouterUser(data?.currentUser ?? null);
  }, [queryClient]);

  // Shared by Logout and by any UNAUTHENTICATED response.
  const signOutLocally = useCallback(async () => {
    const currentUserKey = useCurrentUserQuery.getKey();
    // Set the user to null in the CurrentUser query instead of removing it.
    // queryClient.clear() removed that query without notifying this
    // component, so AuthProvider and router.options.context kept the old
    // user, the /login guard sent the browser back to "/", the page's queries
    // failed with UNAUTHENTICATED, and the cycle repeated without end.
    queryClient.setQueryData<CurrentUserQuery>(currentUserKey, {
      currentUser: null,
    });
    setRouterUser(null);
    await router.navigate({ to: "/login" });
    // Drop the previous user's data after the navigation to /login.
    queryClient.removeQueries({
      predicate: (query) => query.queryKey[0] !== currentUserKey[0],
    });
    queryClient.getMutationCache().clear();
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
    await signOutLocally();
  }, [signOutLocally]);

  // Register the UNAUTHENTICATED handler so any subsequent query that gets
  // rejected with code=UNAUTHENTICATED signs the user out locally and
  // bounces to /login.
  useEffect(() => {
    setUnauthenticatedHandler(() => {
      void signOutLocally();
    });
    return () => {
      setUnauthenticatedHandler(null);
    };
  }, [signOutLocally]);

  const value = useMemo<AuthContextValue>(
    () => ({ currentUser, loading, refresh, logout }),
    [currentUser, loading, refresh, logout],
  );

  // Push the auth context into the router synchronously, BEFORE we mount
  // the router as a child. A useEffect-based update would run after
  // ``children`` mount on this same commit, and the router's beforeLoad
  // guards would observe a stale ``auth = undefined`` on the very first
  // route resolution — bouncing a deep link like ``/settings`` to /login,
  // then immediately back to / once the effect lands. ``router.options``
  // is TanStack Router's own mutable config bag, not React state; the
  // react-hooks/immutability rule fires on the assignment but this is a
  // deliberate, deterministic write.
  // eslint-disable-next-line react-hooks/immutability
  router.options.context = { ...router.options.context, auth: value };

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
