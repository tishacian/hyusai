/**
 * `<ck-code-editor>` — the shared code-editing surface.
 *
 * CodeMirror 6 is the first editor dependency of this repo, so it is loaded
 * as a DYNAMIC import: the main bundle only carries this small shell, and the
 * editor chunk is fetched the first time a code editor actually renders.
 * Until the chunk arrives (or if it never does), a plain `<textarea>` serves
 * the exact same contract — value in, `valueChange` out — so the surface is
 * usable from the first frame and degrades to what the repo had before.
 *
 * Theming maps the `--ck-*` design tokens onto CodeMirror's theme extension
 * rather than importing a packaged theme, so the editor sits in the cockpit
 * chrome instead of next to it.
 */
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  afterNextRender,
  effect,
  inject,
  input,
  output,
  signal,
  viewChild,
} from '@angular/core';

/** Languages the editor knows how to highlight. Anything else stays plain. */
export type CodeEditorLanguage = 'python' | 'text';

/** The slice of the CodeMirror API this component uses (typed loosely on
 * purpose: the real types live in the lazy chunk). */
interface CodeMirrorHandle {
  view: {
    destroy(): void;
    state: { doc: { toString(): string } };
    dispatch(spec: unknown): void;
    contentDOM: HTMLElement;
  };
}

@Component({
  selector: 'ck-code-editor',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  styles: [
    `
      :host {
        display: block;
        min-height: 0;
      }
      .ck-code-editor {
        height: 100%;
        min-height: inherit;
        display: flex;
        flex-direction: column;
        border: 1px solid var(--ck-stroke-2, rgba(255, 255, 255, 0.08));
        border-radius: var(--ck-radius-sm, 4px);
        background: var(--ck-bg-inset, #0a0d11);
        overflow: hidden;
      }
      .ck-code-editor:focus-within {
        border-color: var(--ck-signal-cool, #7dd3fc);
        box-shadow: 0 0 0 1px var(--ck-signal-cool, #7dd3fc);
      }
      .ck-code-editor__host {
        flex: 1 1 auto;
        min-height: 0;
        overflow: auto;
      }
      .ck-code-editor__fallback {
        flex: 1 1 auto;
        min-height: inherit;
        width: 100%;
        box-sizing: border-box;
        resize: none;
        border: 0;
        outline: none;
        padding: 10px 12px;
        color: var(--ck-fg-1, #f2f5f8);
        background: transparent;
        font-family: var(--ck-font-mono, monospace);
        font-size: 12.5px;
        line-height: 1.55;
        tab-size: 4;
      }
      .ck-code-editor__fallback::placeholder {
        color: var(--ck-fg-4, #5a6270);
      }
    `,
  ],
  template: `
    <div class="ck-code-editor">
      @if (!editorReady()) {
        <textarea
          class="ck-code-editor__fallback"
          [value]="value()"
          [readOnly]="readOnly()"
          [attr.aria-label]="ariaLabel() || null"
          [attr.placeholder]="placeholder() || null"
          spellcheck="false"
          autocapitalize="off"
          autocomplete="off"
          (input)="onFallbackInput($event)"
        ></textarea>
      }
      <div
        class="ck-code-editor__host"
        #cmHost
        [hidden]="!editorReady()"
      ></div>
    </div>
  `,
})
export class CodeEditorComponent {
  private readonly destroyRef = inject(DestroyRef);
  private readonly host = viewChild.required<ElementRef<HTMLDivElement>>('cmHost');

  readonly value = input('');
  readonly language = input<CodeEditorLanguage>('text');
  readonly readOnly = input(false);
  readonly placeholder = input('');
  readonly ariaLabel = input('');
  readonly valueChange = output<string>();

  /** True once the CodeMirror chunk mounted; the textarea serves until then. */
  readonly editorReady = signal(false);

  private handle: CodeMirrorHandle | null = null;
  /** Last doc text this component pushed out or received; the loop breaker. */
  private lastKnownValue = '';
  private destroyed = false;

  constructor() {
    this.lastKnownValue = this.value();
    afterNextRender(() => void this.mountEditor());
    // External rewrites (undo, node switch, requirements import) land in the
    // editor without echoing back the edits the editor itself just emitted.
    effect(() => {
      const next = this.value();
      if (!this.handle || next === this.lastKnownValue) return;
      this.lastKnownValue = next;
      const current = this.handle.view.state.doc.toString();
      if (current === next) return;
      this.handle.view.dispatch({
        changes: { from: 0, to: current.length, insert: next },
      });
    });
    this.destroyRef.onDestroy(() => {
      this.destroyed = true;
      this.handle?.view.destroy();
      this.handle = null;
    });
  }

  onFallbackInput(event: Event): void {
    const next = (event.target as HTMLTextAreaElement).value;
    this.lastKnownValue = next;
    this.valueChange.emit(next);
  }

  private async mountEditor(): Promise<void> {
    if (typeof window === 'undefined') return;
    try {
      const [{ basicSetup }, { EditorView, keymap }, { EditorState }, { indentWithTab }] =
        await Promise.all([
          import('codemirror'),
          import('@codemirror/view'),
          import('@codemirror/state'),
          import('@codemirror/commands'),
        ]);
      if (this.destroyed) return;

      const extensions: unknown[] = [
        basicSetup,
        keymap.of([indentWithTab]),
        this.ckTheme(EditorView),
        EditorView.updateListener.of((update: { docChanged: boolean }) => {
          if (!update.docChanged || !this.handle) return;
          const text = this.handle.view.state.doc.toString();
          if (text === this.lastKnownValue) return;
          this.lastKnownValue = text;
          this.valueChange.emit(text);
        }),
      ];
      if (this.readOnly()) {
        extensions.push(EditorState.readOnly.of(true), EditorView.editable.of(false));
      }
      if (this.language() === 'python') {
        const { python } = await import('@codemirror/lang-python');
        if (this.destroyed) return;
        extensions.push(python());
      }

      const view = new EditorView({
        doc: this.value(),
        parent: this.host().nativeElement,
        extensions: extensions as [],
      });
      this.lastKnownValue = view.state.doc.toString();
      this.handle = { view };
      if (this.ariaLabel()) {
        view.contentDOM.setAttribute('aria-label', this.ariaLabel());
      }
      this.editorReady.set(true);
    } catch {
      // Chunk unavailable (offline build, blocked CDN…): the textarea stays.
    }
  }

  /** Design-token theme: the editor inherits the cockpit, not the reverse. */
  private ckTheme(EditorView: {
    theme(spec: Record<string, Record<string, string>>, options?: { dark: boolean }): unknown;
  }): unknown {
    return EditorView.theme(
      {
        '&': {
          height: '100%',
          fontSize: '12.5px',
          backgroundColor: 'transparent',
          color: 'var(--ck-fg-1, #f2f5f8)',
        },
        '.cm-content': {
          fontFamily: 'var(--ck-font-mono, monospace)',
          caretColor: 'var(--ck-signal-cool, #7dd3fc)',
          padding: '10px 0',
        },
        '.cm-cursor, .cm-dropCursor': {
          borderLeftColor: 'var(--ck-signal-cool, #7dd3fc)',
        },
        '&.cm-focused': { outline: 'none' },
        '.cm-scroller': { lineHeight: '1.55' },
        '.cm-gutters': {
          backgroundColor: 'var(--ck-bg-panel, #0c1014)',
          color: 'var(--ck-fg-4, #5a6270)',
          border: 'none',
          borderRight: '1px solid var(--ck-stroke-2, rgba(255, 255, 255, 0.08))',
        },
        '.cm-activeLine': {
          backgroundColor: 'color-mix(in srgb, var(--ck-signal-cool, #7dd3fc) 6%, transparent)',
        },
        '.cm-activeLineGutter': {
          backgroundColor: 'color-mix(in srgb, var(--ck-signal-cool, #7dd3fc) 10%, transparent)',
          color: 'var(--ck-fg-2, #c8cdd4)',
        },
        '.cm-selectionBackground, &.cm-focused .cm-selectionBackground': {
          backgroundColor: 'color-mix(in srgb, var(--ck-signal-cool, #7dd3fc) 22%, transparent)',
        },
        '.cm-matchingBracket': {
          backgroundColor: 'color-mix(in srgb, var(--ck-signal-cool, #7dd3fc) 18%, transparent)',
          outline: 'none',
        },
        '.cm-tooltip': {
          backgroundColor: 'var(--ck-bg-panel, #0c1014)',
          border: '1px solid var(--ck-stroke-2, rgba(255, 255, 255, 0.08))',
          color: 'var(--ck-fg-1, #f2f5f8)',
        },
      },
      { dark: true },
    );
  }
}
