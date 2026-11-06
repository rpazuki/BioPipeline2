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
import { PageBackLink } from "@/components/layout/PageBackLink";
import { FirstPassword } from "@/features/auth/FirstPassword";
import { ReauthDialog } from "@/features/auth/ReauthDialog";
import { useSession } from "@/features/auth/session";
import { mayVisit, visibleNav } from "@/lib/route-policy";

const NAV_ICONS: Record<string, string> = {
  "/catalog": "M4 4h6v6H4z M14 4h6v6h-6z M4 14h6v6H4z M14 14h6v6h-6z",
  "/runs": "M8 5l11 7-11 7z",
  "/schedules": "M5 5h14v15H5z M8 3v4 M16 3v4 M5 10h14 M9 14h2 M14 14h1",
  "/pipelines": "M4 4h6v6H4z M14 14h6v6h-6z M7 10v7h7 M10 7h7v7",
  "/publications": "M5 4h11l3 3v13H5z M8 10h8 M8 14h8 M8 17h5",
  "/storage": "M4 5h16v5H4z M4 14h16v5H4z M7 7h1 M7 16h1",
  "/environments": "M9 3v6l-5 9a2 2 0 0 0 2 3h12a2 2 0 0 0 2-3l-5-9V3 M8 3h8 M7 15h10",
  "/admin": "M4 7h16 M4 17h16 M8 4v6 M16 14v6",
  "/account": "M8 7a4 4 0 1 0 8 0a4 4 0 1 0-8 0 M5 21v-2a7 7 0 0 1 14 0v2",
};

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
    <div className="shell page">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="shell__bar">
        <Link href="/runs" className="shell__brand">
          <span className="shell__mark" aria-hidden="true">
            B
          </span>
          <span>
            {config.app_name}
            <small>Workflow workspace</small>
          </span>
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
                <svg
                  className="shell__nav-icon"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.7"
                  aria-hidden="true"
                >
                  <path
                    d={NAV_ICONS[item.href] ?? "M5 5h14v14H5z"}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
                {item.label}
              </Link>
            );
          })}
        </nav>
        <div className="shell__user">
          <span className="avatar avatar-sm shell__avatar" aria-hidden="true">
            {user?.display_name?.slice(0, 1).toUpperCase()}
          </span>
          <span>
            {user?.display_name}
            <small className="shell__role">
              {role === "admin" ? "Administrator" : "Researcher"}
            </small>
          </span>
          <button
            type="button"
            className="button btn button--quiet btn-ghost-secondary"
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
          <>
            <PageBackLink pathname={pathname} />
            {children}
          </>
        ) : (
          <div className="state feedback feedback--error" role="alert">
            <p className="state__title">This page is for administrators.</p>
            <p className="muted">Signed in as {user?.email}.</p>
          </div>
        )}
      </main>

      <ReauthDialog />
    </div>
  );
}
