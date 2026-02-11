# Release Notes

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
