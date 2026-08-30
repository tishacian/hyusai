/**
 * PR to PO factory execution contract. Angular-free so the unit spec can
 * pin App → Binding → System → Run without a TestBed.
 *
 * The public /work binding resolve deliberately omits system_id. The desk
 * therefore starts a cycle through the Experience binding, then reads the
 * System from the Run the binding created.
 */
import type { RuntimeNodeContext } from '../runtime/model';

export const FACTORY_EXPERIENCE_SLUG = 'pr-to-po';
export const FACTORY_BINDING_KEY = 'procurement.pr_to_po.run';
export const FACTORY_PAGE_ID = 'home';
export const FACTORY_COMPONENT_ID = 'factory-cycle';

export function factoryRunOrigin(): string {
  return `experience:${FACTORY_EXPERIENCE_SLUG}`;
}

export function factoryRuntimeContext(): RuntimeNodeContext {
  return {
    experienceSlug: FACTORY_EXPERIENCE_SLUG,
    pageId: FACTORY_PAGE_ID,
    componentId: FACTORY_COMPONENT_ID,
    stateKey: FACTORY_BINDING_KEY,
    sourceStateKey: FACTORY_BINDING_KEY,
    mode: 'live',
  };
}

export function canStartFactoryCycle(resolved: { status?: string } | null | undefined): boolean {
  return resolved?.status === 'ok';
}

export function factorySystemHref(systemId: string): string {
  return `/systems/${encodeURIComponent(systemId)}`;
}

export function factoryFlowHref(systemId: string): string {
  return `/systems/${encodeURIComponent(systemId)}/flow`;
}

export function factoryRunHref(runId: string): string {
  return `/runs/${encodeURIComponent(runId)}`;
}

export function runAdapterOrigin(inputRef: Record<string, unknown> | null | undefined): string | null {
  const ingress = inputRef?.['_ingress'];
  if (!ingress || typeof ingress !== 'object') return null;
  const adapter = (ingress as Record<string, unknown>)['adapter'];
  if (!adapter || typeof adapter !== 'object') return null;
  const origin = (adapter as Record<string, unknown>)['origin'];
  return typeof origin === 'string' && origin ? origin : null;
}

export function isFactoryOriginRun(inputRef: Record<string, unknown> | null | undefined): boolean {
  return runAdapterOrigin(inputRef) === factoryRunOrigin();
}
