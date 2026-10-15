# Validation finale du code figé

Le 15 octobre 2026, sur la branche `codex/execution-observability` issue de
`demo/agentic` (`0b63fcec`), la suite backend complète termine avec **9 596 tests
réussis, 152 ignorés, aucun échec**, code de sortie 0, en 925,72 secondes.
Les 108 fichiers applicatifs, tests et configurations relevés dans
`source-sha256.json` sont identiques avant et après ce passage. La validation
précède le commit local ; le SHA de base seul n'identifie donc pas le code testé.

Le frontend passe **2 238 tests unitaires**, le build de production, les gardes
i18n/navigation/chrome et **5 scénarios Chromium**. Ces scénarios utilisent des
réponses API/SSE contrôlées. Ils ne constituent pas une recette sur la VM.

La conformité statique passe : 16/22 assertions vérifiées statiquement, les
attestations de runners restant séparées. Les 53 nouveaux fichiers Python
passent Ruff. Sur les 26 fichiers existants modifiés, aucun diagnostic n'est
ajouté aux diagnostics antérieurs. L'API, les tâches générales et le worker de
contrôle se chargent dans un processus interdisant les SDK Temporal/LangGraph.

Les tests opt-in réels sont conservés dans des dossiers distincts :

- [Temporal natif C](../native-c/report.md) : 29 tests, dont 2 compositions sur
  serveur Temporal réel et 3 tests PostgreSQL ; fournisseurs simulés.
- [Contrôle et transport](../control-and-scaffold/report.md) : concurrence et
  bornes PostgreSQL, migration 134 réversible à vide, RabbitMQ réel et rendu des
  scaffolds. Le transport utilise une petite opération transactionnelle de test.
- [Mécanismes A/B](../report.md) : expériences historiques LangGraph et plugin
  Temporal, antérieures au candidat C. Leur image et leur verdict ne qualifient
  pas l'image C.

Les logs, commandes, versions et limites figurent dans `validation.json` et
les sous-rapports. Les XML JUnit et log unitaire frontend complets restent dans
le workspace ; leurs empreintes sont conservées avec les résumés. Le nombre de
warnings backend (141 269) est enregistré, sans être transformé en échec ou
masqué par une déclaration de lint globalement propre.

La qualification VM, les images release et C, les fournisseurs réels, le scoring
quotidien de 2–3 millions de lignes avec reçu, les percentiles de charge et la
comparaison des runtimes sur un corpus identique restent ouverts. Aucun
déploiement, activation, changement de plafond ou transfert de Run en cours
n'est effectué par cette validation. Voir la
[recette déléguée](../../../agentium-execution-operations.md).
