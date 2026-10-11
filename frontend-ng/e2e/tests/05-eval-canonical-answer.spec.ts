import { expect, test } from '@playwright/test';
import { appFetch, expectOk } from '../fixtures/api';
import { loginAsAlice } from '../fixtures/auth';

/**
 * E2.05 — E1.5 guardrail: canonical answer bypass.
 *
 * This is the smallest stable browser-backed test for the evaluation loop's
 * new deterministic remediation path. It uses the authenticated browser
 * context to create a canonical answer, then verifies `/chat/completion`
 * returns it without depending on the LLM/orchestrator.
 */
test.describe('E2.05 — Evaluation canonical answer', () => {
  test('creates a canonical answer and chat uses it deterministically', async ({ page }) => {
    await loginAsAlice(page);

    const suffix = Date.now().toString(36);
    const question = `E2 canonical SLA question ${suffix}?`;
    const answer = `E2 canonical answer ${suffix}: the SLA is 99.9%.`;

    const created = await expectOk<{ id: string; hit_count: number }>(
      page,
      '/api/v1/evaluation/canonical-answers',
      {
        method: 'POST',
        data: {
          question,
          answer,
          actor: 'playwright',
          similarity_threshold: 0.9,
        },
      },
    );
    expect(created.id).toBeTruthy();
    expect(created.hit_count).toBe(0);

    const chat = await expectOk<{
      content: string;
      canonical_answer_hit?: boolean;
      canonical_answer_id?: string;
    }>(page, '/api/v1/chat/completion', {
      method: 'POST',
      data: { query: question, stream: false },
    });

    expect(chat.canonical_answer_hit).toBe(true);
    expect(chat.canonical_answer_id).toBe(created.id);
    expect(chat.content).toBe(answer);

    const listed = await appFetch<{
      items?: Array<{ id: string; hit_count: number }>;
    }>(page, '/api/v1/evaluation/canonical-answers?limit=100');
    const row = (listed.body.items ?? []).find((item) => item.id === created.id);
    expect(row?.hit_count).toBeGreaterThanOrEqual(1);
  });
});

