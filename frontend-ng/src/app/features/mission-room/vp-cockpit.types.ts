export type VpDrillDownView = 'briefing' | 'presse' | 'decisions' | 'agenda' | 'strategie';

export interface VpDrillDown {
  view: VpDrillDownView;
  route?: string;
  anchor?: string;
}

export interface VpStatusBarItem {
  key: string;
  label: string;
  value: string;
  detail?: string;
  tone?: string;
}

export interface VpArbitrationCard {
  id: string;
  rank: number;
  domain: string;
  domain_label: string;
  title: string;
  summary: string;
  status: string;
  status_label: string;
  deadline: string;
  tone: string;
  cta_label: string;
  cta_route?: string;
  drill_down: VpDrillDown;
  draft_ready?: boolean;
  aya_prepared?: boolean;
}

export interface VpIntelligenceFeed {
  key: string;
  label: string;
  subtitle: string;
  metric: string;
  confidence: number;
  freshness_at?: string;
  tone?: string;
}

export interface VpZoneScore {
  name: string;
  score: number;
  trend?: string;
  tone?: string;
}

export interface VpGeoPreview {
  camera?: { center?: number[]; zoom?: number; bounds?: number[][] };
  active_layers?: string[];
  zone_scores: VpZoneScore[];
  top_zone_id?: string;
}

export interface VpPressPreviewItem {
  id: string;
  title: string;
  source: string;
  risk: string;
  risk_label?: string;
  summary?: string;
  tone?: string;
  drill_down?: VpDrillDown;
}

export interface VpAgendaTimelineEvent {
  id?: string;
  time: string;
  end_time?: string;
  title: string;
  location?: string;
  tone?: string;
  is_now?: boolean;
  countdown?: string;
  status?: string;
}

export interface VpAgendaTimeline {
  label?: string;
  now_marker?: string;
  events: VpAgendaTimelineEvent[];
  separate_from_actions?: boolean;
}

export interface VpSovereignIndicator {
  label: string;
  value: number | string;
  unit?: string;
  source?: string;
  confidence?: string;
  trend?: string;
  tone?: string;
}

export interface VpDirectiveOfDay {
  label?: string;
  text: string;
  deadline?: string;
  generated_by?: string;
  window?: string;
  primary_cta?: string;
  voice_cta?: string;
}

export interface VpAyaRecommendation {
  assistant?: string;
  voice_first?: boolean;
  prompt?: string;
  answer?: string;
  cta_primary?: string;
  cta_secondary?: string;
}

export interface VpDecisionTeaser {
  id: string;
  title: string;
  recommended_option: string;
  deadline?: string;
  confidence?: number;
}

export interface VpScenarioMode {
  key: string;
  label: string;
  goal?: string;
}

export interface VpOptionCompareMetric {
  key: string;
  label: string;
  option_a: number;
  option_b: number;
}

export interface VpOptionCompare {
  title: string;
  subtitle?: string;
  option_a_label: string;
  option_b_label: string;
  recommended: 'a' | 'b';
  metrics: VpOptionCompareMetric[];
}

export interface VpMapPreviewContext {
  route: string;
  label: string;
  zones: Array<Record<string, unknown>>;
  map: Record<string, unknown> | null;
  mapSystem: Record<string, unknown> | null;
  geoPreview: VpGeoPreview;
  topZoneId: string | null;
}
