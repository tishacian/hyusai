/**
 * Playground — the model answering, live, in front of the room.
 *
 * A model card can prove a fit was measured. Only a prediction proves the model
 * exists: change "contract type" from postpaid to month-to-month, press Predict,
 * and watch the churn probability jump. That is the argument this tab makes, and
 * everything in it is shaped by three decisions.
 *
 * **The form comes from the contract, not from a hand-written schema.** Fields,
 * their order, their ranges and a categorical column's actual values were all
 * computed by the fit and carried in the model's signature, so the form is
 * correct by construction and opens pre-filled with the training set's typical
 * row. Nobody demos a model by typing forty fields.
 *
 * **The gauge names its class.** A bare 0.87 means nothing; "P(churn = 1) = 87%"
 * is a claim. The contributions under it are measured counterfactuals — what the
 * answer would have been had this field held its typical value — and they say so,
 * because calling them feature attributions would be a Shapley claim this does
 * not compute.
 *
 * **The cURL is the request this form just made.** Same route, same body shape,
 * only the credential differs. A snippet that has to be edited before it works
 * is a snippet the audience does not believe — so the key panel sits next to it,
 * and the secret is substituted for real in the one response that carried it.
 */
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  Injector,
  afterNextRender,
  computed,
  inject,
  input,
  linkedSignal,
  output,
  signal,
  viewChild,
} from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { Router, RouterLink } from '@angular/router';
import { ZoomContextService } from '@app/core/zoom-context.service';
import { ToastrService } from 'ngx-toastr';
import { IconComponent } from '@app/shared/ui/icon.component';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import { I18nService } from '@app/core/i18n.service';
import { ModelsService } from './models.service';
import { ForecastPlaygroundComponent } from './forecast-playground.component';
import { forecastCurlSnippet, type ForecastRequestBody } from './forecast.vm';
import {
  GAUGE_ARC,
  GAUGE_HANDLE,
  contributionBars,
  curlSnippet,
  formatMetric,
  gaugeView,
  pinnedVersion,
  playgroundSeed,
  predictPayload,
  primaryScore,
  servingErrorKey,
  type ApiKeyRow,
  type ModelDto,
  type PredictAnswer,
  type ServingBlock,
  type SignatureField,
} from './models.vm';

/** Instances so far, for the one id each dial's gradient needs to itself. */
let gauges = 0;

/** The nearest ancestor that scrolls vertically — the cockpit's main column here. */
function scrollParentOf(el: HTMLElement): HTMLElement | null {
  if (typeof getComputedStyle !== 'function') return null;
  for (let node = el.parentElement; node; node = node.parentElement) {
    const { overflowY } = getComputedStyle(node);
    if ((overflowY === 'auto' || overflowY === 'scroll') && node.scrollHeight > node.clientHeight) {
      return node;
    }
  }
  return null;
}

@Component({
  selector: 'app-model-playground',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, IconComponent, EmptyStateComponent, ForecastPlaygroundComponent],
  template: `
    @if (serving(); as block) {
      @if (!block.callable) {
        <app-empty-state
          icon="zap-off"
          [title]="i18n.t('models.play.unavailable.title')"
          [description]="
            !block.enabled
              ? i18n.t('models.play.unavailable.disabled')
              : block.mode === 'forecast' && model().status === 'ready'
                ? i18n.t('models.play.unavailable.no_forecast_worker')
                : i18n.t('models.play.unavailable.untrained')
          "
        />
      } @else {
        @if (block.mode === 'forecast') {
          <ck-forecast-playground
            [model]="model()"
            [serving]="block"
            (requestChange)="forecastBody.set($event)"
          />
        } @else {
        <!-- The query container the split below measures. A wrapper rather than
             a media query on the viewport: what decides whether the form and the
             dial fit side by side is the width this tab actually has, and on a
             page with rails, a sidebar and a drawer that is not the window's. -->
        <div class="ck-play-shell">
        <div class="ck-play">
          <!-- ── The form: generated from the model's own contract ─────────── -->
          <section class="ck-panel">
            <div class="ck-section-label">{{ i18n.t('models.play.inputs') }}</div>
            <div class="ck-hint">{{ i18n.t('models.play.inputs.hint') }}</div>
            <div class="ck-fields mt-3">
              @for (field of block.fields; track field.name) {
                <label class="ck-field">
                  <span class="ck-field__name ck-mono">{{ field.name }}</span>
                  @if (field.choices?.length) {
                    <select
                      class="ck-input ck-mono"
                      [value]="valueOf(field.name)"
                      (change)="setValue(field.name, $any($event.target).value)"
                    >
                      @for (choice of field.choices; track choice) {
                        <option [value]="choice">{{ choice }}</option>
                      }
                    </select>
                  } @else if (field.kind === 'number') {
                    <span class="ck-number">
                      <input
                        type="number"
                        class="ck-input ck-mono"
                        [value]="valueOf(field.name)"
                        [attr.min]="field.min"
                        [attr.max]="field.max"
                        [attr.step]="stepOf(field)"
                        (input)="setValue(field.name, $any($event.target).value)"
                      />
                      @if (field.min !== null && field.max !== null) {
                        <input
                          type="range"
                          class="ck-range"
                          [value]="valueOf(field.name)"
                          [attr.min]="field.min"
                          [attr.max]="field.max"
                          [attr.step]="stepOf(field)"
                          [attr.aria-label]="field.name"
                          (input)="setValue(field.name, $any($event.target).value)"
                        />
                        <span class="ck-field__range ck-mono">
                          {{ rangeOf(field) }}
                        </span>
                      }
                    </span>
                  } @else {
                    <input
                      type="text"
                      class="ck-input ck-mono"
                      [value]="valueOf(field.name)"
                      (input)="setValue(field.name, $any($event.target).value)"
                    />
                  }
                </label>
              }
            </div>
            <div class="flex items-center gap-2 flex-wrap mt-3">
              <button
                type="button"
                class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium bg-sky-500 hover:bg-sky-600 text-white transition disabled:opacity-50"
                [disabled]="running()"
                (click)="predict()"
              >
                @if (running()) {
                  <app-icon name="loader-2" [size]="14" class="animate-spin" />
                } @else {
                  <app-icon name="zap" [size]="14" />
                }
                {{ i18n.t('models.play.run') }}
              </button>
              <button
                type="button"
                class="ck-btn-soft inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm"
                (click)="reset()"
              >
                <app-icon name="rotate-ccw" [size]="13" />
                {{ i18n.t('models.play.reset') }}
              </button>
              <span class="text-[10.5px] ck-mono" style="color: var(--ck-fg-4)">
                {{ servedLine(block) }}
              </span>
            </div>
            @if (refusal(); as message) {
              <div class="ck-error rounded px-3 py-2 mt-3 text-[12px]">{{ message }}</div>
            }
          </section>

          <!-- ── The answer ────────────────────────────────────────────────── -->
          <section class="ck-panel ck-panel--answer" #answerPanel>
            <div class="ck-section-label">{{ i18n.t('models.play.answer') }}</div>
            @if (!answer()) {
              <div class="ck-idle">
                <app-icon name="activity" [size]="20" />
                <span>{{ i18n.t('models.play.idle') }}</span>
              </div>
            } @else if (gauge(); as dial) {
              <div class="ck-gauge" [class.ck-gauge--flag]="dial.flagged">
                <svg viewBox="0 0 140 82" class="ck-gauge__svg" role="img"
                     [attr.aria-label]="i18n.t('models.play.answer')">
                  <defs>
                    <linearGradient [attr.id]="rampId" x1="0" y1="0" x2="1" y2="0">
                      <stop class="ck-gauge__stop ck-gauge__stop--from" offset="0" />
                      <stop class="ck-gauge__stop ck-gauge__stop--to" offset="1" />
                    </linearGradient>
                  </defs>
                  <path class="ck-gauge__track" d="M12,74 A56,56 0 0 1 128,74" />
                  <path
                    class="ck-gauge__fill"
                    d="M12,74 A56,56 0 0 1 128,74"
                    [attr.stroke]="'url(#' + rampId + ')'"
                    [attr.stroke-dasharray]="arc"
                    [attr.stroke-dashoffset]="arc - dial.dash"
                  />
                  <!-- The handle rides the tip of the fill, so the dial has a
                       read-off point rather than only a length. It is the same
                       path under a one-dot dash pattern, moved by the same
                       property as the fill: that is what keeps the two in step
                       through the sweep, which a rotation did not. Two passes,
                       wide then narrow, make the dot a ring. -->
                  <path
                    class="ck-gauge__hand"
                    d="M12,74 A56,56 0 0 1 128,74"
                    [attr.stroke-dasharray]="handleDash"
                    [attr.stroke-dashoffset]="dial.handle"
                  />
                  <path
                    class="ck-gauge__hand ck-gauge__hand--core"
                    d="M12,74 A56,56 0 0 1 128,74"
                    [attr.stroke-dasharray]="handleDash"
                    [attr.stroke-dashoffset]="dial.handle"
                  />
                </svg>
                <div class="ck-gauge__read">
                  <div class="ck-gauge__value" [class.ck-gauge__value--flag]="dial.flagged">
                    {{ dial.percent }}
                  </div>
                  <div class="ck-gauge__label ck-mono">
                    {{ i18n.t('models.play.probability', {
                      target: target(),
                      label: dial.label,
                    }) }}
                  </div>
                </div>
              </div>
              <div class="ck-verdict">
                <span
                  class="ck-badge ck-mono"
                  [class.ck-badge--flag]="dial.flagged"
                >{{ i18n.t('models.play.predicted', { label: dial.predicted }) }}</span>
                @for (entry of vector(); track entry.label) {
                  <span class="ck-chip ck-mono">{{ entry.label }} · {{ percent(entry.value) }}</span>
                }
              </div>
            } @else if (numeric() !== null) {
              <div class="ck-numeric">
                <div class="ck-numeric__value">{{ numericDisplay() }}</div>
                <div class="ck-numeric__label ck-mono">
                  {{ i18n.t('models.play.estimate', { target: target() }) }}
                </div>
                @if (position() !== null) {
                  <div class="ck-scaleline">
                    <div class="ck-scaleline__track">
                      <div class="ck-scaleline__mark" [style.left.%]="position()"></div>
                    </div>
                    <div class="ck-scaleline__ends ck-mono">
                      <span>{{ trainedRange().min }}</span>
                      <span>{{ i18n.t('models.play.range') }}</span>
                      <span>{{ trainedRange().max }}</span>
                    </div>
                  </div>
                }
              </div>
            }

            @if (contributions().length) {
              <div class="mt-4">
                <div class="ck-section-label">{{ i18n.t('models.play.why') }}</div>
                <div class="space-y-1.5">
                  @for (bar of contributions(); track bar.field) {
                    <div>
                      <div class="ck-bar__head ck-mono">
                        <span>{{ bar.field }} = {{ bar.value }}</span>
                        <span [style.color]="bar.raises ? 'var(--ck-signal-neg)' : 'var(--ck-signal-pos)'">
                          {{ bar.raises ? '+' : '−' }}{{ effect(bar.effect) }}
                        </span>
                      </div>
                      <div class="ck-bar">
                        <div
                          class="ck-bar__fill"
                          [class.ck-bar__fill--neg]="bar.raises"
                          [style.width.%]="bar.width"
                        ></div>
                      </div>
                      <div class="ck-bar__foot ck-mono">
                        {{ i18n.t('models.play.why.typical', { value: bar.typical }) }}
                      </div>
                    </div>
                  }
                </div>
                <div class="ck-hint">{{ i18n.t('models.play.why.hint') }}</div>
              </div>
            }
            @if (answer(); as done) {
              <div class="text-[10.5px] ck-mono mt-3" style="color: var(--ck-fg-4)">
                {{ i18n.t('models.play.timing', { ms: done.duration_ms }) }}
                @if (done.prediction_id) {
                  · {{ i18n.t('models.play.prediction_id', { id: done.prediction_id }) }}
                }
              </div>
            }
          </section>
        </div>
        </div>
        }

        <!-- ── The same call, for a machine ─────────────────────────────────── -->
        <section class="ck-panel mt-3">
          <div class="flex items-start justify-between gap-3 flex-wrap">
            <div>
              <div class="ck-section-label">{{ i18n.t('models.play.curl') }}</div>
              <div class="ck-hint" style="margin-top: 0">{{ i18n.t('models.play.curl.hint') }}</div>
            </div>
            <button
              type="button"
              class="ck-btn-soft inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded text-[11px]"
              (click)="copyCurl()"
            >
              <app-icon [name]="copied() ? 'check' : 'copy'" [size]="12" />
              {{ i18n.t(copied() ? 'models.play.copied' : 'models.play.copy') }}
            </button>
          </div>
          <pre class="ck-code mt-2">{{ curl() }}</pre>
        </section>

        <!-- ── Keys ─────────────────────────────────────────────────────────── -->
        <section class="ck-panel mt-3">
          <div class="ck-section-label">{{ i18n.t('models.keys.title') }}</div>
          <div class="ck-hint" style="margin-top: 0">{{ i18n.t('models.keys.hint') }}</div>
          @if (minted(); as fresh) {
            <div class="ck-minted mt-3">
              <div class="text-[11px] font-medium" style="color: var(--ck-signal-pos)">
                {{ i18n.t('models.keys.minted') }}
              </div>
              <div class="flex items-center gap-2 mt-1.5">
                <code class="ck-secret ck-mono">{{ fresh.secret }}</code>
                <button
                  type="button"
                  class="ck-btn-soft inline-flex items-center gap-1.5 px-2 py-1 rounded text-[11px]"
                  (click)="copySecret(fresh.secret ?? '')"
                >
                  <app-icon name="copy" [size]="11" /> {{ i18n.t('models.play.copy') }}
                </button>
              </div>
              <div class="ck-hint">{{ i18n.t('models.keys.minted.hint') }}</div>
            </div>
          }
          <div class="flex items-center gap-2 flex-wrap mt-3">
            <input
              type="text"
              class="ck-input ck-mono"
              style="max-width: 220px"
              [value]="keyName()"
              [placeholder]="i18n.t('models.keys.name.placeholder')"
              (input)="keyName.set($any($event.target).value)"
            />
            <button
              type="button"
              class="ck-btn-soft inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm"
              [disabled]="minting()"
              (click)="mint()"
            >
              <app-icon name="key" [size]="13" /> {{ i18n.t('models.keys.mint') }}
            </button>
          </div>
          @if (block.keys.length) {
            <div class="ck-surface rounded-md ck-h-scroll mt-3">
              <table class="w-full text-sm ck-schema">
                <thead>
                  <tr>
                    <th class="ck-schema__th">{{ i18n.t('models.keys.col.name') }}</th>
                    <th class="ck-schema__th">{{ i18n.t('models.keys.col.prefix') }}</th>
                    <th class="ck-schema__th">{{ i18n.t('models.keys.col.uses') }}</th>
                    <th class="ck-schema__th">{{ i18n.t('models.keys.col.state') }}</th>
                    <th class="ck-schema__th"></th>
                  </tr>
                </thead>
                <tbody>
                  @for (key of block.keys; track key.id) {
                    <tr class="ck-schema__tr">
                      <td class="ck-schema__td" style="color: var(--ck-fg-1)">{{ key.name }}</td>
                      <td class="ck-schema__td ck-mono">{{ key.prefix }}…</td>
                      <td class="ck-schema__td ck-mono">{{ usesLine(key) }}</td>
                      <td class="ck-schema__td">
                        <span class="ck-badge ck-mono" [class.ck-badge--warn]="key.revoked">
                          {{ i18n.t(key.revoked ? 'models.keys.revoked' : 'models.keys.live') }}
                        </span>
                      </td>
                      <td class="ck-schema__td" style="text-align: right">
                        @if (!key.revoked) {
                          <button
                            type="button"
                            class="ck-btn-soft inline-flex items-center gap-1 px-2 py-1 rounded text-[11px]"
                            (click)="revoke(key)"
                          >
                            <app-icon name="ban" [size]="11" /> {{ i18n.t('models.keys.revoke') }}
                          </button>
                        }
                      </td>
                    </tr>
                  }
                </tbody>
              </table>
            </div>
          }
        </section>

        <!-- ── Publish as a Skill ───────────────────────────────────────────── -->
        <!-- A forecast is published with its own skills (a horizon, not rows),
             which arrive with the Flow nodes that call them. -->
        @if (block.mode !== 'forecast') {
        <section class="ck-panel mt-3">
          <div class="ck-section-label">{{ i18n.t('models.publish.title') }}</div>
          <div class="ck-hint" style="margin-top: 0">{{ i18n.t('models.publish.hint') }}</div>
          @if (block.published_skill; as published) {
            <div class="ck-published mt-3">
              <div class="flex items-center gap-2 flex-wrap">
                <span class="ck-badge ck-badge--on ck-mono">
                  <app-icon name="badge-check" [size]="10" /> {{ i18n.t('models.publish.live') }}
                </span>
                <span class="text-[12px]" style="color: var(--ck-fg-1)">{{ published.name }}</span>
                <code class="text-[10.5px] ck-mono" style="color: var(--ck-fg-4)">{{ published.slug }}</code>
              </div>
              <div class="ck-chip ck-mono mt-2">{{ provenance() }}</div>
              <div class="flex items-center gap-2 flex-wrap mt-3">
                <a
                  [routerLink]="navigation.surfaceUrlTree('skills')"
                  [queryParams]="{ q: published.slug }"
                  class="ck-btn-soft inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm"
                >
                  <app-icon name="external-link" [size]="13" />
                  {{ i18n.t('models.publish.open') }}
                </a>
                <button
                  type="button"
                  class="ck-btn-soft inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm"
                  (click)="unpublish()"
                >
                  <app-icon name="undo-2" [size]="13" /> {{ i18n.t('models.publish.withdraw') }}
                </button>
              </div>
            </div>
          } @else {
            <button
              type="button"
              class="ck-btn-primary inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium mt-3"
              [disabled]="publishing()"
              (click)="publish()"
            >
              <app-icon name="share-2" [size]="14" /> {{ i18n.t('models.publish.action') }}
            </button>
          }
        </section>
        }
      }
    }
  `,
  styles: [
    `
      .ck-play-shell {
        container-type: inline-size;
      }
      .ck-play {
        display: grid;
        grid-template-columns: 1fr;
        gap: 12px;
      }
      /* Asked of the container, not of the window. A viewport query put the dial
         in a second column whenever the *screen* was wide enough, including when
         the tab itself was not — and a column that does not fit is a column the
         reader cannot get to, because the shell clips rather than scrolls. Where
         container queries are unsupported the panels stack, which is the safe
         direction: below the form is somewhere you can still scroll to. */
      @container (min-width: 900px) {
        .ck-play {
          grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
        }
        /* Pinned beside the form, under the page header: the dial is still on
           screen when the reader reaches the button at the bottom of the form,
           and it moves in place instead of somewhere they have to scroll back
           to. The offset is measured by the component (see the constructor). */
        .ck-play > .ck-panel--answer {
          position: sticky;
          top: var(--play-pin-top, 12px);
          align-self: start;
        }
      }
      :host {
        display: block;
        min-width: 0;
        max-width: 100%;
      }
      .ck-panel {
        padding: 14px 16px;
        border-radius: 6px;
        min-width: 0;
        background: var(--ck-bg-panel-hi, rgba(255, 255, 255, 0.02));
        box-shadow: inset 0 0 0 1px var(--ck-stroke-2, rgba(255, 255, 255, 0.06));
      }
      .ck-section-label {
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.1em;
        color: var(--ck-fg-4, #8891a0);
        margin-bottom: 7px;
      }
      .ck-hint {
        font-size: 10.5px;
        line-height: 1.45;
        color: var(--ck-fg-4, #8891a0);
        margin-top: 6px;
      }
      .ck-fields {
        display: grid;
        grid-template-columns: 1fr;
        gap: 9px;
      }
      @media (min-width: 620px) {
        .ck-fields {
          grid-template-columns: 1fr 1fr;
        }
      }
      .ck-field {
        display: block;
      }
      .ck-field__name {
        display: block;
        font-size: 10.5px;
        color: var(--ck-fg-3, #a6aebc);
        margin-bottom: 3px;
      }
      .ck-field__range {
        display: block;
        font-size: 9.5px;
        color: var(--ck-fg-5, #6b7280);
        margin-top: 2px;
      }
      .ck-input {
        width: 100%;
        padding: 6px 9px;
        font-size: 12px;
        border-radius: 4px;
        color: var(--ck-fg-1, #e6e9ef);
        background: var(--ck-bg-2, rgba(0, 0, 0, 0.25));
        border: 1px solid var(--ck-stroke-2, rgba(255, 255, 255, 0.09));
      }
      .ck-input:focus {
        outline: none;
        border-color: var(--ck-signal-cool, #7dd3fc);
      }
      .ck-range {
        width: 100%;
        margin-top: 4px;
        accent-color: var(--ck-signal-cool, #7dd3fc);
      }
      .ck-error {
        border: 1px solid rgba(239, 90, 111, 0.25);
        background: rgba(239, 90, 111, 0.06);
        color: var(--ck-signal-neg, #ef5a6f);
      }
      .ck-idle {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        gap: 6px;
        min-height: 150px;
        font-size: 11px;
        color: var(--ck-fg-5, #6b7280);
      }
      /* One custom property carries the dial's state to everything drawn from
         it — the ramp's two stops, the glow, the handle's ring — so a flagged
         answer recolours the whole instrument from one declaration. Named
         outside the --ck-* namespace on purpose: that prefix belongs to the
         design system, and this is one component's wiring. */
      .ck-gauge {
        --gauge-ink: var(--ck-signal-cool, #7dd3fc);
        display: flex;
        flex-direction: column;
        align-items: center;
      }
      .ck-gauge--flag {
        --gauge-ink: var(--ck-signal-neg, #ef5a6f);
      }
      .ck-gauge__svg {
        width: 200px;
        max-width: 100%;
        height: auto;
        overflow: visible;
      }
      .ck-gauge__track {
        fill: none;
        stroke: var(--ck-stroke-1, rgba(255, 255, 255, 0.07));
        stroke-width: 11;
        stroke-linecap: round;
      }
      /* The ramp runs the width of the track, not the width of the drawn part,
         so a given probability is always the same colour: the arc darkens as it
         climbs instead of restaining itself on every answer. */
      .ck-gauge__stop {
        stop-color: var(--gauge-ink);
      }
      .ck-gauge__stop--from {
        stop-opacity: 0.35;
      }
      .ck-gauge__stop--to {
        stop-opacity: 1;
      }
      /* No stroke declared here: the paint is a gradient this instance owns,
         bound as an attribute, and a declaration in this block would outrank
         it. */
      .ck-gauge__fill {
        fill: none;
        stroke-width: 11;
        stroke-linecap: round;
        filter: drop-shadow(
          0 0 7px color-mix(in srgb, var(--gauge-ink) 45%, transparent)
        );
        /* The movement IS the demo: a jump from 0.2 to 0.8 has to be seen. */
        transition:
          stroke-dashoffset 620ms cubic-bezier(0.22, 1, 0.36, 1),
          filter 300ms ease-out;
      }
      /* Same property, same duration, same curve as the fill: the handle is not
         chasing the stroke, it is the stroke's own dash pattern. */
      .ck-gauge__hand {
        fill: none;
        stroke: var(--gauge-ink);
        stroke-width: 13;
        stroke-linecap: round;
        filter: drop-shadow(
          0 0 6px color-mix(in srgb, var(--gauge-ink) 65%, transparent)
        );
        transition: stroke-dashoffset 620ms cubic-bezier(0.22, 1, 0.36, 1);
      }
      /* The narrower pass punches the ring's middle out. */
      .ck-gauge__hand--core {
        stroke: var(--ck-bg-panel, #0f141a);
        stroke-width: 7;
        filter: none;
      }
      /* A dial that arrives already at its answer says nothing about which way
         it travelled, but a reader who asked for less motion has asked for
         exactly that. */
      @media (prefers-reduced-motion: reduce) {
        .ck-gauge__fill,
        .ck-gauge__hand {
          transition: none;
        }
      }
      .ck-gauge__read {
        text-align: center;
        margin-top: -18px;
      }
      .ck-gauge__value {
        font-size: 30px;
        font-weight: 650;
        font-variant-numeric: tabular-nums;
        line-height: 1.1;
        color: var(--ck-fg-1, #e6e9ef);
      }
      .ck-gauge__value--flag {
        color: var(--ck-signal-neg, #ef5a6f);
      }
      .ck-gauge__label {
        font-size: 10.5px;
        color: var(--ck-fg-4, #8891a0);
        margin-top: 2px;
      }
      .ck-verdict {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 5px;
        flex-wrap: wrap;
        margin-top: 10px;
      }
      .ck-numeric {
        text-align: center;
        padding: 18px 0 6px;
      }
      .ck-numeric__value {
        font-size: 32px;
        font-weight: 650;
        font-variant-numeric: tabular-nums;
        color: var(--ck-fg-1, #e6e9ef);
      }
      .ck-numeric__label {
        font-size: 10.5px;
        color: var(--ck-fg-4, #8891a0);
        margin-top: 2px;
      }
      .ck-scaleline {
        margin-top: 14px;
      }
      .ck-scaleline__track {
        position: relative;
        height: 4px;
        border-radius: 2px;
        background: var(--ck-stroke-1, rgba(255, 255, 255, 0.07));
      }
      .ck-scaleline__mark {
        position: absolute;
        top: -3px;
        width: 10px;
        height: 10px;
        margin-left: -5px;
        border-radius: 50%;
        background: var(--ck-signal-cool, #7dd3fc);
        transition: left 520ms cubic-bezier(0.22, 1, 0.36, 1);
      }
      .ck-scaleline__ends {
        display: flex;
        justify-content: space-between;
        font-size: 9.5px;
        color: var(--ck-fg-5, #6b7280);
        margin-top: 5px;
      }
      .ck-bar__head {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        gap: 8px;
        font-size: 10.5px;
        color: var(--ck-fg-2, #c3c9d4);
        margin-bottom: 2px;
      }
      .ck-bar__foot {
        font-size: 9.5px;
        color: var(--ck-fg-5, #6b7280);
        margin-top: 2px;
      }
      .ck-bar {
        height: 6px;
        border-radius: 3px;
        background: var(--ck-stroke-1, rgba(255, 255, 255, 0.05));
        overflow: hidden;
      }
      .ck-bar__fill {
        height: 100%;
        border-radius: 3px;
        background: linear-gradient(
          90deg,
          rgba(52, 211, 153, 0.4) 0%,
          var(--ck-signal-pos, #34d399) 100%
        );
        transition: width 420ms cubic-bezier(0.22, 1, 0.36, 1);
      }
      .ck-bar__fill--neg {
        background: linear-gradient(
          90deg,
          rgba(239, 90, 111, 0.4) 0%,
          var(--ck-signal-neg, #ef5a6f) 100%
        );
      }
      /* The request body is one JSON line, and a line that cannot break is a
         width the whole page inherits: on a laptop it once carried the tab to
         2.8k pixels and the dial with it. Wrapping keeps the snippet exact and
         the page the width of the window. */
      .ck-code {
        font-size: 11px;
        line-height: 1.55;
        padding: 10px 12px;
        border-radius: 5px;
        min-width: 0;
        max-width: 100%;
        white-space: pre-wrap;
        overflow-wrap: anywhere;
        color: var(--ck-fg-2, #c3c9d4);
        background: var(--ck-bg-2, rgba(0, 0, 0, 0.28));
        box-shadow: inset 0 0 0 1px var(--ck-stroke-2, rgba(255, 255, 255, 0.07));
      }
      .ck-minted {
        padding: 10px 12px;
        border-radius: 5px;
        border: 1px solid rgba(52, 211, 153, 0.25);
        background: rgba(52, 211, 153, 0.05);
      }
      .ck-secret {
        font-size: 11px;
        padding: 4px 8px;
        border-radius: 4px;
        color: var(--ck-signal-pos, #34d399);
        background: rgba(0, 0, 0, 0.3);
        word-break: break-all;
      }
      .ck-published {
        padding: 10px 12px;
        border-radius: 5px;
        border: 1px solid rgba(125, 211, 252, 0.22);
        background: rgba(125, 211, 252, 0.04);
      }
      .ck-chip {
        display: inline-flex;
        align-items: center;
        font-size: 10.5px;
        padding: 2px 7px;
        border-radius: 4px;
        color: var(--ck-fg-3, #a6aebc);
        background: rgba(255, 255, 255, 0.04);
        box-shadow: inset 0 0 0 1px var(--ck-stroke-2, rgba(255, 255, 255, 0.07));
      }
      .ck-badge {
        display: inline-flex;
        align-items: center;
        gap: 3px;
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        padding: 2px 5px;
        border-radius: 3px;
        color: var(--ck-fg-4, #8891a0);
        background: rgba(255, 255, 255, 0.04);
        box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.06);
      }
      .ck-badge--on {
        color: var(--ck-signal-cool, #7dd3fc);
        background: rgba(125, 211, 252, 0.1);
      }
      .ck-badge--warn {
        color: var(--ck-signal-neg, #ef5a6f);
        background: rgba(239, 90, 111, 0.08);
      }
      .ck-badge--flag {
        color: var(--ck-signal-neg, #ef5a6f);
        background: rgba(239, 90, 111, 0.1);
        box-shadow: inset 0 0 0 1px rgba(239, 90, 111, 0.28);
      }
      .ck-schema {
        border-collapse: separate;
        border-spacing: 0;
      }
      .ck-schema__th {
        text-align: left;
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.1em;
        font-weight: 600;
        color: var(--ck-fg-4, #8891a0);
        padding: 8px 12px;
        background: var(--ck-bg-panel-hi, rgba(255, 255, 255, 0.03));
        border-bottom: 1px solid var(--ck-stroke-2, rgba(255, 255, 255, 0.08));
      }
      .ck-schema__td {
        padding: 7px 12px;
        border-bottom: 1px solid var(--ck-stroke-1, rgba(255, 255, 255, 0.03));
        color: var(--ck-fg-2, #c3c9d4);
        font-size: 12px;
      }
    `,
  ],
})
export class ModelPlaygroundComponent {
  readonly model = input.required<ModelDto>();
  /** The card's own read of the serving plane; this tab never fetches it. */
  readonly serving = input.required<ServingBlock>();
  /** A mint, a revoke or a publish: the card holds the new block. */
  readonly servingChange = output<ServingBlock>();
  /** Publishing changes the lineage, so the card reloads the row. */
  readonly changed = output<void>();

  readonly i18n = inject(I18nService);
  private readonly models = inject(ModelsService);
  private readonly toast = inject(ToastrService);
  private readonly router = inject(Router);
  protected readonly navigation = inject(ZoomContextService);
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  private readonly destroyRef = inject(DestroyRef);
  private readonly injector = inject(Injector);

  constructor() {
    // Side by side, the answer panel stays pinned while the reader works down
    // twenty fields — but pinned *below* the page's sticky object header, whose
    // height depends on the width its subtitle wraps at. The header is measured
    // rather than guessed and written to a custom property the stylesheet reads.
    afterNextRender(() => {
      const scroller = scrollParentOf(this.host.nativeElement);
      const header = scroller?.querySelector<HTMLElement>('ck-object-header header');
      if (!header) return;
      const pin = () => {
        this.host.nativeElement.style.setProperty(
          '--play-pin-top',
          `${Math.round(header.getBoundingClientRect().height) + 12}px`,
        );
      };
      pin();
      if (typeof ResizeObserver === 'undefined') return;
      const observer = new ResizeObserver(pin);
      observer.observe(header);
      this.destroyRef.onDestroy(() => observer.disconnect());
    });
  }

  protected readonly arc = GAUGE_ARC;

  /** One dot, then a gap the length of the whole track. */
  protected readonly handleDash = `${GAUGE_HANDLE} ${GAUGE_ARC}`;

  /**
   * The dial's gradient is referenced by `url(#id)`, and an id is document-wide.
   * Two Playgrounds on one page would otherwise both paint themselves with
   * whichever definition came first — including its flagged/unflagged colour.
   */
  protected readonly rampId = `ck-gauge-ramp-${++gauges}`;

  protected readonly answer = signal<PredictAnswer | null>(null);
  protected readonly refusal = signal<string>('');
  protected readonly running = signal(false);
  protected readonly minting = signal(false);
  /** The panel a finished prediction has to be able to show itself in. */
  private readonly answerPanel = viewChild<ElementRef<HTMLElement>>('answerPanel');
  protected readonly publishing = signal(false);
  protected readonly copied = signal(false);
  protected readonly minted = signal<ApiKeyRow | null>(null);
  protected readonly keyName = signal('');

  /**
   * The form, seeded from the contract and kept until the version changes.
   *
   * Keyed on the model id rather than on the block: the card re-reads the block
   * after every mint and after every poll, and a form that reset itself on an
   * unrelated refresh would throw away what the presenter just typed.
   */
  private readonly values = linkedSignal<string, Record<string, string>>({
    source: () => this.model().id,
    computation: () => playgroundSeed(this.serving().fields, this.model().input_example),
  });

  protected valueOf(name: string): string {
    return this.values()[name] ?? '';
  }

  protected setValue(name: string, value: string): void {
    this.values.update((current) => ({ ...current, [name]: value }));
  }

  /** A tenure in months steps by one; a rate between 0 and 1 cannot. */
  protected stepOf(field: SignatureField): number {
    const min = Number(field.min);
    const max = Number(field.max);
    if (!Number.isFinite(min) || !Number.isFinite(max)) return 1;
    const span = Math.abs(max - min);
    if (span >= 100) return 1;
    if (span >= 10) return 0.5;
    if (span >= 1) return 0.01;
    return 0.001;
  }

  protected rangeOf(field: SignatureField): string {
    return this.i18n.t('models.play.range.bounds', {
      min: this.number(field.min),
      max: this.number(field.max),
    });
  }

  protected reset(): void {
    this.values.set(playgroundSeed(this.serving().fields, this.model().input_example));
    this.answer.set(null);
    this.refusal.set('');
  }

  /**
   * The version this tab names when it calls, or `null` to let the alias pick.
   *
   * Read once and used by both the button and the snippet beside it, so the
   * command the audience copies reproduces the answer they just watched appear.
   */
  protected readonly pinned = computed(() =>
    pinnedVersion(this.serving(), this.model().version),
  );

  protected async predict(): Promise<void> {
    this.running.set(true);
    this.refusal.set('');
    try {
      const row = predictPayload(this.serving().fields, this.values());
      const pinned = this.pinned();
      this.answer.set(
        await this.models.predict(this.model().id, row, {
          explain: true,
          ...(pinned ? { version: pinned } : {}),
        }),
      );
      this.revealAnswer();
    } catch (error) {
      this.answer.set(null);
      this.refusal.set(this.sentence(error));
    } finally {
      this.running.set(false);
    }
  }

  /**
   * Bring the answer to where the person who pressed the button is looking.
   *
   * A button that appears to do nothing is worse than one that fails, and this
   * tab could produce exactly that: twenty fields and their sliders are taller
   * than a screen, so on a narrow layout the dial lands below the fold, and on a
   * layout whose second column does not fit it lands outside the box entirely.
   * The shell clips rather than scrolls, so in that second case there was no
   * gesture available to reach it at all.
   *
   * The move is a scroll and not a layout fix because it works even where
   * ``overflow: hidden`` denies the reader a scrollbar. It is not
   * ``scrollIntoView``: the model page keeps its object header sticky over the
   * top of the scroller, and "in view" for the layout engine is "under the
   * header" for the reader — the dial, which sits at the top of the panel, is
   * exactly the part that ended up covered. So the panel's top is aligned just
   * below whatever is sticky at the scroller's top, and nothing moves when it
   * already reads from there, which is the common case and must stay undisturbed.
   *
   * Measured after the answer has rendered, not when it arrives: the panel grows
   * from an idle placeholder to a dial and its bars, and a pinned panel that no
   * longer fits under the form's bottom edge is pushed up under the header. The
   * geometry that matters is the one the reader is about to see.
   */
  private revealAnswer(): void {
    afterNextRender(() => this.alignAnswer(), { injector: this.injector });
  }

  private alignAnswer(): void {
    const panel = this.answerPanel()?.nativeElement;
    if (!panel) return;
    let smooth = true;
    if (typeof window !== 'undefined' && typeof window.matchMedia === 'function') {
      smooth = !window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    }
    const behavior: ScrollBehavior = smooth ? 'smooth' : 'auto';
    const scroller = scrollParentOf(panel);
    if (!scroller) {
      panel.scrollIntoView?.({ block: 'nearest', inline: 'nearest', behavior });
      return;
    }
    const box = scroller.getBoundingClientRect();
    const sticky = scroller.querySelector<HTMLElement>('ck-object-header header');
    const readableTop = Math.max(box.top, sticky?.getBoundingClientRect().bottom ?? box.top);
    const rect = panel.getBoundingClientRect();
    const gap = 12;
    if (rect.top >= readableTop + gap && rect.bottom <= box.bottom) return;
    scroller.scrollBy({ top: rect.top - readableTop - gap, behavior });
  }

  protected readonly gauge = computed(() =>
    this.model().task === 'classification'
      ? gaugeView(
          this.answer()?.predictions?.[0],
          this.answer()?.positive_label,
          this.i18n.locale(),
        )
      : null,
  );

  protected readonly vector = computed(
    () => this.answer()?.predictions?.[0]?.probabilities ?? [],
  );

  protected readonly contributions = computed(() =>
    contributionBars(this.answer()?.predictions?.[0]?.contributions),
  );

  protected readonly numeric = computed(() => {
    if (this.model().task !== 'regression') return null;
    const value = this.answer()?.predictions?.[0]?.prediction;
    return typeof value === 'number' && Number.isFinite(value) ? value : null;
  });

  protected numericDisplay(): string {
    const value = this.numeric();
    return value === null ? '—' : this.number(value);
  }

  /** Where the estimate sits in the range the fit actually saw, 0–100. */
  protected position(): number | null {
    const value = this.numeric();
    const target = this.model().metrics?.target;
    const min = Number(target?.min);
    const max = Number(target?.max);
    if (value === null || !Number.isFinite(min) || !Number.isFinite(max) || max <= min) {
      return null;
    }
    return Math.round(Math.min(100, Math.max(0, ((value - min) / (max - min)) * 100)));
  }

  protected trainedRange(): { min: string; max: string } {
    const target = this.model().metrics?.target;
    return { min: this.number(target?.min), max: this.number(target?.max) };
  }

  protected target(): string {
    return this.model().target;
  }

  protected percent(value: number): string {
    return `${(value * 100).toLocaleString(this.i18n.locale(), {
      maximumFractionDigits: 1,
    })}%`;
  }

  protected effect(value: number): string {
    return Math.abs(value).toLocaleString(this.i18n.locale(), {
      maximumFractionDigits: 3,
    });
  }

  /**
   * Which version answered — the point of an alias is that it may not be this
   * one. Read before any answer exists it stands for which version *will*,
   * so a pin shows itself rather than the champion it deliberately bypasses.
   */
  protected servedLine(block: ServingBlock): string {
    const served = this.answer()?.served;
    const version = served?.version ?? this.pinned() ?? block.serving_version;
    if (!version) return '';
    return this.i18n.t('models.play.served', { version });
  }

  /** The forecast the Play tab is about to ask for, mirrored into the cURL. */
  protected readonly forecastBody = signal<ForecastRequestBody | null>(null);

  protected readonly curl = computed(() => {
    const block = this.serving();
    const live = block.keys.find((key) => !key.revoked);
    const forecast = this.forecastBody();
    if (block.mode === 'forecast') {
      return forecastCurlSnippet({
        origin: this.origin(),
        endpoint: block.endpoint,
        header: block.key_header,
        body: forecast ?? { params: { horizon: 24, interval_level: 0.8 }, inputs: [] },
        secret: this.minted()?.secret ?? null,
        prefix: live?.prefix ?? null,
      });
    }
    return curlSnippet({
      origin: this.origin(),
      endpoint: block.endpoint,
      header: block.key_header,
      row: predictPayload(block.fields, this.values()),
      secret: this.minted()?.secret ?? null,
      prefix: live?.prefix ?? null,
      version: this.pinned(),
    });
  });

  protected usesLine(key: ApiKeyRow): string {
    if (!key.use_count) return '—';
    return this.i18n.t('models.keys.uses', { count: key.use_count });
  }

  protected async mint(): Promise<void> {
    this.minting.set(true);
    try {
      const response = await this.models.mintKey(
        this.model().id,
        this.keyName().trim() || this.i18n.t('models.keys.name.default'),
      );
      this.minted.set(response.key);
      this.servingChange.emit(response.serving);
      this.keyName.set('');
      this.toast.success(this.i18n.t('models.keys.minted'));
    } catch (error) {
      this.toast.error(this.sentence(error));
    } finally {
      this.minting.set(false);
    }
  }

  protected async revoke(key: ApiKeyRow): Promise<void> {
    try {
      this.servingChange.emit(await this.models.revokeKey(this.model().id, key.id));
      if (this.minted()?.id === key.id) this.minted.set(null);
      this.toast.info(this.i18n.t('models.keys.revoked.toast', { name: key.name }));
    } catch (error) {
      this.toast.error(this.sentence(error));
    }
  }

  protected async publish(): Promise<void> {
    this.publishing.set(true);
    try {
      const response = await this.models.publish(this.model().id);
      this.servingChange.emit(response.serving);
      // The toast is the deep link, not just an announcement: the point of
      // publishing is that the model is now a Skill in the catalogue, and the
      // shortest path to seeing that is a tap on the thing that said so.
      const slug = response.skill.slug;
      this.toast
        .success(
          this.i18n.t('models.publish.done', { name: response.skill.name }),
          undefined,
          { tapToDismiss: false, closeButton: true },
        )
        .onTap.subscribe(() => {
          const tree = this.router.parseUrl(this.navigation.surfaceUrl('skills'));
          tree.queryParams = { ...tree.queryParams, q: slug };
          void this.router.navigateByUrl(tree);
        });
      this.changed.emit();
    } catch (error) {
      this.toast.error(this.sentence(error));
    } finally {
      this.publishing.set(false);
    }
  }

  protected async unpublish(): Promise<void> {
    try {
      const response = await this.models.unpublish(this.model().id);
      this.servingChange.emit(response.serving);
      this.toast.info(this.i18n.t('models.publish.withdrawn'));
      this.changed.emit();
    } catch (error) {
      this.toast.error(this.sentence(error));
    }
  }

  /** The chip the published Skill carries: which model, which version, how good. */
  protected provenance(): string {
    const row = this.model();
    const score = primaryScore(row);
    const evidence = score
      ? `${this.i18n.t('models.metric.' + score.key)} ${formatMetric(
          score.key,
          score.value,
          this.i18n.locale(),
        )}`
      : '';
    return this.i18n.t('models.publish.provenance', {
      name: row.name,
      version: this.serving().serving_version ?? row.version,
      evidence,
    });
  }

  protected copyCurl(): void {
    this.copy(this.curl());
  }

  protected copySecret(secret: string): void {
    this.copy(secret);
  }

  private copy(text: string): void {
    navigator.clipboard?.writeText(text).then(() => {
      this.copied.set(true);
      setTimeout(() => this.copied.set(false), 1500);
    });
  }

  private origin(): string {
    return typeof window === 'undefined' ? '' : window.location.origin;
  }

  /** A coded refusal in the product's words, or the server's own sentence. */
  private sentence(error: unknown): string {
    const detail =
      error instanceof HttpErrorResponse
        ? (error.error?.detail ?? error.error)
        : null;
    const code = typeof detail === 'object' && detail ? String(detail.code ?? '') : '';
    const key = servingErrorKey(code);
    if (key) return this.i18n.t(key);
    const message =
      typeof detail === 'object' && detail ? String(detail.message ?? '') : '';
    return message || this.i18n.t('models.play.failed');
  }

  private number(value: unknown): string {
    const raw = Number(value);
    if (!Number.isFinite(raw)) return '—';
    return raw.toLocaleString(this.i18n.locale(), { maximumFractionDigits: 3 });
  }
}
