import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async redirects() {
    return [
      {
        source: '/dashboard/blotter',
        destination: '/dashboard',
        permanent: true,
      },
    ]
  },
};

export default nextConfig;
