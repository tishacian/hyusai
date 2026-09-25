import { Routes } from '@angular/router';

export const conversationsRoutes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./conversations.component').then((m) => m.ConversationsComponent),
  },
  {
    path: ':conversationId',
    loadComponent: () =>
      import('./conversation-page.component').then((m) => m.ConversationPageComponent),
  },
];
