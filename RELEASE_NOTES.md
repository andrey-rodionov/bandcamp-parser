# Release Notes

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
