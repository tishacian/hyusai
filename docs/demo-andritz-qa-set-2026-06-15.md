# Jeu de questions/réponses — Démo Chat base de connaissances ANDRITZ

**Date de vérification :** 15/06/2026 — **VM :** `omnirag-demo` (conteneur `agentium-backend`) — **commit :** `094f41e1`
**Workspace :** `andritz` (`0cce0bee-7e86-485d-95b1-672e82f16600`)
**Collection vedette :** `andritz-notices-techniques-spl-pilot` (≈ 99 481 documents / ≈ 1,49 M chunks — notices techniques / pièces de rechange ANDRITZ, FR/EN/DE).

> **Réponses VÉRIFIÉES EN LIVE** via le vrai chemin du chat (orchestrateur → `retrieve_rag_context` → génération), profil **balanced** (`chat`, le défaut). Les résumés ci-dessous reflètent ce que le système a *réellement* répondu, pas une réponse idéalisée.

---

## ⚠️ Pré-requis de présentation (IMPORTANT — à lire avant la démo)

**Le routage n'est PAS cassé** : il route correctement dès qu'un scope de connaissances est actif. Historiquement le **scope par défaut du workspace était `Andritz manuals BBA120 pilot`** (22 docs, sans SPL), d'où les replis observés sans sélection manuelle.

> ✅ **Le scope par défaut a été basculé sur `Contexte Andritz SPL` (15/06).** La démo fonctionne donc **out of the box**, même sans sélection manuelle.
> Ce scope couvre `andritz-notices-techniques-spl-pilot` (SPL) **+** `andritz-manuals-bba120-pilot` (BBA120) **+** `andritz-non-wovens-france-excel-pilot`. **Vérifié le 15/06 : ce seul scope répond correctement aux 12 questions, Q12 incluse** — pas besoin de changer de scope entre les questions.

- **Q1 à Q12 : aucun geste de scope nécessaire** (le défaut `Contexte Andritz SPL` les couvre toutes ; Q12/Etachrom est servie par le volet BBA120 du scope). Vérifier simplement, dans le sélecteur de connaissances, que `Contexte Andritz SPL` est bien le scope actif.
- **Profil : `balanced` suffit partout.** Ne **PAS** utiliser `deep` (le planner deep scanne le ledger ~65 s sur cette collection → 0 passage → repli ; voir « À ÉVITER »).
- **Latence :** sous ce scope multi-collections le budget de candidats est réparti sur 3 collections, donc les temps sont **un peu supérieurs** aux chiffres par question ci-dessous (mesurés en ciblage SPL seul) — compter ~8–17 s selon la question. Le 1ᵉʳ appel est plus lent (préchargement du cross-encoder).

---

## Récapitulatif par catégorie (sources & latence vérifiées le 15/06)

| # | Question (abrégé) | Capacité | Collection | Sources citées | Latence |
|---|---|---|---|---|---|
| Q1 | AKK200 — largeur/vitesse (FR) | Spec lookup | SPL | 1 doc clé (Section II.2) /scope 8 | ~6,5 s |
| Q2 | AKK200 — Arbeitsbreite/Geschw. (DE) | Multilingue | SPL | Section II.2 | ~5,4 s |
| Q3 | AKK200 — sections du manuel | Scope projet | SPL | menu + sections I–VI | ~6,5 s |
| Q4 | CU250S-2 — rôle/configuration | Spec lookup | SPL | 3 notices Control Units | ~12 s |
| Q5 | CU250S-2 — mise en service (STARTER) | Procédure | SPL | 3 docs automation | ~14 s |
| Q6 | ACJ200 — description de la carde | Scope projet | SPL | 8 docs Manual_ACJ200 | ~24 s |
| Q7 | ACJ200 — risques résiduels & sécurité | Procédure + sécurité | SPL | 8 docs Manual_ACJ200 (SERVO X) | ~32 s |
| Q8 | Qualiscan QMS-12 — fonction (FR) | Multilingue | SPL | 3 notices QMS-12 (fr/en/de) | ~12 s |
| Q9 | Qualiscan QMS-12 — function (EN) | Multilingue | SPL | 3 notices QMS-12 | ~10 s |
| Q10 | Qualiscan QMS-12 — Funktion (DE) | Multilingue | SPL | 3 notices QMS-12 | ~10 s |
| Q11 | QMS-12 — calibration des capteurs | Procédure | SPL | 3 notices QMS-12 (ASY200/BHX100) | ~12 s |
| Q12 | Etachrom B — pièces de rechange | Spec lookup | BBA120 | Etachrom B.PDF + Spare Parts List | ~5,6 s |

**12 questions retenues** couvrant : Spec lookup (Q1, Q4, Q12), Multilingue (Q2, Q8, Q9, Q10), Scope projet (Q3, Q6), Procédure + sécurité (Q5, Q7, Q11).

---

## Questions retenues (détail)

### Q1 — Spec lookup (AKK200, FR) ⭐ valeur sûre
- **Question :** « Quelle est la largeur de travail et la vitesse de production du système AKK200 Nonwoven ? »
- **Capacité :** Lookup factuel de valeurs exactes (scope projet → bon document).
- **Réponse réelle :** « **Largeur de travail : 0,3 m — Vitesse de production : 10 à 20 m/min**. Référence : AKK200 – Section II : Technical Data, II.2 Specifications and performances. » Réponse courte, exacte, une seule citation pertinente.
- **Sources :** `AKK200 … section_II/II.2.html` (Technical Data), confiance de scope 0,94.
- **Profil :** balanced. **Latence :** ~6,5 s.
- **Notes :** la réponse la plus « propre » du lot — idéale pour ouvrir. Bien vérifier que le scope `Contexte Andritz SPL` est sélectionné.

### Q2 — Multilingue (AKK200, DE → doc EN) ⭐
- **Question :** « Wie groß sind die Arbeitsbreite und die Produktionsgeschwindigkeit des AKK200 Nonwoven-Systems? »
- **Capacité :** Question en **allemand** sur un document **anglais** → même fait retrouvé.
- **Réponse réelle :** « Arbeitsbreite: 0,3 m — Produktionsgeschwindigkeit: 10–20 m/min. Quelle: AKK200 User's Manual, Section II.2. »
- **Sources :** `AKK200 … section_II/II.2.html`.
- **Profil :** balanced. **Latence :** ~5,4 s.
- **Notes :** parfait à enchaîner juste après Q1 pour montrer le cross-lingue (même valeur, langue de la question respectée).

### Q3 — Scope projet (AKK200, sommaire)
- **Question :** « Quelles sont les sections principales du manuel utilisateur de l'AKK200 ? »
- **Capacité :** Le code projet AKK200 cadre correctement la recherche sur le bon manuel.
- **Réponse réelle :** liste structurée — Section I General Informations, II Technical Data, III Safety Instructions, IV System Unit, etc., avec sous-sections (I.2 Copyright, II.2 Specifications…).
- **Sources :** `AKK200 … menu/menu.html` + plusieurs `section_I/*.html`.
- **Profil :** balanced. **Latence :** ~6,5 s.

### Q4 — Spec lookup (CU250S-2) ⭐
- **Question :** « À quoi sert l'unité de commande CU250S-2 et comment la configurer ? »
- **Capacité :** Lookup factuel sur un composant d'automatisme.
- **Réponse réelle :** la CU250S-2 est l'unité de commande d'un variateur vectoriel (Siemens) : contrôle moteur (vitesse/couple), gestion/sauvegarde des paramètres, mise en service via BOP-2 ou STARTER, optimisation de régulation (KP/TN), transfert par carte mémoire.
- **Sources :** 3 notices `Control_Units_CU250S-2_…pdf` (sections hydroentanglement ACJ100/AVA500/AMM100).
- **Profil :** balanced. **Latence :** ~12 s.

### Q5 — Procédure (CU250S-2, mise en service)
- **Question :** « Comment mettre en service et paramétrer l'unité de commande CU250S-2 avec l'outil STARTER ? »
- **Capacité :** Procédure pas-à-pas.
- **Réponse réelle :** procédure STARTER : créer un projet, rattacher le variateur (USB), assistant de mise en service (basic commissioning : mode de commande, modules fonctionnels, interfaces), charger la config, passage en ligne pour réglages/optimisations.
- **Sources :** docs « Automation documentation » (Manual_ORL310) + section AMM100.
- **Profil :** balanced. **Latence :** ~14 s.

### Q6 — Scope projet (carde ACJ200) ⭐
- **Question :** « Décris la carde ACJ200 et ses principaux composants. »
- **Capacité :** Scope projet (ACJ200 → bon manuel) + synthèse structurée.
- **Réponse réelle :** description par sous-ensembles (entrée/INLET : bâtis, demi-lunes, table d'alimentation, pré-ouvreurs ; rouleaux ; etc.) avec références de pièces et n° de projet 69200.
- **Sources :** 8 extraits de `Manual_ACJ200-revA` (Card documentation, listes de pièces).
- **Profil :** balanced. **Latence :** ~24 s (un peu plus longue — prévenir).

### Q7 — Procédure + sécurité (ACJ200, risques résiduels) ⭐
- **Question :** « Quels sont les risques résiduels et les consignes de sécurité de la carde ACJ200 ? »
- **Capacité :** Procédure / sécurité (excellent grounding).
- **Réponse réelle :** risques liés au **rayonnement X du système de mesure SERVO X** (interverrouillage des protecteurs), risques mécaniques de la carde (rouleaux, grand tambour), obligation d'appliquer le chapitre Sécurité avant intervention.
- **Sources :** 8 extraits `Manual_ACJ200-revA` (dont « ACJ200 Residual risks », SERVO X).
- **Profil :** balanced. **Latence :** ~32 s (la plus longue — éviter de la placer en premier).

### Q8 — Multilingue (Qualiscan QMS-12, FR) ⭐
- **Question :** « À quoi sert le système de mesure Qualiscan QMS-12 et comment fonctionne-t-il ? »
- **Capacité :** Question FR sur des notices DE/EN/multilingues.
- **Réponse réelle :** QMS-12 = système qualité en ligne à balayage transversal (grammage, humidité, profil) ; capteurs sur portique mobile ; architecture PC central + ponts de mesure ; gestion des recettes, limites de profil, calibration linéaire ; configurations Profix / Uniscan / Webpro.
- **Sources :** notices `QMS-12_Qualiscan` (Manual_ASY200 fr_FR, Manual_BHX100 en_GB & de_DE).
- **Profil :** balanced. **Latence :** ~12 s.

### Q9 — Multilingue (Qualiscan QMS-12, EN) ⭐
- **Question :** « What is the Qualiscan QMS-12 system used for and how does it work? »
- **Réponse réelle (EN) :** « traversing quality measurement and control system for running webs… measures moisture/basis weight across the web width via sensors on a measuring bridge… central visualization/logging/host communication. »
- **Sources :** notices `QMS-12_Qualiscan` (BHX100 + ASY200).
- **Profil :** balanced. **Latence :** ~10 s.

### Q10 — Multilingue (Qualiscan QMS-12, DE) ⭐
- **Question :** « Wozu dient das Qualiscan QMS-12 System und wie funktioniert es? »
- **Réponse réelle (DE) :** mesure/journalisation/régulation de paramètres qualité sur toute la largeur (Flächenmasse, Feuchte, Schichtdicke) ; Traversierrahmen + capteurs ; transmission Ethernet vers PC central.
- **Sources :** notices `QMS-12_Qualiscan`.
- **Profil :** balanced. **Latence :** ~10 s.
- **Notes :** Q8/Q9/Q10 forment un trio puissant — **même équipement, même fait, posé en 3 langues, sources DE/EN/FR**.

### Q11 — Procédure (QMS-12, calibration)
- **Question :** « Comment calibrer les capteurs du système de mesure Qualiscan QMS-12 ? »
- **Capacité :** Procédure technique fine.
- **Réponse réelle :** calibration via « linéarisation » dans l'IHM opérateur (mesure d'échantillons de référence, enregistrement des valeurs, activation de la courbe) ; calibration dédiée IR (Infralot IMF) calculant des coefficients avec contrôle de qualité du fit.
- **Sources :** notices `QMS-12_Qualiscan` (ASY200 + BHX100).
- **Profil :** balanced. **Latence :** ~12 s.

### Q12 — Spec lookup (Etachrom B, pièces de rechange) ⭐ — volet BBA120 du scope
- **Question :** « Quelles pièces de rechange sont recommandées pour la pompe centrifuge Etachrom ? »
- **Capacité :** Lookup factuel (références de pièces + règle de stock).
- **Réponse réelle :** stock recommandé pour 2 ans (DIN 24296) : arbre (210), roue/impeller (230), joints toriques (412.35), garniture mécanique (433), bagues d'usure (502.01/.02/.06) avec exceptions selon tailles de pompe.
- **Sources :** `Etachrom B.PDF` + `Spare Parts List_BBA120.pdf`.
- **Profil :** balanced. **Latence :** ~6–17 s.
- **Notes :** ✅ **Servie par le scope `Contexte Andritz SPL`** (qui inclut BBA120) — vérifié le 15/06 : le manuel `…ETACHROM.pdf` / `Etachrom B.PDF` remonte bien. **Aucun changement de scope nécessaire** pour enchaîner après Q11.

---

## 🚫 À ÉVITER en démo (vérifié — repli / timeout / scope erroné)

| Question type | Pourquoi l'éviter (constaté le 15/06) |
|---|---|
| **Pompe URACA KD724-G** (caractéristiques / sécurité / maintenance) | Le PDF `KD724.PDF` est indexé mais **son contenu n'a pas pu être extrait** ; le scope ledger retombe sur l'annexe « pompe à pied » (`10_Foot-operated air pump`) → réponse « je n'ai pas trouvé ». |
| **Nettoyage des cartouches injecteur EXH** | Aucune procédure EXH trouvée même collection SPL sélectionnée → repli partiel. (L'« ancre » historique ne fonctionne plus en live.) |
| **Carde Excelle S5PP6TT** (caractéristiques / sécurité) | Seul un extrait de la section Sécurité remonte, réponse fortement hédgée (« il manque… »). |
| **Système Hydro-Dry** (séchage) | 0 passage exploitable, uniquement le guide méthodologique → repli total. |
| **Intervalles de maintenance filtration / cellule de flottation (PIT)** | Les docs de filtration remontent mais **sans périodicités chiffrées** → repli (« pas d'intervalles explicites »). |
| **Comparatif CONTINENTAL vs POLLRICH** | Un seul côté est documenté (CONTINENTAL : déclaration CE, exhauster 151A.06) ; **aucune source POLLRICH** → pas de vrai comparatif. |
| **« Liste-moi toutes les pompes de tous les projets »** (large/non scopé) | Dépend de l'écart d'ingestion PG⊋Qdrant (notices pompes non vectorisées) ; le scope retombe sur 1 doc générique → réponse générique. |
| **Toute question avec un code projet quand le scope par défaut (BBA120 pilot) est laissé** | Tombe sur le garde-fou « retrieval-exact-match-guardrail » (scope ledger trouvé, mais 0 hit exact-metadata côté Qdrant) → « je n'ai pas trouvé ». **Corrigé en sélectionnant le scope `Contexte Andritz SPL`.** |
| **Profil `deep` sur la collection SPL** | Le planner deep scanne le ledger (~65 s observé) → 0 passage → repli. Rester en `balanced`. |

---

## Note méthodologique

- **Combien de candidates testées :** ~61 exécutions live (≈ 50 questions distinctes, plusieurs reformulations/variantes de collection). **12 retenues**, le reste écarté (repli « je n'ai pas trouvé », scope erroné, ou timeout deep).
- **Comment vérifié :** chaque question rejouée dans le conteneur `agentium-backend` via l'orchestrateur réel (`rag_service.answer` → `process_request` → `retrieve_rag_context` + génération), workspace `andritz`, profil `chat`/balanced. Capturés pour chacune : texte de réponse, nombre/identité des sources citées, scope/collection, `scope_confidence`, présence de repli/`fallback_reason`, statut sparse/cross-encoder, latence.
- **Critère de rétention :** réponse réellement *ancrée* (cite des documents réels, pas de « je n'ai pas trouvé », pas de garde-fou exact-match, pas de `deep_timeout`).
- **Enseignement clé pour la démo :** le routage est sain ; tout dépend du scope actif. Le défaut était le mauvais scope (pilote BBA120, 22 docs, sans SPL), ce qui déclenchait les replis.
- **Correctif appliqué (15/06) :** `is_default` a été basculé sur le scope `andritz-spl-knowledge-experiment` (« Contexte Andritz SPL ») dans `workspaces.settings.knowledge_scopes`. Désormais une requête **sans sélection** résout vers ce scope (vérifié : `resolve_knowledge_scope(None)` → SPL+BBA120+France-Excel, et le retrieval no-scope remonte bien les docs AKK200 SPL). ⚠️ Changement de comportement du workspace : impacte aussi les usages hors démo.
- **Vérification routage (15/06) :** au niveau planner, `Contexte Andritz SPL` résout vers les 3 collections (SPL inclus, `scope_confidence` 0,94, aucun `fallback_reason`) ; en retrieval end-to-end il remonte les bons documents SPL **et** BBA120.
- **Reproductibilité :** valeurs observées le 15/06/2026 sur la VM, commit `094f41e1` ; latences indicatives (1ʳᵉ requête plus lente à cause du préchargement du cross-encoder).
