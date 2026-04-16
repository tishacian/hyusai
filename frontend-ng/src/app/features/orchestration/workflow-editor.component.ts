import { Component, ElementRef, viewChild, AfterViewInit, DestroyRef, inject } from '@angular/core';

@Component({
  selector: 'app-workflow-editor',
  standalone: true,
  template: `
    <h1 class="text-2xl font-bold text-gray-900 dark:text-white mb-4">Orchestration</h1>
    @defer (on viewport) {
      <div class="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 overflow-hidden" style="height: 600px">
        <div #drawflowContainer class="w-full h-full"></div>
      </div>
    } @placeholder {
      <div class="h-96 flex items-center justify-center text-gray-400">Loading workflow editor...</div>
    }
  `,
})
export class WorkflowEditorComponent implements AfterViewInit {
  private readonly destroyRef = inject(DestroyRef);
  private readonly container = viewChild<ElementRef>('drawflowContainer');
  private editor: any;

  async ngAfterViewInit(): Promise<void> {
    const el = this.container()?.nativeElement;
    if (!el) return;

    try {
      const Drawflow = (await import('drawflow')).default;
      this.editor = new Drawflow(el);
      this.editor.start();
      this.editor.addNode('start', 0, 1, 150, 100, 'start', {}, 'Start');
      this.editor.addNode('agent', 1, 1, 400, 100, 'agent', {}, 'Agent');
    } catch {
      el.innerHTML = '<div class="p-8 text-center text-gray-400">Drawflow not available</div>';
    }

    this.destroyRef.onDestroy(() => {
      this.editor?.clear?.();
    });
  }
}
