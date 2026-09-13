import { Chart, registerables } from 'chart.js';

let registered = false;

/** Register Chart.js only when a chart-bearing lazy surface is opened. */
export function ensureChartsRegistered(): void {
  if (registered) return;
  Chart.register(...registerables);
  registered = true;
}
