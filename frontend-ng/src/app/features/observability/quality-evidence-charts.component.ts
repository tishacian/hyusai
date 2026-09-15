import { ChangeDetectionStrategy, Component, computed, inject, input, signal } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import { NavLinkDirective } from '@app/shared/cockpit';
export interface QualityChartRow {id:string;run_id?:string|null;status?:string;composite_score?:number|null;scores?:Record<string,number>;created_at?:string|null;}
import { scoreValue } from './observability-chart.vm';
@Component({selector:'app-quality-evidence-charts',standalone:true,imports:[NavLinkDirective],changeDetection:ChangeDetectionStrategy.OnPush,
 template:`<section class="quality-charts">
 <header><div><p class="eyebrow">{{i18n.t('observability.charts.eyebrow')}}</p><h2>{{i18n.t('observability.charts.title')}}</h2></div><div class="coverage"><strong>{{measured().length}}<span> / {{rows().length}}</span></strong><p>{{i18n.t('observability.charts.coverage')}}</p></div></header>
 <p class="scope">{{i18n.t('observability.charts.scope',{count:rows().length})}}</p>
 @if(rows().length){
 <div class="plot" role="group" [attr.aria-label]="i18n.t('observability.charts.title')">
 <svg viewBox="0 0 1000 270" role="img" [attr.aria-label]="i18n.t('observability.charts.axis')">
  @for(tick of [0,25,50,75,100];track tick){<line x1="44" x2="980" [attr.y1]="230-tick*2" [attr.y2]="230-tick*2" class="gridline"/><text x="30" [attr.y]="235-tick*2" text-anchor="end" class="axis">{{tick}}</text>}
  @for(segment of segments();track $index){<path [attr.d]="segment.area" class="area"/><path [attr.d]="segment.line" class="curve"/>}
  @for(point of points();track point.row.id){
   @if(point.value !== null){
    <line [attr.x1]="point.x" [attr.x2]="point.x" y1="230" [attr.y2]="point.y" class="stem"/>
    <circle [attr.cx]="point.x" [attr.cy]="point.y" [attr.r]="selected()?.id===point.row.id?9:6" class="point" tabindex="0" role="button" [attr.aria-label]="point.label" (click)="selectedId.set(point.row.id)" (keydown.enter)="selectedId.set(point.row.id)" (keydown.space)="$event.preventDefault();selectedId.set(point.row.id)"><title>{{point.label}}</title></circle>
   } @else {<path [attr.d]="'M '+(point.x-4)+' 240 l 8 8 m 0 -8 l -8 8'" class="missing" tabindex="0" role="button" [attr.aria-label]="point.label" (click)="selectedId.set(point.row.id)" (keydown.enter)="selectedId.set(point.row.id)" (keydown.space)="$event.preventDefault();selectedId.set(point.row.id)"><title>{{i18n.t('observability.charts.missing')}}</title></path>}
  }
  <text x="44" y="266" class="axis">{{i18n.t('observability.charts.earlier')}}</text><text x="980" y="266" text-anchor="end" class="axis">{{i18n.t('observability.charts.latest')}}</text>
 </svg></div>
 <div class="matrix-header"><h3>{{i18n.t('observability.charts.matrix')}}</h3><p>{{i18n.t('observability.charts.legend')}}</p></div>
 <div class="matrix-scroll"><div class="matrix" [style.grid-template-columns]="'160px repeat('+ordered().length+', minmax(32px,1fr))'">
  @for(dimension of dimensions();track dimension){<div class="dimension">{{dimensionLabel(dimension)}}</div>
   @for(row of ordered();track row.id){<button type="button" class="cell" [class.active]="selected()?.id===row.id" [class.absent]="value(row,dimension)===null" [style.background-color]="cellColor(row,dimension)" [attr.aria-label]="dimension + ': ' + (value(row,dimension) ?? i18n.t('observability.charts.missing')) + ' · ' + (row.run_id || row.id)" (click)="selectedId.set(row.id)">{{value(row,dimension) ?? '—'}}</button>}
  }
 </div></div>
 @if(selected();as row){<div class="selection" aria-live="polite"><div><strong>{{row.composite_score ?? '—'}} / 100</strong><span>{{i18n.t('runs.investigation.status.' + (row.status || 'historical'))}}</span></div>@if(row.run_id){<a [navLink]="{type:'run',ref:row.run_id}">{{i18n.t('observability.charts.examine')}} →</a>}</div>}
 } @else {<p>{{i18n.t('observability.charts.empty')}}</p>}
 </section>`,
 styles:[`.quality-charts{padding:28px 0 32px;color:var(--ck-fg-1)}header{display:flex;align-items:start;justify-content:space-between;gap:24px}.eyebrow{font-size:13px;color:var(--ck-fg-3);margin:0 0 10px}h2{font-size:30px;font-weight:600;letter-spacing:-.025em;line-height:1.15}h3{font-size:18px;font-weight:600}.coverage{text-align:right}.coverage strong{font-size:42px;line-height:1;font-weight:600;font-variant-numeric:tabular-nums}.coverage span{font-size:22px;color:var(--ck-fg-3)}.coverage p,.scope{font-size:13px;color:var(--ck-fg-3);margin:10px 0}.plot{width:100%;margin:20px 0;background:var(--ck-bg-panel-hi);padding:20px 12px;border-radius:6px}svg{width:100%;min-height:220px;overflow:visible}.gridline{stroke:var(--ck-stroke-2);stroke-width:1}.axis{fill:var(--ck-fg-3);font:13px sans-serif}.area{fill:var(--ck-signal-cool);opacity:.10}.curve{fill:none;stroke:var(--ck-signal-cool);stroke-width:2.5;stroke-linejoin:round}.stem{stroke:var(--ck-signal-cool);stroke-width:2;opacity:.2}.point{fill:var(--ck-signal-cool);stroke:var(--ck-bg-panel-hi);stroke-width:2;cursor:pointer}.point:focus{outline:none;stroke:var(--ck-fg-1);stroke-width:3}.missing{cursor:pointer;stroke:var(--ck-fg-3);stroke-width:2}.missing:focus{outline:2px solid var(--ck-signal-cool)}.matrix-header{display:flex;justify-content:space-between;align-items:baseline;gap:20px;margin:24px 0 14px}.matrix-header p{font-size:13px;color:var(--ck-fg-3)}.matrix-scroll{overflow-x:auto}.matrix{display:grid;gap:5px;min-width:500px}.dimension{font-size:13px;display:flex;align-items:center;color:var(--ck-fg-2)}.cell{height:36px;border-radius:3px;color:var(--ck-fg-1);border:1px solid transparent;font-size:11px;font-weight:600;cursor:pointer;font-variant-numeric:tabular-nums}.cell.absent{background:repeating-linear-gradient(135deg,transparent,transparent 4px,var(--ck-stroke-2) 4px,var(--ck-stroke-2) 5px)}.cell.active,.cell:focus-visible{outline:2px solid var(--ck-signal-cool);outline-offset:1px}.selection{display:flex;align-items:center;justify-content:space-between;gap:24px;border-top:1px solid var(--ck-stroke-2);margin-top:22px;padding-top:18px}.selection strong{font-size:24px}.selection span{margin-left:18px;font-size:14px;color:var(--ck-fg-3)}a{color:var(--ck-signal-cool);font-weight:500}@media(max-width:600px){h2{font-size:24px}.coverage strong{font-size:30px}.matrix-header{display:block}header{gap:12px}.selection{align-items:start;flex-direction:column}}`]
})
export class QualityEvidenceChartsComponent{
 readonly rows=input<QualityChartRow[]>([]);readonly i18n=inject(I18nService);readonly selectedId=signal('');
 readonly ordered=computed(()=>[...this.rows()].reverse());
 readonly measured=computed(()=>this.rows().filter(r=>scoreValue(r.composite_score)!==null));
 readonly dimensions=computed(()=>[...new Set(this.rows().flatMap(r=>Object.keys(r.scores || {})))].sort());
 readonly selected=computed(()=>this.rows().find(r=>r.id===this.selectedId()) || this.rows()[0] || null);
 readonly points=computed(()=>this.ordered().map((row,index,rows)=>{const value=scoreValue(row.composite_score);return {row,value,x:60+(rows.length>1?index/(rows.length-1):.5)*900,y:value===null?244:230-value*2,label:(row.run_id || row.id)+': '+(value ?? this.i18n.t('observability.charts.missing'))};}));
 readonly segments=computed(()=>{
  const segments:Array<Array<{x:number;y:number}>>=[];let current:Array<{x:number;y:number}>=[];
  for(const point of this.points()){if(point.value===null){if(current.length>1)segments.push(current);current=[];}else current.push(point);}
  if(current.length>1)segments.push(current);
  return segments.map(points=>{const line=points.map((p,i)=>(i?'L':'M')+p.x+' '+p.y).join(' ');return {line,area:line+' L '+points[points.length-1].x+' 230 L '+points[0].x+' 230 Z'};});
 });
 dimensionLabel(dimension:string):string {const key='observability.charts.dimension.'+dimension;const label=this.i18n.t(key);return label===key?dimension:label;}
 value(row:QualityChartRow,dimension:string):number|null{return scoreValue(row.scores?.[dimension]);}
 cellColor(row:QualityChartRow,dimension:string):string|null{const value=this.value(row,dimension);return value===null?null:`color-mix(in srgb, var(--ck-signal-cool) ${Math.round(value*.65+8)}%, var(--ck-bg-panel-hi))`;}
}
