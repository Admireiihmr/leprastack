/** Compute the join-window phase for an appointment.
 *
 *  Window: [scheduled_at - EARLY_MIN, scheduled_at + duration_minutes]
 *  Outside that window joining is not allowed.
 *
 *  Returns:
 *    phase:           'upcoming' | 'active' | 'expired'
 *    minsUntilStart:  signed minutes until scheduled_at (negative once started)
 *    minsRemaining:   signed minutes until the end of the slot (negative once expired)
 *    label:           human-readable countdown ("In 3 hours", "5 min left", "Session expired")
 */
const EARLY_MIN = 5;

export function meetingPhase(scheduledAtIso, durationMinutes = 30, now = new Date()) {
  if (!scheduledAtIso) {
    return { phase: 'upcoming', minsUntilStart: Infinity, minsRemaining: Infinity, label: '' };
  }
  const start = new Date(scheduledAtIso);
  const end = new Date(start.getTime() + durationMinutes * 60_000);
  const minsUntilStart = Math.round((start - now) / 60_000);
  const minsRemaining = Math.round((end - now) / 60_000);

  if (now < new Date(start.getTime() - EARLY_MIN * 60_000)) {
    return { phase: 'upcoming', minsUntilStart, minsRemaining, label: relativeFuture(minsUntilStart) };
  }
  if (now > end) {
    return { phase: 'expired', minsUntilStart, minsRemaining, label: 'Session expired' };
  }
  // Active: within [start - 5 min, end]
  const remainLabel =
    minsRemaining <= 0
      ? 'Ending now'
      : minsRemaining === 1
        ? '1 minute left'
        : `${minsRemaining} minutes left`;
  return { phase: 'active', minsUntilStart, minsRemaining, label: remainLabel };
}

function relativeFuture(mins) {
  if (mins > 60 * 24) return `In ${Math.round(mins / (60 * 24))} day(s)`;
  if (mins > 60) return `In ${Math.round(mins / 60)} hour(s)`;
  if (mins > 1) return `In ${mins} minutes`;
  if (mins === 1) return 'In 1 minute';
  return 'Starting soon';
}
