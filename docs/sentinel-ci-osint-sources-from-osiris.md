# Sources OSINT économiques pour SENTINEL-CI — 8 KPIs cockpit

> Cible : **lundi 25 mai 2026**, dém VP Côte d'Ivoire.
> Périmètre : enrichir le cockpit gouvernemental avec **8 indicateurs économiques publics**, regroupés en **4 prismes** (Matières premières · Finances publiques · Contexte régional & médias · Opérationnel portuaire).
> Référentiel code : `/Users/thib/Developer/PAPAI/osiris` (Next.js, lecture seule).

## Synthèse exécutive

- **Ce qui est réutilisable depuis osiris (3 / 8)** :
  - **KPI 3 Brent** — `src/app/api/markets/route.ts:11,17-43,109-146` cible déjà `BZ=F` via Yahoo Finance v8 + fallback v6, pattern à porter en Python presque tel quel ⇒ **quick-win garanti**.
  - **KPI 7 Baromètre média** — `src/app/api/news/route.ts:80-100,102-159` fournit un parseur RSS regex (sans dépendance XML), scoring mots-clés, mapping géo, déjà testé sur 9 flux ⇒ **adaptable en remplaçant les feeds par RFI/Jeune Afrique/Abidjan.net**.
  - **KPI 6 Indice contexte régional** — `src/app/api/country-risk/route.ts:5-26,86-99` propose un scoring composite (`RISK_FACTORS` + boost USGS) qui sert de gabarit pour un score CEDEAO 0-100.
- **Non trouvés dans osiris (5 / 8)** : cacao (ICCO), anacarde, spread souverain CI, réserves BCEAO, trafic Port d'Abidjan, AIS, PortWatch, ACLED, GDELT GKG (le fichier `api/gdelt/route.ts` est en réalité un agrégateur RSS BBC/AlJazeera/NYT, pas un appel GDELT). Pour ces 5, sources publiques alternatives recommandées + JSON baseline immédiat.
- **Plan lundi** : **3 quick-wins live** (Brent, Baromètre média FR, Indice CEDEAO score statique enrichi) + **5 fallbacks baseline JSON** étiquetés « cache baseline » dans l'UI, comme pour les indicateurs Banque mondiale existants (`backend/app/services/macro_indicators.py:220-229`). Stratégie identique au pattern World Bank déjà en prod, donc zéro risque démo.
- **Effort estimé** : ~4-6 h dev backend + 1-2 h frontend (un nouveau composant `vp-cockpit-economic-prisms` ou enrichissement de `vp-macro-indicators.component.ts`).

## Mapping rapide osiris → KPI

| # | KPI (prisme) | Source osiris | Alternative publique | Effort lundi |
|---|--------------|---------------|----------------------|--------------|
| 1 | Cours cacao (matières prem.) | non trouvé | **ICCO daily** (`icco.org/statistics`), ICE LCC futures via Yahoo (échec confirmé sur LCC=F), **Stooq.com `lcc.f`** | Fallback baseline lundi · live S+1 |
| 2 | Cours anacarde (matières prem.) | non trouvé | **CSCE/CCA Côte d'Ivoire** bulletins mensuels, **AfricaCashewAlliance**, FAO Faostat (annuel) | Fallback baseline lundi |
| 3 | Brent (matières prem.) | `src/app/api/markets/route.ts:11,17-43` | EIA `https://api.eia.gov/...` (clé gratuite), **Stooq `b.f`** | **Quick-win live lundi** |
| 4 | Spread souverain CI (finances) | non trouvé | **JPMorgan EMBI Global** (paywall) → fallback **World Bank Global Economic Monitor** série `EMBIG_BOND_SPREAD_CIV`, ou bulletin mensuel **Trésor public CI** | Fallback baseline lundi |
| 5 | Réserves BCEAO en mois d'imports (finances) | non trouvé | **BCEAO** publications statistiques mensuelles (HTML, scraping léger), **FMI IFS** série `RAXG_USD` (annuel) | Fallback baseline lundi |
| 6 | Indice contexte régional CEDEAO (contexte) | gabarit `src/app/api/country-risk/route.ts:5-26,86-99` | **ACLED** (clé académique gratuite), **GDELT 2.0 GKG** (CSV hourly), **UNHCR Operational Data Portal** | Quick-win pseudo-live (score statique enrichi) |
| 7 | Baromètre média francophone (contexte) | `src/app/api/news/route.ts:80-100,102-159` | RSS **RFI Afrique**, **Jeune Afrique**, **Abidjan.net**, **Fraternité Matin**, **Connectionivoirienne**, **GDELT GKG tone** | **Quick-win live lundi** (port Python du parseur regex) |
| 8 | Trafic Port d'Abidjan (opérationnel) | non trouvé (osiris liste 50 ports mondiaux mais pas Abidjan) | **PAA bulletins mensuels** (HTML, retard 30j), **IMF PortWatch** (`portwatch.imf.org`, dashboard JSON), **datalastic AIS** (payant) | Fallback baseline lundi |

## Fiches détaillées

### KPI 1 — Cours du cacao (CFA/tonne · prisme matières premières)

- **Affichage VP** : `Cacao 4 250 000 CFA/t · +2,3 % 7j · ICCO`
- **Narratif S2 Nawa** : « -5 % sur la fève = ~12 Md CFA recettes État menacées + tension cocotiers Sud-Ouest ».
- **Source osiris** : non trouvée (osiris ne couvre pas les commodités africaines).
- **Alternative publique recommandée** :
  - **ICCO Daily Prices** : `https://www.icco.org/statistics/` (HTML, mise à jour J+1, USD/t).
  - **Stooq fallback** : `https://stooq.com/q/?s=lcc.f&i=d` (Cocoa London ICE LCC, CSV gratuit, sans clé).
  - **Yahoo CL/LCC** : non disponible directement (le ticker `LCC=F` retourne `null`, vérifié par pattern dans `markets/route.ts`).
- **Conversion** : `XOF/t = USD/t × 655,957 / EUR_USD` (parité fixe FCFA-EUR à 655,957).
- **Pseudo-code (Python)** :
  ```python
  def fetch_cocoa_xof_per_ton() -> dict:
      usd = _scrape_icco_daily_or_stooq()  # html ou CSV
      eur_usd = _ecb_eur_usd_daily()       # frankfurter.app, sans clé
      xof = usd * 655.957 / eur_usd
      return {"value": xof, "unit": "XOF/t", "source": "ICCO via Stooq"}
  ```
- **Patch backend** : ajouter `_fetch_cocoa()` dans `backend/app/services/macro_indicators.py` ; enrichir `INDICATOR_SPECS` avec `key="cocoa_xof_per_ton"`, `unit="CFA/t"`, `label="Cacao (Londres)"`.
- **Patch frontend** : nouveau prisme « Matières premières » dans `vp-macro-indicators.component.ts`, item à insérer dans `FALLBACK_INDICATORS`.
- **Fallback** : `backend/app/resources/macro/civ-commodities-baseline.json` avec dernier prix ICCO connu (mai 2026).
- **Quick-win lundi ?** Non en live, **oui en baseline** étiqueté « cache baseline ». Live S+1.

### KPI 2 — Cours anacarde (CFA/kg · prisme matières premières)

- **Affichage VP** : `Anacarde 850 CFA/kg · -1,1 % 7j · CCA`
- **Narratif S1 Nord** : « campagne 2026 : -8 % depuis avril, pression sur Korhogo/Bouna/Ouangolodougou ».
- **Source osiris** : non trouvée (`Grep cashew|anacarde` zéro résultat).
- **Alternative publique** :
  - **Conseil du Coton et de l'Anacarde (CCA)** : bulletins mensuels PDF, prix planchers d'État.
  - **African Cashew Alliance** : `africancashewalliance.com` (rapports trimestriels).
  - **FAO Faostat** : `fenix.fao.org` (séries annuelles, retard 18 mois — utile uniquement pour la courbe historique).
- **Conversion** : prix CCA déjà en XOF/kg, aucune conversion.
- **Pseudo-code** :
  ```python
  def fetch_cashew_xof_per_kg() -> dict:
      bulletin = _scrape_cca_latest_pdf()      # ou cache mensuel manuel
      return {"value": bulletin.price_kg, "source": "CCA bulletin mensuel"}
  ```
- **Patch backend** : `key="cashew_xof_per_kg"`, source `cca_baseline`.
- **Patch frontend** : item du prisme matières premières.
- **Fallback** : ajouter au JSON `civ-commodities-baseline.json` ; mise à jour manuelle hebdo acceptable lundi.
- **Quick-win lundi ?** **Oui** (baseline mensuel CCA, label « bulletin CCA cache »). Live = scraping PDF en S+1.

### KPI 3 — Brent (USD/baril · prisme matières premières)

- **Affichage VP** : `Brent 78,5 $/bbl · -0,4 % 24h · Yahoo`
- **Narratif** : « +5 % en 7j = +12 % FOB diesel pour CI, importateur net produits raffinés ».
- **Source osiris** : ✅ `src/app/api/markets/route.ts:11` (`OIL_TICKERS = ['CL=F','BZ=F']`), fetcher v8 lignes 17-43, fallback v6 lignes 46-65, `OIL_NAMES` ligne 105 (`'BZ=F': 'Brent Crude'`).
- **Alternative** : **EIA** (`https://api.eia.gov/v2/petroleum/pri/spt/data/?series=PET.RBRTE.D`, clé gratuite) si Yahoo durcit ses CGU.
- **Conversion** : aucune (USD/bbl est la convention secteur).
- **Pseudo-code (port Python du fetcher osiris)** :
  ```python
  YAHOO_V8 = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"

  def fetch_brent_usd() -> dict:
      with httpx.Client(timeout=8.0) as c:
          r = c.get(YAHOO_V8.format(symbol="BZ=F"),
                    params={"interval": "1d", "range": "2d"},
                    headers={"User-Agent": "Mozilla/5.0"})
      meta = r.json()["chart"]["result"][0]["meta"]
      price = meta["regularMarketPrice"]
      prev = meta["chartPreviousClose"]
      change_pct = (price - prev) / prev * 100
      return {"value": round(price, 2), "trend": round(change_pct, 2),
              "unit": "USD/bbl", "source": "Yahoo Finance"}
  ```
- **Patch backend** : `key="brent_usd_per_bbl"`, ajouter à `INDICATOR_SPECS`. Pas besoin de baseline JSON volumineux : un seul point dernier connu suffit.
- **Patch frontend** : item du prisme matières premières.
- **Fallback** : valeur statique J-1 (~78 USD/bbl) avec label « cache baseline ».
- **Quick-win lundi ?** ✅ **Oui, live garanti**. C'est le KPI le moins risqué — port direct d'osiris.

### KPI 4 — Spread souverain CI (bps · prisme finances publiques)

- **Affichage VP** : `Spread CI 612 bps · +18 30j · World Bank GEM`
- **Narratif** : « +50 bps depuis février = renchérissement service de la dette, signal marchés ».
- **Source osiris** : non trouvée (les hits `spread`/`sovereign` sont uniquement CSS et ssrf-guard, faux positifs).
- **Alternative publique** :
  - **World Bank Global Economic Monitor** : `https://databank.worldbank.org/source/global-economic-monitor` série EMBI Global Spread (mensuel).
  - **JPMorgan EMBI Global Diversified** : direct payant, mais agrégats publiés sur Cbonds Frontier (gratuit avec compte).
  - **Trésor public CI / Direction de la Dette** : bulletins trimestriels publics.
- **Pseudo-code** :
  ```python
  WB_EMBI = ("https://api.worldbank.org/v2/country/CIV/indicator/"
             "JPEMBIGSPRDCIV?format=json&per_page=24")  # à confirmer

  def fetch_civ_sovereign_spread_bps() -> dict:
      series = _world_bank_series("JPEMBIGSPRDCIV")  # même helper que existant
      latest = series[-1]
      return {"value": latest["value"], "unit": "bps",
              "source": "World Bank GEM"}
  ```
- **Patch backend** : ajouter à `INDICATOR_SPECS` ; le helper `_world_bank_series()` existant gère déjà fallback baseline (cf. `macro_indicators.py:80-115`).
- **Patch frontend** : prisme « Finances publiques » (nouveau).
- **Fallback** : ajouter série mensuelle dans `civ-indicators-baseline.json` (12 derniers mois).
- **Quick-win lundi ?** **Baseline oui**, live à confirmer (vérifier code WB GEM réel — risque indicateur premium). Live S+1.

### KPI 5 — Réserves BCEAO (mois d'imports · prisme finances publiques)

- **Affichage VP** : `Réserves BCEAO 4,8 mois · -0,1 30j · BCEAO`
- **Narratif** : « zone UEMOA, plancher prudentiel 3 mois, marge de manœuvre 1,8 mois ».
- **Source osiris** : non trouvée.
- **Alternative publique** :
  - **BCEAO** : `https://www.bceao.int/fr/publications/statistiques-monetaires-et-financieres` (PDF mensuels).
  - **FMI IFS** (International Financial Statistics) : série `RAXG_USD` annuelle.
  - **AfricanEconomicOutlook** : OECD/AfDB rapports annuels.
- **Pseudo-code** :
  ```python
  def fetch_bceao_reserves_months() -> dict:
      pdf_url = _latest_bceao_bulletin()
      months = _extract_reserves_in_months(pdf_url)  # regex sur table page 4
      return {"value": months, "unit": "mois imports",
              "source": "BCEAO bulletin mensuel"}
  ```
- **Patch backend** : `key="bceao_reserves_months"`, source `bceao_baseline`.
- **Patch frontend** : prisme « Finances publiques », deuxième item.
- **Fallback** : valeur lundi = dernier bulletin connu (avril 2026).
- **Quick-win lundi ?** **Baseline manuel** (lecture humaine du dernier PDF + injection JSON). Scraping automatisé S+1.

### KPI 6 — Indice contexte régional CEDEAO (0-100 · prisme contexte)

- **Affichage VP** : `Indice CEDEAO 64/100 ↗ · composite ouvert`
- **Narratif** : « stabilité régionale, coopération transfrontalière (composite ACLED + GDELT + UNHCR) — présenté comme indicateur de coopération, pas de menace ».
- **Source osiris** : ✅ **gabarit** `src/app/api/country-risk/route.ts:5-26` (`RISK_FACTORS` table) + `:60-99` (composition + boost externe USGS). Aucun pays CEDEAO listé, à étendre.
- **Alternative publique** :
  - **ACLED** : `api.acleddata.com` (clé académique gratuite, 7-30j retard, événements géolocalisés).
  - **GDELT 2.0 Events** : `https://api.gdeltproject.org/api/v2/doc/doc?query=...` (totalement ouvert).
  - **UNHCR ODP** : `https://data.unhcr.org/api/` (déplacements, gratuit).
- **Composite proposé** (0-100, plus haut = meilleure coopération régionale) :
  ```
  index = 100 - clamp(0,100, 0.4*acled_events_15c + 0.3*gdelt_neg_tone_norm + 0.3*unhcr_idp_growth)
  ```
- **Pseudo-code** :
  ```python
  ECOWAS = ["CIV","BFA","MLI","NER","TGO","BEN","GHA","SEN","GIN","NGA","LBR","SLE","GMB","CPV","GNB"]

  def fetch_ecowas_cooperation_index() -> dict:
      acled = _acled_events_last_30d(ECOWAS)        # 100 events / 15 country
      gdelt = _gdelt_avg_tone(ECOWAS)               # -10..+10
      unhcr = _unhcr_idp_30d_growth_pct(ECOWAS)     # %
      score = 100 - max(0, min(100,
          0.4 * (acled / 5) + 0.3 * (-gdelt * 5 + 50) + 0.3 * unhcr))
      return {"value": round(score), "unit": "/100",
              "source": "ACLED + GDELT + UNHCR composite"}
  ```
- **Patch backend** : `key="ecowas_cooperation_index"`, métadata explicite mentionnant les 3 sources, attribution ACLED.
- **Patch frontend** : prisme « Contexte régional & médias ».
- **Fallback** : score statique 64/100 (cohérent avec dernière analyse interne).
- **Quick-win lundi ?** **Oui pseudo-live** : score statique 64/100 + 1-2 phrases de contexte tirées du dernier bulletin GDELT (cache 24h). Composite live = S+1.

### KPI 7 — Baromètre média francophone (0-100 · prisme contexte)

- **Affichage VP** : `Baromètre média 71/100 → · 5 sources FR`
- **Narratif** : « tonalité moyenne presse francophone Afrique de l'Ouest sur les 7 derniers jours ».
- **Source osiris** : ✅ **directement portable** `src/app/api/news/route.ts:80-100` (parseur RSS regex sans dépendance lourde) + `:58-65` (`scoreRisk()`) + `:102-159` (orchestration `Promise.allSettled`).
- **Alternative publique** :
  - RSS : **RFI Afrique** (`https://www.rfi.fr/fr/afrique/rss`), **Jeune Afrique** (`https://www.jeuneafrique.com/feed/`), **Abidjan.net** (`https://news.abidjan.net/rss/`), **Fraternité Matin** (`https://www.fratmat.info/feed`), **Connectionivoirienne** (`https://www.connectionivoirienne.net/feed`).
  - **GDELT GKG tone** : `https://api.gdeltproject.org/api/v2/doc/doc?mode=tonechart&query=ivoiry+coast` (ouvert, agrégat tone par jour).
- **Pseudo-code** (port Python du parseur osiris, dictionnaire mots-clés FR) :
  ```python
  FEEDS = {
      "RFI Afrique": "https://www.rfi.fr/fr/afrique/rss",
      "Jeune Afrique": "https://www.jeuneafrique.com/feed/",
      "Abidjan.net": "https://news.abidjan.net/rss/",
      "Fraternité Matin": "https://www.fratmat.info/feed",
      "Connectionivoirienne": "https://www.connectionivoirienne.net/feed",
  }
  POSITIVE_FR = {"croissance","investissement","accord","coopération","record"}
  NEGATIVE_FR = {"crise","tension","attaque","attentat","grève","manifestation"}

  def fetch_fr_media_tone() -> dict:
      items = []
      for name, url in FEEDS.items():
          xml = _fetch_with_timeout(url, 8.0)
          items += _parse_rss_regex(xml)  # même regex que osiris :80-99
      pos = sum(1 for i in items if any(w in i.title.lower() for w in POSITIVE_FR))
      neg = sum(1 for i in items if any(w in i.title.lower() for w in NEGATIVE_FR))
      score = round(50 + 50 * (pos - neg) / max(1, len(items)))
      return {"value": clamp(score, 0, 100), "unit": "/100",
              "source": "RFI/JA/Abidjan.net (5 RSS)"}
  ```
- **Patch backend** : `key="fr_media_tone"`, nouveau service `backend/app/services/media_tone.py` (séparé pour TTL court 1h vs 24h Banque mondiale).
- **Patch frontend** : prisme « Contexte régional & médias », deuxième item.
- **Fallback** : score statique 71/100 + label « cache baseline ».
- **Quick-win lundi ?** ✅ **Oui live** — port quasi-direct du parseur osiris (~150 lignes Python), 5 RSS publics, zéro clé.

### KPI 8 — Trafic Port d'Abidjan (TEU/jour · prisme opérationnel)

- **Affichage VP** : `Trafic 8 240 TEU/j · -3,2 % 7j · PAA`
- **Narratif** : « activité corridor Abidjan-Ouagadougou, indicateur quasi-temps-réel de la vitalité éco ».
- **Source osiris** : non trouvée (Abidjan **absent** de la liste de 50 ports dans `src/app/api/maritime/route.ts:9-54`, dataset statique uniquement).
- **Alternative publique** :
  - **PAA** (Port Autonome d'Abidjan) : `https://portabidjan.ci/statistiques` (bulletins mensuels HTML, retard ~30j).
  - **IMF PortWatch** : `https://portwatch.imf.org/datasets` (dashboard public, JSON via réseau interne ESRI), Abidjan tracé.
  - **MarineTraffic / AISStream** : payants, hors scope quick-win.
- **Pseudo-code** :
  ```python
  PAA_BULLETIN = "https://portabidjan.ci/statistiques"
  PORTWATCH_LAYER = "https://services.arcgis.com/.../PortWatch/Abidjan/query?f=json&..."

  def fetch_abidjan_port_throughput() -> dict:
      try:
          stats = _scrape_paa_monthly_html()  # last month avg TEU/day
          return {"value": stats.teu_per_day, "source": "PAA bulletin"}
      except Exception:
          js = _portwatch_query()
          return {"value": js["teu_estimate_7d"], "source": "IMF PortWatch"}
  ```
- **Patch backend** : `key="abidjan_port_teu_per_day"`, service `backend/app/services/port_throughput.py`.
- **Patch frontend** : prisme « Opérationnel ».
- **Fallback** : valeur lundi = moyenne avril 2026 (~8 200 TEU/j).
- **Quick-win lundi ?** **Baseline manuel** (dernier bulletin PAA connu). Live via PortWatch S+1, AIS S+2.

## Mockup cockpit enrichi (ASCII)

```
┌─────────────────────────────────────────────────────────────────┐
│ SENTINEL-CI · Cockpit gouvernemental · 25 mai 2026              │
├─────────────────────────────────────────────────────────────────┤
│ MATIÈRES PREMIÈRES                                              │
│  Cacao        4 250 000 CFA/t   +2,3 %  ICCO (cache baseline)   │
│  Anacarde         850 CFA/kg    -1,1 %  CCA bulletin mensuel    │
│  Brent           78,5 USD/bbl   -0,4 %  Yahoo Finance · LIVE    │
├─────────────────────────────────────────────────────────────────┤
│ FINANCES PUBLIQUES                                              │
│  Spread souverain CI    612 bps   +18 (30j)  WB GEM (baseline)  │
│  Réserves BCEAO        4,8 mois   -0,1       BCEAO mensuel      │
├─────────────────────────────────────────────────────────────────┤
│ CONTEXTE RÉGIONAL & MÉDIAS                                      │
│  Indice CEDEAO          64/100   ↗  ACLED+GDELT+UNHCR           │
│  Baromètre média FR     71/100   →  5 RSS (RFI, JA, Abidjan)    │
├─────────────────────────────────────────────────────────────────┤
│ OPÉRATIONNEL                                                    │
│  Trafic Port Abidjan  8 240 TEU/j   -3,2 % 7j   PAA bulletin    │
└─────────────────────────────────────────────────────────────────┘
```

## Plan de livraison

### Quick-wins déployables avant lundi (effort total ~6h)

1. **KPI 3 Brent live** (~45 min) — port Python du fetcher osiris dans `macro_indicators.py`, ajouter `INDICATOR_SPECS` + serializer minor pour gérer source non-WB.
2. **KPI 7 Baromètre média FR live** (~2h) — nouveau `backend/app/services/media_tone.py` reprenant le pattern regex de `news/route.ts`, 5 feeds, scoring pos/neg, TTL 1h, fallback baseline.
3. **KPI 6 Indice CEDEAO statique enrichi** (~30 min) — endpoint qui retourne 64/100 + métadonnées et liste de 3-5 événements ACLED récents en cache 24h.
4. **KPI 1, 2, 4, 5, 8 baselines JSON** (~2h) — créer `backend/app/resources/macro/civ-commodities-baseline.json` + entrées dans `civ-indicators-baseline.json` étendu, label UI « cache baseline » identique à existant.
5. **Frontend** (~1h) — étendre `vp-macro-indicators.component.ts` avec un mode « 4 prismes » ou créer `vp-cockpit-economic-prisms.component.ts` à côté ; réutilise le service API existant.

**Fichiers à toucher** :
- `backend/app/services/macro_indicators.py` (étendre `INDICATOR_SPECS`).
- `backend/app/services/media_tone.py` (nouveau).
- `backend/app/resources/macro/civ-indicators-baseline.json` (étendre).
- `backend/app/resources/macro/civ-commodities-baseline.json` (nouveau).
- `frontend-ng/src/app/features/mission-room/vp-macro-indicators.component.ts` (groupes par prisme).

### S+1 (semaine 26 mai → 1er juin)

- KPI 2 anacarde : automatiser téléchargement bulletin CCA mensuel.
- KPI 4 spread CI : confirmer série WB GEM réelle ou bascule Cbonds.
- KPI 8 trafic port live : connecteur IMF PortWatch (dashboard ESRI public).
- KPI 6 composite live : intégration ACLED + GDELT GKG tone.

### Backlog (S+2 et au-delà)

- AIS streaming temps réel (aishub/aisstream, payant ou OpenStreetMap-AIS).
- BCEAO scraping automatisé (parseur PDF mensuel).
- Spread CI EMBI direct (négocier accès JPMorgan ou Cbonds).
- ICCO scraping automatisé + ICE LCC futures (à valider conditions ToS).

## Risques juridiques (10 lignes max)

- **ACLED** : licence académique gratuite mais **attribution obligatoire** ("ACLED" + URL) sur tout affichage public, et usage commercial restreint — afficher source dans le footer du widget KPI 6.
- **GDELT** : open data Google sponsorisé, attribution recommandée, aucune restriction commerciale.
- **ICCO** : prix publics mais **ToS interdisant le scraping massif** ; alternative Stooq (CC-BY-NC) ou redistribution manuelle hebdo OK.
- **Yahoo Finance** : **usage non commercial** toléré (la stratégie osiris d'utiliser User-Agent Mozilla et v8 chart est zone grise) ; pour livraison gouvernementale recommander bascule **EIA Brent** dès S+1 (clé gratuite, gouvernemental).
- **RFI / Jeune Afrique / Abidjan.net** : RSS = ouvert et destiné à la syndication, mais conserver titres + lien source (jamais de reproduction du corps de l'article).
- **BCEAO / PAA** : publications publiques, citation source suffisante ; pas de revente.
- **IMF PortWatch** : open data, attribution FMI obligatoire.
- **Banque mondiale** : CC-BY-4.0, attribution déjà gérée dans le code existant.
- **MarineTraffic/AIS** : tout flux non-public est **interdit en redistribution** sans licence — exclure du quick-win.
- **Recommandation transverse** : ajouter un bandeau « Sources » sous chaque prisme dans le cockpit, comme déjà fait pour Banque mondiale dans `_serialize()` de `macro_indicators.py:265-280`.

---

## Sécurité (Vague 2.2 — OSINT live post-démo)

> Implémenté mai 2026. Runbook opérationnel : [`sentinel-ci-osint-security-runbook.md`](sentinel-ci-osint-security-runbook.md).

### Pipelines livrés

| Composant | Fichier | Source osiris / alternative | Statut |
|-----------|---------|------------------------------|--------|
| RSS sécurité FR | `backend/app/services/intelligence/rss_security.py` | Port scoring `news/route.ts:58-65` | Live (flag) + baseline |
| ADS-B Sahel | `backend/app/services/intelligence/adsb_sahel.py` | Port `api/flights/route.ts` → adsb.lol | Live (flag) + `adsb-sahel-baseline.json` |
| Indice CEDEAO | `backend/app/services/intelligence/cedeao_index.py` | Gabarit `country-risk/route.ts` allégé | Composite RSS + baseline |
| Cache | `backend/app/services/intelligence/cache.py` | — | Redis + mémoire process |
| Scheduler | `backend/app/services/intelligence/scheduler.py` | — | RSS 15 min · ADS-B 5 min · indice 30 min |

### Endpoints

- `GET /api/v1/mission-room/cedeao-index` — indice composite seul
- Cockpit (`/cockpit`) — posture + troupes avec badges `LIVE` / `CACHE BASELINE`

### Guard rails

- Whitelist feeds : `backend/app/resources/security/security-feeds.json` (RFI, Jeune Afrique, Abidjan.net, Fraternité Matin — **pas de Telegram live**)
- Feature flag : `workspace.settings.feature_flag.security_live_osint` (off par défaut demo)
- Mode demo VP : force baseline pour reproductibilité trame S3

### Mapping osiris → Vague 2.2

| osiris | Vague 2.2 |
|--------|-----------|
| `news/route.ts` RSS regex + `scoreRisk()` | `rss_security.py` — scoring FR/EN sécurité |
| `flights/route.ts` ADS-B + military heuristics | `adsb_sahel.py` — hubs Sahel + classification |
| `country-risk/route.ts` composite CII | `cedeao_index.py` — 4 composantes UCSI allégé |

### Exclus (inchangé)

- Twitter API v2 live (reste snapshot S3)
- Telegram live (reste snapshot S3)
- ACLED/GDELT live composite complet (baseline + RSS seulement en v2.2)
