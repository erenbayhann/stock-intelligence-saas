// Parses app/ml/explain.py's "Key factors: A; B; C." format into short tags
// for the hero card. Falls back to showing the whole sentence as one tag
// when the model didn't produce the "Key factors" form (e.g. no factor
// stood out that day).
export function explanationToFactors(explanation: string): string[] {
  const prefix = "Key factors: ";
  if (!explanation.startsWith(prefix)) return [explanation];
  const body = explanation.slice(prefix.length).replace(/\.$/, "");
  return body
    .split(";")
    .map((s) => s.trim())
    .filter(Boolean);
}
