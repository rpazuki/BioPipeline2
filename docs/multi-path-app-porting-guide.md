# Multi-Path App Porting Guide For Agents

This guide is for a coding agent updating this repo or another lab app so it can run as a good tenant behind the shared RLA Lab Apps Gateway.

Target public architecture:

```text
https://rlalab-assist.dept.ic.ac.uk/
  /protocols    -> Protocols, internal port 3000
  /biopipeline  -> bioPipeline, internal port 3001
  /assist       -> rlalab-assist, internal port 3002
```

Only the gateway listens publicly on ports `80` and `443`. Backend app ports are private.

## Agent Goal

Make the app path-prefix aware without weakening auth, cookies, exports, redirects, or isolation from the other apps.

For Protocols, the target public base path is:

`/protocols`

The target public app URL is:

`https://rlalab-assist.dept.ic.ac.uk/protocols`

## Deployment Contract

Each app gets:

- one public base path, for example `/protocols`;
- one internal port, for example `3000`;
- its own app secrets;
- its own cookie names and cookie path;
- its own database/schema/user if it uses PostgreSQL;
- its own health checks and logs;
- no public direct access to its backend port.

The gateway owns:

- port `80` redirecting to `443`;
- TLS termination;
- route matching by path;
- optional central SSO;
- stripping and injecting trusted identity headers;
- access logs.

## Path Routing Mode

Prefer **prefix-preserving proxying**.

Good:

```text
Browser requests /protocols/reports
Gateway proxies /protocols/reports to backend
Backend app knows it is mounted at /protocols
```

Avoid prefix stripping unless there is a strong reason:

```text
Browser requests /protocols/reports
Gateway proxies /reports to backend
Backend app thinks it is mounted at /
```

Prefix stripping often breaks generated links, redirects, auth callbacks, static assets, cookies, and server actions. If an app framework supports a base path, use it.

## Next.js Base Path Checklist

For a Next.js app, add or verify these items.

### 1. Build-Time Base Path

Next.js `basePath` is a build-time setting. The Docker image must be built with the intended base path, or the app must be rebuilt when the base path changes.

In `next.config.ts`, add a base path from an environment variable such as:

```ts
const basePath = process.env.NEXT_PUBLIC_BASE_PATH || '';

const config: NextConfig = {
  basePath,
  output: 'standalone',
  // existing settings...
};
```

Use `/protocols` for this app:

```bash
NEXT_PUBLIC_BASE_PATH=/protocols npm run build
```

Do not set `assetPrefix` unless there is a separate asset host. `basePath` is the setting needed for path hosting.

### 2. Public URL Helpers

Do not concatenate public URLs by hand throughout the app.

Create central helpers:

```ts
export const appBasePath = normalizeBasePath(process.env.APP_BASE_PATH || '');
export const publicOrigin = new URL(process.env.PUBLIC_ORIGIN || process.env.APP_URL!).origin;

export function appPath(path = '/'): string {
  const suffix = path.startsWith('/') ? path : `/${path}`;
  if (suffix === '/') return appBasePath || '/';
  return `${appBasePath}${suffix}`;
}

export function appUrl(path = '/'): string {
  return new URL(appPath(path), publicOrigin).toString();
}
```

For Protocols, the deployment values should be:

```bash
PUBLIC_ORIGIN=https://rlalab-assist.dept.ic.ac.uk
APP_BASE_PATH=/protocols
APP_URL=https://rlalab-assist.dept.ic.ac.uk/protocols
NEXT_PUBLIC_BASE_PATH=/protocols
```

Important: `new URL('/auth/callback', 'https://host/protocols')` produces `https://host/auth/callback`, because a leading slash resets to the origin root. Use `appUrl('/auth/callback')` instead.

### 3. Links, Forms, And Redirects

Audit every root-relative URL.

Search patterns:

```bash
rg -n "\"/[A-Za-z0-9_/-]|'/[A-Za-z0-9_/-]|href=\\{|action=\\{|redirect\\(|NextResponse.redirect|new URL\\(" apps packages
```

Fix categories:

- `next/link` usually understands `basePath`; keep internal `href="/reports"` only after verifying rendered output under `/protocols`.
- Plain `<a href="/...">` does not get framework magic. Use `appPath('/...')`.
- Plain HTML `<form action="/...">` does not get framework magic. Use `appPath('/...')`.
- Route-handler redirects using `new URL('/...', config.appUrl)` are unsafe with path bases. Use `appUrl('/...')`.
- Server `redirect('/...')` must be verified under `basePath`; if it renders root paths, use the central helper.
- API calls from client code must target `appPath('/api/...')` unless they are relative to the current page.

Protocols hotspots:

- `apps/web/src/app/auth/signin/page.tsx`
- `apps/web/src/app/auth/callback/route.ts`
- `apps/web/src/app/auth/signout/route.ts`
- `apps/web/src/server/auth/principal.ts`
- `apps/web/src/server/auth/session.ts`
- `apps/web/src/app/admin/export/page.tsx`
- `apps/web/src/components/ReportFilters.tsx`
- `apps/web/src/components/ReportTable.tsx`
- `apps/web/src/components/ReportForm.tsx`
- every `redirect()` in `apps/web/src/server/actions/`

### 4. Cookies

Each app must use unique cookie names and path-limited cookies.

For Protocols:

- keep unique names such as `protocols_session` and `protocols_auth_tx`;
- set cookie `path` to `/protocols`, not `/`;
- keep `httpOnly: true`;
- keep `secure: true` in production;
- keep `sameSite: 'lax'` for IdP redirect compatibility.

The auth transaction cookie must be sent to:

`/protocols/auth/callback`

So the cookie path must cover `/protocols/auth/callback`.

Do not share one session cookie across the three apps unless a deliberate gateway session product is being built. Cross-app cookie sharing is not needed here and makes incidents harder to reason about.

### 5. Auth Callback URLs

If Protocols handles OIDC directly, configure:

```bash
AUTH_ADAPTER=entra-oidc
APP_URL=https://rlalab-assist.dept.ic.ac.uk/protocols
ENTRA_REDIRECT_URI=https://rlalab-assist.dept.ic.ac.uk/protocols/auth/callback
ENTRA_POST_LOGOUT_REDIRECT_URI=https://rlalab-assist.dept.ic.ac.uk/
```

If the gateway handles SSO and forwards trusted headers, configure the app for a trusted-header style adapter. The existing Shibboleth proxy adapter already follows this security pattern:

```bash
AUTH_ADAPTER=shibboleth-saml
SHIBBOLETH_PROXY_SECRET=<gateway-injected-secret>
SHIBBOLETH_EMAIL_HEADER=mail
SHIBBOLETH_SESSION_HEADER=shib-session-id
```

For an Entra/OIDC gateway that injects headers, add a generic trusted-header adapter rather than putting OIDC client secrets in every app. The adapter should require a shared proxy secret and a session marker, then read only the approved email header.

### 6. Static Assets

Verify all static assets load below the app prefix:

- Next.js chunks under `/protocols/_next/...`;
- images under `/protocols/...` or imported through Next;
- CSS and fonts under `/protocols/...`;
- no requests to root `/_next/...` from a path-hosted page.

If a page under `/protocols` requests `/_next/static/...`, the app is not correctly base-path aware.

### 7. Server Actions And POST Routes

Next server actions have same-origin checks. Behind a gateway, configure the public origin, not the backend port.

Use:

```bash
ALLOWED_ORIGINS=https://rlalab-assist.dept.ic.ac.uk
```

Do not use backend origins such as:

```bash
http://127.0.0.1:3000
http://localhost:3000
```

For non-server-action POST routes, compare browser `Origin` against the public origin. Do not trust `X-Forwarded-Host` or `X-Forwarded-Proto` for authorization unless the proxy is proven to strip and overwrite them.

### 8. API And Health Routes

Public API routes must sit under the app path:

```text
/protocols/api/health
/protocols/admin/export/download
```

Internal health checks from Docker can still call the backend directly if they never leave the VM. Public health endpoints should not reveal secrets, user counts, database URLs, or config values.

### 9. Database Isolation

If several apps share one PostgreSQL server:

- use a separate database or schema per app;
- use a separate database role per app;
- keep migration tables separate;
- do not let one app role write another app's tables;
- document backup and restore per app.

For Protocols, keep the `protocols_app` role scoped to its own database/schema.

### 10. Logging

Each request should be attributable to:

- gateway hostname;
- public path prefix;
- backend app;
- authenticated email if the app has a trusted identity;
- request id if available.

Do not log tokens, cookies, report free text, or protocol export contents.

## Gateway Configuration Checklist

The exact config depends on nginx, Apache, Caddy, Traefik, or ICT's preferred stack. The behavior should be:

```text
80:
  redirect all requests to https://rlalab-assist.dept.ic.ac.uk$request_uri

443:
  terminate TLS for rlalab-assist.dept.ic.ac.uk
  strip client-supplied identity headers
  protect /protocols with SSO when enabled
  route /protocols to Protocols backend
  route /biopipeline to bioPipeline backend
  route /assist to rlalab-assist backend
```

For prefix-preserving nginx-style proxying, the important detail is to pass the original URI through:

```nginx
location = /protocols {
  return 308 /protocols/;
}

location /protocols/ {
  proxy_pass http://127.0.0.1:3000;
  proxy_set_header Host $host;
  proxy_set_header X-Forwarded-Proto https;
  proxy_set_header X-Forwarded-Host $host;
  proxy_set_header X-Forwarded-Prefix /protocols;
}
```

Do not copy this as final production config without adapting it to the chosen proxy, TLS files, SSO module, and ICT security requirements.

## Identity Header Contract

For gateway-level SSO, standardize a tiny identity contract. Example:

```text
X-Authenticated-Email: user@ic.ac.uk
X-Authenticated-Issuer: imperial-entra
X-Authenticated-Session: opaque-session-id
X-App-Proxy-Secret: shared-random-secret
```

Rules:

- The gateway must remove these headers from incoming client requests.
- The gateway injects them only after successful SSO.
- Backend apps reject requests without the shared proxy secret.
- Backend apps normalize and validate the email address.
- Backend apps do not accept roles or admin flags from the gateway unless that is a deliberate, documented design.

Protocols should continue to manage admin status in its own database allowlist.

## Verification Checklist

Run these checks from a browser over the VPN and from the VM shell.

Browser checks:

- `https://rlalab-assist.dept.ic.ac.uk/` loads the gateway page or redirects deliberately.
- `https://rlalab-assist.dept.ic.ac.uk/protocols` redirects to `/protocols/` or loads cleanly.
- Protocols static assets load from `/protocols/_next/...`, not `/_next/...`.
- Sign-in starts from `/protocols/auth/signin` or the gateway SSO path.
- Callback returns to `/protocols/...`, not `/...`.
- Sign-out returns to the intended public route.
- Protocols cookies have `Path=/protocols`.
- Visiting `/biopipeline` does not send Protocols cookies.
- Export/download POSTs to `/protocols/admin/export/download`.
- Report filters submit to `/protocols/reports` or `/protocols/admin/reports`.

VM checks:

- External users cannot reach backend ports directly.
- Docker exposes app ports only on loopback or private networks.
- The gateway access log identifies the public path.
- App logs identify the backend app.
- Database credentials are different per app.

Automated checks:

- Build with `NEXT_PUBLIC_BASE_PATH=/protocols`.
- Run unit tests.
- Add route/render tests that assert generated links include the base path where raw HTML is used.
- Add a smoke test against the deployed gateway for `/protocols`, `/protocols/auth/signin`, `/protocols/api/health`, and `/protocols/admin/export`.

## Common Failure Modes

- App redirects to `/auth/signin` instead of `/protocols/auth/signin`.
- OIDC callback registered as `/auth/callback` instead of `/protocols/auth/callback`.
- Cookie path is `/`, so cookies bleed into `/biopipeline` and `/assist`.
- Static assets request `/_next/...` at the gateway root.
- Plain `<form action="/...">` escapes the base path.
- A root-level `/api` route collides with another app.
- Gateway strips the path prefix while the app is built with `basePath`.
- App trusts `X-Forwarded-Host` for security decisions.
- SSO gateway forwards user-supplied identity headers instead of overwriting them.
- One app's database role can read or write another app's data.

## Done Definition

An app is ready for this hosting model when:

- it can run under its assigned path prefix in production mode;
- all links, forms, redirects, assets, callbacks, and APIs stay under that prefix;
- cookies are path-limited and uniquely named;
- backend ports are private;
- SSO-enabled paths receive identity only from the trusted gateway;
- app authorization remains app-owned;
- deployment docs list public path, internal port, database/schema, secrets, and owner;
- a smoke test proves the app works through `https://rlalab-assist.dept.ic.ac.uk/<base-path>`.
