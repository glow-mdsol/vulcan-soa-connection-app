// Rough character-count word wrap for SVG <text>, which has no native wrapping.
const MAX_CHARS_PER_LINE = 20;
const MAX_LINES = 3;

export function wrapLabel(label: string): string[] {
  const words = label.split(/\s+/);
  const lines: string[] = [];
  let current = "";

  for (const word of words) {
    const candidate = current ? `${current} ${word}` : word;
    if (candidate.length > MAX_CHARS_PER_LINE && current) {
      lines.push(current);
      current = word;
    } else {
      current = candidate;
    }
  }
  if (current) {
    lines.push(current);
  }

  if (lines.length > MAX_LINES) {
    const truncated = lines.slice(0, MAX_LINES);
    truncated[MAX_LINES - 1] = `${truncated[MAX_LINES - 1].replace(/.{3}$/, "")}...`;
    return truncated;
  }
  return lines;
}
