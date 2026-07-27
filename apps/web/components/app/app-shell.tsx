"use client";

import Link from "next/link";
import type { Route } from "next";
import { usePathname } from "next/navigation";
import { Archive, BookOpenText, FileCheck2, History, ShieldCheck } from "lucide-react";
import type { ReactNode } from "react";

import { AuthControls } from "@/components/app/auth-controls";
import { cn } from "@/lib/utils";

const navItems: Array<{ href: Route; label: string; icon: typeof FileCheck2 }> = [
  { href: "/", label: "Workspace", icon: FileCheck2 },
  { href: "/verify", label: "Verify", icon: ShieldCheck },
  { href: "/history", label: "History", icon: History },
  { href: "/saved", label: "Saved", icon: Archive },
  { href: "/methodology", label: "Methodology", icon: BookOpenText },
];

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-30 border-b bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-4 py-3">
          <Link href="/" className="flex items-center gap-3">
            <span className="flex h-9 w-9 items-center justify-center rounded-md bg-primary text-primary-foreground">
              <ShieldCheck className="h-5 w-5" aria-hidden="true" />
            </span>
            <span>
              <span className="block text-sm font-semibold leading-4">Elara.ai</span>
              <span className="block text-xs text-muted-foreground">Evidence workspace</span>
            </span>
          </Link>
          <nav className="hidden items-center gap-1 lg:flex" aria-label="Primary">
            {navItems.map((item) => {
              const active = pathname === item.href || (item.href !== "/" && pathname.startsWith(item.href));
              const Icon = item.icon;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={cn(
                    "inline-flex h-9 items-center gap-2 rounded-md px-3 text-sm font-medium text-muted-foreground transition hover:bg-muted hover:text-foreground",
                    active && "bg-secondary text-secondary-foreground",
                  )}
                >
                  <Icon className="h-4 w-4" aria-hidden="true" />
                  {item.label}
                </Link>
              );
            })}
          </nav>
          <div className="flex items-center gap-2">
            <AuthControls />
          </div>
        </div>
        <nav className="flex gap-1 overflow-x-auto border-t px-3 py-2 lg:hidden" aria-label="Mobile primary">
          {navItems.map((item) => {
            const active = pathname === item.href || (item.href !== "/" && pathname.startsWith(item.href));
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "inline-flex min-w-fit items-center gap-2 rounded-md px-3 py-2 text-xs font-medium text-muted-foreground",
                  active && "bg-secondary text-secondary-foreground",
                )}
              >
                <Icon className="h-4 w-4" aria-hidden="true" />
                {item.label}
              </Link>
            );
          })}
        </nav>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-5">{children}</main>
    </div>
  );
}
