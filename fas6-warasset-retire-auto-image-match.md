# Kickoff: WarAsset – Phase 6: Retire automatic miniset.net matching, cache manually-linked images locally

## Background

Following the miniset.net incident, Sivan has decided the fuzzy auto-matching feature (Phase 4's `miniset_client.py` search/matching logic — guessing a product page from a unit name and fetching whatever image it finds) should be retired entirely, not just left disabled. It's the highest-risk part of the integration (multiple guessed requests per unit, pagination fallback, no human confirming the match is even correct) for the least reliable payoff (the known recall problems — chapter-specific catalogues, multi-pack hero sets, multiple sculpts). Removing it reduces both the risk of tripping miniset's bot-protection again and the amount of code to maintain.

What stays: the **manual link-paste flow** from Phase 4b — Sivan finds the right miniset.net product page themselves and pastes the URL in. That's a single, human-confirmed, low-volume request per unit, which is a fundamentally different risk profile than automated guessing. This phase also upgrades that flow: instead of hotlinking the image (fetching it from miniset.net on every page load, per the original Phase 4 decision), the image file itself is now downloaded once and stored locally on the Unraid volume, then always served from there afterward — removing the ongoing dependency on miniset.net staying up/unblocked for images already linked.

## Tasks

### 1. Remove the automatic fuzzy-matching feature

- Remove the fuzzy-match search/scoring logic (rapidfuzz-based name matching, the category-slug guessing for 40k, and the paginated fallback crawler for Kill Team/AoS) from `miniset_client.py` — this is genuinely retired, not just disabled behind a flag, since it was flagged as the actual risk driver.
- Remove the `POST /api/units/<id>/fetch-image` endpoint (the "guess and fetch" path) and its corresponding UI button/flow. Keep `POST /api/units/<id>/image-from-url` (Phase 4b) as the only remaining way to attach a miniset.net image.
- Keep the persisted circuit breaker / block-detection / cooldown logic built during the incident fix — it still applies, just now only guards the single remaining call path (`image-from-url`) instead of two.
- Clean up now-dead code paths, DB columns, or UI copy that only existed to support the auto-match flow (e.g. any "auto-matched" badge/label, `image_source = 'auto'` handling can be simplified since `'auto'` will no longer be produced going forward — decide whether to keep it for historical rows or backfill them to a neutral value, and document the choice).

### 2. Download and cache the image on `image-from-url`

- When a valid miniset.net product URL is submitted, download the extracted image file itself (not just record its URL) and store it in the same persistent volume used for user-uploaded photos (e.g. `data/uploads/miniset/<unit_id>.<ext>`), reusing the existing static-file-serving route pattern already used for `photo_path`.
- `collection_units.image_url` should now point at the **local** served path, not the remote miniset.net URL. Keep `image_source_url` as-is (the original miniset.net product page) purely for the attribution credit link shown on the card ("Image: miniset.net" → links to the source page) — that's just a link, not a network call, so it's fine for it to stay remote.
- This download still goes through the same rate-limit/circuit-breaker/cooldown protections as before (it's still one request to miniset.net) — don't bypass those just because it's "only downloading a file now."
- Decide and document what happens to units that already have a **hotlinked** `image_url` from before this phase (the earlier auto-matched or manually-linked-but-not-yet-cached images): leave them as hotlinks until Sivan re-links them (simplest, no extra risk), or do a one-time opportunistic local-cache-on-next-view. Prefer the simpler "leave as-is, re-link if you want it cached" approach unless there's a clear reason not to — avoid quietly generating a burst of new requests to miniset.net as a side effect of this change, which would undercut the whole point of this phase.

### 3. UI

- Remove the "Fetch/match image (auto)" button and any UI copy referring to automatic matching.
- Keep the "Link correct image (miniset.net)" field from Phase 4b as the only image-linking flow, and update its copy/help text if it previously mentioned the auto-match feature.
- Update the empty-state / placeholder messaging if it previously suggested images could be found automatically.

## Verification

1. No code path in the app can reach miniset.net without a human having pasted a specific URL first — confirm by searching the codebase for remaining calls into the old fuzzy-match function and removing any leftovers.
2. Link a real miniset.net product page for a unit → the image file is downloaded and saved locally, `image_url` serves it from the local path, and the page still loads the image correctly with the server offline from miniset.net's perspective afterward (e.g. verify the image still renders after temporarily blocking outbound access to miniset.net in a test, to prove it's genuinely local now and not still hotlinked).
3. The circuit breaker / cooldown still works for this single remaining path — simulate a block response and confirm `image-from-url` fails gracefully with the same clear message as before.
4. Existing units with hotlinked images from before this phase still display correctly (as hotlinks) and aren't broken by the change.
5. Test in a real browser, deploy to Unraid per the usual flow (this can wait until the current cooldown, active until 2026-08-28, has lifted, since the verification step above needs to make a real request), verify live.

## Wrap-up

- Update `CLAUDE.md`/`TODO.md`: document that automatic matching was retired (and why — risk vs. recall tradeoff, tied to the miniset.net incident), that `image-from-url` now downloads and caches locally instead of hotlinking, and where cached images live on disk/in the volume.
