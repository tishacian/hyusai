import { Injectable, inject } from '@angular/core';
import { Router } from '@angular/router';

export interface AssistantNavigateEffect {
  workspace?: string;
  route: string;
  queryParams?: Record<string, string>;
  highlight?: string;
  metadata?: {
    last_focus?: string;
    focus_node_type?: string;
    focus_node_id?: string;
    [key: string]: unknown;
  };
}

export interface AssistantProposeEffect {
  proposal_id: string;
  label: string;
  prompt?: string;
  confirm_action?: string;
  decline_action?: string;
}

export interface AssistantDraftOpenEffect {
  target_type: string;
  target_id: string;
  draft_payload?: Record<string, unknown>;
}

@Injectable({ providedIn: 'root' })
export class AssistantEffectsService {
  private readonly router = inject(Router);

  dispatchNavigate(effect: AssistantNavigateEffect): void {
    window.dispatchEvent(new CustomEvent('agentium:assistant-navigate', { detail: effect }));
  }

  dispatchPropose(effect: AssistantProposeEffect): void {
    window.dispatchEvent(new CustomEvent('agentium:assistant-propose', { detail: effect }));
  }

  dispatchDraftOpen(effect: AssistantDraftOpenEffect): void {
    window.dispatchEvent(new CustomEvent('agentium:assistant-draft-open', { detail: effect }));
  }

  handleActionEffect(payload: Record<string, unknown>): void {
    const kind = String(payload['kind'] || payload['effect'] || payload['type'] || '').toLowerCase();
    if (kind.includes('navigate')) {
      this.dispatchNavigate(this.normalizeNavigate(payload));
      return;
    }
    if (kind.includes('propose')) {
      this.dispatchPropose(payload as unknown as AssistantProposeEffect);
      return;
    }
    if (kind.includes('draft')) {
      this.dispatchDraftOpen(payload as unknown as AssistantDraftOpenEffect);
    }
  }

  navigate(effect: AssistantNavigateEffect): void {
    const queryParams: Record<string, string> = { ...(effect.queryParams || {}) };
    const focus = this.resolveFocusNode(effect);
    if (effect.highlight) queryParams['highlight'] = effect.highlight;
    else if (focus) queryParams['highlight'] = focus;
    if (focus) queryParams['focus_node'] = focus;
    const route = effect.route.startsWith('/') ? effect.route : `/${effect.route}`;
    void this.router.navigate([route], { queryParams });
  }

  private resolveFocusNode(effect: AssistantNavigateEffect): string | undefined {
    const metadata = effect.metadata || {};
    if (metadata.last_focus) return String(metadata.last_focus);
    if (metadata.focus_node_id) return String(metadata.focus_node_id);
    return effect.highlight;
  }

  private normalizeNavigate(payload: Record<string, unknown>): AssistantNavigateEffect {
    const queryParams = (payload['queryParams'] || payload['query_params']) as Record<string, string> | undefined;
    const metadata = (payload['metadata'] || {}) as Record<string, unknown>;
    return {
      workspace: payload['workspace'] ? String(payload['workspace']) : undefined,
      route: String(payload['route'] || '/'),
      queryParams,
      highlight: payload['highlight'] ? String(payload['highlight']) : undefined,
      metadata: {
        last_focus: metadata['last_focus'] ? String(metadata['last_focus']) : undefined,
        focus_node_type: metadata['focus_node_type'] ? String(metadata['focus_node_type']) : undefined,
        focus_node_id: metadata['focus_node_id'] ? String(metadata['focus_node_id']) : undefined,
        ...metadata,
      },
    };
  }
}
