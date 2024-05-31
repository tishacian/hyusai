# R.A.G Evaluation metrics
---

### Fluency
Compute the fluency by counting grammatical errors and returns a fluency score. The score is obtained by first computing the perplexity (how reasonable a generated text) score of the LLM.

$\text{Fluency} = 1 - \frac{\text{Number of Grammatical Errors}}{\text{Number of Words}}$

To uses perplexity (PPL):

$\text{Fluency} = \frac{\text{Max PPL} - \min(\text{PPL}, \text{ Max PPL})}{\text{Max PPL} - \text{Min PPL}}$

### Consistency
Computes the maximum cosine similarity between the generated text and source texts.

$\text{Consistency} = \max(\text{Cosine Similarity}(E_g, E_s))$

Where:
- $E_g$ is the embedding of the generated text.
- $E_s$ is the embedding of each source text.

### Latency
Measures the time taken to generate the response.

$\text{Latency} = t_{\text{end}} - t_{\text{start}}$

Where:
- $t_{\text{end}}$ is the time at the end of the generation.
- $t_{\text{start}}$ is the time at the start of the generation.

### Coherence
Calculates the average cosine similarity between consecutive sentence embeddings in the generated text.

$\text{Coherence} = \frac{1}{N-1} \sum_{i=1}^{N-1} \text{Cosine Similarity}(E_{s_i}, E_{s_{i+1}})$

Where:
- $E_{s_i}$ is the embedding of the $i$-th sentence.
- $N$ is the total number of sentences in the generated text.


### Relevance
Computes the cosine similarity between the question and the generated text embeddings.


$\text{Relevance} = \text{Cosine Similarity}(E_q, E_g)$

Where:
- $E_q$ is the embedding of the question.
- $E_g$ is the embedding of the generated text.


### Factuality
Uses an NLI model to check if the generated response is entailed by any of the source documents. The calculate_factuality function computes entailment scores and returns the highest score to indicate factuality.

$\text{Factuality} = \max(\text{NLI Score}(G, S))$

Where:
- $G$ is the generated text.
- $S$ is each source document.
- The NLI score indicates the degree of entailment.

### HHEM
The Hughes Hallucination Evaluation Metric (HHEM) is used to assess the degree of hallucination in generated text by comparing it with reference texts or factual sources. To compute this metric, we can leverage Natural Language Inference (NLI) models and textual similarity measures.

$\text{HHEM} = \frac{1}{\text{Mean Similarity} \times \text{Mean NLI} + \epsilon}$

Where:
- $\text{Mean Similarity}$ is the average cosine similarity between generated text and source texts.
- $\text{Mean NLI}$ is the average entailment score.
- $\epsilon$ is a small constant to avoid division by zero.


### Advance HHEM
Similar to the HHEM but uses the NLI model to ensure factual consistency; semantic similarity to compare the generated text and source documents and finally a QA model to validate specific facts extracted from the generated text.

$\text{Advanced HHEM} = \frac{1}{\text{Mean Similarity} \times \text{Mean NLI} \times \text{Fact Validation} + \epsilon}$

Where:
- $\text{Mean Similarity}$ is the average cosine similarity between generated text and source texts.
- $\text{Mean NLI}$ is the average entailment score.
- $\text{Fact Validation}$ is the proportion of validated facts in the generated text.
- $\epsilon$ is a small constant to avoid division by zero (default for us is $1e-8$).

