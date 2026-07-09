/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: "standalone",              // self-contained server for Docker
  async rewrites() {
    // browser calls same-origin /api/* ; Next proxies it to the backend
    const backend = process.env.BACKEND_URL || "http://127.0.0.1:8000";
    return [{ source: "/api/:path*", destination: `${backend}/:path*` }];
  },
};
module.exports = nextConfig;
