// Canonical list of Indian states and union territories, used both to populate
// state dropdowns (so new records can't be misspelled) and to reconcile older
// free-text records that were typed by hand (e.g. "Andrapradesh", "rajasthan ").
export const INDIAN_STATES_AND_UTS = [
  'Andhra Pradesh', 'Arunachal Pradesh', 'Assam', 'Bihar', 'Chhattisgarh', 'Goa', 'Gujarat',
  'Haryana', 'Himachal Pradesh', 'Jharkhand', 'Karnataka', 'Kerala', 'Madhya Pradesh',
  'Maharashtra', 'Manipur', 'Meghalaya', 'Mizoram', 'Nagaland', 'Odisha', 'Punjab',
  'Rajasthan', 'Sikkim', 'Tamil Nadu', 'Telangana', 'Tripura', 'Uttar Pradesh',
  'Uttarakhand', 'West Bengal',
  'Andaman and Nicobar Islands', 'Chandigarh', 'Dadra and Nagar Haveli and Daman and Diu',
  'Delhi', 'Jammu and Kashmir', 'Ladakh', 'Lakshadweep', 'Puducherry'
];

export function levenshtein(a: string, b: string): number {
  const dp: number[][] = Array.from({ length: a.length + 1 }, () => new Array(b.length + 1).fill(0));
  for (let i = 0; i <= a.length; i++) dp[i][0] = i;
  for (let j = 0; j <= b.length; j++) dp[0][j] = j;
  for (let i = 1; i <= a.length; i++) {
    for (let j = 1; j <= b.length; j++) {
      dp[i][j] = a[i - 1] === b[j - 1]
        ? dp[i - 1][j - 1]
        : 1 + Math.min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1]);
    }
  }
  return dp[a.length][b.length];
}

const canonicalByKey = new Map(
  INDIAN_STATES_AND_UTS.map(name => [name.toLowerCase().replace(/[^a-z]/g, ''), name])
);

// Collapses case/whitespace variants and near-miss typos (e.g. "Andrapradesh",
// "andrapreadesh") onto the canonical state name, so records that mean the same
// state group together instead of showing up as separate rows.
export function normalizeStateName(raw: string | undefined | null): string {
  const trimmed = (raw || '').trim();
  if (!trimmed) return trimmed;

  const key = trimmed.toLowerCase().replace(/[^a-z]/g, '');
  const exact = canonicalByKey.get(key);
  if (exact) return exact;

  let bestName: string | null = null;
  let bestDistance = Infinity;
  for (const [canonicalKey, canonicalName] of canonicalByKey) {
    const distance = levenshtein(key, canonicalKey);
    if (distance < bestDistance) {
      bestDistance = distance;
      bestName = canonicalName;
    }
  }


  
  const threshold = Math.max(2, Math.ceil(key.length * 0.25));
  return bestName && bestDistance <= threshold ? bestName : trimmed;
}
