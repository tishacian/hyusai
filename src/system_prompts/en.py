from src.globalvariables import ReasoningType
from src.system_prompts.types import SystemPromptTypes

REASONING_PATTERNS = {
    ReasoningType.FACTUAL: ["what", "who", "where", "when", "which", "list", "describe", "define", "identify", "specify", "verify", "confirm", "show", "demonstrate", "belongs to", "consists of", "contains", "comprises", "how many", "how much", "how often", "how long", "properties of", "characteristics", "features", "attributes", "categorize", "classify", "group", "type of"],
    ReasoningType.ANALYTICAL: ["how", "analyze", "examine", "investigate", "evaluate", "assess", "appraise", "review", "break down", "dissect", "decrypt", "decode", "pattern", "trend", "relationship", "correlation", "justify", "validate", "prove", "substantiate", "solve", "resolve", "determine", "figure out", "function", "operate", "work", "process", "interpret", "understand", "comprehend", "grasp"],
    ReasoningType.COMPARATIVE: ["compare", "contrast", "differ", "distinguish", "similar", "alike", "resemble", "parallel", "versus", "vs", "difference", "distinction", "better", "worse", "stronger", "weaker", "rank", "rate", "grade", "score", "prefer", "choice", "select", "opt", "more than", "less than", "equal to", "greater than", "advantage", "disadvantage", "pro", "con"],
    ReasoningType.CAUSAL: ["why", "because", "cause", "effect", "result", "outcome", "consequence", "impact", "lead to", "follow from", "derive from", "stem from", "influence", "affect", "determine", "shape", "trigger", "initiate", "spark", "prompt", "cascade", "chain", "sequence", "series", "factor", "contributor", "driver", "determinant", "strong", "weak", "direct", "indirect"],
    ReasoningType.HYPOTHETICAL: ["if", "would", "could", "might", "assume", "suppose", "presume", "consider", "predict", "forecast", "project", "estimate", "scenario", "situation", "case", "instance", "possible", "probable", "likely", "potential", "alternative", "option", "choice", "path", "risk", "chance", "probability", "likelihood", "what if", "otherwise", "alternatively", "instead"],
}  # fmt: skip
TRIVIAL_VOCABULARY = {"hello", "hi", "hey", "yo", "sup", "good morning", "good afternoon", "good evening", "howdy", "greetings", "how are you", "how are ya", "thanks", "thank you", "thx", "ty", "merci", "gracias", "cool, thanks", "ok, thanks", "great, thanks", "morning", "evening", "good noon", "good eve", "gm", "gn", "thank u", "thanx", "thnx", "thanks a lot", "thank you so much", "appreciate it", "much obliged", "cheers", "cheers mate", "ta", "hiya", "wassup", "thanks a ton", "how are you doing today", "good night", "night", "nite", "sleep well", "sweet dreams", "see ya", "see you", "bye", "goodbye", "farewell", "catch ya later", "later", "peace", "peace out", "take care", "have a good one", "until next time", "ttyl", "brb", "is", "it", "you", "your", "you're", "you've", "you'll", "you'd", "in", "at", "to", "of", "and", "or", "but", "if", "be right back", "one sec", "hold on", "wait up", "just a minute", "give me a sec", "hang tight", "bear with me", "sorry", "my bad", "oops", "whoops", "my apologies", "excuse me", "pardon", "forgive me", "apologies", "no worries", "no problem", "dont mention it", "you're welcome", "anytime", "my pleasure", "glad to help", "happy to help", "sure thing", "of course", "absolutely", "definitely", "for sure", "yep", "yeah", "yes", "yup", "uh huh", "right on", "sounds good", "okay", "ok", "alright", "fine", "not bad", "decent", "fair enough", "i see", "got it", "understood", "makes sense", "right", "bingo", "that's it", "you got it", "spot on", "on point", "nailed it", "well done", "good job", "nice work", "keep it up", "way to go", "congrats", "congratulations", "well played", "impressive", "goodnight", "adios", "ciao", "au revoir", "sayonara", "cheerio", "toodles", "so long", "talk soon", "solid", "tight", "clean", "smooth", "slick", "fresh", "crisp", "sharp", "on fleek", "tell me about it", "you said it", "couldnt agree more", "totally", "completely", "entirely", "wholly", "utterly", "fully", "100%", "all the way", "through and through", "to the core", "without a doubt", "no question", "hands down", "by far", "thats for sure", "you bet", "you betcha", "quite so", "quite", "somewhat", "kind of", "sort of", "more or less", "roughly", "approximately", "about", "around", "nearly", "almost", "close to", "just about", "not bad at all", "never", "not ever", "at no time", "under no circumstances", "by no means", "not at all", "not in the least", "not one bit", "not a chance", "no way", "forget it", "dream on", "in your dreams", "fat chance", "when pigs fly", "over my dead body", "not if i can help it", "not on my watch", "not happening", "aint gonna happen", "nope", "nah", "negative", "nada", "zilch", "nothing", "none", "neither", "nor", "however", "nevertheless", "nonetheless", "still", "yet", "though", "although", "even though", "despite", "in spite of", "regardless", "anyway", "anyhow", "in any case", "at any rate", "either way", "one way or another", "somehow", "someway", "whatever", "whenever", "wherever", "whoever", "whomever", "whichever", "why not", "sure why not", "why not indeed", "indeed why not", "what the heck", "what the hell", "why the hell not", "might as well", "could be worse", "better than nothing", "something is better than nothing", "half a loaf is better than none", "beggars cant be choosers", "take what you can get", "it is what it is", "such is life", "thats life", "life goes on", "cest la vie", "what can you do", "what are you gonna do", "whatcha gonna do", "whaddya gonna do", "what else is new", "same old same old", "nothing new under the sun", "been there done that", "story of my life", "tell me something i dont know", "no kidding", "you dont say", "are you serious", "are you kidding me", "youve got to be kidding", "you must be joking", "pull the other one", "get out of here", "get outta here", "no way jose", "come on", "come off it", "give me a break", "cut it out", "knock it off", "stop it", "quit it", "enough", "thats enough", "im done", "im out", "i gotta go", "anyone", "someone", "somebody", "i", 'a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'j', 'k', 'l', 'm', 'n', 'o', 'p', 'q', 'r', 's', 't', 'u', 'v', 'w', 'x', 'y', 'z', "I'm", "I've", "I'll", "I'd", "re", "im", "ive", "ill", "id", "youre", "youve", "gotta run", "thank you very much", "hey there how are you doing today", "hello there good sir hope everything is okay", "thank you very much that was very helpful", "don", "dont", "didnt", "couldn", "couldnt", "shouldnt", "wont", "for", "from", "as", "by", "that", "this", "these", "those", "them", "their", "theirs", "not", "no", "got", "be", "me", "out", "outta", "outta here", "outta there", "our", "ours", "yours", "anybody", "anybody there", "anybody there?", "my", "anywhere", "somewhere", "everywhere", "have", "has", "had", "off", "with", "we", "we're", "we've", "we'll", "we'd", "went", "without", "on", "need", "should", "would", "could", "might", "may", "can", "must", "mustn't", "mustn", "mustnt", "ought", "oughtn't", "oughtnt", "gotta", "gotta go", "anything", "something", "ve", "was", "were", "sometime", "sometimes", "time to go"}  # fmt: skip

DEFAULT_SYSTEM_PROMPT_ROLE = ""

SYSTEM_PROMPT_TEMPLATES = {
    SystemPromptTypes.FACTUAL: """[INST] You are an AI assistant specialized in providing precise and factual information. {assistant_role}
                                                Analysis Steps:
                                                1. Identify key facts from context
                                                2. Extract relevant information
                                                3. Verify factual consistency
                                                4. Present information clearly and concisely
                                                
                                                Context: {context}
                                                
                                                Question: {question}
                                                
                                                Provide a clear factual response based on the context: [/INST]""",
    SystemPromptTypes.ANALYTICAL: """[INST] You are an AI assistant specialized in detailed analysis. {assistant_role}
                                                Analysis Steps:
                                                1. Identify the core goal and constraints
                                                2. Break down key requirements and parameters
                                                3. Research factual information relevant to the query
                                                4. Verify accuracy of names, locations, and specific details
                                                5. Examine relationships between facts and context provided
                                                6. Synthesize insights relevant to user's situation
                                                7. Draw conclusions based on verified evidence
                                                                                               
                                                Context: {context}
                                                                                               
                                                Question: {question}
                                                                                               
                                                Provide a thorough analysis that combines factual accuracy with analytical insights based on the context: [/INST]""",
    SystemPromptTypes.COMPARATIVE: """[INST] You are an AI assistant specialized in comparative analysis. {assistant_role}
                                                Analysis Steps:
                                                1. Identify elements for comparison
                                                2. Examine similarities and differences
                                                3. Evaluate relative strengths/weaknesses
                                                4. Draw balanced conclusions
                                                
                                                Context: {context}
                                                
                                                Question: {question}
                                                
                                                Compare and contrast based on the context: [/INST]""",
    SystemPromptTypes.CAUSAL: """[INST] You are an AI assistant specialized in causal analysis. {assistant_role}
                                                Analysis Steps:
                                                1. Identify cause-effect relationships
                                                2. Examine contributing factors
                                                3. Analyze implications and consequences
                                                4. Establish causal chains
                                                
                                                Context: {context}
                                                
                                                Question: {question}
                                                
                                                Explain the causal relationships based on the context: [/INST]""",
    SystemPromptTypes.HYPOTHETICAL: """[INST] You are an AI assistant specialized in hypothetical reasoning. {assistant_role}
                                                Analysis Steps:
                                                1. Consider given conditions
                                                2. Analyze potential scenarios
                                                3. Evaluate implications
                                                4. Draw reasoned conclusions
                                                
                                                Context: {context}
                                                
                                                Question: {question}
                                                
                                                Explore this scenario based on the context: [/INST]""",
    SystemPromptTypes.NAIVE: """[INST] You are an AI assistant specialized in providing precise and detailed information. {assistant_role}
                                                Focus on important information that directly addresses the main topic or question.
                                                Include relevant details that provide context or support your points.
                                                Ensure the information is engaging by highlighting unique accuracy, precision, completeness, conciseness, clarity, relevance, objectivity, and emotional resonance.

                                                Your task is to answer the following question based on the given context:
                                                {context}

                                                Question: {question}

                                                Answer: [/INST]""",
    SystemPromptTypes.TRIVIAL: """[INST] You are a friendly conversational assistant. {assistant_role} If there is any previous conversation below, keep it in mind. Otherwise just answer the user's short message naturally (greeting, thanks, farewell, etc.). Do NOT provide additional information beyond what is appropriate for the user's message.

{context}

User: {question}
Assistant: [/INST]""",
}

SYSTEM_PROMPT_SECTIONS_TO_REMOVE = [
    r"Analysis Steps\s*:(.*?)(?=Context\s*\d*\s*:)",
    r"Context\s*\d*\s*:(.*?)(?=Question\s*:)",
]
SYSTEM_PROMPT_PHRASES_TO_REMOVE = [
    r"You are an AI assistant specialized in .*",
    r"You are a friendly conversational assistant.*",
    r"Include relevant details that provide context or support your points.",
    r"Ensure the information is engaging by highlighting unique accuracy, precision, completeness, conciseness, clarity, relevance, objectivity, and emotional resonance.",
    r"Your task is to answer the following question based on the given context.",
    r"Question\s*:.*",
    r"User\s*:.*",
    r"Provide .*? based on the context:",
    r"Compare .*? based on the context:",
    r"Explain .*? based on the context:",
    r"Explore .*? based on the context:",
    r"Answer\s*:\s*",
    r"Assistant\s*:\s*",
]
