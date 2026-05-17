'use client'

/**
 * QueryProvider — wraps children in TanStack Query's QueryClientProvider.
 *
 * Uses useState to ensure a single QueryClient instance per browser session
 * (the documented Next.js + React Query v5 pattern to avoid sharing state
 * across server-rendered requests).
 *
 * Docs consulted: apps/web/node_modules/next/dist/docs/01-app/02-guides/
 */

import { useState } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

export default function QueryProvider({
  children,
}: {
  children: React.ReactNode
}) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            // Avoid refetching on every window focus during trading hours
            refetchOnWindowFocus: false,
          },
        },
      })
  )

  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  )
}
