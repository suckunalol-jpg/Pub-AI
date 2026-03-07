import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Pub AI",
  description: "AI-powered development platform",
  icons: { icon: "/favicon.ico" },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className="bg-navy-950 text-white antialiased">
        {children}
      </body>
    </html>
  );
}
