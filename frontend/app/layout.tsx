import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "FreeClipper: free AI video clipper",
  description: "Turn any YouTube video or live stream into 9:16 viral shorts with translated captions. 100% free.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen font-sans">{children}</body>
    </html>
  );
}
