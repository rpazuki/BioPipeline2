"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { Loading } from "@/components/ui/states";

/**
 * There is no dashboard yet, and an empty one would be worse than none. Runs
 * is what both roles open the application to look at.
 */
export default function Home() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/runs");
  }, [router]);
  return <Loading what="your runs" />;
}
