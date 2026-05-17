import type { Metadata } from "next";
import "./globals.css";
import QueryProvider from "@/components/QueryProvider";

export const metadata: Metadata = {
  title: "ES Futures Trading System",
  description: "Phase 3 — Bloomberg-style trading dashboard.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full flex flex-col font-mono">
        <QueryProvider>{children}</QueryProvider>
      </body>
    </html>
  );
}
