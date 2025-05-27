from src.globalvariables import ReasoningType

REASONING_PATTERNS = {
    ReasoningType.FACTUAL: ["what", "who", "where", "when", "which", "list", "describe", "define", "identify", "specify", "verify", "confirm", "show", "demonstrate", "belongs to", "consists of", "contains", "comprises", "how many", "how much", "how often", "how long", "properties of", "characteristics", "features", "attributes", "categorize", "classify", "group", "type of"],
    ReasoningType.ANALYTICAL: ["how", "analyze", "examine", "investigate", "evaluate", "assess", "appraise", "review", "break down", "dissect", "decrypt", "decode", "pattern", "trend", "relationship", "correlation", "justify", "validate", "prove", "substantiate", "solve", "resolve", "determine", "figure out", "function", "operate", "work", "process", "interpret", "understand", "comprehend", "grasp"],
    ReasoningType.COMPARATIVE: ["compare", "contrast", "differ", "distinguish", "similar", "alike", "resemble", "parallel", "versus", "vs", "difference", "distinction", "better", "worse", "stronger", "weaker", "rank", "rate", "grade", "score", "prefer", "choice", "select", "opt", "more than", "less than", "equal to", "greater than", "advantage", "disadvantage", "pro", "con"],
    ReasoningType.CAUSAL: ["why", "because", "cause", "effect", "result", "outcome", "consequence", "impact", "lead to", "follow from", "derive from", "stem from", "influence", "affect", "determine", "shape", "trigger", "initiate", "spark", "prompt", "cascade", "chain", "sequence", "series", "factor", "contributor", "driver", "determinant", "strong", "weak", "direct", "indirect"],
    ReasoningType.HYPOTHETICAL: ["if", "would", "could", "might", "assume", "suppose", "presume", "consider", "predict", "forecast", "project", "estimate", "scenario", "situation", "case", "instance", "possible", "probable", "likely", "potential", "alternative", "option", "choice", "path", "risk", "chance", "probability", "likelihood", "what if", "otherwise", "alternatively", "instead"],
}  # fmt: skip

REASONING_INSTRUCTIONS = {
    ReasoningType.FACTUAL: """[INST] You are an AI assistant specialized in providing precise and factual information.
                                                Analysis Steps:
                                                1. Identify key facts from context
                                                2. Extract relevant information
                                                3. Verify factual consistency
                                                4. Present information clearly and concisely
                                                
                                                Context: {context}
                                                
                                                Question: {question}
                                                
                                                Provide a clear factual response based on the context: [/INST]""",
    ReasoningType.ANALYTICAL: """[INST] You are an AI assistant specialized in detailed analysis.
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
    ReasoningType.COMPARATIVE: """[INST] You are an AI assistant specialized in comparative analysis.
                                                Analysis Steps:
                                                1. Identify elements for comparison
                                                2. Examine similarities and differences
                                                3. Evaluate relative strengths/weaknesses
                                                4. Draw balanced conclusions
                                                
                                                Context: {context}
                                                
                                                Question: {question}
                                                
                                                Compare and contrast based on the context: [/INST]""",
    ReasoningType.CAUSAL: """[INST] You are an AI assistant specialized in causal analysis.
                                                Analysis Steps:
                                                1. Identify cause-effect relationships
                                                2. Examine contributing factors
                                                3. Analyze implications and consequences
                                                4. Establish causal chains
                                                
                                                Context: {context}
                                                
                                                Question: {question}
                                                
                                                Explain the causal relationships based on the context: [/INST]""",
    ReasoningType.HYPOTHETICAL: """[INST] You are an AI assistant specialized in hypothetical reasoning.
                                                Analysis Steps:
                                                1. Consider given conditions
                                                2. Analyze potential scenarios
                                                3. Evaluate implications
                                                4. Draw reasoned conclusions
                                                
                                                Context: {context}
                                                
                                                Question: {question}
                                                
                                                Explore this scenario based on the context: [/INST]""",
}
