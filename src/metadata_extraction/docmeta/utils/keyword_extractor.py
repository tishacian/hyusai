"""
Utility for keyword extraction.
"""
from typing import List, Optional
import re
from sklearn.feature_extraction.text import TfidfVectorizer #TODO remove this import for testing purposes only 

# Attempt to import TfidfVectorizer
try:
    from sklearn.feature_extraction.text import TfidfVectorizer
except ImportError:
    TfidfVectorizer = None
    print("Warning: scikit-learn not found. TF-IDF keyword extraction will not be available.")

# A list of French stop words. 
# This list can be expanded for more comprehensive coverage or sourced from a dedicated NLP library.
# It includes common French stop words and words that appeared as non-keywords in example outputs.
FRENCH_STOP_WORDS = [
    'a', 'afin', 'ai', 'aie', 'aient', 'aies', 'ailleurs', 'ainsi', 'ait', 'allaient', 'allo', 'allons', 'allô', 
    'alors', 'anterieur', 'anterieure', 'anterieures', 'apres', 'après', 'as', 'assez', 'attendu', 'au', 'aucun', 
    'aucune', 'aucuns', 'aujourd', 'aujourdhui', 'aupres', 'auquel', 'aura', 'aurai', 'auraient', 'aurais', 'aurait', 
    'auras', 'aurez', 'auriez', 'aurions', 'aurons', 'auront', 'aussi', 'autre', 'autrefois', 'autrement', 'autres', 
    'autrui', 'aux', 'auxquelles', 'auxquels', 'avaient', 'avais', 'avait', 'avant', 'avec', 'avez', 'aviez', 
    'avions', 'avoir', 'avons', 'ayant', 'ayez', 'ayons', 'b', 'bah', 'bas', 'basee', 'bat', 'beau', 'beaucoup', 'bien', 
    'bigre', 'bon', 'boum', 'bravo', 'brrr', 'c', 'car', 'ce', 'ceci', 'cela', 'celle', 'celle-ci', 'celle-là', 'celles', 
    'celles-ci', 'celles-là', 'celui', 'celui-ci', 'celui-là', 'celà', 'cent', 'cependant', 'certain', 'certaine', 
    'certaines', 'certains', 'certes', 'ces', 'cet', 'cette', 'ceux', 'ceux-ci', 'ceux-là', 'chacun', 'chacune', 
    'chaque', 'cher', 'chers', 'chez', 'chiche', 'chut', 'chère', 'chères', 'ci', 'cinq', 'cinquantaine', 'cinquante', 
    'cinquantième', 'cinquième', 'clac', 'clic', 'combien', 'comme', 'comment', 'comparable', 'comparables', 'compris', 
    'concernant', 'contre', 'couic', 'crac', 'd', 'da', 'dans', 'de', 'debout', 'dedans', 'dehors', 'deja', 'delà', 
    'depuis', 'dernier', 'derniere', 'derriere', 'derrière', 'des', 'desormais', 'desquelles', 'desquels', 'dessous', 
    'dessus', 'deux', 'deuxième', 'deuxièmement', 'devant', 'devers', 'devra', 'devrait', 'different', 'differentes', 
    'differents', 'différent', 'différente', 'différentes', 'différents', 'dire', 'directe', 'directement', 'dit', 
    'dite', 'dits', 'divers', 'diverse', 'diverses', 'dix', 'dix-huit', 'dix-neuf', 'dix-sept', 'dixième', 'doit', 
    'doivent', 'donc', 'dont', 'dos', 'douze', 'douzième', 'dring', 'droite', 'du', 'duquel', 'durant', 'dès', 
    'début', 'désormais', 'e', 'effet', 'egale', 'egalement', 'egales', 'eh', 'elle', 'elle-même', 'elles', 'elles-mêmes', 
    'en', 'encore', 'enfin', 'entre', 'envers', 'environ', 'es', 'essai', 'est', 'et', 'etant', 'etc', 'etre', 'eu', 
    'eue', 'eues', 'euh', 'eurent', 'eus', 'eusse', 'eussent', 'eusses', 'eussiez', 'eussions', 'eut', 'eux', 'eux-mêmes', 
    'exactement', 'excepté', 'extenso', 'exterieur', 'f', 'fais', 'faisaient', 'faisant', 'fait', 'faites', 'façon', 
    'feront', 'fi', 'flac', 'floc', 'fois', 'font', 'force', 'furent', 'fus', 'fusse', 'fussent', 'fusses', 'fussiez', 
    'fussions', 'fut', 'fûmes', 'fût', 'fûtes', 'g', 'gens', 'h', 'ha', 'haut', 'hein', 'hem', 'hep', 'hi', 'ho', 'holà', 
    'hop', 'hormis', 'hors', 'hou', 'houp', 'hue', 'hui', 'huit', 'huitième', 'hum', 'hurrah', 'hé', 'hélas', 'i', 'ici', 
    'il', 'ils', 'importe', 'j', 'je', 'jusqu', 'jusque', 'juste', 'k', 'l', 'la', 'laisser', 'laquelle', 'las', 'le', 
    'lequel', 'les', 'lesquelles', 'lesquels', 'leur', 'leurs', 'longtemps', 'lors', 'lorsque', 'lui', 'lui-meme', 
    'lui-même', 'là', 'lès', 'm', 'ma', 'maint', 'maintenant', 'mais', 'malgre', 'malgré', 'maximale', 'me', 'meme', 
    'memes', 'merci', 'mes', 'mien', 'mienne', 'miennes', 'miens', 'mille', 'mince', 'minimale', 'moi', 'moi-meme', 
    'moi-même', 'moindres', 'moins', 'mon', 'moyennant', 'multiple', 'multiples', 'même', 'mêmes', 'n', 'na', 'naturelle', 
    'naturelles', 'ne', 'neanmoins', 'necessaire', 'necessairement', 'neuf', 'neuvième', 'ni', 'nombreuses', 'nombreux', 
    'nommés', 'non', 'nos', 'notamment', 'notre', 'nous', 'nous-mêmes', 'nouveau', 'nouveaux', 'nul', 'néanmoins', 'o', 
    'oh', 'ohé', 'ollé', 'olé', 'on', 'ont', 'onze', 'onzième', 'ore', 'ou', 'ouf', 'ouias', 'oust', 'ouste', 'outre', 
    'ouvert', 'ouverte', 'ouverts', 'o|', 'où', 'p', 'paf', 'pan', 'par', 'parce', 'parfois', 'parle', 'parlent', 'parler', 
    'parmi', 'parole', 'parseme', 'partant', 'particulier', 'particulière', 'particulièrement', 'pas', 'passé', 'pendant', 
    'pense', 'permet', 'personne', 'personnes', 'peu', 'peut', 'peuvent', 'peux', 'pff', 'pfft', 'pfut', 'pif', 'pire', 
    'pièce', 'plein', 'plouf', 'plupart', 'plus', 'plusieurs', 'plutôt', 'possessif', 'possessifs', 'possible', 'possibles', 
    'pouah', 'pour', 'pourquoi', 'pourrais', 'pourrait', 'pouvait', 'prealable', 'precisement', 'premier', 'première', 
    'premièrement', 'pres', 'probable', 'probante', 'procedant', 'proche', 'près', 'psitt', 'pu', 'puis', 'puisque', 'pur', 
    'pure', 'q', 'qu', 'quand', 'quant', 'quant-à-soi', 'quanta', 'quarante', 'quatorze', 'quatre', 'quatre-vingt', 
    'quatrième', 'quatrièmement', 'que', 'quel', 'quelconque', 'quelle', 'quelles', 'quelqu', 'quelque', 'quelques', 
    'quels', 'qui', 'quiconque', 'quinze', 'quoi', 'quoique', 'r', 'rare', 'rarement', 'rares', 'relative', 'relativement', 
    'remarquable', 'rend', 'rendre', 'restant', 'reste', 'restent', 'restrictif', 'retour', 'revoici', 'revoilà', 'rien', 
    's', 'sa', 'sacrebleu', 'sait', 'sans', 'sapristi', 'sauf', 'se', 'sein', 'seize', 'selon', 'semblable', 'semblaient', 
    'semble', 'semblent', 'sent', 'sept', 'septième', 'sera', 'serai', 'seraient', 'serais', 'serait', 'seras', 'serez', 
    'seriez', 'serions', 'serons', 'seront', 'ses', 'seul', 'seule', 'seulement', 'si', 'sien', 'sienne', 'siennes', 'siens', 
    'sinon', 'six', 'sixième', 'soi', 'soi-même', 'soient', 'sois', 'soit', 'soixante', 'sommes', 'son', 'sont', 'sous', 
    'souvent', 'specifique', 'specifiques', 'speculatif', 'stop', 'strictement', 'subtiles', 'suffisant', 'suffisante', 
    'suffit', 'suis', 'suit', 'suivant', 'suivante', 'suivantes', 'suivants', 'suivre', 'sujet', 'superpose', 'sur', 
    'surtout', 't', 'ta', 'tac', 'tandis', 'tant', 'tardive', 'te', 'tel', 'telle', 'tellement', 'telles', 'tels', 'tenant', 
    'tend', 'tenir', 'tente', 'tes', 'tic', 'tien', 'tienne', 'tiennes', 'tiens', 'toc', 'toi', 'toi-même', 'ton', 'touchant', 
    'toujours', 'tous', 'tout', 'toute', 'toutefois', 'toutes', 'treize', 'trente', 'tres', 'trois', 'troisième', 
    'troisièmement', 'trop', 'très', 'tsoin', 'tsouin', 'tu', 'té', 'u', 'un', 'une', 'unes', 'uniformement', 'unique', 
    'uniques', 'uns', 'v', 'va', 'vais', 'valeur', 'vas', 'vers', 'via', 'vif', 'vifs', 'vingt', 'vivat', 'vive', 'vives', 
    'vlan', 'voici', 'voie', 'voient', 'voilà', 'vont', 'vos', 'votre', 'vous', 'vous-mêmes', 'vu', 'vé', 'vôtre', 'vôtres', 
    'w', 'x', 'y', 'z', 'zut', 'à', 'ç', 'ça', 'ès', 'étaient', 'étais', 'était', 'étant', 'étante', 'étantes', 'étants', 
    'étiez', 'étions', 'été', 'étée', 'étées', 'étés', 'êtes', 'être', 'ô'
]


def clean_text_for_tfidf(text: str) -> str:
    """Basic text cleaning for TF-IDF."""
    if not text:
        return ""
    text = text.lower()
    text = re.sub(r'\d+', '', text)  # Remove numbers
    text = re.sub(r'\s+', ' ', text) # Normalize whitespace
    # Remove punctuation but keep intra-word hyphens/apostrophes for phrases
    text = re.sub(r'(?<!\w)[^\w\s\'\-]+(?<!\w)|(?<=\w)[^\w\s\'\-]+(?=\w)', '', text)
    text = text.strip()
    return text

def extract_keywords_tfidf(text: str, max_keywords: int = 10) -> Optional[List[str]]:
    """
    Extract keywords from text using TF-IDF.

    Args:
        text: The input text.
        max_keywords: The maximum number of keywords to return.

    Returns:
        A list of keywords, or None if extraction fails or text is empty.
    """
    if TfidfVectorizer is None:
        print("TF-IDF vectorizer not available (scikit-learn might be missing). Cannot extract keywords.")
        return None

    if not text or not text.strip():
        return None

    cleaned_text = clean_text_for_tfidf(text)
    if not cleaned_text:
        return None

    try:
        vectorizer = TfidfVectorizer(
            stop_words=FRENCH_STOP_WORDS, 
            max_features=max_keywords,
            ngram_range=(1, 2) # Consider unigrams and bigrams
        )
        
        vectorizer.fit_transform([cleaned_text])
        
        feature_names = vectorizer.get_feature_names_out()
        
        return list(feature_names)

    except Exception as e:
        print(f"Error during TF-IDF keyword extraction: {e}")
        return None 