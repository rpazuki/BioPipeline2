/**
 * Who may see which screen.
 *
 * A usability rule, not a security one. The backend authorises every request
 * on its own; hiding a link the server would refuse keeps a researcher from
 * walking into a 403, and nothing more. Anything enforced only here is not
 * enforced.
 */

import type { UserRole } from "@/lib/api";

export interface NavItem {
  href: string;
  label: string;
  /** Omitted means any signed-in user. */
  role?: UserRole;
  /** Shown in the shell but not yet backed by an endpoint. */
  pending?: string;
}

export const NAV: NavItem[] = [
  // First, and for everyone: the catalog is what a researcher opens the
  // application to do, and an admin publishing an entry wants to see what they
  // published.
  { href: "/catalog", label: "Catalog" },
  { href: "/runs", label: "Runs" },
  { href: "/schedules", label: "Schedules" },
  { href: "/pipelines", label: "Pipelines", role: "admin" },
  { href: "/publications", label: "Publications", role: "admin" },
  { href: "/storage", label: "Storage", role: "admin" },
  { href: "/account", label: "Account" },
];

export function visibleNav(role: UserRole | undefined): NavItem[] {
  if (!role) return [];
  return NAV.filter((item) => !item.role || item.role === role);
}

export function mayVisit(path: string, role: UserRole | undefined): boolean {
  if (!role) return false;
  const item = NAV.find((entry) => path === entry.href || path.startsWith(`${entry.href}/`));
  if (!item) return true;
  return !item.role || item.role === role;
}
