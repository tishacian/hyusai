from src.globalvariables import ReasoningType

REASONING_PATTERNS = {
    ReasoningType.FACTUAL: ["quoi", "qu'est-ce que", "qui", "où", "quand", "quel", "quelle", "liste", "lister", "décrire", "définir", "identifier", "spécifier", "vérifier", "confirmer", "montrer", "démontrer", "appartient à", "consiste en", "contient", "comprend", "combien", "combien de", "à quelle fréquence", "combien de temps", "propriétés de", "caractéristiques", "fonctionnalités", "attributs", "catégoriser", "classer", "grouper", "type de"],
    ReasoningType.ANALYTICAL: ["comment", "analyser", "examiner", "enquêter", "évaluer", "apprécier", "réviser", "décomposer", "disséquer", "décrypter", "décoder", "modèle", "tendance", "relation", "corrélation", "justifier", "valider", "prouver", "étayer", "résoudre", "déterminer", "découvrir", "fonction", "fonctionner", "opérer", "processus", "interpréter", "comprendre", "saisir"],
    ReasoningType.COMPARATIVE: ["comparer", "contraster", "différer", "distinguer", "similaire", "semblable", "ressembler", "parallèle", "versus", "vs", "contre", "différence", "distinction", "meilleur", "pire", "plus fort", "plus faible", "classer", "noter", "évaluer", "scorer", "préférer", "choix", "sélectionner", "opter", "plus que", "moins que", "égal à", "supérieur à", "avantage", "inconvénient", "pour", "contre"],
    ReasoningType.CAUSAL: ["pourquoi", "parce que", "cause", "effet", "résultat", "conséquence", "impact", "mener à", "découler de", "provenir de", "influencer", "affecter", "déterminer", "façonner", "déclencher", "initier", "susciter", "inciter", "cascade", "chaîne", "séquence", "série", "facteur", "contributeur", "moteur", "déterminant", "fort", "faible", "direct", "indirect"],
    ReasoningType.HYPOTHETICAL: ["si", "serait", "pourrait", "devrait", "supposer", "présumer", "considérer", "prédire", "prévoir", "projeter", "estimer", "scénario", "situation", "cas", "instance", "possible", "probable", "potentiel", "alternative", "option", "choix", "chemin", "risque", "chance", "probabilité", "et si", "sinon", "alternativement", "à la place"],
}  # fmt: skip

REASONING_INSTRUCTIONS = {
    ReasoningType.FACTUAL: """[INST] Tu es un assistant IA spécialisé dans la fourniture d'informations précises et factuelles.
                                                Étapes d'analyse :
                                                1. Identifier les faits clés du contexte
                                                2. Extraire les informations pertinentes
                                                3. Vérifier la cohérence factuelle
                                                4. Présenter les informations clairement et de manière concise
                                                
                                                Contexte : {context}
                                                
                                                Question : {question}
                                                
                                                Fournis une réponse factuelle claire en t'appuyant sur le contexte : [/INST]""",
    ReasoningType.ANALYTICAL: """[INST] Tu es un assistant IA spécialisé dans l'analyse approfondie.
                                                Étapes d'analyse :
                                                1. Identifier l'objectif principal et les contraintes
                                                2. Décomposer les exigences clés et les paramètres
                                                3. Rechercher des informations factuelles pertinentes à la requête
                                                4. Vérifier l'exactitude des noms, lieux et détails spécifiques
                                                5. Examiner les relations entre les faits et le contexte fourni
                                                6. Synthétiser des renseignements pertinents à la situation de l'utilisateur
                                                7. Tirer des conclusions basées sur des preuves vérifiées
                                                                                               
                                                Context: {context}
                                                                                               
                                                Question: {question}
                                                                                               
                                                Fournis une analyse approfondie qui combine précision factuelle et renseignements analytiques en t'appuyant sur le contexte : [/INST]""",
    ReasoningType.COMPARATIVE: """[INST] Tu es un assistant IA spécialisé dans l'analyse comparative.
                                                Étapes d'analyse :
                                                1. Identifier les éléments à comparer
                                                2. Examiner les similitudes et différences
                                                3. Évaluer les forces/faiblesses comparativement
                                                4. Tirer des conclusions nuancées
                                                
                                                Context: {context}
                                                
                                                Question: {question}
                                                
                                                Fournis une analyse comparative en t'appuyant sur le contexte : [/INST]""",
    ReasoningType.CAUSAL: """[INST] Tu es un assistant IA spécialisé dans l'analyse causale.
                                                Étapes d'analyse :
                                                1. Identifier les relations de cause à effet
                                                2. Examiner les facteurs contribuants
                                                3. Analyser les implications et conséquences
                                                4. Établir les chaînes de causalité
                                                
                                                Contexte : {context}
                                                
                                                Question : {question}
                                                
                                                Explique les relations causales en t'appuyant sur le contexte : [/INST]""",
    ReasoningType.HYPOTHETICAL: """[INST] Vous êtes un assistant IA spécialisé dans le raisonnement hypothétique.
                                                Étapes d'analyse :
                                                1. Considérer les hypothèses conditionnelles
                                                2. Analyser les scénarios potentiels
                                                3. Évaluer les implications
                                                4. Tirer des conclusions logiquement déduites
                                                
                                                Contexte : {context}
                                                
                                                Question : {question}
                                                
                                                Explore ce scénario en t'appuyant sur le contexte : [/INST]""",
}
