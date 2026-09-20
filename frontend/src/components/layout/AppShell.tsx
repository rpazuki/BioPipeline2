"use client";

/**
 * The signed-in frame: navigation, who you are, and the re-auth dialog.
 *
 * Also the place that keeps an anonymous visitor off an authenticated page.
 * That is a redirect for convenience, not a control — the backend refuses the
 * requests either way, and a shell that hid a page it could not protect would
 * be worse than one that admits what it is.
 */

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import type { ReactNode } from "react";

import { Loading } from "@/components/ui/states";
import { FirstPassword } from "@/features/auth/FirstPassword";
import { ReauthDialog } from "@/features/auth/ReauthDialog";
import { useSession } from "@/features/auth/session";
import { mayVisit, visibleNav } from "@/lib/route-policy";

export function AppShell({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const { status, user, role, config, signOut } = useSession();

  useEffect(() => {
    if (status === "anonymous") router.replace("/login");
  }, [status, router]);

  if (status === "loading") return <Loading what="your session" />;
  if (status === "anonymous") return <Loading what="the sign-in page" />;

  // In front of everything, not beside it: the server accepts exactly one
  // request from this session, so any page shown here would be a page whose
  // every button returns a 403.
  if (user?.must_change_password) return <FirstPassword />;

  const permitted = mayVisit(pathname, role);

  return (
    <div className="shell">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="shell__bar">
        <Link href="/runs" className="shell__brand">
          {config.app_name}
        </Link>
        {config.environment !== "production" ? (
          <span className="environment-tag">{config.environment}</span>
        ) : null}
        <nav className="shell__nav" aria-label="Main">
          {visibleNav(role).map((item) => {
            const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={active ? "shell__link shell__link--active" : "shell__link"}
                aria-current={active ? "page" : undefined}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
        <div className="shell__user">
          <span className="muted">{user?.display_name}</span>
          <button
            type="button"
            className="button button--quiet"
            onClick={() => {
              void signOut().then(() => router.replace("/login"));
            }}
          >
            Sign out
          </button>
        </div>
      </header>

      <main id="main" className="shell__main">
        {permitted ? (
          children
        ) : (
          <div className="state state--failed" role="alert">
            <p className="state__title">This page is for administrators.</p>
            <p className="muted">Signed in as {user?.email}.</p>
          </div>
        )}
      </main>

      <ReauthDialog />
    </div>
  );
}
