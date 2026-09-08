export type CkChartTone = 'ink' | 'declared' | 'negative';

export type CkStreamTone = 'ink' | 'declared' | 'declared-soft';

export interface CkChartTick {
  index: number;
  label: string;
  anchor?: 'start' | 'middle' | 'end';
}

export function ckChartToneVar(tone: CkChartTone | CkStreamTone): string {
  switch (tone) {
    case 'declared':
    case 'declared-soft':
      return 'var(--ck-signal-cool)';
    case 'negative':
      return 'var(--ck-signal-neg)';
    default:
      return 'var(--ck-fg-1)';
  }
}

export function ckChartUid(prefix: string): string {
  return `${prefix}-${Math.random().toString(36).slice(2, 10)}`;
}
