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

export interface AssistantWebcamCycleEntry {
  source_id: string;
  label?: string | null;
  proxy_url: string;
}

export interface AssistantShowWebcamEffect {
  source_id: string;
  vessel_mmsi?: string | null;
  vessel_name?: string | null;
  cargo_id?: string | null;
  label?: string | null;
  attribution?: string | null;
  label_disclaimer?: string | null;
  proxy_url: string;
  cycle?: AssistantWebcamCycleEntry[];
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

  dispatchShowWebcam(effect: AssistantShowWebcamEffect): void {
    window.dispatchEvent(new CustomEvent('agentium:assistant-show-webcam', { detail: effect }));
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
    if (kind.includes('webcam')) {
      this.dispatchShowWebcam(this.normalizeShowWebcam(payload));
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

  private normalizeShowWebcam(payload: Record<string, unknown>): AssistantShowWebcamEffect {
    const sourceId = String(payload['source_id'] || '').trim();
    const proxyUrl = String(
      payload['proxy_url'] || (sourceId ? `/api/v1/mission-room/webcams/proxy?source_id=${sourceId}` : ''),
    );
    const rawCycle = Array.isArray(payload['cycle']) ? (payload['cycle'] as unknown[]) : [];
    const cycle: AssistantWebcamCycleEntry[] = rawCycle
      .map((entry) => {
        if (!entry || typeof entry !== 'object') return null;
        const record = entry as Record<string, unknown>;
        const id = String(record['source_id'] || '').trim();
        if (!id) return null;
        return {
          source_id: id,
          label: record['label'] != null ? String(record['label']) : undefined,
          proxy_url: String(
            record['proxy_url'] || `/api/v1/mission-room/webcams/proxy?source_id=${id}`,
          ),
        } satisfies AssistantWebcamCycleEntry;
      })
      .filter((entry): entry is AssistantWebcamCycleEntry => entry !== null);
    return {
      source_id: sourceId,
      vessel_mmsi: payload['vessel_mmsi'] != null ? String(payload['vessel_mmsi']) : null,
      vessel_name: payload['vessel_name'] != null ? String(payload['vessel_name']) : null,
      cargo_id: payload['cargo_id'] != null ? String(payload['cargo_id']) : null,
      label: payload['label'] != null ? String(payload['label']) : null,
      attribution: payload['attribution'] != null ? String(payload['attribution']) : null,
      label_disclaimer:
        payload['label_disclaimer'] != null ? String(payload['label_disclaimer']) : null,
      proxy_url: proxyUrl,
      cycle,
    };
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
