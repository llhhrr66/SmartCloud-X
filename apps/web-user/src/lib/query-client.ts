import { QueryClient } from "@tanstack/react-query";
import { ApiError } from "@smartcloud-x/frontend-sdk/core";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      gcTime: 5 * 60_000,
      retry: (count, err) => {
        if (err instanceof ApiError) {
          if (err.status === 401 || err.status === 403 || err.status === 404 || err.status === 422) return false;
        }
        return count < 2;
      },
      refetchOnWindowFocus: false,
    },
    mutations: {
      retry: false,
    },
  },
});
