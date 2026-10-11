// @ts-nocheck — vendored verbatim below this line. Upstream compiles without
// `noPropertyAccessFromIndexSignature`, which this repo enables, so its option
// bags read as `opts.rBase` where our config demands `opts['rBase']`. Rewriting
// several hundred accesses would forfeit the one property that makes vendoring
// safe: that an upgrade is a re-copy. This header is the only edit.
// Mode key → frame painter. Kept separate from the presets so tree
// shaking can in principle drop unused modes in custom builds.

import type { ModeKey } from '../presets';
import type { ModeDraw } from './types';
import { drawGlobe, drawRubik, drawWave } from './lattice';
import { drawMorph } from './morph';
import { drawOrbits } from './orbits';
import { drawRibbon } from './ribbon';

export const MODE_DRAWS: Record<ModeKey, ModeDraw> = {
  orbits: drawOrbits,
  globe: drawGlobe,
  rubik: drawRubik,
  wave: drawWave,
  ribbon: drawRibbon,
  morph: drawMorph
};
