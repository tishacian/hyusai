from src.globalvariables import ReasoningType
from src.system_prompts.types import SystemPromptTypes

REASONING_PATTERNS = {
    ReasoningType.FACTUAL: ["quoi", "qu'est-ce que", "qui", "où", "quand", "quel", "quelle", "liste", "lister", "décrire", "définir", "identifier", "spécifier", "vérifier", "confirmer", "montrer", "démontrer", "appartient à", "consiste en", "contient", "comprend", "combien", "combien de", "à quelle fréquence", "combien de temps", "propriétés de", "caractéristiques", "fonctionnalités", "attributs", "catégoriser", "classer", "grouper", "type de"],
    ReasoningType.ANALYTICAL: ["comment", "analyser", "examiner", "enquêter", "évaluer", "apprécier", "réviser", "décomposer", "disséquer", "décrypter", "décoder", "modèle", "tendance", "relation", "corrélation", "justifier", "valider", "prouver", "étayer", "résoudre", "déterminer", "découvrir", "fonction", "fonctionner", "opérer", "processus", "interpréter", "comprendre", "saisir"],
    ReasoningType.COMPARATIVE: ["comparer", "contraster", "différer", "distinguer", "similaire", "semblable", "ressembler", "parallèle", "versus", "vs", "contre", "différence", "distinction", "meilleur", "pire", "plus fort", "plus faible", "classer", "noter", "évaluer", "scorer", "préférer", "choix", "sélectionner", "opter", "plus que", "moins que", "égal à", "supérieur à", "avantage", "inconvénient", "pour", "contre"],
    ReasoningType.CAUSAL: ["pourquoi", "parce que", "cause", "effet", "résultat", "conséquence", "impact", "mener à", "découler de", "provenir de", "influencer", "affecter", "déterminer", "façonner", "déclencher", "initier", "susciter", "inciter", "cascade", "chaîne", "séquence", "série", "facteur", "contributeur", "moteur", "déterminant", "fort", "faible", "direct", "indirect"],
    ReasoningType.HYPOTHETICAL: ["si", "serait", "pourrait", "devrait", "supposer", "présumer", "considérer", "prédire", "prévoir", "projeter", "estimer", "scénario", "situation", "cas", "instance", "possible", "probable", "potentiel", "alternative", "option", "choix", "chemin", "risque", "chance", "probabilité", "et si", "sinon", "alternativement", "à la place"],
}  # fmt: skip
TRIVIAL_VOCABULARY = {"bonjour", "salut", "coucou", "bonsoir", "bonne nuit", "bonne journée", "bonne soirée", "bon matin", "bon après-midi", "comment allez-vous", "comment ça va", "ça va", "comment tu vas", "merci", "merci beaucoup", "merci bien", "je vous remercie", "je te remercie", "grand merci", "mille mercis", "de rien", "il n'y a pas de quoi", "je vous en prie", "je t'en prie", "avec plaisir", "tout le plaisir est pour moi", "pas de problème", "pas de souci", "aucun problème", "s'il vous plaît", "s'il te plaît", "svp", "excusez-moi", "excuse-moi", "pardon", "désolé", "désolée", "je suis désolé", "je suis désolée", "mes excuses", "toutes mes excuses", "au revoir", "à bientôt", "à plus tard", "à plus", "à tout à l'heure", "à demain", "bonne continuation", "portez-vous bien", "porte-toi bien", "prenez soin de vous", "prends soin de toi", "salut", "ciao", "tchao", "bye", "adieu", "oui", "si", "ouais", "d'accord", "ok", "okay", "très bien", "parfait", "excellent", "super", "génial", "formidable", "magnifique", "fantastique", "non", "nan", "pas du tout", "absolument pas", "jamais", "jamais de la vie", "hors de question", "pas question", "peut-être", "probablement", "sûrement", "certainement", "bien sûr", "évidemment", "naturellement", "effectivement", "exactement", "précisément", "tout à fait", "absolument", "complètement", "entièrement", "totalement", "vraiment", "réellement", "véritablement", "franchement", "sincèrement", "honnêtement", "je", "tu", "il", "elle", "nous", "vous", "ils", "elles", "le", "la", "les", "un", "une", "des", "du", "de", "à", "au", "aux", "dans", "sur", "sous", "avec", "sans", "pour", "par", "en", "et", "ou", "mais", "donc", "or", "ni", "car", "si", "que", "qui", "quoi", "où", "quand", "comment", "pourquoi", "combien", "quel", "quelle", "quels", "quelles", "ce", "cette", "ces", "cet", "mon", "ma", "mes", "ton", "ta", "tes", "son", "sa", "ses", "notre", "nos", "votre", "vos", "leur", "leurs", "être", "avoir", "faire", "aller", "venir", "voir", "savoir", "pouvoir", "vouloir", "devoir", "falloir", "dire", "prendre", "donner", "mettre", "partir", "sortir", "entrer", "rester", "arriver", "passer", "regarder", "écouter", "parler", "comprendre", "apprendre", "connaître", "reconnaître", "croire", "penser", "trouver", "chercher", "demander", "répondre", "attendre", "espérer", "aimer", "préférer", "détester", "adorer", "c'est", "c'était", "c'est ça", "voilà", "voici", "il y a", "il n'y a pas", "qu'est-ce que", "qu'est-ce qui", "est-ce que", "n'est-ce pas", "bien", "mal", "bon", "mauvais", "bonne", "mauvaise", "grand", "petit", "grande", "petite", "gros", "mince", "grosse", "beau", "belle", "joli", "jolie", "laid", "laide", "jeune", "vieux", "vieille", "nouveau", "nouvelle", "ancien", "ancienne", "premier", "première", "dernier", "dernière", "autre", "même", "tout", "toute", "tous", "toutes", "chaque", "plusieurs", "quelque", "quelques", "beaucoup", "peu", "assez", "trop", "très", "plus", "moins", "aussi", "autant", "encore", "déjà", "toujours", "souvent", "parfois", "quelquefois", "rarement", "jamais", "maintenant", "aujourd'hui", "hier", "demain", "avant", "après", "pendant", "depuis", "jusqu'à", "ici", "là", "là-bas", "partout", "nulle part", "quelque part", "ailleurs", "dehors", "dedans", "dessus", "dessous", "devant", "derrière", "à côté", "loin", "près", "autour", "entre", "parmi", "contre", "vers", "chez", "malgré", "selon", "sauf", "environ", "presque", "seulement", "même", "aussi", "non plus", "ne... pas", "ne... plus", "ne... jamais", "ne... rien", "ne... personne", "ne... que", "ne... guère", "ne... point", "quelqu'un", "quelque chose", "personne", "rien", "tout le monde", "n'importe qui", "n'importe quoi", "n'importe où", "n'importe quand", "n'importe comment", "tant mieux", "tant pis", "comme ça", "comme ci comme ça", "ça dépend", "ça va", "ça marche", "ça roule", "ça baigne", "ça gaze", "nickel", "impec", "cool", "sympa", "chouette", "génial", "top", "extra", "super", "hyper", "méga", "ultra", "archi", "vachement", "drôlement", "sacrément", "bigrement", "rudement", "fichement", "bougrement", "diablement", "terriblement", "affreusement", "horriblement", "épouvantablement", "incroyablement", "extraordinairement", "remarquablement", "particulièrement", "spécialement", "surtout", "notamment", "principalement", "essentiellement", "fondamentalement", "globalement", "généralement", "habituellement", "normalement", "ordinairement", "couramment", "fréquemment", "régulièrement", "constamment", "continuellement", "perpétuellement", "éternellement", "définitivement", "finalement", "enfin", "bref", "en fait", "en effet", "en réalité", "au fait", "à propos", "d'ailleurs", "par ailleurs", "en outre", "de plus", "en plus", "aussi", "également", "pareillement", "de même", "ainsi", "donc", "alors", "puis", "ensuite", "après", "enfin", "finalement", "d'abord", "premièrement", "deuxièmement", "troisièmement", "d'une part", "d'autre part", "par contre", "en revanche", "cependant", "néanmoins", "toutefois", "pourtant", "malgré tout", "quand même", "tout de même", "malgré cela", "en dépit de", "bien que", "quoique", "encore que", "même si", "sauf si", "à moins que", "pourvu que", "à condition que", "dans la mesure où", "étant donné que", "vu que", "puisque", "comme", "parce que", "car", "en raison de", "à cause de", "grâce à", "faute de", "par manque de", "par suite de", "suite à", "à la suite de", "par conséquent", "en conséquence", "de ce fait", "c'est pourquoi", "voilà pourquoi", "d'où", "de là", "par là", "de cette façon", "de cette manière", "ainsi", "comme ça", "comme cela", "de la sorte", "autrement dit", "c'est-à-dire", "en d'autres termes", "pour ainsi dire", "si l'on peut dire", "en quelque sorte", "d'une certaine façon", "d'une certaine manière", "en un sens", "dans un sens", "à vrai dire", "pour tout dire", "à dire vrai", "pour être franc", "pour être honnête", "franchement parlant", "honnêtement parlant", "entre nous", "soit dit en passant", "au passage", "en passant", "incidemment", "accessoirement", "subsidiairement", "secondairement", "marginalement", "superficiellement", "approximativement", "grossièrement", "vaguement", "confusément", "obscurément", "clairement", "nettement", "distinctement", "précisément", "exactement", "rigoureusement", "strictement", "littéralement", "textuellement", "mot pour mot", "au pied de la lettre", "à la lettre", "au sens propre", "au sens figuré", "métaphoriquement", "symboliquement", "allégoriquement", "ironiquement", "sarcastiquement", "humoristiquement", "plaisamment", "drôlement", "amusamment", "comiquement", "bizarrement", "étrangement", "curieusement", "singulièrement", "particulièrement", "spécialement", "exceptionnellement", "extraordinairement", "inhabituellement", "anormalement", "irrégulièrement", "illégalement", "légalement", "officiellement", "officieusement", "publiquement", "privément", "secrètement", "confidentiellement", "discrètement", "ouvertement", "franchement", "sincèrement", "honnêtement", "loyalement", "fidèlement", "scrupuleusement", "consciencieusement", "soigneusement", "attentivement", "minutieusement", "méticuleusement", "précautionneusement", "prudemment", "sagement", "raisonnablement", "logiquement", "rationnellement", "intelligemment", "astucieusement", "habilement", "adroitement", "savamment", "expertement", "professionnellement", "techniquement", "pratiquement", "concrètement", "effectivement", "réellement", "véritablement", "authentiquement", "genuinement", "sincèrement", "spontanément", "naturellement", "instinctivement", "intuitivement", "automatiquement", "mécaniquement", "systématiquement", "méthodiquement", "organisé", "structuré", "planifié", "prévu", "programmé", "calculé", "délibéré", "intentionnel", "volontaire", "conscient", "réfléchi", "pensé", "étudié", "analysé", "examiné", "observé", "regardé", "vu", "aperçu", "remarqué", "noté", "constaté", "découvert", "trouvé", "rencontré", "croisé", "tombé sur", "buté sur", "achoppé sur", "échoué sur", "raté", "manqué", "loupé", "foiré", "planté", "merdé", "déconné", "fait n'importe quoi", "n'importe quoi", "nawak", "ohlala", "oh là là", "mon dieu", "mon dieu", "seigneur", "jésus", "christ", "putain", "merde", "bordel", "zut", "flûte", "mince", "crotte", "purée", "saperlipopette", "sacrebleu", "morbleu", "palsambleu", "ventrebleu", "corbleu", "tudieu", "pardieu", "ma foi", "dame", "fichtre", "diantre", "que diable", "diable", "peste", "tonnerre", "sacré", "sacrée", "fichu", "fichue", "foutu", "foutue", "satané", "satanée", "maudit", "maudite", "damné", "damnée"}  # fmt: skip

DEFAULT_SYSTEM_PROMPT_ROLE = ""

SYSTEM_PROMPT_TEMPLATES = {
    SystemPromptTypes.FACTUAL: """[INST] Tu es un assistant IA spécialisé dans la fourniture d'informations précises et factuelles. {assistant_role}
                                                Étapes d'analyse :
                                                1. Identifier les faits clés du contexte
                                                2. Extraire les informations pertinentes
                                                3. Vérifier la cohérence factuelle
                                                4. Présenter les informations clairement et de manière concise
                                                
                                                Contexte : {context}
                                                
                                                Question : {question}
                                                
                                                Fournis une réponse factuelle claire en t'appuyant sur le contexte : [/INST]""",
    SystemPromptTypes.ANALYTICAL: """[INST] Tu es un assistant IA spécialisé dans l'analyse approfondie. {assistant_role}
                                                Étapes d'analyse :
                                                1. Identifier l'objectif principal et les contraintes
                                                2. Décomposer les exigences clés et les paramètres
                                                3. Rechercher des informations factuelles pertinentes à la requête
                                                4. Vérifier l'exactitude des noms, lieux et détails spécifiques
                                                5. Examiner les relations entre les faits et le contexte fourni
                                                6. Synthétiser des renseignements pertinents à la situation de l'utilisateur
                                                7. Tirer des conclusions basées sur des preuves vérifiées
                                                                                               
                                                Contexte : {context}
                                                                                               
                                                Question : {question}
                                                                                               
                                                Fournis une analyse approfondie qui combine précision factuelle et renseignements analytiques en t'appuyant sur le contexte : [/INST]""",
    SystemPromptTypes.COMPARATIVE: """[INST] Tu es un assistant IA spécialisé dans l'analyse comparative. {assistant_role}
                                                Étapes d'analyse :
                                                1. Identifier les éléments à comparer
                                                2. Examiner les similitudes et différences
                                                3. Évaluer les forces/faiblesses comparativement
                                                4. Tirer des conclusions nuancées
                                                
                                                Contexte : {context}
                                                
                                                Question : {question}
                                                
                                                Fournis une analyse comparative en t'appuyant sur le contexte : [/INST]""",
    SystemPromptTypes.CAUSAL: """[INST] Tu es un assistant IA spécialisé dans l'analyse causale. {assistant_role}
                                                Étapes d'analyse :
                                                1. Identifier les relations de cause à effet
                                                2. Examiner les facteurs contribuants
                                                3. Analyser les implications et conséquences
                                                4. Établir les chaînes de causalité
                                                
                                                Contexte : {context}
                                                
                                                Question : {question}
                                                
                                                Explique les relations causales en t'appuyant sur le contexte : [/INST]""",
    SystemPromptTypes.HYPOTHETICAL: """[INST] Tu es un assistant IA spécialisé dans le raisonnement hypothétique. {assistant_role}
                                                Étapes d'analyse :
                                                1. Considérer les hypothèses conditionnelles
                                                2. Analyser les scénarios potentiels
                                                3. Évaluer les implications
                                                4. Tirer des conclusions logiquement déduites
                                                
                                                Contexte : {context}
                                                
                                                Question : {question}
                                                
                                                Explore ce scénario en t'appuyant sur le contexte : [/INST]""",
    SystemPromptTypes.NAIVE: """[INST] Tu es un assistant IA spécialisé dans la fourniture d'informations précises et détaillées. {assistant_role}
                                                Concentre-toi sur les informations importantes qui traitent directement du sujet ou de la question principale.
                                                Inclue des détails pertinents qui fournissent un contexte ou appuient tes arguments.
                                                Veille à ce que les informations soient intéressantes en faisant attention à l'exactitude, la précision, l'exhaustivité, la concision, la clarté, la pertinence, l'objectivité et la résonance émotionnelle.

                                                Ta tâche consiste à répondre à la question suivante en te basant sur le contexte donné :
                                                {context}
                                                
                                                Question : {question}
                                                
                                                Réponse : [/INST]""",
    SystemPromptTypes.TRIVIAL: """[INST] Tu es un assistant conversationnel amical. {assistant_role} Si il y a une conversation précédente ci-dessous, garde-la à l'esprit. Sinon, réponds simplement au message court de l'utilisateur de manière naturelle (salutation, remerciements, adieu, etc.). Ne fournis PAS d'informations supplémentaires au-delà de ce qui est approprié pour le message de l'utilisateur.

{context}

Utilisateur: {question}
Assistant: [/INST]""",
}

PROMPT_SECTIONS_TO_REMOVE = [
    r"Étapes d'analyse\s*:((.|\n)*?)(?=Contexte?\s*\d*\s*:)",
    r"Contexte?\s*\d*\s*:((.|\n)*?)(?=Question\s*:)",
]
PROMPT_PHRASES_TO_REMOVE = [
    r"Tu es un assistant IA spécialisé dans .*",
    r"Tu es un assistant conversationnel amical.*",
    r"Inclue des détails pertinents qui fournissent un contexte ou appuient tes arguments.",
    r"Veille à ce que les informations soient intéressantes en faisant attention à l'exactitude, la précision, l'exhaustivité, la concision, la clarté, la pertinence, l'objectivité et la résonance émotionnelle qui leur sont propres.",
    r"Ta tâche consiste à répondre à la question suivante en te basant sur le contexte donné.",
    r"Question\s*:.*",
    r"Utilisateur\s*:.*",
    r"Fournis .*? en t'appuyant sur le contexte :",
    r"Explique .*? en t'appuyant sur le contexte :",
    r"Explore .*? en t'appuyant sur le contexte :",
    r"Réponse\s*:\s*",
    r"Assistant\s*:\s*",
]
