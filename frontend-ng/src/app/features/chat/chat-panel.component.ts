import { ChangeDetectionStrategy, Component, input, signal, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { SseService, SseChunk } from '@app/core/sse.service';

interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  toolCalls?: unknown[];
}

@Component({
  selector: 'app-chat-panel',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule],
  template: `
    <!-- Messages -->
    <div class="space-y-4 max-h-[60vh] overflow-y-auto mb-4 pr-2">
      @for (msg of messages(); track $index) {
        <div [class]="msg.role === 'user' ? 'flex justify-end' : 'flex justify-start'">
          <div
            [class]="msg.role === 'user'
              ? 'max-w-[80%] bg-brand-500 text-white rounded-2xl rounded-br-sm px-4 py-2.5'
              : 'max-w-[80%] bg-gray-100 dark:bg-gray-800 text-gray-900 dark:text-gray-100 rounded-2xl rounded-bl-sm px-4 py-2.5'"
          >
            <div class="prose prose-sm dark:prose-invert max-w-none whitespace-pre-wrap">{{ msg.content }}</div>
          </div>
        </div>
      }

      @if (streaming()) {
        <div class="flex justify-start">
          <div class="max-w-[80%] bg-gray-100 dark:bg-gray-800 rounded-2xl rounded-bl-sm px-4 py-2.5">
            <div class="prose prose-sm dark:prose-invert max-w-none whitespace-pre-wrap">{{ streamBuffer() }}<span class="animate-pulse">▌</span></div>
          </div>
        </div>
      }
    </div>

    <!-- Input -->
    <form (ngSubmit)="send()" class="flex gap-2">
      <input
        [(ngModel)]="userInput"
        name="userInput"
        class="flex-1 px-4 py-2.5 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl focus:outline-none focus:ring-2 focus:ring-brand-400 text-sm"
        placeholder="Ask anything..."
        [disabled]="streaming()"
      />
      <button
        type="submit"
        [disabled]="streaming() || !userInput.trim()"
        class="px-4 py-2.5 bg-brand-500 hover:bg-brand-600 disabled:opacity-50 text-white rounded-xl transition text-sm font-medium"
      >
        Send
      </button>
    </form>
  `,
})
export class ChatPanelComponent {
  readonly systemId = input.required<string>();

  private readonly sse = inject(SseService);

  messages = signal<ChatMessage[]>([]);
  streaming = signal(false);
  streamBuffer = signal('');
  userInput = '';

  send(): void {
    const text = this.userInput.trim();
    if (!text) return;

    this.messages.update((msgs) => [...msgs, { role: 'user', content: text }]);
    this.userInput = '';
    this.streaming.set(true);
    this.streamBuffer.set('');

    let buffer = '';

    this.sse
      .stream('/api/v1/chat/stream', {
        message: text,
        agent_id: this.systemId(),
        session_id: null,
      })
      .subscribe({
        next: (chunk: SseChunk) => {
          if (chunk.type === 'text' && chunk.content) {
            buffer += chunk.content;
            this.streamBuffer.set(buffer);
          } else if (chunk.type === 'done') {
            this.messages.update((msgs) => [
              ...msgs,
              { role: 'assistant', content: buffer || '(no response)' },
            ]);
            this.streaming.set(false);
            this.streamBuffer.set('');
          } else if (chunk.type === 'error') {
            this.messages.update((msgs) => [
              ...msgs,
              { role: 'assistant', content: `Error: ${chunk.content}` },
            ]);
            this.streaming.set(false);
          }
        },
        error: () => {
          this.streaming.set(false);
        },
      });
  }
}
