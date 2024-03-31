import re
import sys
import math
import torch
import asyncio
import logging
from collections import Counter
import nltk
from nltk.corpus import wordnet
from nltk.tokenize import word_tokenize
from nltk.corpus import stopwords
from collections import defaultdict
from sentence_transformers import util
from sklearn.metrics.pairwise import cosine_similarity

# --
nltk.download("punkt")
nltk.download("wordnet")
nltk.download("stopwords")
nltk.download("averaged_perceptron_tagger")

# --
logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

# %%

DUMMY_METRICS = {
    "fluency": 0.0,
    "coherence": 0.0,
    "relevance": 0.0,
    "factuality": 0.0,
    "correctness": 0.0,
    "hhem": 0.0,
    "Advance_HHEM": 0.0,
}


# N-gram model
def _ngram_model(text, n=2):
    """N-gram model

    Parameters
        text (str) : input text
        n (int): n-tokens to use for n-gram evaluation. The default is 2.

    Raises
    ------
    ValueError
        Input value error is returned is input text is not string.

    Returns
    -------
    model (n-gram model): n-gram model

    """
    if not isinstance(text, str):
        raise ValueError("Input text must be a string")
    words = re.findall(r"\w+", text.lower())
    model = defaultdict(lambda: defaultdict(int))
    for i in range(len(words) - n + 1):
        context = tuple(words[i : i + n - 1])
        target = words[i + n - 1]
        model[context][target] += 1
    return model


# computes fluency
def calculate_fluency(text, model, n=2):
    words = re.findall(r"\w+", text.lower())
    total_log_prob = 0
    count = 0
    for i in range(n - 1, len(words)):
        context = tuple(words[i - n + 1 : i])
        target = words[i]
        if context in model and target in model[context]:
            prob = model[context][target] / sum(model[context].values())
            total_log_prob += math.log(prob)
            count += 1

    if count == 0:
        return 0

    average_log_prob = total_log_prob / count
    fluency = math.exp(average_log_prob)
    return fluency


# computes perplexity
async def perplexity(generated_text, tokenizer, model):
    """Perplexity

    Parameters
    ----------
        generated_text (str): generated input text
        tokenizer (Model): Tokenizer model
        model (Model): Huggingface Model

    Returns
    -------
    float
        Perplexity.
    """
    if not generated_text.strip():
        return float("inf")  # Return a high perplexity for empty text
    # Encoding
    encodings = tokenizer(generated_text, return_tensors="pt")
    if encodings.input_ids.size(1) == 0:
        return float("inf")  # Return a high perplexity for improper encoding
    input_ids = encodings.input_ids
    try:
        with torch.no_grad():
            outputs = model(input_ids, labels=input_ids)
            loss = outputs.loss
            perplexity = torch.exp(loss)
    except (ValueError, IndexError, IOError, KeyError, RuntimeError) as e:
        logging.error(
            f"🚩 A perplexity computation error occurred during computation: {str(e)}"
        )

    return perplexity.item()


# fluency based on llm
async def fluency_llm(generated_text, tokenizer, model):
    """
    Fluency is a measures the grammatical fluency of the generated response.

    Parameters
        generated_tex (str): model generated text.
        tokenizer (Tokenizer type): Tokenizer model
        LLM Evaluator model (Model): LLM Evaluation model
        result (str): result dictionary
        lock (Thread): Thread

    Returns
    None: fluency score using llm
    """
    ppl = await perplexity(generated_text, tokenizer, model)
    min_ppl = 10
    max_ppl = 100
    norm_perplexity = max(min(ppl, max_ppl), min_ppl)
    fluency_ = (max_ppl - norm_perplexity) / (max_ppl - min_ppl)
    return fluency_


# fluency based on n-grams
async def fluency_ngram(generated_text, reference_text, n_gram=3):
    """
    Fluency measures the grammatical fluency of the generated response.

    Parameters:
        generated_text (str): model generated text.
        reference_text (str): reference text to build the language model.
        n_gram (int): size of n-gram

    Returns:
        float: Fluency score using n-gram
    """
    model = _ngram_model(reference_text, n_gram)
    fluency_score = calculate_fluency(generated_text, model, n_gram)

    # Normalize the fluency score to a range between 0 and 1
    min_fluency = 0
    max_fluency = 1
    norm_fluency = max(min(fluency_score, max_fluency), min_fluency)
    normalized_fluency = (norm_fluency - min_fluency) / (
        max_fluency - min_fluency
    )

    return normalized_fluency


# computes fluency
async def fluency(
    generated_text,
    reference_text,
    method="ngram",
    n_gram=2,
    tokenizer=None,
    model=None,
):
    """
    Computes the fluency of the generated text using the specified method.

    Parameters:
        generated_text (str): The text generated by the model.
        reference_text (str): The reference text to build the language model (for n-gram).
        method (str): The method to use for fluency calculation ('ngram' or 'llm').
        n_gram (int): The n-gram size to use if method is 'ngram'.
        tokenizer: The tokenizer used for the LLM method.
        model: The language model used for the LLM method.

    Returns:
        float: Fluency score, higher is better.
    """
    if method == "ngram":
        return await fluency_ngram(generated_text, reference_text, n_gram)
    elif method == "llm":
        return await fluency_llm(generated_text, tokenizer, model)
    else:
        raise ValueError("Invalid method specified. Use 'ngram' or 'llm'.")


# computes coherence
async def coherence(generated_text, embedding_model):
    """
    Coherence measures the formation of a cohesive body of text from the sentences.

    Parameters
        generated_tex (str): model generated text.
        embedding_model (torch model): embedding model
        result (str): result dictionary
        lock (Thread): Thread

    Returns
    None: Coherence
    """
    sentences = generated_text.split(".")
    embeddings = embedding_model.encode(
        sentences, convert_to_tensor=True, show_progress_bar=False
    )
    coherence_scores = [
        cosine_similarity(
            [embeddings[i].cpu().numpy()], [embeddings[i + 1].cpu().numpy()]
        )[0][0]
        for i in range(len(sentences) - 1)
    ]
    coherence_value = sum(coherence_scores) / (len(coherence_scores) + 1e-8)
    return coherence_value


# computes relevance
async def relevance(question, generated_text, embedding_model):
    """
    Relevance measure the factual alignment between anwser and response.

    Parameters
        question (str): input question
        generated_text (str): generated text
        embedding_model (torch model): Embedding model
        result (str): result dictionary
        lock (Thread): Thread

    Returns
    None: relevance similarity
    """
    question_embedding = embedding_model.encode(
        question, convert_to_tensor=True, show_progress_bar=False
    )
    response_embedding = embedding_model.encode(
        generated_text, convert_to_tensor=True, show_progress_bar=False
    )
    similarity = util.pytorch_cos_sim(
        question_embedding, response_embedding
    ).item()
    return similarity


# %% Factuality,  Consistency and HHEM require knowledge of source text --> We can use the document for this or tavily for search online
# Imagine if we have no idea of the source response (aka ground-truth)? coin N-inputs from source document for evaluation. --> Tavily it.


# computes factuality
async def factuality(generated_text, source_texts, embedding_model):
    """
    Measures the factual alignment between the answer and the context using embedding similarity.

    Parameters:
        generated_text (str): generated text
        source_texts (list of str): Source texts
        embedding_model (SentenceTransformer): Embedding model

    Returns:
        float: Factuality score, higher is better
    """
    if not generated_text.strip() or not source_texts:
        return 0.0

    generated_embedding = embedding_model.encode(
        generated_text, convert_to_tensor=True, show_progress_bar=False
    )
    source_embeddings = embedding_model.encode(
        source_texts, convert_to_tensor=True, show_progress_bar=False
    )

    # Compute cosine similarities
    similarities = util.pytorch_cos_sim(generated_embedding, source_embeddings)

    # Use the max similarity as the entailment score
    entailment_score = (
        similarities.max().item() if similarities.numel() > 0 else 0.0
    )

    return entailment_score


# computes consistency
async def consistency(generated_text, source_texts, embedding_model):
    """
    Consistency measures the factual alignment between the answer and the context.
    Parameters
    generated_text (str): generated text
    source_texts (list of str): Source text
    embedding_model (SentenceTransformer): Embedding model
    Returns
    float: Consistency score, higher is better
    """
    if not generated_text.strip() or not source_texts:
        return 0.0  # Return 0 if inputs are empty

    generated_embedding = embedding_model.encode(
        generated_text, convert_to_tensor=True, show_progress_bar=False
    )
    if generated_embedding.dim() == 1:
        generated_embedding = generated_embedding.unsqueeze(0)

    if generated_embedding.size(0) == 0:  # Check if embedding is empty
        return 0.0

    source_embeddings = embedding_model.encode(
        source_texts, convert_to_tensor=True, show_progress_bar=False
    )
    if source_embeddings.size(0) == 0:  # Check if source embeddings are empty
        return 0.0

    similarities = util.pytorch_cos_sim(
        generated_embedding, source_embeddings
    )[0]
    consistency_value = (
        similarities.max().item() if similarities.numel() > 0 else 0.0
    )

    return consistency_value


# computes faithfullness
async def faithfulness(generated_text, reference_text):
    """
    Compute faithfulness by comparing the semantic similarity of the generated text to the reference text.

    Parameters:
        generated_text (str): The text generated by the model.
        reference_text (str): The original reference text.

    Returns:
        float: A faithfulness score between 0 and 1.
    """

    def preprocess(text):
        tokens = word_tokenize(text.lower())
        stop_words = set(stopwords.words("english"))
        return [
            token
            for token in tokens
            if token.isalnum() and token not in stop_words
        ]

    def semantic_similarity(word1, word2):
        synsets1 = wordnet.synsets(word1)
        synsets2 = wordnet.synsets(word2)
        max_similarity = 0
        for syn1 in synsets1:
            for syn2 in synsets2:
                similarity = syn1.path_similarity(syn2)
                if similarity and similarity > max_similarity:
                    max_similarity = similarity
        return max_similarity

    gen_tokens = preprocess(generated_text)
    ref_tokens = preprocess(reference_text)

    total_similarity = 0
    for gen_token in gen_tokens:
        max_token_similarity = max(
            semantic_similarity(gen_token, ref_token)
            for ref_token in ref_tokens
        )
        total_similarity += max_token_similarity

    faithfulness_score = (
        total_similarity / len(gen_tokens) if gen_tokens else 0
    )
    return min(faithfulness_score, 1)  # Ensure the score is between 0 and 1


# computes harmfullness
async def harmfulness(generated_text, harmful_words=None):
    """
    Compute harmfulness by checking for the presence of potentially harmful words or phrases.

    Parameters:
        text (str): The text to evaluate.
        harmful_words (list): A list of words or phrases considered harmful.

    Returns:
        float: A harmfulness score between 0 and 1.
    """
    if harmful_words is None:
        harmful_words = [
            "violence",
            "hate",
            "discrimination",
            "abuse",
            "threat",
            "harassment",
            "explicit",
            "offensive",
            "dangerous",
            "illegal",
        ]

    text_lower = generated_text.lower()
    word_count = len(re.findall(r"\w+", text_lower))

    harmful_word_count = sum(text_lower.count(word) for word in harmful_words)
    harmfulness_score = (
        harmful_word_count / word_count if word_count > 0 else 0
    )

    return min(harmfulness_score, 1)  # Ensure the score is between 0 and 1


# computes correctness
async def correctness(generated_text, reference_text, embedding_model):
    """
    Compute correctness by comparing the semantic similarity and key information
    between the generated text and the reference text.

    Parameters:
        generated_text (str): The text generated by the model.
        reference_text (str): The original reference text containing factual information.

    Returns:
        float: A correctness score between 0 and 1. Higher is better
    """

    async def extract_key_info(text):
        # Extract potential key phrases (e.g., noun phrases)
        words = text.split()
        bigrams = [" ".join(words[i : i + 2]) for i in range(len(words) - 1)]
        trigrams = [" ".join(words[i : i + 3]) for i in range(len(words) - 2)]
        return words + bigrams + trigrams

    # -- preprocess text
    gen_processed = re.sub(r"[^\w\s]", "", generated_text.lower())
    ref_processed = re.sub(r"[^\w\s]", "", reference_text.lower())

    # -- extract key information
    gen_key_info = await extract_key_info(gen_processed)
    ref_key_info = await extract_key_info(ref_processed)

    # -- compute information overlap (key information score)
    gen_counter = Counter(gen_key_info)
    ref_counter = Counter(ref_key_info)
    overlap = sum((gen_counter & ref_counter).values())
    total = sum(ref_counter.values())
    key_info_score = overlap / total if total > 0 else 0

    # -- compute semantic similarity using sentence embeddings
    gen_embedding = embedding_model.encode(
        [generated_text], convert_to_tensor=True, show_progress_bar=False
    )
    ref_embedding = embedding_model.encode(
        [reference_text], convert_to_tensor=True, show_progress_bar=False
    )

    # Compute cosine similarity between embeddings
    semantic_score = cosine_similarity(
        gen_embedding.cpu().numpy(), ref_embedding.cpu().numpy()
    )[0][0]

    # Combine scores (you can adjust the weights as needed)
    correctness_score = 0.5 * semantic_score + 0.5 * key_info_score

    return correctness_score


# computes hallucination metric
async def HHEM(generated_text, source_texts, embedding_model):
    """
    Computes the HHEM (Hallucination Evaluation Metric) for the generated text.

    Parameters:
        generated_text (str): The text generated by the model.
        source_texts (list of str): List of source documents to compare against.
        embedding_model (SentenceTransformer): Embedding model

    Returns:
        float: The hallucination score between 0 and 1. The lower the better
    """
    generated_embedding = embedding_model.encode(
        generated_text, convert_to_tensor=True, show_progress_bar=False
    )
    if generated_embedding.dim() == 1:
        generated_embedding = generated_embedding.unsqueeze(0)

    source_embeddings = embedding_model.encode(
        source_texts, convert_to_tensor=True, show_progress_bar=False
    )

    if source_embeddings.dim() == 1:
        source_embeddings = source_embeddings.unsqueeze(0)

    # Compute cosine similarities
    similarities = [
        util.pytorch_cos_sim(generated_embedding, source_embedding)[0]
        for source_embedding in source_embeddings
    ]

    mean_similarity_score = (
        torch.mean(torch.tensor(similarities)).item() if similarities else 0.0
    )
    factuality_score = await factuality(
        generated_text, source_texts, embedding_model
    )

    # Combine the scores
    hhem_score = (mean_similarity_score * factuality_score) / (
        1 + mean_similarity_score * factuality_score + 1e-8
    )

    return hhem_score


# computes the advanced hallucination metric
async def Advance_HHEM(
    generated_text, source_texts, question, embedding_model
):
    """
    Computes the Advanced HHEM (Adv. Hallucination Evaluation Metric) for the generated text.

    Parameters:
        generated_text (str): The text generated by the model.
        source_texts (list of str): List of source documents to compare against.
        question (str): The question posed to the model.
        embedding_model (SentenceTransformer): Embedding model

    Returns:
        float: The advance hallucination score between 0 and 1. The lower the better
    """
    generated_embedding = embedding_model.encode(
        generated_text, convert_to_tensor=True, show_progress_bar=False
    )

    if generated_embedding.dim() == 1:
        generated_embedding = generated_embedding.unsqueeze(0)

    source_embeddings = embedding_model.encode(
        source_texts, convert_to_tensor=True, show_progress_bar=False
    )
    if source_embeddings.dim() == 1:
        source_embeddings = source_embeddings.unsqueeze(0)

    similarities = [
        util.pytorch_cos_sim(generated_embedding, source_embedding).item()
        for source_embedding in source_embeddings
    ]
    mean_similarity_score = (
        torch.mean(torch.tensor(similarities)).item() if similarities else 0.0
    )
    factuality_score = await factuality(
        generated_text, source_texts, embedding_model
    )

    # -- additional checks for coherence and relevance
    coherence_score = await coherence(generated_text, embedding_model)
    relevance_score = await relevance(
        question, generated_text, embedding_model
    )

    # -- combined scores
    advanced_hhem_score = (
        mean_similarity_score
        * factuality_score
        * coherence_score
        * relevance_score
    ) / (1 + mean_similarity_score * factuality_score + 1e-8)

    return advanced_hhem_score


async def Evaluatrix(
    generated_text,
    source_texts,
    tokenizer,
    model,
    embedding_model,
    question,
    method,
    n_gram,
) -> dict:
    result = {}

    # --
    tasks = {
        "fluency": fluency(
            generated_text, source_texts, method, n_gram, tokenizer, model
        ),
        "coherence": coherence(generated_text, embedding_model),
        "relevance": relevance(question, generated_text, embedding_model),
        "factuality": factuality(
            generated_text, source_texts, embedding_model
        ),
        "correctness": correctness(
            generated_text,
            source_texts,
            embedding_model,
        ),
        "hhem": HHEM(generated_text, source_texts, embedding_model),
        "Advance_HHEM": Advance_HHEM(
            generated_text, source_texts, question, embedding_model
        ),
    }

    results = await asyncio.gather(*tasks.values())
    result.update(dict(zip(tasks.keys(), results)))
    return result
