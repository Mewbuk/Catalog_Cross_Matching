/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: "standalone",              // self-contained server for Docker

  // Plate solving + catalog queries can legitimately take minutes. Without a
  // raised timeout the dev/proxy layer hangs up mid-solve ("socket hang up").
  experimental: {
    proxyTimeout: 300_000,           // 5 minutes
  },

  async rewrites() {
    // browser calls same-origin /api/* ; Next proxies it to the backend
    const backend = process.env.BACKEND_URL || "http://127.0.0.1:8000";
    return [{ source: "/api/:path*", destination: `${backend}/:path*` }];
  },
};
module.exports = nextConfig;
