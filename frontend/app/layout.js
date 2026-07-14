import "./globals.css";

export const metadata = {
  title: "Catalog Cross-Matching",
  description: "Detect optical sources in a FITS frame, match them to star catalogs, and flag new objects.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link
          href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="min-h-screen font-display antialiased">{children}</body>
    </html>
  );
}
