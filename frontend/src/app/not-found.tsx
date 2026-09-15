import Link from "next/link";

export default function NotFound() {
  return (
    <div className="state state--empty">
      <p className="state__title">There is nothing at this address.</p>
      <Link href="/runs" className="button">
        Go to runs
      </Link>
    </div>
  );
}
