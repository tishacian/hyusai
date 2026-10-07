/**
 * Dependency-light unit-test runner for the Flow Builder's engine-agnostic
 * logic (adapter + CanonicalFlow serializer).
 *
 * The repo has no Angular unit-test harness (no Karma/Jasmine/Vitest) and the
 * Playwright e2e suite targets a live VM + Keycloak, so it can't run locally.
 * Rather than add a heavy runner, this bundles each co-located `*.spec.ts`
 * with the already-installed esbuild (which erases `import type`, applies the
 * tsconfig `@app/*` paths, and aliases `@angular/core` to a metadata-only
 * stub) and runs the bundles with Node's built-in test runner.
 *
 * Usage: `npm run test:unit`
 */
import { build } from 'esbuild';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname, basename } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..');
const stub = join(here, 'ng-core.stub.mjs');

// Pure specs: engine-agnostic logic. `@angular/core` is aliased to a
// metadata-only stub (the serializer uses it only for `@Injectable`).
const pureSpecs = [
  'src/app/features/models/tuning-evidence.vm.spec.ts',
  'src/app/features/auth/cursor-wake.spec.ts',
  'src/app/features/auth/auth-atom.spec.ts',
  'src/app/features/auth/gravity.spec.ts',
  'src/app/features/experience/work/claim-run.spec.ts',
  'src/app/features/experience/work/claim-triage.spec.ts',
  'src/app/features/hypervisor/v2/impact-product-blocks.spec.ts',
  'src/app/features/governance/audit-trail.vm.spec.ts',
  'src/app/features/intelligence/intelligence.vm.spec.ts',
  'src/app/features/hypervisor/v2/demo-finishings.spec.ts',
  'src/app/features/mandate/mandate.models.spec.ts',
  'src/app/features/chat/chat-proof.spec.ts',
  'src/app/shared/work-sources/work-source.spec.ts',
  'src/app/features/mandate/mandate-editor.vm.spec.ts',
  'src/app/features/systems/system-mandate-coverage.vm.spec.ts',
  'src/app/features/experience/work/work-decision.spec.ts',
  'src/app/features/experience/hub/automation-draft.model.spec.ts',
  'src/app/features/observability/observability-labels.spec.ts',
  'src/app/features/observability/observability-chart.vm.spec.ts',
  'src/app/features/observability/observability-facets.spec.ts',
  'src/app/features/observability/observability.routes.spec.ts',
  'src/app/features/observability/traces-facet.spec.ts',
  'src/app/features/knowledge/knowledge-facets.spec.ts',
  'src/app/features/knowledge/collection-access-form.spec.ts',
  'src/app/features/knowledge/knowledge-capture-redirect.spec.ts',
  'src/app/features/knowledge/knowledge-base-status.spec.ts',
  'src/app/features/runs/run-trace.vm.spec.ts',
  'src/app/features/orchestration/flow/agent-loop-inspector.vm.spec.ts',
  'src/app/features/orchestration/flow/flow-foblex.adapter.spec.ts',
  'src/app/features/orchestration/flow/flow-preconnect.spec.ts',
  'src/app/features/orchestration/flow/flow-builder-ui-contract.spec.ts',
  'src/app/features/orchestration/flow/automation-palette.spec.ts',
  'src/app/features/orchestration/flow/automation-turn.spec.ts',
  'src/app/features/orchestration/flow/automation-job.spec.ts',
  'src/app/features/systems/value-contract.vm.spec.ts',
  'src/app/features/orchestration/flow/review-loop.vm.spec.ts',
  'src/app/features/orchestration/flow/flow-keyboard-target.vm.spec.ts',
  'src/app/features/orchestration/flow/flow-recipe.vm.spec.ts',
  'src/app/features/orchestration/flow/flow-recipe-ui-contract.spec.ts',
  'src/app/features/orchestration/flow/flow-transform.vm.spec.ts',
  'src/app/features/orchestration/flow/flow-transform-ui-contract.spec.ts',
  'src/app/features/orchestration/flow/flow-ml.vm.spec.ts',
  'src/app/features/orchestration/flow/flow-ml-ui-contract.spec.ts',
  'src/app/features/orchestration/flow/flow-node-run.vm.spec.ts',
  'src/app/features/orchestration/flow/flow-semantic-diff.vm.spec.ts',
  'src/app/features/orchestration/flow/flow.types.spec.ts',
  'src/app/features/orchestration/flow/flow-palette.vm.spec.ts',
  'src/app/features/orchestration/flow/flow-data-sources.vm.spec.ts',
  'src/app/features/connectors/postgresql/postgresql.types.spec.ts',
  'src/app/features/orchestration/flow/flow-ingress-prefill.spec.ts',
  'src/app/features/orchestration/flow/flow-manifest-strip.vm.spec.ts',
  'src/app/features/orchestration/flow/flow-variable.service.spec.ts',
  'src/app/features/orchestration/flow/flow-contract-bindings.vm.spec.ts',
  'src/app/features/orchestration/flow/flow-validation-strip.vm.spec.ts',
  'src/app/features/orchestration/flow/flow-draft.storage.spec.ts',
  'src/app/core/flow-serializer.service.spec.ts',
  'src/app/core/workspace-local-storage.spec.ts',
  'src/app/core/workspace-view-context.spec.ts',
  'src/app/core/navigation.catalog.spec.ts',
  'src/app/core/navigation.routes.spec.ts',
  'src/app/core/client-applications.spec.ts',
  'src/app/core/i18n.lexicon.spec.ts',
  'src/app/core/rail-labels.spec.ts',
  'src/app/features/layout/command-palette.intent.spec.ts',
  'src/app/shared/cockpit/panel-resize.spec.ts',
  'src/app/core/theme-preference.spec.ts',
  'src/app/core/platform-brand.spec.ts',
  'src/app/core/brand-appearance.spec.ts',
  'src/app/core/route-focus.spec.ts',
  'src/app/core/workspace-locale.spec.ts',
  'src/app/shared/cockpit/thinking-orb/thinking-orb.spec.ts',
  'src/app/shared/cockpit/cockpit-contrast.spec.ts',
  'src/app/shared/cockpit/yield-format.spec.ts',
  'src/app/shared/cockpit/charts/svg-path.spec.ts',
  'src/app/shared/cockpit/charts/chart-interact.spec.ts',
  'src/app/shared/cockpit/charts/sankey-layout.spec.ts',
  'src/app/shared/schema-builder/schema-builder.vm.spec.ts',
  'src/app/shared/ui/data-table.vm.spec.ts',
  'src/app/shared/ui/icon-registry.spec.ts',
  'src/app/features/data/data.vm.spec.ts',
  'src/app/features/data/viz/viz.vm.spec.ts',
  'src/app/features/data/viz/viz-kit-ui-contract.spec.ts',
  'src/app/features/models/models.vm.spec.ts',
  'src/app/features/models/forecast.vm.spec.ts',
  'src/app/features/models/tabular-options.vm.spec.ts',
  'src/app/features/models/model-serving-ui-contract.spec.ts',
  'src/app/shared/ui/modal-contract.spec.ts',
  'src/app/core/workspace-experience.spec.ts',
  'src/app/core/workspace-app-canary.spec.ts',
  'src/app/features/governance/workspace-blueprint-plan.spec.ts',
  'src/app/features/governance/experience-governance.models.spec.ts',
  'src/app/features/governance/workspace-app-lifecycle.models.spec.ts',
  'src/app/features/auth/signin-experience.spec.ts',
  'src/app/features/mission-room/mission-room.extension.spec.ts',
  'src/app/features/resources/resources.catalog.spec.ts',
  'src/app/features/connectors/connector-storage.spec.ts',
  'src/app/features/connectors/mcp/mcp-catalog.spec.ts',
  'src/app/features/connectors/mcp/mcp-showcase.spec.ts',
  'src/app/features/systems/system-flow-profile.spec.ts',
  'src/app/features/systems/systems-grid.vm.spec.ts',
  'src/app/features/hypervisor/hypervisor-impact.spec.ts',
  'src/app/features/hypervisor/hypervisor-value-loop.spec.ts',
  'src/app/features/hypervisor/v2/hypervisor-v2-series.spec.ts',
  'src/app/features/hypervisor/v2/hypervisor-v2-views.spec.ts',
  'src/app/features/hypervisor/v2/impact-block-data.spec.ts',
  'src/app/features/hypervisor/v2/impact-sources.spec.ts',
  'src/app/features/hypervisor/v2/impact-synthese.spec.ts',
  'src/app/features/hypervisor/v2/impact-presentation.spec.ts',
  'src/app/features/hypervisor/v2/blocks/impact-blocks.spec.ts',
  'src/app/features/nawa/nawa-run-projection.spec.ts',
  'src/app/features/nawa/nawa-catalog-view.spec.ts',
  'src/app/features/nawa/nawa-inbound-queue.spec.ts',
  'src/app/features/nawa/nawa-conversation.spec.ts',
  'src/app/features/nawa/nawa-assistant.spec.ts',
  'src/app/features/nawa/nawa-engine.spec.ts',
  'src/app/features/nawa/nawa-demo-regression.spec.ts',
  'src/app/features/nawa/nawa-intake.spec.ts',
  'src/app/features/nawa/nawa-preview.spec.ts',
  'src/app/features/nawa/nawa-speech.spec.ts',
  'src/app/features/nawa/nawa-itsd.model.spec.ts',
  'src/app/features/knowledge/capture-fil/fse-system-resolve.spec.ts',
  'src/app/features/experience/runtime/runtime.spec.ts',
  'src/app/features/experience/runtime/system-home.spec.ts',
  'src/app/features/experience/experience.guard.spec.ts',
  'src/app/features/experience/work/work-catalog.spec.ts',
  'src/app/features/workspace/members.component.spec.ts',
  'src/app/features/experience/work/work-launcher.vm.spec.ts',
  'src/app/features/experience/work/work-home.vm.spec.ts',
  'src/app/core/adoption-journey.spec.ts',
  'src/app/features/experience/work/work-language.spec.ts',
  'src/app/features/experience/work/pr-to-po-runtime.spec.ts',
  'src/app/features/experience/work/pr-to-po-studio.spec.ts',
  'src/app/features/experience/work/pr-to-po-receipt.spec.ts',
  'src/app/features/experience/studio/studio.spec.ts',
  'src/app/features/runs/runs-origin.spec.ts',
];

// Store specs: exercised through a REAL Angular Injector (ngrx signalStore +
// JIT). No `@angular/core` alias; the spec imports `@angular/compiler` itself.
const storeSpecs = [
  'src/app/features/mandate/mandate-components.spec.ts',
  'src/app/features/mandate/mandate-editor.component.spec.ts',
  'src/app/features/systems/system-mandate-coverage.component.spec.ts',
  'src/app/shared/cockpit/nav-link.directive.spec.ts',
  'src/app/features/resources/resources-page.component.spec.ts',
  'src/app/features/connectors/generic-connector-drawer.component.spec.ts',
  'src/app/features/chat/assistant-pilot.service.spec.ts',
  'src/app/features/chat/assistant-object-context.service.spec.ts',
  'src/app/features/experience/runtime/renderer-registry.spec.ts',
  'src/app/features/experience/runtime/chart-block.spec.ts',
  'src/app/features/experience/work/work-shell.component.spec.ts',
  'src/app/features/systems/system-view.component.spec.ts',
  'src/app/features/hypervisor/v2/hypervisor-v2-sources.spec.ts',
  'src/app/core/canonical-api-skills.spec.ts',
  'src/app/core/canonical-api-versions.spec.ts',
  'src/app/core/api.service.spec.ts',
  'src/app/store/auth.store.spec.ts',
  'src/app/core/auth.interceptor.spec.ts',
  'src/app/core/navigation-profile.guard.spec.ts',
  'src/app/core/object-perspective.store.spec.ts',
  'src/app/core/zoom-context.service.spec.ts',
  'src/app/shared/cockpit/run-outcome-card.component.spec.ts',
  'src/app/shared/cockpit/charts/chart-declared.spec.ts',
  'src/app/core/workspace-experience-shadow.service.spec.ts',
  'src/app/core/navigation-profile.service.spec.ts',
  'src/app/core/navigation-resolver.service.spec.ts',
  'src/app/core/navigation-telemetry.service.spec.ts',
  'src/app/core/workspace-fetch.service.spec.ts',
  'src/app/core/workspace-route-reuse.strategy.spec.ts',
  'src/app/core/workspace-switch.service.spec.ts',
  'src/app/core/workspace.service.spec.ts',
  'src/app/core/workspace-streams.spec.ts',
  'src/app/core/workspace-scoped-services.spec.ts',
  'src/app/core/voice-session.service.spec.ts',
  'src/app/core/voice-loop-controller.service.spec.ts',
  'src/app/core/voice-tts-playback.service.spec.ts',
  'src/app/core/livekit-conversation.service.spec.ts',
  'src/app/features/chat/assistant-draft-drawer.component.spec.ts',
  'src/app/features/chat/chat-panel.component.spec.ts',
  'src/app/features/chat/chat-workspace.component.spec.ts',
  'src/app/features/chat/conversations.component.spec.ts',
  'src/app/features/chat/conversation-page.component.spec.ts',
  'src/app/features/help/help-panel.component.spec.ts',
  'src/app/features/help/help-guide.component.spec.ts',
  'src/app/core/help.service.spec.ts',
  'src/app/features/experience/work/work-bar.component.spec.ts',
  'src/app/features/knowledge/capture-published-chat.component.spec.ts',
  'src/app/features/andritz/client360/client360-page.component.spec.ts',
  'src/app/features/capabilities/capabilities.component.spec.ts',
  'src/app/features/capabilities/capability-view.component.spec.ts',
  'src/app/features/capabilities/catalog-curation.component.spec.ts',
  'src/app/features/skills/skill-view.component.spec.ts',
  'src/app/features/skills/skill-authoring.component.spec.ts',
  'src/app/features/skills/brd-system-proposal.component.spec.ts',
  'src/app/core/adoption.service.spec.ts',
  'src/app/features/layout/command-palette.component.spec.ts',
  'src/app/features/layout/side-rail.component.spec.ts',
  'src/app/features/layout/mini-rail.component.spec.ts',
  'src/app/features/layout/semantic-zoom-breadcrumb.component.spec.ts',
  'src/app/features/layout/command-bar.component.spec.ts',
  'src/app/features/layout/title-bar.component.spec.ts',
  'src/app/features/layout/business-shell-header.component.spec.ts',
  'src/app/features/mission-room/mission-room.component.spec.ts',
  'src/app/features/mission-room/generic-mission-room.component.spec.ts',
  'src/app/features/mission-room/vp-macro-indicators.component.spec.ts',
  'src/app/features/mission-room/mission-room.routes.spec.ts',
  'src/app/features/runs/runs.routes.spec.ts',
  'src/app/features/runs/run-view.component.spec.ts',
  'src/app/features/runs/correction-review.component.spec.ts',
  'src/app/features/steering/review-queue-scope.spec.ts',
  'src/app/features/steering/steering-l21b.spec.ts',
  'src/app/features/orchestration/flow/flow-correction-context.spec.ts',
  'src/app/features/runs/skill-invocation-view.component.spec.ts',
  'src/app/features/systems/system-value-loop.component.spec.ts',
  'src/app/features/systems/flow-runner.component.spec.ts',
  'src/app/features/governance/workspace-app-lifecycle.component.spec.ts',
  'src/app/features/governance/workspace-app-admin.guard.spec.ts',
  'src/app/features/workspace/chat-knowledge-settings.component.spec.ts',
  'src/app/features/workspace/workspace-entitlements.component.spec.ts',
  'src/app/features/knowledge/knowledge-capture.component.spec.ts',
  'src/app/features/knowledge/ingestion-status.component.spec.ts',
  'src/app/features/nawa/nawa-assistant.component.spec.ts',
  'src/app/features/knowledge/capture-fil/capture-engine.spec.ts',
  'src/app/features/knowledge/capture-fil/capture-templates.spec.ts',
  'src/app/features/orchestration/flow/flow.store.spec.ts',
  'src/app/features/orchestration/flow/flow-run.service.spec.ts',
  'src/app/features/orchestration/flow/flow-workbench.service.spec.ts',
  'src/app/features/orchestration/flow/flow-workbench-panel.component.spec.ts',
  'src/app/features/orchestration/flow/flow-versions.component.spec.ts',
  'src/app/features/orchestration/flow/flow-persistence.service.spec.ts',
  'src/app/features/orchestration/flow/flow-publication-panel.component.spec.ts',
  'src/app/features/orchestration/flow/flow-validation.service.spec.ts',
  'src/app/features/orchestration/flow/flow-validation-strip.spec.ts',
  'src/app/features/orchestration/flow/flow-catalog.service.spec.ts',
  'src/app/features/orchestration/flow/flow-data-sources.service.spec.ts',
  'src/app/features/orchestration/flow/flow-collections.service.spec.ts',
  'src/app/features/orchestration/flow/flow-inspector-retrieval.spec.ts',
  'src/app/features/orchestration/flow/manifest-fields.component.spec.ts',
  'src/app/features/orchestration/flow/flow-palette.component.spec.ts',
];

// Optional comma-separated basename/path filter for constrained developer
// machines and focused CI jobs. The default remains the complete suite.
const requested = (process.env['FLOW_UNIT_FILTER'] ?? '')
  .split(',')
  .map((value) => value.trim())
  .filter(Boolean);
const selected = (specs) => requested.length === 0
  ? specs
  : specs.filter((spec) => requested.some((value) => spec.includes(value)));
const selectedPureSpecs = selected(pureSpecs);
const selectedStoreSpecs = selected(storeSpecs);
if (requested.length > 0 && selectedPureSpecs.length + selectedStoreSpecs.length === 0) {
  throw new Error(`FLOW_UNIT_FILTER matched no specs: ${requested.join(', ')}`);
}

const outDir = mkdtempSync(join(tmpdir(), 'flow-unit-'));
const common = {
  bundle: true,
  platform: 'node',
  format: 'esm',
  target: 'es2022',
  outExtension: { '.js': '.mjs' },
  sourcemap: 'inline',
  absWorkingDir: root,
  nodePaths: [join(root, 'node_modules')],
  tsconfig: join(root, 'tsconfig.json'),
  logLevel: 'warning',
};

let exitCode = 1;
try {
  if (selectedPureSpecs.length > 0) {
    await build({
      ...common,
      entryPoints: selectedPureSpecs.map((s) => join(root, s)),
      outdir: outDir,
      outbase: root,
      alias: { '@angular/core': stub },
    });
  }
  if (selectedStoreSpecs.length > 0) {
    await build({
      ...common,
      entryPoints: selectedStoreSpecs.map((s) => join(root, s)),
      outdir: outDir,
      outbase: root,
    });
  }

  const bundles = [...selectedPureSpecs, ...selectedStoreSpecs].map((s) =>
    join(outDir, s.replace(/\.ts$/, '.mjs')),
  );
  const result = spawnSync(process.execPath, ['--test', ...bundles], {
    stdio: 'inherit',
  });
  exitCode = result.status ?? 1;
} finally {
  rmSync(outDir, { recursive: true, force: true });
}
process.exitCode = exitCode;
