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
export type CodeEditorLanguage = 'python' | 'sql' | 'yaml' | 'text';

/**
 * Tables the SQL editor completes against: view name → column names.
 *
 * Passed by the SQL workshop from the source catalog the server resolved, so
 * `input.` offers the real columns of the real dataset instead of a keyword
 * list. Reconfigured in place when the sources change (see `languageSlot`).
 */
export type SqlCompletionSchema = Record<string, string[]>;

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

/** A CodeMirror `Compartment`, narrowed to what this component calls. */
interface LanguageSlot {
  of(extension: unknown): unknown;
  reconfigure(extension: unknown): unknown;
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
          (keydown)="onFallbackKeydown($event)"
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
  /** SQL only: the tables and columns completion should offer. */
  readonly sqlSchema = input<SqlCompletionSchema | null>(null);
  readonly valueChange = output<string>();
  /** Mod-Enter: the "run this" gesture every query editor is expected to have. */
  readonly submit = output<void>();

  /** True once the CodeMirror chunk mounted; the textarea serves until then. */
  readonly editorReady = signal(false);

  private handle: CodeMirrorHandle | null = null;
  /** Last doc text this component pushed out or received; the loop breaker. */
  private lastKnownValue = '';
  private destroyed = false;
  /** Compartment holding the language extension, so a schema change — or a
   *  switch between two files of one project — is a reconfigure rather than a
   *  remount (which would lose the cursor and the undo history). */
  private languageSlot: LanguageSlot | null = null;
  private appliedLanguage = '';

  constructor() {
    this.lastKnownValue = this.value();
    afterNextRender(() => void this.mountEditor());
    // Two things move under the editor after the first paint: the resolved
    // sources (so SQL completion gains real columns) and the active file of a
    // multi-file project (so `schema.yml` highlights as YAML, not as SQL).
    // Both are the same reconfigure.
    effect(() => {
      const signature = this.languageSignature();
      if (!this.handle || !this.languageSlot) return;
      if (signature === this.appliedLanguage) return;
      this.appliedLanguage = signature;
      void this.reconfigureLanguage();
    });
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

  /** The run gesture must work before the editor chunk lands, too. */
  onFallbackKeydown(event: KeyboardEvent): void {
    if (event.key !== 'Enter' || !(event.metaKey || event.ctrlKey)) return;
    event.preventDefault();
    this.submit.emit();
  }

  private async mountEditor(): Promise<void> {
    if (typeof window === 'undefined') return;
    try {
      const [
        { basicSetup },
        { EditorView, keymap },
        { Compartment, EditorState },
        { indentWithTab },
      ] = await Promise.all([
        import('codemirror'),
        import('@codemirror/view'),
        import('@codemirror/state'),
        import('@codemirror/commands'),
      ]);
      if (this.destroyed) return;

      const extensions: unknown[] = [
        basicSetup,
        keymap.of([
          indentWithTab,
          {
            key: 'Mod-Enter',
            run: () => {
              this.submit.emit();
              return true;
            },
          },
        ]),
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
      const slot = new Compartment() as unknown as LanguageSlot;
      this.languageSlot = slot;
      this.appliedLanguage = this.languageSignature();
      extensions.push(slot.of((await this.languageExtension()) ?? []));
      if (this.destroyed) return;

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

  /** What the active highlighting depends on: the language and, for SQL, the
   *  tables completion offers. */
  private languageSignature(): string {
    const language = this.language();
    if (language !== 'sql') return language;
    return `sql:${JSON.stringify(this.sqlSchema() ?? {})}`;
  }

  /** The language extension for the current inputs, or `null` for plain text.
   *
   * Every grammar is a lazy import of its own: a workspace that only ever
   * writes SQL never fetches the Python or YAML chunk. */
  private async languageExtension(): Promise<unknown | null> {
    switch (this.language()) {
      case 'python': {
        const { python } = await import('@codemirror/lang-python');
        return python();
      }
      case 'yaml': {
        const { yaml } = await import('@codemirror/lang-yaml');
        return yaml();
      }
      case 'sql': {
        const { PostgreSQL, sql } = await import('@codemirror/lang-sql');
        const schema = this.sqlSchema();
        // `lang-sql` takes the schema as configuration, so a schema change is
        // a language reconfigure; the compartment is what makes that cheap.
        return sql({
          dialect: PostgreSQL,
          upperCaseKeywords: true,
          schema: schema ?? {},
          defaultTable: schema && schema['input'] ? 'input' : undefined,
        });
      }
      default:
        return null;
    }
  }

  private async reconfigureLanguage(): Promise<void> {
    const extension = await this.languageExtension();
    if (this.destroyed || !this.handle || !this.languageSlot) return;
    this.handle.view.dispatch({
      effects: this.languageSlot.reconfigure(extension ?? []),
    });
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
