/**
 * Root layout of the Alphaleo BD frontend.
 *
 * Next.js requires one root layout that wraps every page; it sets the document
 * language and title. The real shell (navigation, session handling) comes in task B3.
 */
import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "Alphaleo BD",
  description: "Internal outbound business development tool",
};

/** Wraps every route in the base HTML document. */
export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
