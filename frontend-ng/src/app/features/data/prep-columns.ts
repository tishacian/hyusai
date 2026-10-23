/**
 * Column choices of a preparation step: the columns of the current preview,
 * plus every column the step is already configured with.
 *
 * Without a preview (a published version read without input, a source not
 * reachable), the configured columns must still be shown and selected;
 * otherwise a step reads as if it kept nothing.
 */
export function columnChoices(available: readonly string[], ...configured: unknown[]): string[] {
  const choices = [...available];
  const seen = new Set(choices);
  const add = (value: unknown) => {
    if (typeof value === 'string' && value && !seen.has(value)) { seen.add(value); choices.push(value); }
  };
  for (const value of configured) {
    if (Array.isArray(value)) value.forEach(add);
    else add(value);
  }
  return choices;
}
