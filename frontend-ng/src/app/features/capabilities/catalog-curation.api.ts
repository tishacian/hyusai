import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from '@app/core/api.service';

/** Which lever releases a group of skills. ``industry`` and ``universal`` are
 *  tier decisions that move many skills at once; ``capability`` names one row;
 *  ``unclaimed`` means no capability reachable here claims them at all, so only
 *  a per-skill override can. */
export type CoverageLever = 'industry' | 'universal' | 'capability' | 'unclaimed';

export interface CoverageGap {
  lever: CoverageLever;
  key: string;
  skills: number;
  skill_slugs: string[];
  capabilities: string[];
}

export interface CatalogOverride {
  kind: 'enabled' | 'hidden';
  entry: string;
  slug: string;
  name: string;
  status: 'effective' | 'redundant' | 'dangling';
  /** ``app:<id>`` when an enabled Workspace App wrote it, else ``admin``. */
  source: string;
}

export interface CategoryCoverage {
  category: string;
  total: number;
  visible: number;
}

export interface CuratedSkill {
  slug: string;
  name: string;
  category: string;
  visible: boolean;
  reason: string;
  capabilities: string[];
  carriers: string[];
}

export interface CuratedCapability {
  slug: string;
  name: string;
  tier?: string | null;
  industry?: string | null;
  skills: number;
  visible: boolean;
  reason: string;
}

export interface CatalogPolicy {
  show_universal: boolean;
  show_unconfigured_industries: boolean;
  allowed_industries: string[];
  enabled_capabilities: string[];
  hidden_capabilities: string[];
  enabled_skills: string[];
  hidden_skills: string[];
  allowed_industries_source: 'configured' | 'inferred';
}

export interface CatalogCurationReport {
  summary: {
    total: number;
    visible: number;
    filtered: number;
    filtered_reasons: Record<string, number>;
  };
  policy: CatalogPolicy;
  categories: CategoryCoverage[];
  gaps: CoverageGap[];
  overrides: CatalogOverride[];
  skills: CuratedSkill[];
  capabilities: CuratedCapability[];
  editable: boolean;
}

/** Only the levers being changed are sent; the rest keep their stored value. */
export type CatalogPolicyPatch = Partial<Omit<CatalogPolicy, 'allowed_industries_source'>>;

@Injectable({ providedIn: 'root' })
export class CatalogCurationApi {
  private readonly api = inject(ApiService);
  private readonly root = '/catalog/curation';

  report(): Observable<CatalogCurationReport> {
    return this.api.get<CatalogCurationReport>(this.root);
  }

  /** Returns the coverage the write produced, so the screen cannot drift. */
  update(patch: CatalogPolicyPatch): Observable<CatalogCurationReport> {
    return this.api.patch<CatalogCurationReport>(this.root, patch);
  }
}
