"use client";

/**
 * The administrator's screen: accounts, the fleet, and what changed.
 *
 * Three things a deployment could not do without shell access. Adding a
 * person meant running a script on the server. Knowing whether the workers
 * were alive meant reading the database. And "who published the entry that
 * started producing wrong results last Tuesday" had no answer at all, because
 * nothing wrote to the audit table.
 *
 * The one-time password is shown **once**, in a dialog that says so. It is
 * not stored anywhere readable and cannot be fetched again; the honest thing
 * is to make that obvious rather than let somebody close the dialog assuming
 * they can come back to it.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { DataTable, type Column } from "@/components/ui/DataTable";
import { Dialog } from "@/components/ui/Dialog";
import { Field } from "@/components/ui/Field";
import { Empty, Failure, Loading } from "@/components/ui/states";
import { useApi, useSession } from "@/features/auth/session";
import { admin, type AdminUser, type AuditEvent, type WorkerSummary } from "@/lib/api";
import { formatRelative, formatTimestamp } from "@/lib/format";
import { fieldErrors } from "@/lib/form";

const KEYS = {
  users: ["admin-users"] as const,
  workers: ["admin-workers"] as const,
  audit: ["admin-audit"] as const,
};

function Accounts() {
  const client = useApi();
  const queryClient = useQueryClient();
  const { user: me } = useSession();
  const [creating, setCreating] = useState(false);
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [issued, setIssued] = useState<{ email: string; password: string } | null>(null);

  const [search, setSearch] = useState("");
  const users = useQuery({
    queryKey: [...KEYS.users, search],
    queryFn: () => admin.users(client, search || undefined),
  });

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: KEYS.users });
    void queryClient.invalidateQueries({ queryKey: KEYS.audit });
  };

  const create = useMutation({
    mutationFn: () =>
      admin.createUser(client, { email, displayName: name, role: "researcher" }),
    onSuccess: (made) => {
      setIssued({ email: made.user.email, password: made.one_time_password });
      setCreating(false);
      setEmail("");
      setName("");
      refresh();
    },
  });

  // Two mutations rather than one with a union: a reset produces something
  // to show and the others do not, and a single handler that sometimes opens
  // a dialog is the shape that eventually opens it for the wrong one.
  const change = useMutation({
    mutationFn: (input: { id: string; kind: "role" | "active"; value: boolean }) =>
      input.kind === "role"
        ? admin.setRole(client, input.id, input.value ? "admin" : "researcher")
        : admin.setActive(client, input.id, input.value),
    onSuccess: refresh,
  });

  const reset = useMutation({
    mutationFn: (userId: string) => admin.resetPassword(client, userId),
    onSuccess: (result) => {
      setIssued({ email: result.user.email, password: result.one_time_password });
      refresh();
    },
  });

  if (users.isPending) return <Loading what="accounts" />;
  if (users.isError)
    return <Failure error={users.error} onRetry={() => void users.refetch()} />;

  const columns: Column<AdminUser>[] = [
    {
      key: "who",
      header: "Who",
      render: (row) => (
        <>
          {row.display_name} <span className="muted">{row.email}</span>
        </>
      ),
    },
    { key: "role", header: "Role", render: (row) => row.role },
    {
      key: "state",
      header: "",
      render: (row) => (
        <>
          {row.is_active ? null : <span className="badge badge--neutral">deactivated</span>}
          {row.must_change_password ? (
            <span className="badge badge--warn">has not signed in</span>
          ) : null}
        </>
      ),
    },
    {
      key: "seen",
      header: "Last signed in",
      secondary: true,
      render: (row) => (row.last_login_at ? formatRelative(row.last_login_at) : "never"),
    },
    {
      key: "actions",
      header: "",
      render: (row) => (
        <div className="button-row">
          {/* No control to change your own role or end your own access: a
              deployment with no administrator has no way back in that does
              not involve the database. */}
          {row.id === me?.user_id ? (
            <span className="muted">you</span>
          ) : (
            <>
              <button
                type="button"
                className="button button--quiet"
                onClick={() =>
                  change.mutate({ id: row.id, kind: "role", value: row.role !== "admin" })
                }
              >
                {row.role === "admin" ? "Make researcher" : "Make admin"}
              </button>
              <button
                type="button"
                className="button button--quiet"
                onClick={() =>
                  change.mutate({ id: row.id, kind: "active", value: !row.is_active })
                }
              >
                {row.is_active ? "Deactivate" : "Reactivate"}
              </button>
              <button
                type="button"
                className="button button--quiet"
                onClick={() => reset.mutate(row.id)}
              >
                Reset password
              </button>
            </>
          )}
        </div>
      ),
    },
  ];

  return (
    <section className="stack">
      <div className="page-header">
        <div>
          <h2>Accounts</h2>
          {/* The count behind the page, not the length of it. */}
          <p className="muted">
            {users.data.total ?? users.data.items.length} account
            {users.data.total === 1 ? "" : "s"}
            {(users.data.total ?? 0) > users.data.items.length
              ? `, showing ${users.data.items.length}`
              : ""}
            .
          </p>
        </div>
        <div className="button-row">
          <input
            type="search"
            aria-label="Find an account"
            placeholder="name or email"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
          <button
            type="button"
            className="button button--primary"
            onClick={() => setCreating(true)}
          >
            Add a person
          </button>
        </div>
      </div>

      {change.isError ? <Failure error={change.error} /> : null}
      {reset.isError ? <Failure error={reset.error} /> : null}

      <DataTable
        rows={users.data.items}
        columns={columns}
        caption="Accounts"
        rowKey={(row) => row.id}
      />

      <Dialog open={creating} title="Add a person" onClose={() => setCreating(false)}>
        <p className="muted">
          The platform generates their password. You will see it once, to pass on — they cannot
          do anything else until they replace it.
        </p>
        <Field id="new-email" label="Email" error={fieldErrors(create.error).for("email")}>
          {(props) => (
            <input
              {...props}
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
          )}
        </Field>
        <Field id="new-name" label="Name">
          {(props) => (
            <input
              {...props}
              type="text"
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          )}
        </Field>
        {create.isError ? <Failure error={create.error} /> : null}
        <div className="dialog__actions">
          <button
            type="button"
            className="button button--quiet"
            onClick={() => setCreating(false)}
          >
            Cancel
          </button>
          <button
            type="button"
            className="button button--primary"
            disabled={!email.trim() || !name.trim() || create.isPending}
            onClick={() => create.mutate()}
          >
            {create.isPending ? "Creating…" : "Create"}
          </button>
        </div>
      </Dialog>

      <Dialog
        open={issued !== null}
        title="Their password, once"
        onClose={() => setIssued(null)}
      >
        <p>
          Pass this to <strong>{issued?.email}</strong>. It is not stored anywhere it can be
          read again, and it stops working the moment they choose their own.
        </p>
        <pre className="log" aria-label="One-time password">
          {issued?.password}
        </pre>
        <div className="dialog__actions">
          <button
            type="button"
            className="button button--primary"
            onClick={() => setIssued(null)}
          >
            I have it
          </button>
        </div>
      </Dialog>
    </section>
  );
}

function Fleet() {
  const client = useApi();
  const workers = useQuery({
    queryKey: KEYS.workers,
    queryFn: () => admin.workers(client),
    refetchInterval: 15_000,
  });

  if (workers.isPending) return <Loading what="workers" />;
  if (workers.isError) return <Failure error={workers.error} />;

  const columns: Column<WorkerSummary>[] = [
    { key: "id", header: "Worker", render: (row) => <code>{row.id}</code> },
    { key: "host", header: "Host", render: (row) => row.hostname },
    { key: "status", header: "Status", render: (row) => row.status },
    {
      key: "heartbeat",
      header: "Last heartbeat",
      render: (row) => (
        // A worker silently falling behind looks identical to a long queue
        // from anywhere else.
        <span className={row.heartbeat_age_seconds > 120 ? "badge badge--bad" : "muted"}>
          {Math.round(row.heartbeat_age_seconds)}s ago
        </span>
      ),
    },
    {
      key: "load",
      header: "Running",
      render: (row) => `${row.running_tasks} of ${row.capacity}`,
    },
  ];

  return (
    <section className="stack">
      <h2>Workers</h2>
      {workers.data.items.length === 0 ? (
        <Empty
          title="No worker has ever registered."
          detail="Nothing will be executed until one starts."
        />
      ) : (
        <DataTable
          rows={workers.data.items}
          columns={columns}
          caption="Workers"
          rowKey={(row) => row.id}
        />
      )}
    </section>
  );
}

function Changes() {
  const client = useApi();
  const [kind, setKind] = useState("");
  const events = useQuery({
    queryKey: [...KEYS.audit, kind],
    queryFn: () => admin.auditEvents(client, { targetType: kind || undefined }),
  });

  if (events.isPending) return <Loading what="the audit log" />;
  if (events.isError) return <Failure error={events.error} />;

  const columns: Column<AuditEvent>[] = [
    { key: "action", header: "What", render: (row) => <code>{row.action}</code> },
    { key: "who", header: "Who", render: (row) => row.actor_email ?? "—" },
    {
      key: "details",
      header: "Detail",
      render: (row) => (
        <span className="muted">
          {Object.entries(row.details ?? {})
            .map(([key, value]) => `${key}: ${String(value)}`)
            .join(" · ")}
        </span>
      ),
    },
    { key: "when", header: "When", render: (row) => formatTimestamp(row.created_at) },
  ];

  return (
    <section className="stack">
      <div className="page-header">
        <h2>What changed</h2>
        <select
          aria-label="Kind of thing"
          value={kind}
          onChange={(event) => setKind(event.target.value)}
        >
          <option value="">Everything</option>
          <option value="user">Accounts</option>
          <option value="storage_root">Storage roots</option>
          <option value="publication">Catalog</option>
          <option value="environment">Environments</option>
        </select>
      </div>
      {events.data.items.length === 0 ? (
        <Empty title="Nothing has been changed yet." />
      ) : (
        <DataTable
          rows={events.data.items}
          columns={columns}
          caption="Administrative changes"
          rowKey={(row) => row.id}
        />
      )}
      <p className="muted">
        Changes to shared authority — who may sign in, what they may do, which paths the
        platform reads and writes, what is in the catalog, what every task imports. A run or a
        schedule records who cancelled or paused it on the run or the schedule itself.
      </p>
    </section>
  );
}

export function AdminScreen() {
  return (
    <div className="stack">
      <header className="page-header">
        <div>
          <h1>Administration</h1>
          <p className="muted">Who can use this, what is running it, and what has changed.</p>
        </div>
      </header>
      <Accounts />
      <Fleet />
      <Changes />
    </div>
  );
}
