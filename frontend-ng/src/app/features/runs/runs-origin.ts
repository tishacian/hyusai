const EXPERIENCE_SLUG = /^[a-z][a-z0-9-]{0,119}$/;

export function experienceOrigin(slug: string): string | null {
  const value = slug.trim().toLocaleLowerCase();
  return EXPERIENCE_SLUG.test(value) ? `experience:${value}` : null;
}

export function experienceSlugFromOrigin(origin: string | null | undefined): string {
  if (!origin?.startsWith('experience:')) return '';
  const slug = origin.slice('experience:'.length);
  return EXPERIENCE_SLUG.test(slug) ? slug : '';
}

export function normalizedExperienceOrigin(origin: string | null | undefined): string | null {
  const slug = experienceSlugFromOrigin(origin);
  return slug ? `experience:${slug}` : null;
}
