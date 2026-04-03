import { QueryClient } from "@tanstack/react-query";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 0,
      gcTime: 300_000,
      retry: 3,
      refetchOnWindowFocus: true,
    },
    mutations: {
      retry: 0,
    },
  },
});
