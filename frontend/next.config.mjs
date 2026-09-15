/**
 * The path prefix is a *build* input, not a runtime one.
 *
 * Next bakes it into every emitted asset URL and router link, so one image
 * cannot serve two deployments mounted at different prefixes. Everything else
 * the browser needs — API prefix, upload limits, the CSRF header — comes from
 * `GET /api/v1/config` at boot, so those really are one-image-many-deployments.
 * See frontend/README.md.
 */
const basePath = process.env.NEXT_PUBLIC_BASE_PATH ?? "";

/** @type {import('next').NextConfig} */
export default {
  basePath,
  // A self-contained server bundle: the deployment target is a VM, not a
  // platform that installs node_modules for us.
  output: "standalone",
  reactStrictMode: true,
  // Linting is its own gate (`npm run lint`), so a lint failure does not
  // masquerade as a build failure.
  eslint: { ignoreDuringBuilds: true },
  typescript: { ignoreBuildErrors: false },
};
