import type { Metadata } from "next";
import type { ReactNode } from "react";

import { AppShell } from "@/components/app/app-shell";
import { AppProviders } from "@/components/providers/app-providers";
import "./globals.css";

export const metadata: Metadata = {
  title: "Elara.ai Demo",
  description: "A read-only archive of completed Elara verification runs.",
};

export default async function RootLayout({ children }: { children: ReactNode }) {
  const environment = process.env;
  const publicFirebaseConfig = {
    apiKey: environment.NEXT_PUBLIC_FIREBASE_API_KEY,
    authDomain: environment.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN,
    projectId: environment.NEXT_PUBLIC_FIREBASE_PROJECT_ID,
    appId: environment.NEXT_PUBLIC_FIREBASE_APP_ID,
  };

  return (
    <html lang="en">
      <body>
        <AppProviders publicFirebaseConfig={publicFirebaseConfig}>
          <AppShell>{children}</AppShell>
        </AppProviders>
      </body>
    </html>
  );
}
