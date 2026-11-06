import Link from "next/link";

const PARENTS = [
  { href: "/runs", label: "Runs" },
  { href: "/pipelines", label: "Pipelines" },
  { href: "/publications", label: "Publications" },
  { href: "/catalog", label: "Catalog" },
  { href: "/schedules", label: "Schedules" },
];

/** Place a detail page's return link before its content, including loading states. */
export function PageBackLink({ pathname }: { pathname: string }) {
  const parent = PARENTS.find(({ href }) => pathname.startsWith(`${href}/`));
  if (!parent) return null;
  return (
    <nav className="page-back" aria-label="Page navigation">
      <Link href={parent.href} className="button btn btn-outline-secondary">
        <svg
          width="18"
          height="18"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          aria-hidden="true"
        >
          <path d="M19 12H5m7-7-7 7 7 7" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        Back to {parent.label}
      </Link>
    </nav>
  );
}
