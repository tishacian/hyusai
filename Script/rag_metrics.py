#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue May 20 10:24:56 2024

@author: kennethezukwoke
"""


import torch
from sentence_transformers import util
from sklearn.metrics.pairwise import cosine_similarity
from transformers import pipeline

# #%% Starter...init
nli_pipeline_model = [
    "xlnet-large-cased",  # returns some accuracy score for a label
    "vish88/xlnet-base-mnli-finetuned",  # returns some accuracy score for a label
    "facebook/bart-large-mnli",  # computes entailment
    "typeform/distilbert-base-uncased-mnli",  # compute entailment
]
# # language_tool = language_tool_python.LanguageTool('en-US')
# #-- for computing fleuncy
# model_name = 'gpt2'
# model = GPT2LMHeadModel.from_pretrained(model_name)
# tokenizer = GPT2Tokenizer.from_pretrained(model_name)
# qa_model = pipeline("text2text-generation", model="facebook/bart-large-cnn")
# embedding_model = SentenceTransformer('sentence-transformers/all-mpnet-base-v2')
nli_model = pipeline(
    "text-classification", model=nli_pipeline_model[3]
)  # to compute factuality

# %%


# -- Fluency v-2
def perplexity(generated_text, tokenizer, model):
    if not generated_text.strip():
        return float("inf")  # Return a high perplexity for empty text
    # -- encoding
    encodings = tokenizer(
        generated_text,
        # padding = True,
        # truncation = True,
        return_tensors="pt",
    )
    # --
    if encodings.input_ids.size(1) == 0:
        return float("inf")  # Return a high perplexity for improper encoding
    # --
    input_ids = encodings.input_ids
    """
    If you experience any IndexError: index out of range in self,
    Check that your propmpt has similar embedding impute size with the model.
    or simply truncate based on maximum token size. 
    """
    with torch.no_grad():
        outputs = model(input_ids, labels=input_ids)
        loss = outputs.loss
        perplexity = torch.exp(loss)
    return perplexity.item()


# Function to calculate fluency
def fluency(generated_text, tokenizer, model):
    ppl = perplexity(generated_text, tokenizer, model)
    # -- define a lower and upper bound for perplexity
    min_ppl = 10
    max_ppl = 100
    norm_perplexity = max(min(ppl, max_ppl), min_ppl)
    fluency_ = (max_ppl - norm_perplexity) / (max_ppl - min_ppl)
    return fluency_


# -- Latency
def latency(start_time, end_time):
    """
    Latency is the inference computational time

    Parameters
        start_time (time): start time.
        end_time (time): end time.

    Returns (time): final inference time. The lower the better.
    """
    return end_time - start_time


# - Coherence
def coherence(generated_text, embedding_model):
    """
    Coherence measures the formation of a cohesive body of text from the sentences.

    Parameters
        generated_tex (str): model generated text.
        embedding_model (torch model): embedding model

    Returns (float): Coherence
    """
    sentences = generated_text.split(".")
    embeddings = embedding_model.encode(sentences, convert_to_tensor=True)
    coherence_scores = [
        cosine_similarity(
            [embeddings[i].cpu().numpy()], [embeddings[i + 1].cpu().numpy()]
        )[0][0]
        for i in range(len(sentences) - 1)
    ]
    return sum(coherence_scores) / (len(coherence_scores) + 1e-8)


# - Relevance
def relevance(question, generated_text, embedding_model):
    """
    Relevance measure the factual alignment between anwser and response.

    Parameters
        question (str): input question
        generated_text (str): generated text
        embedding_model (torch model): Embedding model

    Returns (float): relevance similarity
    """
    question_embedding = embedding_model.encode(question, convert_to_tensor=True)
    response_embedding = embedding_model.encode(generated_text, convert_to_tensor=True)
    similarity = util.pytorch_cos_sim(question_embedding, response_embedding).item()
    return similarity


# %% Factuality,  Consistency and HHEM require knowledge of source text --> We can use the document for this or tavily for search online
# Imagine if we have no idea of the source response (aka ground-truth)? Coin N-inputs from source document for evaluation. --> Tavily it.


# --factuality
def factuality(generated_text, source_texts, nli_model):
    nli_scores = []
    for source_text in source_texts:
        result = nli_model(f"{generated_text} entails {source_text}")
        score = result[0]["score"] if result[0]["label"] == "entailment" else 0
        nli_scores.append(score)
    return max(nli_scores) if len(nli_scores) > 0 else 0


# -- Consistency
def consistency(generated_text, source_texts, embedding_model):
    """
    Consistency measures the factual alignment between the anwer and the context.

    Parameters
        generated_text (str): generated text
        source_texts (str): Source text
        embedding_model (torch model): Embedding model

    Returns
    Consistency (float): Consistency score, higher is better
    """
    generated_embedding = embedding_model.encode(generated_text, convert_to_tensor=True)
    source_embeddings = embedding_model.encode(source_texts, convert_to_tensor=True)
    similarities = [
        util.pytorch_cos_sim(generated_embedding, src_embed)
        for src_embed in source_embeddings
    ]
    return max(similarities).item()


# -- HHEM
def HHEM(generated_text, source_texts, nli_model, embedding_model):
    """
    Computes the HHEM (Hallucination Evaluation Metric) for the generated text.

    Parameters:
        generated_text (str): The text generated by the model.
        source_texts (list of str): List of source documents to compare against.

    Returns:
    hhem_score (float): The hallucination score between 0 and 1.
    """
    # Compute entailment scores using NLI
    nli_scores = []
    for s_text in source_texts:
        result = nli_model(f"{generated_text} entails {s_text}")
        nli_scores.append(
            result[0]["score"] if result[0]["label"] == "entailment" else 0
        )

    mean_nli_score = torch.mean(torch.tensor(nli_scores), dtype=torch.float32).item()
    # -- compute similarities
    generated_embedding = embedding_model.encode(generated_text, convert_to_tensor=True)
    source_embeddings = embedding_model.encode(source_texts, convert_to_tensor=True)
    similarities = [
        util.pytorch_cos_sim(generated_embedding, source_embedding).item()
        for source_embedding in source_embeddings
    ]
    mean_similarity_score = torch.mean(torch.tensor(similarities)).item()

    hhem_score = (mean_nli_score * mean_similarity_score) / (
        1 + mean_nli_score * mean_similarity_score
    )

    return hhem_score


# -- Advanced HHEM
def Advance_HHEM(
    generated_text, source_texts, question, nli_model, embedding_model, qa_model
):
    """
    Computes the advanced HHEM (Hallucination Evaluation Metric) for the generated text.

    Parameters:
        generated_text (str): The text generated by the model.
        source_texts (list of str): List of source documents to compare against.
        question (str): The original question or context for the generated response.

    Returns:
    hhem_score (float): The hallucination score (lower is better, indicating less hallucination).
    """
    # Compute entailment scores using NLI
    nli_scores = []
    for source_text in source_texts:
        result = nli_model(
            inputs=generated_text,
            # candidate_labels = ["entailment", "contradiction", "neutral"],
            # hypothesis_template = "This implies that {}."
        )

        entailment_score = (
            result[0]["score"] if result[0]["label"] == "entailment" else 0
        )
        nli_scores.append(entailment_score)

    mean_nli_score = torch.mean(torch.tensor(nli_scores, dtype=torch.float32)).item()
    generated_embedding = embedding_model.encode(generated_text, convert_to_tensor=True)
    source_embeddings = embedding_model.encode(source_texts, convert_to_tensor=True)
    similarities = [
        util.pytorch_cos_sim(generated_embedding, source_embedding).item()
        for source_embedding in source_embeddings
    ]

    mean_similarity_score = torch.mean(torch.tensor(similarities)).item()
    # Extract and validate key facts from the generated text
    facts_validated = 0
    facts_total = 0
    for sentence in generated_text.split("."):
        if sentence.strip():
            facts_total += 1
            qa_result = qa_model(question=question, context=sentence)
            for source_text in source_texts:
                if qa_result["answer"] in source_text:
                    facts_validated += 1
                    break

    fact_validation_score = facts_validated / facts_total if facts_total > 0 else 0
    hhem_score = 1 / (
        mean_similarity_score * mean_nli_score * fact_validation_score + 1e-8
    )  # Adding a small epsilon to avoid division by zero
    return hhem_score


# %% Download source of conversations to test here
# from os.path import join
# import json

# download_path = '/Users/kennethezukwoke/Downloads'
# with open(join(download_path, 'data.json'), 'rb') as filename:
#     docs_sec = json.load(filename)


# question = docs_sec[0]['question']
# anwser = docs_sec[0]['answer']
# documents = docs_sec[0]['document']

# #%%

# factuality_ = factuality(anwser, documents, nli_model)
# consistency_ = consistency(anwser, documents, embedding_model)
# hhem_ = HHEM(anwser, documents, nli_model, embedding_model)
# adv_hhem_ = Advance_HHEM(anwser, documents, question, nli_model, embedding_model, qa_model)

# print(f'Factuality: {factuality_:.2f}')
# print(f'Consistency: {consistency_:.2f}')
# print(f'HHEM: {hhem_:.2f}')
# print(f'Advance HHEM: {adv_hhem_:.2f}')

# %%
# from langchain_community.retrievers import TavilySearchAPIRetriever
# os.environ["TAVILY_API_KEY"] = "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"

# retriever = TavilySearchAPIRetriever(k = 4)

# question = [docs_sec[i]['question'] for i in range(len(docs_sec))]
# anwser = [docs_sec[i]['answer'] for i in range(len(docs_sec))]
# documents = [docs_sec[i]['document'] for i in range(len(docs_sec))]

# tavily_gen = {}
# for i, anwser_ in enumerate(anwser):
#     document = retriever.invoke(anwser_)
#     tavily_gen[f'{i}'] = document

# #%%

# factuality_max = []
# for (k, doc_file), anwser_ in zip(tavily_gen.items(), anwser):
#     if len(doc_file) == 0:
#         fact_score  = 0.0
#         factuality_max.append(fact_score)
#     else:
#         source_text = [i.page_content for i in doc_file] # text generated from the internet on the given assmption...
#         fact_score = factuality(anwser_, source_text, nli_model)
#         factuality_max.append(fact_score)
#         print(f'Maximum factuality: {fact_score:.2f}')
#         print()
