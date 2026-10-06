/**
 * Display helpers for case / patient identifiers.
 *
 * New records use human-readable codes (CASE-00001, PAT-00001) which are short
 * enough to show in full. Records created before that change have legacy random
 * Firestore ids, which we still truncate to a short prefix.
 */
const CODE_RE = /^(CASE|PAT|APPT)-/i;

/** Short label for an id: full code for new records, `#abcd1234` for legacy. */
export function formatId(id) {
  if (!id) return '';
  return CODE_RE.test(id) ? id : `#${id.slice(0, 8)}`;
}

/** Same as formatId but safe for filenames (no leading `#`). */
export function idForFilename(id) {
  if (!id) return 'unknown';
  return CODE_RE.test(id) ? id : id.slice(0, 8);
}
