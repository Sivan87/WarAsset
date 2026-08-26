# Kickoff: WarAsset – Incident: miniset.net has rate-limited the Unraid server's IP

## Background

miniset.net is now returning "Access to this page has been temporarily restricted due to suspicious automated activity from your network address" for requests from the Unraid server. This means the site's own bot-protection has flagged WarAsset's traffic, despite the intended 10-second global rate-limit built in Phase 4/4b. This needs to be investigated and fixed properly — not guessed at — before any more requests are sent to miniset.net, since continuing to hit a site that has just flagged you as suspicious risks turning a temporary block into a longer/permanent one, and undermines the whole "respectful, low-footprint hobbyist tool" posture this integration was built on.

**Do not send any further requests to miniset.net (automatic or via a manual "Hämta bild"/image-from-url test) until root cause is understood and a fix is deployed.** Treat this as a stop-the-line issue for that one integration, not something to route around by trying again.

## Decision: disable automatic on-save image fetching

Sivan has decided to remove the automatic background image match that currently triggers whenever a unit is saved (Phase 4). Going forward, image fetching from miniset.net is **manual-only** — the per-card "Hämta bild"/"Fetch image" button and the Phase 4b manual image-from-url field remain, but nothing fires automatically anymore.

**Important:** this reduces the risk of tripping miniset's bot-protection again (a human clicking one unit at a time naturally spaces out requests far more than an automatic trigger firing on every save), but it does **not** by itself fix the current block, and it does not replace the root-cause investigation below — if the real bug is that a single match attempt (manual or automatic) fires multiple rapid sub-requests internally (e.g. the paginated fallback search), a manual-only click could trip the same protection again. Do task 1 regardless of this change.

- Remove the automatic trigger on unit save. Keep the manual fetch-image and image-from-url endpoints as they are (still gated by the same rate limit and, once built, the same block-detection/cooldown from task 2).
- Update `CLAUDE.md`/`TODO.md` to reflect that image fetching is now manual-only and why.

## Tasks

### 1. Find the actual root cause — don't guess

- Check the WarAsset container logs for the real request history against miniset.net: how many requests were made, over what time span, and whether the gap between consecutive requests was ever actually less than 10 seconds in practice (not just in the code's intent).
- Audit every code path that calls into `miniset_client.py`'s rate-limited fetch function — the automatic on-demand match (Phase 4), the manual `POST /api/units/<id>/fetch-image`, and the manual `POST /api/units/<id>/image-from-url` (Phase 4b). Confirm all three genuinely share the *same* global lock/timestamp, not three independent ones that each individually wait 10s but collectively could still fire close together.
- Check whether the Kill Team/AoS **paginated fallback** search (mentioned in the Phase 4 summary) issues multiple sequential page requests per single unit-match attempt — if each of those already goes through the 10s gate that's fine, but confirm it, since a "one unit lookup = several page fetches" pattern could still look bot-like in aggregate even if individually spaced out (miniset's protection may be volume-based over a time window, not purely gap-based).
- Check what `User-Agent` header the requests are sent with. A generic default (e.g. a raw Python HTTP library's default string) is a common trigger for this kind of automated protection. Consider identifying honestly as a small tool (a descriptive UA string, not spoofing a real browser) — but confirm this is actually a contributing factor via the logs before treating it as *the* fix.

### 2. Detect the block and fail gracefully instead of retrying blindly

- Detect this specific restricted-access response (status code and/or the page's distinctive text) as its own case, not a generic fetch failure.
- On detecting it: stop making further miniset.net requests entirely for a cooldown period (e.g. 24–48 hours, configurable), and surface a clear, honest message in the UI ("Image lookup from miniset.net is temporarily unavailable — try again later, or link an image manually") rather than silently failing or — worse — retrying and hammering the block further.
- This should apply to the automatic on-demand fetch, the manual fetch-image button, and the manual image-from-url endpoint alike — all three need to respect the same cooldown state.

### 3. Reduce risk once the block lifts

- Once root cause is identified (e.g. genuinely-too-tight timing across code paths, request volume from pagination, or User-Agent), fix that specific cause rather than applying speculative changes.
- Consider adding real observability here going forward: log every actual outbound request to miniset.net with a timestamp, so a future issue like this can be diagnosed from logs immediately instead of reconstructing it after the fact.

## Verification

1. Logs show the true root cause (not a guess) — e.g. "pagination fallback made N requests in under 10s each due to bug X" or "three code paths held independent locks."
2. A simulated/observed block response is caught and handled distinctly from other fetch errors, with the UI message confirmed in a real browser test.
3. No further requests are sent to miniset.net while the cooldown is active — verify this by checking logs after triggering the block-detection path in a test, not just reading the code.
4. Deploy the fix, but do **not** immediately hammer miniset.net to "test" it live — wait out a reasonable cooldown first (this is as much about being a good citizen of a small hobby site as it is a technical fix).

## Wrap-up

- Document this incident in `CLAUDE.md` and `TODO.md`: what caused it, what was fixed, and the cooldown/circuit-breaker behavior now in place, so it's clear this integration has this failure mode and how it's handled if it happens again.
