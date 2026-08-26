# Kickoff: WarAsset – Phase 5: Brand identity (logo, favicon, navbar)

## Background

Sivan only has a style-guide reference image (no exported SVG/PNG source files), saved alongside this document as `C:\WarAsset\brand\warasset-brand-reference.png` — **look at that image file directly before starting**, the description below is a guide, not a replacement for actually seeing it. It shows the intended WarAsset brand mark and how it should appear in the navbar, as a favicon, and as an app icon. This phase recreates that mark as scalable inline SVG directly in the codebase — consistent with how the current placeholder logo in the nav is already built (an inline `<svg>` polygon), and avoids depending on any external asset file. All UI text in this phase must be in **English** (the whole tool's UI was switched to English in a previous phase — do not reintroduce Swedish).

## Mark description (build from this, don't guess pixel values — get it close, then let Sivan review live and iterate)

- **Shape:** a pointy-top hexagon outline (not filled), stroked in the app's existing accent purple (the same `--color-accent` / `#9184d9`-family already used throughout the Nocturne design system — reuse the token, don't hardcode a new hex).
- **Vertex accents:** a small solid diamond (rotated square) sits at each of the hexagon's 6 vertices, same accent color, giving the outline a "circuit node" look.
- **Monogram:** a bold "WA" wordmark centered inside the hexagon, in white, with the letters slightly overlapping/interlocked (the "W" and "A" share a stroke where they meet) — condensed/heavy weight, not the body font.
- **Wordmark lockup:** next to the icon, "WarAsset" in the same heavy display weight — "War" in white, "Asset" in the accent purple (matches the app's existing pattern of using the accent to highlight part of a compound word, consistent with `.tag-accent` etc.).
- **Favicon / app icon:** the same hexagon mark on a small rounded-square dark card background (matches `--color-bg`/neutral-800-ish surface), not just the bare icon on transparent — gives it a contained "app icon" feel in a browser tab or bookmark.
- **Scaling:** the mark should read clearly down to 16×16 (favicon size) — keep the diamond vertex accents and monogram simple enough that they don't turn to mush at that size; it's fine if the vertex diamonds get visually smaller/merge into the outline at the smallest size rather than trying to preserve every detail.

## Tasks

### 1. Build the mark as a reusable inline SVG component

- Implement the hexagon+diamonds+WA monogram as a single inline `<svg>` (viewBox-based, so it scales cleanly), parameterized by size where it's used (nav: ~32-40px, favicon: 16/32px, app icon: larger).
- Replace the current placeholder nav icon (the inline `<svg><polygon>...</polygon></svg>` currently in the nav markup) with this new mark.
- Keep it inline SVG (not a separate `.svg` file/image request) so it inherits the accent color via CSS custom properties and stays crisp at any size, consistent with how icons are already handled per the Nocturne readme (Phosphor icons are also referenced via markup, not raster images).

### 2. Favicon and app icon

- Generate a favicon from the same mark (on the dark rounded-card background described above). Since there's no existing PNG export, render the SVG to the needed favicon sizes (16×16, 32×32) as part of the build — e.g. a small script using an SVG-to-PNG/ICO tool available in the dev environment (or, if simpler and sufficient for a self-hosted single-user tool on a modern browser, ship an SVG favicon directly via `<link rel="icon" type="image/svg+xml">` with a PNG fallback) — use whatever's simplest and already available rather than adding a heavy new dependency just for this.
- Add appropriate `<link rel="icon">` / `<link rel="apple-touch-icon">` tags in the page head.

### 3. Navbar layout — match the two reference examples

- **Expanded (wide viewport):** icon + "WarAsset" wordmark on the left, a search input ("Search units...") next to it, then the system-filter pills (All / 40k / Kill Team / AoS) — matches the reference image's expanded navbar exactly, and lines up with the existing filter/system-toggle behavior already in the app (just restyled/repositioned to sit inline in the nav per this reference instead of wherever it currently sits).
- **Compact (narrow viewport):** icon + wordmark on the left, then just a search icon button and a hamburger/menu icon button on the right — the full filter pill row and text search input collapse behind those two icons. Implement this as a responsive breakpoint (CSS, not two separate templates) — pick a reasonable breakpoint (e.g. ~768px) and verify both states actually render correctly, not just assume the CSS works.
- This ties into the earlier UI polish (filter bar made compact, sitting next to the Grid/List toggle) — make sure the new navbar layout and that existing filter row don't end up duplicating controls or conflicting; reconcile them into one coherent header area matching the reference's intent.

## Verification

1. Nav renders the new hexagon+WA mark instead of the old placeholder polygon icon, at the correct size, in the accent purple, crisp (not blurry/pixelated) at normal display size.
2. Browser tab favicon shows the mark (check both light and dark OS/browser chrome if easy to verify, since the favicon has its own dark card background regardless).
3. Resize the browser window across the compact breakpoint → nav switches cleanly between the expanded and compact layouts shown in the two reference examples, no overlapping/broken controls at any width in between.
4. Test in a real browser (same Playwright approach as previous phases), not just visual inspection of the HTML.
5. Deploy to Unraid per the usual flow, verify live.

## Wrap-up

- Document in `CLAUDE.md` that the brand mark is hand-built inline SVG (no source design file exists — the style-guide reference image is the only source of truth), and note the exact accent color / breakpoint values chosen so a future change starts from the same reference instead of re-guessing.
- Since this was built from a reference image rather than exported assets, flag clearly that Sivan should review the live result against the reference and call out anything that doesn't match closely enough (proportions, weight, spacing) for a follow-up pass.
