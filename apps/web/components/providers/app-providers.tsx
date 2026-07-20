"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { FirebaseAuthProvider } from "@/components/providers/firebase-auth-provider";
import type { PublicFirebaseConfig } from "@/lib/firebase";

export function AppProviders({ children, publicFirebaseConfig }: { children: ReactNode; publicFirebaseConfig: PublicFirebaseConfig }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            refetchOnWindowFocus: false,
          },
        },
      }),
  );

  return (
    <QueryClientProvider client={queryClient}>
      <FirebaseAuthProvider publicFirebaseConfig={publicFirebaseConfig}>{children}</FirebaseAuthProvider>
    </QueryClientProvider>
  );
}
