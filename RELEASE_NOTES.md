# Release Notes

## Version 2.0.2 - Direct Tag-Based Search, Removing Genre Guessing

### Summary
Replaced the genre-fallback mechanism with a second Bandcamp discover
endpoint that filters directly by tag across every genre, so a release is
found by the exact tag it carries instead of by guessing which curated
parent genre it might be filed under. This closes a real gap: a release
tagged "hardcore punk" but filed by Bandcamp under an unrelated primary
genre (Rock, Metal, Electronic, etc.) was previously invisible unless that
other genre happened to also be scanned.

### Changes

#### Breaking / Architecture
- `BandcampParser` now calls `/api/discover/1/discover_web` with
  `tag_norm_names` instead of `/api/discover/3/get_web` with a curated
  genre slug - every configured tag is searched for directly, matching
  Bandcamp's own real tag data rather than a curated top-level genre
- Removed `GENRE_FALLBACK` and the whole informal-tag-to-genre mapping
  table - it's no longer needed since every tag, official or informal, is
  looked up the same way
- Removed the `/genre_list`, `/genre_set`, and `/genre_remove` Telegram
  commands along with `Config.genre_fallback`, since there's no longer a
  mapping to inspect or edit

#### Technical Details
- Pagination moved from numeric genre pages to opaque cursors returned by
  the new endpoint; the freshest page (cursor `"*"`) is always fetched so
  a genuinely new release is never missed, plus one supplemental page per
  call that advances through the tag's back catalog over successive runs
- Verified directly against live results: sampling releases returned for
  the "hardcore punk" tag, roughly a quarter carried a primary genre other
  than Punk (Rock, Metal, Alternative, World, Electronic, Experimental) -
  every one of them was confirmed, via its own release page, to genuinely
  carry the `hardcore-punk` tag
- Also verified against several tags with no official subgenre status
  (`d-beat`, `raw-punk`, `street-punk`, `uk82`, `h8000`, `egg-punk`) -  all
  return real, matching results the same way

### Database Impact
- No schema changes

### Migration Notes
- No action needed - `config.overrides.yaml` entries under `genre_fallback`
  (if any were ever set via the now-removed commands) are simply ignored

### Testing Recommendations
1. Confirm releases keep arriving for existing tags after upgrading
2. Try a tag whose releases often sit under an unrelated primary genre and
   confirm those releases now come through
3. Confirm `/genre_list` etc. are gone from `/help` and no longer respond

---

## Version 2.0.1 - Real Tag Verification for Genre-Fallback Releases

### Summary
The discover API only ever reports a release's single curated parent genre
(e.g. "punk"), never the specific tags an artist actually applied (e.g.
"hardcore punk", "d-beat"). For tags served via `GENRE_FALLBACK`, this made
it impossible to confirm a release genuinely carried the tag it was found
under, rather than just happening to share its parent genre. Adds a check
that fetches each newly found release's own page - which, unlike
`/discover`, is server-rendered and lists every tag the artist applied - and
uses the real tags for both storage and the Telegram message.

### Changes

#### New Features
- `BandcampParser.fetch_release_tags()`: fetches a release's own page and
  extracts its full, real tag list from the server-rendered tag links
- New releases now have their tags refined with this real list before being
  saved and sent, in both the main-tags and blacklist processing paths

### Technical Details
- Verified against real releases: sampling fresh "punk"-genre results
  fetched for the "hardcore punk" tag, roughly a quarter carried the
  `hardcore-punk` tag specifically (the rest were plain "punk" or informal
  variants like "punk-hardcore"/"crustpunk") - confirming genuinely
  tagged releases are captured through the genre-fallback feed, not just
  releases that happen to share the parent genre
- Adds one extra HTTP GET per newly discovered release (not per genre-feed
  page), since release pages are only fetched for releases not already in
  the database

### Database Impact
- No schema changes - the `tags` column now stores the release's real tags
  when available, instead of the generic parent-genre label

---

## Version 2.0.0 - API-Based Scraping, Admin Commands, and Reliability Fixes

### Summary
Replaced the Selenium/browser-based scraper with direct calls to Bandcamp's
internal discovery API, removing the heaviest and most fragile part of the
stack. Added a Telegram command interface for changing tags, schedule, and
genre mappings without server access, plus several reliability and cleanup
fixes.

### Changes

#### Breaking / Architecture
- Removed Selenium, undetected-chromedriver, webdriver-manager, and
  BeautifulSoup entirely - the scraper now fetches releases via a lightweight
  HTTP call to Bandcamp's internal discover API instead of driving a headless
  browser
- Added a genre-fallback mapping so tags that aren't one of Bandcamp's
  curated top-level genres (e.g. "hardcore punk", "d-beat", "metalcore") are
  served from the closest matching genre feed
- Pagination now always includes the freshest page of a genre feed plus one
  supplementary page per call, so multiple tags mapped to the same genre
  still get broad, non-redundant coverage without ever missing newly
  published releases

#### New Features
- **Telegram admin commands**: manage tags, blacklist, schedule
  (times/jitter), and genre mappings directly from Telegram, restricted to
  the configured chat - see `/help` for the full command list
- **Schedule jitter**: a configurable random delay after each scheduled time,
  so runs don't fire at a perfectly predictable moment
- **Disk-usage-based cleanup**: the database now also prunes its oldest
  records once disk usage crosses a configurable threshold, independent of
  the existing age-based retention window
- **Log rotation**: application logs now rotate daily and are kept for 4
  weeks instead of growing unbounded

#### Bug Fixes
- `run_once.py` no longer silently drops a release if the Telegram send
  fails - it's now persisted to the database first, same as the
  long-running service, so it gets picked up by the retry mechanism
- Removed a duplicate tag entry in the default configuration that mapped to
  the same genre twice

#### Removed
- Legacy/compatibility aliases in the config and database modules that had
  no remaining callers
- Unused dependencies: aiohttp, beautifulsoup4, Pillow, selenium,
  webdriver-manager, undetected-chromedriver

#### Technical Details

**New/changed modules:**
- `src/admin_bot.py`: Telegram command handlers, running on a dedicated
  polling thread separate from the notification bot
- `src/parser.py`: rewritten around the discover API; `BandcampParser` no
  longer manages a browser driver
- `src/config.py`: adds a bot-writable `config.overrides.yaml` layer
  (gitignored) so admin commands can change settings without editing the
  main config file, plus a `genre_fallback` property
- `src/database.py`: adds `cleanup_by_disk_pressure()` and a public
  `disk_usage_percent()`

**Behavior:**
- Tag and blacklist changes made via Telegram commands take effect on the
  next scheduled run, no restart needed
- Schedule and genre-mapping changes require a restart to take effect; the
  admin bot triggers this itself and the service comes back up automatically

#### Database Impact
- No schema changes
- Disk-pressure cleanup deletes the oldest records (regardless of age) once
  the configured disk-usage threshold is reached, then reclaims the freed
  space with `VACUUM`

### Migration Notes
- Copy `.env.example` to `.env` and fill in your own Telegram bot token and
  chat ID
- Remove `selenium`, `undetected-chromedriver`, `webdriver-manager`,
  `beautifulsoup4`, `aiohttp`, and `Pillow` from any existing virtual
  environment if you're upgrading in place - they're no longer required
- No database migration required

### Testing Recommendations
1. Confirm the bot can still fetch and send releases for your configured
   tags after upgrading
2. Test `/status`, `/tags_add`, and `/schedule_set` via Telegram to confirm
   the admin commands work and are restricted to your own chat
3. Verify the service still starts and stops cleanly under your process
   manager

---

## Version 1.2.0 - Automatic Retry for Failed Releases

### Summary
Added automatic retry mechanism that attempts to resend failed releases every 20 minutes until successful delivery.

### Changes

#### New Features
- **Automatic retry system**: Failed releases (with `sent_at=NULL`) are now automatically retried every 20 minutes
- **Background retry task**: Runs continuously in a separate thread, checking for unsent releases and attempting to send them
- **Immediate retry on startup**: Retry task runs immediately when bot starts, then continues every 20 minutes
- **Persistent retry**: Retries continue indefinitely until release is successfully sent

#### Technical Details

**New Methods:**
- `Database.get_unsent_releases()`: Returns all releases with `sent_at=NULL` from the database
- `BandcampBot._retry_failed_releases()`: Processes unsent releases and attempts to send them to Telegram
- `BandcampBot._retry_loop()`: Background loop that runs retry task every 20 minutes
- `BandcampBot._start_retry_task()` / `_stop_retry_task()`: Control methods for retry task lifecycle

**Implementation:**
- Retry task runs in a separate daemon thread
- Uses asyncio.run() to execute async retry operations
- Gracefully stops on application shutdown
- Logs all retry attempts and results

**Behavior:**
- Retry task starts automatically when bot starts
- First retry attempt happens immediately on startup
- Subsequent retries occur every 20 minutes
- Only releases with `sent_at=NULL` are retried
- Successfully sent releases are marked with `mark_sent()` and removed from retry queue
- Failed retries continue to be retried every 20 minutes

#### Database Impact
- No schema changes required
- Uses existing `sent_at` field to identify unsent releases
- Failed releases remain in database until successfully sent

### Migration Notes
- No migration required
- Retry mechanism starts automatically on bot startup
- Existing failed releases will be retried automatically

### Testing Recommendations
1. Test with network interruptions to verify retries work correctly
2. Verify retry task starts on bot startup
3. Confirm retries occur every 20 minutes
4. Check that successfully sent releases are removed from retry queue
5. Verify retry task stops gracefully on shutdown

---

## Version 1.1.0 - Failed Release Persistence Fix

### Summary
Fixed critical issue where releases that failed to send to Telegram were being lost instead of being saved to the database for potential retry.

### Changes

#### Bug Fixes
- **Fixed release loss on Telegram send failures**: Releases that fail to send to Telegram (due to timeouts, network errors, etc.) are now saved to the database with `sent_at=NULL` instead of being discarded
- **Improved error handling**: Failed releases are now logged with a warning message indicating they were saved to the database for potential retry

#### Technical Details

**Before:**
- Releases were only saved to the database after successful Telegram delivery
- If sending failed after all retry attempts, the release was completely lost
- No way to track or retry failed releases

**After:**
- Releases are saved to the database **before** attempting to send to Telegram
- `mark_sent()` is only called when Telegram delivery succeeds
- Failed releases remain in the database with `sent_at=NULL`, allowing them to be tracked via the `pending` count in database statistics
- This enables future implementation of retry mechanisms for failed releases

#### Affected Methods
- `_process_release()`: Now saves releases to DB before sending, marks as sent only on success
- `_process_main_tags()`: Now saves releases to DB before sending, marks as sent only on success

#### Database Impact
- Failed releases will now appear in the database with `sent_at=NULL`
- The `pending` count (total - sent) will accurately reflect releases that failed to send
- No database schema changes required - existing structure supports this behavior

### Migration Notes
- No migration required - this is a behavioral change only
- Existing database records are unaffected
- Failed releases from previous runs are not recoverable (they were not saved)

### Testing Recommendations
1. Test with network interruptions to verify releases are saved even when Telegram is unreachable
2. Verify database statistics show correct `pending` count for failed releases
3. Confirm that failed releases don't get reprocessed on subsequent runs (they already exist in DB)

### Related Issues
- Fixes issue where releases were lost when Telegram API had connection pool timeouts
- Addresses the problem where temporary network issues caused permanent data loss
