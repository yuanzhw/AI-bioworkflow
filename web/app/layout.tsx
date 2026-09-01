import type { Metadata } from "next";

import { SiteFooter } from "@/components/site-footer";
import { SiteHeader } from "@/components/site-header";
import "@xyflow/react/dist/style.css";
import "./globals.css";

const siteUrl = new URL("https://yuanzhw.com");
const siteTitle = "AI-bioworkflow | Auditable Bioinformatics Workflow Compiler";
const siteDescription =
  "Catalog-bound bioinformatics planning, canonical Workflow IR, and deterministic compilation to validated WDL 1.0.";

export const metadata: Metadata = {
  metadataBase: siteUrl,
  title: {
    default: siteTitle,
    template: "%s | AI-bioworkflow",
  },
  description: siteDescription,
  alternates: {
    canonical: "/",
  },
  openGraph: {
    type: "website",
    locale: "zh_CN",
    alternateLocale: ["en_US"],
    url: "/",
    siteName: "AI-bioworkflow",
    title: siteTitle,
    description: siteDescription,
    images: [
      {
        url: "/og.png",
        width: 1280,
        height: 640,
        alt: "AI-bioworkflow catalog-bound planning to validated WDL",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: siteTitle,
    description: siteDescription,
    images: ["/og.png"],
  },
  robots: {
    index: true,
    follow: true,
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body className="min-h-screen font-sans antialiased">
        <div className="flex min-h-screen flex-col">
          <SiteHeader />
          <main className="flex-1">{children}</main>
          <SiteFooter />
        </div>
      </body>
    </html>
  );
}
