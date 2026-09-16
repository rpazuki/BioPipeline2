"use client";

/**
 * What a researcher opens the application to do.
 *
 * Deliberately sparse. A catalog entry is a thing somebody might start a
 * day-long job from, so the list shows what it is and what it is for, and the
 * decisions live on the entry itself.
 */

import Link from "next/link";
import { useState } from "react";

import { Empty, Failure, Loading } from "@/components/ui/states";
import { useCatalog } from "@/features/catalog/useCatalog";

export function CatalogScreen() {
  const [search, setSearch] = useState("");
  const query = useCatalog(search);

  return (
    <div className="stack">
      <header className="page-header">
        <h1>Catalog</h1>
        <div className="filters">
          <label className="visually-hidden" htmlFor="catalog-search">
            Search the catalog
          </label>
          <input
            id="catalog-search"
            type="search"
            placeholder="Search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </div>
      </header>

      {query.isPending ? <Loading what="the catalog" /> : null}
      {query.isError ? (
        <Failure error={query.error} onRetry={() => void query.refetch()} />
      ) : null}

      {query.data ? (
        query.data.items.length === 0 ? (
          <Empty
            title={search ? `Nothing matches "${search}".` : "Nothing has been published yet."}
            detail={
              search
                ? undefined
                : "An administrator publishes a pipeline here once it is ready for people to run."
            }
          />
        ) : (
          <ul className="card-list">
            {query.data.items.map((entry) => (
              <li key={entry.slug}>
                <Link href={`/catalog/${entry.slug}`} className="card">
                  <span className="card__title">{entry.title}</span>
                  {entry.description ? (
                    <span className="card__detail">{entry.description}</span>
                  ) : null}
                  <span className="muted">version {entry.version}</span>
                </Link>
              </li>
            ))}
          </ul>
        )
      ) : null}
    </div>
  );
}
