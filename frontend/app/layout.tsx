import type { Metadata, Viewport } from "next";

import { AuthProvider } from "@/lib/auth";
import { THEME_BOOTSTRAP } from "@/lib/theme";

import "./globals.css";

export const metadata: Metadata = {
  title: "Elimu Analytics",
  description:
    "Learning gap detection for Kenya's Competency-Based Education",
};

// viewportFit "cover" lets the bottom tab bar extend under a phone's home
// indicator and pad itself with env(safe-area-inset-bottom), instead of
// floating above a strip of dead space.
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#fcfcfb" },
    { media: "(prefers-color-scheme: dark)", color: "#1a1a19" },
  ],
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    // suppressHydrationWarning: the bootstrap script may set data-theme on
    // <html> before React hydrates, which is the point of running it early.
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOTSTRAP }} />
      </head>
      <body className="min-h-screen bg-canvas text-ink">
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
