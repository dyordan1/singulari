export const INK = "#c9c9c9";
export const DIM = "#8a8a8a";
export const FAINT = "#5a5a5a";
export const RULE = "#1e1e1e";
export const WHITE = "#fff";
export const mono = "ui-monospace, SFMono-Regular, Menlo, monospace";

export function ago(ms: number): string {
  const s = Math.max(0, Math.round(ms / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

export function stamp(iso: string): string {
  return iso.replace("T", " ").replace("Z", "").slice(0, 16);
}
