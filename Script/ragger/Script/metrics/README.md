# R.A.G Evaluation metrics
-----------------------------------

- Fluency: Compute the fluency by counting grammatical errors and returns a fluency score. The score is obtained by first computing the perplexity (how reasonable a generated text) score of the LLM.
- Consistency: Computes the maximum cosine similarity between the generated text and source texts.
- Latency: Measures the time taken to generate the response.
- Coherence: Calculates the average cosine similarity between consecutive sentence embeddings in the generated text.
- Relevance: Computes the cosine similarity between the question and the generated text embeddings.
- Factuality: Uses an NLI model to check if the generated response is entailed by any of the source documents. The calculate_factuality function computes entailment scores and returns the highest score to indicate factuality.
- HHEM: The Hughes Hallucination Evaluation Metric (HHEM) is used to assess the degree of hallucination in generated text by comparing it with reference texts or factual sources. To compute this metric, we can leverage Natural Language Inference (NLI) models and textual similarity measures.
- Advance HHEM: Similar to the HHEM but uses the NLI model to ensure factual consistency; semantic similarity to compare the generated text and source documents and finally a QA model to validate specific facts extracted from the generated text.