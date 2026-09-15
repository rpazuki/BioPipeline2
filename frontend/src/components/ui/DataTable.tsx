"use client";

/**
 * One table, so every list behaves the same.
 *
 * Keyboard operability is the reason this is a component rather than markup
 * repeated per screen: a row that navigates somewhere must be reachable by
 * Tab and activated by Enter or Space, and that is easy to get right once and
 * forget everywhere else.
 */

import type { ReactNode } from "react";

export interface Column<T> {
  key: string;
  header: string;
  render: (row: T) => ReactNode;
  /** Long, low-information cells that may be dropped on a narrow screen. */
  secondary?: boolean;
}

export function DataTable<T>({
  rows,
  columns,
  caption,
  rowKey,
  onOpen,
  emptyMessage = "Nothing to show.",
}: {
  rows: T[];
  columns: Column<T>[];
  caption: string;
  rowKey: (row: T) => string;
  onOpen?: (row: T) => void;
  emptyMessage?: string;
}) {
  return (
    <div className="table-wrap">
      <table className="table">
        <caption className="visually-hidden">{caption}</caption>
        <thead>
          <tr>
            {columns.map((column) => (
              <th
                key={column.key}
                scope="col"
                className={column.secondary ? "cell--secondary" : undefined}
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className="muted">
                {emptyMessage}
              </td>
            </tr>
          ) : (
            rows.map((row) => (
              <tr
                key={rowKey(row)}
                className={onOpen ? "row--clickable" : undefined}
                {...(onOpen
                  ? {
                      tabIndex: 0,
                      role: "link",
                      onClick: () => onOpen(row),
                      onKeyDown: (event: React.KeyboardEvent) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault();
                          onOpen(row);
                        }
                      },
                    }
                  : {})}
              >
                {columns.map((column) => (
                  <td
                    key={column.key}
                    className={column.secondary ? "cell--secondary" : undefined}
                  >
                    {column.render(row)}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
