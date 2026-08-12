import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { catchError, of } from 'rxjs';
import { ApiService } from '@app/core/api.service';
import { I18nService } from '@app/core/i18n.service';
import {
  SocialSnapshot,
  SocialTweet,
  VpSocialPulseDrawerComponent,
} from './vp-social-pulse-drawer.component';

type BucketFilter = 'all' | 'officiel' | 'citoyen' | 'rumeur';
type SentimentFilter = 'all' | 'positive' | 'neutral' | 'negative';
type SortKey = 'engagement' | 'time';

@Component({
  selector: 'app-social-pulse-page',
  standalone: true,
  imports: [CommonModule, RouterLink, FormsModule, VpSocialPulseDrawerComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="social-pulse-page" [attr.aria-label]="i18n.t('mission.social.title')">
      <header class="spp-topbar">
        <a routerLink="/hypervisor/mission-room/cockpit" class="spp-back">
          <span>← {{ i18n.t('mission.room.title') }}</span>
        </a>
        <div>
          <span class="eyebrow">{{ i18n.t('mission.social.eyebrow') }}</span>
          <h1>{{ i18n.t('mission.social.title') }} · Abidjan</h1>
        </div>
        <button type="button" class="spp-export" (click)="exportCsv()">
          {{ i18n.t('mission.social.export') }}
        </button>
      </header>

      <div class="spp-toolbar">
        <label>
          <span>{{ i18n.t('mission.social.filter.scope') }}</span>
          <select [(ngModel)]="bucketFilter">
            <option value="all">{{ i18n.t('common.all') }}</option>
            <option value="officiel">{{ i18n.t('mission.social.scope.official') }}</option>
            <option value="citoyen">{{ i18n.t('mission.social.scope.citizen') }}</option>
            <option value="rumeur">{{ i18n.t('mission.social.scope.rumor') }}</option>
          </select>
        </label>
        <label>
          <span>{{ i18n.t('mission.social.filter.sentiment') }}</span>
          <select [(ngModel)]="sentimentFilter">
            <option value="all">{{ i18n.t('common.all') }}</option>
            <option value="positive">{{ i18n.t('mission.social.sentiment.positive') }}</option>
            <option value="neutral">{{ i18n.t('mission.social.sentiment.neutral') }}</option>
            <option value="negative">{{ i18n.t('mission.social.sentiment.negative') }}</option>
          </select>
        </label>
        <label>
          <span>{{ i18n.t('mission.social.filter.period') }}</span>
          <select [(ngModel)]="periodFilter">
            <option value="all">{{ i18n.t('mission.social.period.all') }}</option>
            <option value="morning">{{ i18n.t('mission.social.period.morning') }}</option>
            <option value="midday">{{ i18n.t('mission.social.period.midday') }}</option>
          </select>
        </label>
        <label>
          <span>{{ i18n.t('mission.social.filter.sort') }}</span>
          <select [(ngModel)]="sortKey">
            <option value="engagement">{{ i18n.t('mission.social.sort.engagement') }}</option>
            <option value="time">{{ i18n.t('mission.social.sort.time') }}</option>
          </select>
        </label>
      </div>

      <app-vp-social-pulse-drawer
        [embedded]="true"
        [open]="true"
        [snapshot]="filteredSnapshot()"
      />
    </section>
  `,
  styles: [
    `
      :host { display: block; min-height: 100vh; background: #070d14; }
      .social-pulse-page { max-width: 960px; margin: 0 auto; padding: 20px 24px 40px; }
      .spp-topbar {
        display: grid;
        grid-template-columns: auto 1fr auto;
        gap: 16px;
        align-items: center;
        margin-bottom: 16px;
      }
      .spp-back {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        color: var(--mission-text-secondary);
        text-decoration: none;
      }
      .spp-topbar h1 { margin: 4px 0 0; font-size: 22px; }
      .spp-export {
        padding: 10px 14px;
        border: 1px solid var(--mission-border);
        border-radius: 8px;
        background: rgba(15, 111, 63, 0.18);
        color: var(--mission-text-primary);
        cursor: pointer;
      }
      .spp-toolbar {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 12px;
        margin-bottom: 16px;
      }
      .spp-toolbar label {
        display: grid;
        gap: 4px;
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: var(--mission-text-secondary);
      }
      .spp-toolbar select {
        padding: 8px 10px;
        border-radius: 8px;
        border: 1px solid var(--mission-border);
        background: rgba(8, 14, 20, 0.8);
        color: var(--mission-text-primary);
      }
      .eyebrow {
        display: block;
        font-size: 11px;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: var(--mission-text-secondary);
      }
      @media (max-width: 800px) {
        .spp-toolbar { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        .spp-topbar { grid-template-columns: 1fr; }
      }
    `,
  ],
})
export class SocialPulsePageComponent implements OnInit {
  private readonly api = inject(ApiService);
  readonly i18n = inject(I18nService);

  readonly rawSnapshot = signal<SocialSnapshot | null>(null);
  bucketFilter: BucketFilter = 'all';
  sentimentFilter: SentimentFilter = 'all';
  periodFilter: 'all' | 'morning' | 'midday' = 'all';
  sortKey: SortKey = 'engagement';

  readonly filteredSnapshot = computed(() => {
    const base = this.rawSnapshot();
    if (!base) return null;
    let tweets = [...(base.tweets || [])];
    if (this.bucketFilter !== 'all') {
      tweets = tweets.filter((tweet) => tweet.kind === this.bucketFilter);
    }
    if (this.sentimentFilter !== 'all') {
      tweets = tweets.filter((tweet) =>
        (tweet.sentiment || 'neutral').toLowerCase().includes(this.sentimentFilter),
      );
    }
    if (this.periodFilter !== 'all') {
      tweets = tweets.filter((tweet) => this.matchesPeriod(tweet, this.periodFilter as 'morning' | 'midday'));
    }
    tweets.sort((a, b) => {
      if (this.sortKey === 'time') {
        return String(b.posted_at || '').localeCompare(String(a.posted_at || ''));
      }
      return (Number(b.engagement) || 0) - (Number(a.engagement) || 0);
    });
    return { ...base, tweets };
  });

  ngOnInit(): void {
    this.api
      .get<{ social_snapshot?: SocialSnapshot }>('/mission-room/cockpit')
      .pipe(catchError(() => of({ social_snapshot: null })))
      .subscribe((payload) => {
        this.rawSnapshot.set(payload.social_snapshot || null);
      });
  }

  exportCsv(): void {
    const tweets = this.filteredSnapshot()?.tweets || [];
    const lines = [
      'id,kind,handle,sentiment,engagement,text,advisory_only',
      ...tweets.map((tweet) =>
        [
          tweet.id || '',
          tweet.kind || '',
          tweet.handle || '',
          tweet.sentiment || '',
          String(tweet.engagement || 0),
          `"${(tweet.text || '').replace(/"/g, '""')}"`,
          'true',
        ].join(','),
      ),
    ];
    const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = 'pulsation-sociale-abidjan-consultatif.csv';
    anchor.click();
    URL.revokeObjectURL(url);
  }

  private matchesPeriod(tweet: SocialTweet, period: 'morning' | 'midday'): boolean {
    const value = tweet.posted_at;
    if (!value) return true;
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return true;
    const hour = date.getHours();
    if (period === 'morning') return hour >= 6 && hour < 12;
    return hour >= 12 && hour < 15;
  }
}
