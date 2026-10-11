import { onAccentColor } from '../features/experience/runtime/style';

/** Shared by the Studio, published Work applications and workspace chrome. */
export interface BrandAppearance {
  palette?: 'agentium' | 'graphite' | 'sand';
  accent?: string;
  corners?: 'square' | 'soft' | 'round';
  logo?: string;
  logo_light?: string;
}

export const BRAND_LOGO_BYTES = 96 * 1024;

export function brandLogo(value: unknown): string {
  if (typeof value !== 'string' || value.length > 132000) return '';
  if (/^data:image\/(png|jpeg|webp);base64,[A-Za-z0-9+/]+={0,2}$/.test(value)) return value;
  if (value.length > 2048 || /[\s\\<>]/.test(value)) return '';
  if (/^\/(?!\/)/.test(value)) return value;
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && !url.username && !url.password ? value : '';
  } catch { return ''; }
}

export function brandAppearance(raw: unknown): BrandAppearance {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return {};
  const row = raw as Record<string, unknown>;
  return {
    ...(row['palette'] === 'graphite' || row['palette'] === 'sand' || row['palette'] === 'agentium' ? { palette: row['palette'] } : {}),
    ...(typeof row['accent'] === 'string' && /^#[\da-f]{6}$/i.test(row['accent']) ? { accent: row['accent'] } : {}),
    ...(row['corners'] === 'square' || row['corners'] === 'soft' || row['corners'] === 'round' ? { corners: row['corners'] } : {}),
    ...(brandLogo(row['logo']) ? { logo: brandLogo(row['logo']) } : {}),
    ...(brandLogo(row['logo_light']) ? { logo_light: brandLogo(row['logo_light']) } : {}),
  };
}

export function appearanceLogo(raw: unknown, mode: string): string {
  const brand = brandAppearance(raw);
  return (mode === 'light' ? brand.logo_light : brand.logo) || brand.logo || brand.logo_light || '';
}

export function appearanceStyles(raw: unknown, mode: string): Record<string, string> {
  const brand = brandAppearance(raw);
  const styles: Record<string, string> = {};
  if (brand.palette && brand.palette !== 'agentium') {
    const dark = mode === 'dark';
    const sand = brand.palette === 'sand';
    const base = dark ? (sand ? '#171410' : '#090909') : (sand ? '#f5efe3' : '#f4f4f4');
    const panel = dark ? (sand ? '#231f18' : '#171717') : (sand ? '#fffbf2' : '#ffffff');
    const fg = dark ? '#f5f5f5' : '#171717';
    const muted = dark ? '#b3b3b3' : '#575757';
    Object.assign(styles, {
      '--ck-bg-void': base, '--ck-bg-base': base, '--ck-bg-panel': panel,
      '--ck-bg-panel-hi': panel, '--ck-bg-inset': base,
      '--ck-fg-1': fg, '--ck-fg-2': fg, '--ck-fg-3': muted, '--ck-fg-4': muted,
    });
  }
  if (brand.accent) {
    Object.assign(styles, {
      '--ck-cta-bg': brand.accent, '--ck-cta-bg-hover': brand.accent,
      '--ck-cta-fg': onAccentColor(brand.accent),
      '--xp-app-accent': brand.accent, '--xp-on-accent': onAccentColor(brand.accent),
    });
  }
  if (brand.corners) {
    const sizes = { square: ['0px', '0px', '0px', '0px'], soft: ['4px', '6px', '10px', '14px'], round: ['8px', '12px', '18px', '24px'] }[brand.corners];
    ['sm', 'md', 'lg', 'xl'].forEach((size, index) => styles[`--ck-radius-${size}`] = sizes[index]!);
  }
  return styles;
}
