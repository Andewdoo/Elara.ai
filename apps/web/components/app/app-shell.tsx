"use client";

import Link from "next/link";
import type { Route } from "next";
import { usePathname } from "next/navigation";
import { Archive, Asterisk, BookOpenText, FileCheck2, History, PanelLeftClose, PanelLeftOpen, ShieldCheck } from "lucide-react";
import { useState, type ReactNode } from "react";

import { AuthControls } from "@/components/app/auth-controls";
import { cn } from "@/lib/utils";

const navItems: Array<{ href: Route; label: string; icon: typeof FileCheck2 }> = [
  { href: "/verify", label: "Verify", icon: ShieldCheck },
  { href: "/history", label: "History", icon: History },
  { href: "/saved", label: "Saved", icon: Archive },
  { href: "/methodology", label: "Methodology", icon: BookOpenText },
  { href: "/", label: "Demo", icon: FileCheck2 },
];

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const isDemo = pathname === "/";
  const [sidebarOpen, setSidebarOpen] = useState(true);

  function closeSidebarOnMobile() {
    if (window.matchMedia("(max-width: 767px)").matches) {
      setSidebarOpen(false);
    }
  }

  if (isDemo) {
    return (
      <div className="min-h-dvh bg-background">
        <a href="#main-content" className="sr-only z-50 rounded-md bg-sidebar px-4 py-3 text-sidebar-foreground focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus-visible:ring-2 focus-visible:ring-white">
          Skip to main content
        </a>
        <header className="border-b bg-card">
          <div className="mx-auto flex min-h-16 max-w-5xl items-center gap-3 px-4 sm:px-6">
            <Asterisk className="h-7 w-7 shrink-0 text-accent" strokeWidth={1.65} aria-hidden="true" />
            <span className="font-editorial text-2xl leading-none tracking-[-0.035em] text-foreground">Elara.ai</span>
            <span className="border-l pl-3 text-sm font-medium text-muted-foreground">Demo</span>
          </div>
        </header>
        <main id="main-content" className="min-h-[calc(100dvh-4rem)] px-4 py-8 sm:px-6 sm:py-12">
          <div className="mx-auto max-w-5xl">{children}</div>
        </main>
      </div>
    );
  }

  return (
    <div className="min-h-dvh bg-background">
      <a href="#main-content" className="sr-only z-50 rounded-md bg-sidebar px-4 py-3 text-sidebar-foreground focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus-visible:ring-2 focus-visible:ring-white">
        Skip to main content
      </a>
      {sidebarOpen && <button type="button" className="fixed inset-0 z-30 bg-black/50 md:hidden" aria-label="Close navigation" onClick={() => setSidebarOpen(false)} />}
      <aside
        id="primary-sidebar"
        className={cn(
          "fixed inset-y-0 left-0 z-40 flex w-72 flex-col border-r border-sidebar-border bg-sidebar px-3 py-4 text-sidebar-foreground transition-[transform,width] duration-200 ease-out motion-reduce:transition-none",
          sidebarOpen ? "w-72 translate-x-0" : "w-16 translate-x-0",
        )}
        aria-label="Primary navigation"
      >
        <div className={cn("border-b border-sidebar-border pb-5", sidebarOpen ? "px-2" : "px-0")}>
          <Link href="/" className={cn("flex min-h-11 items-center gap-3 rounded-md outline-none focus-visible:ring-2 focus-visible:ring-white focus-visible:ring-offset-2 focus-visible:ring-offset-sidebar", sidebarOpen ? "px-1" : "justify-center")} aria-label="Elara.ai home" title={sidebarOpen ? undefined : "Elara.ai home"}>
            <Asterisk className="h-9 w-9 shrink-0 text-accent" strokeWidth={1.65} aria-hidden="true" />
            {sidebarOpen && <span className="font-editorial text-[1.85rem] font-normal leading-none tracking-[-0.035em]">Elara.ai</span>}
          </Link>
        </div>

        <button
          type="button"
          className="absolute -right-4 top-6 z-50 inline-flex h-8 w-8 items-center justify-center rounded-full border border-sidebar-border bg-sidebar text-sidebar-muted shadow-subtle transition duration-200 hover:bg-sidebar-active hover:text-sidebar-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-sidebar motion-reduce:transition-none"
          aria-label={sidebarOpen ? "Collapse Elara navigation" : "Open Elara navigation"}
          aria-controls="primary-sidebar"
          aria-expanded={sidebarOpen}
          onClick={() => setSidebarOpen((open) => !open)}
        >
          {sidebarOpen ? <PanelLeftClose className="h-4 w-4" aria-hidden="true" /> : <PanelLeftOpen className="h-4 w-4" aria-hidden="true" />}
        </button>

        <nav className="mt-6 grid gap-1" aria-label="Workspace navigation">
          {navItems.map((item) => {
            const active = pathname === item.href || (item.href !== "/" && pathname.startsWith(item.href));
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                onClick={closeSidebarOnMobile}
                aria-current={active ? "page" : undefined}
                title={sidebarOpen ? undefined : item.label}
                className={cn(
                  "flex min-h-11 items-center rounded-md text-sm font-medium outline-none transition duration-200 hover:bg-white/10 hover:text-sidebar-foreground focus-visible:ring-2 focus-visible:ring-white focus-visible:ring-offset-2 focus-visible:ring-offset-sidebar",
                  sidebarOpen ? "gap-3 px-3" : "justify-center px-2",
                  active ? "bg-sidebar-active text-sidebar-foreground" : "text-sidebar-muted",
                )}
              >
                <Icon className="h-5 w-5 shrink-0" aria-hidden="true" />
                {sidebarOpen && item.label}
              </Link>
            );
          })}
        </nav>

        <div className="mt-auto border-t border-sidebar-border pt-3">
          <AuthControls sidebarOpen={sidebarOpen} />
        </div>
      </aside>

      <main id="main-content" className={cn("min-h-dvh px-4 py-5 transition-[margin] duration-200 ease-out motion-reduce:transition-none sm:px-6", sidebarOpen ? "md:ml-72" : "ml-16")}>
        <div className="mx-auto max-w-7xl">{children}</div>
      </main>
    </div>
  );
}
