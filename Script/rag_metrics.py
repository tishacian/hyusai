#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue May 20 10:24:56 2024

@author: kennethezukwoke
"""

import threading
import time

import torch

# --
from sentence_transformers import SentenceTransformer, util
from sklearn.metrics.pairwise import cosine_similarity
from transformers import GPT2LMHeadModel, GPT2Tokenizer, pipeline

# %% Starter...init

nli_pipeline_model = [
    "xlnet-large-cased",  # returns some accuracy score for a label
    "vish88/xlnet-base-mnli-finetuned",  # returns some accuracy score for a label
    "facebook/bart-large-mnli",  # computes entailment
    "typeform/distilbert-base-uncased-mnli",  # compute entailment
]

# -- for computing fleuncy et al.
model_name = "gpt2"
model_evaluator = GPT2LMHeadModel.from_pretrained(model_name)
tokenizer = GPT2Tokenizer.from_pretrained(model_name)
qa_model = pipeline("text2text-generation", model="facebook/bart-large-cnn")
embedding_model = SentenceTransformer("sentence-transformers/all-mpnet-base-v2")
nli_model = pipeline(
    "text-classification",
    model=nli_pipeline_model[2],
)  # to compute factuality et al.


# %%


# Function to calculate perplexity
def perplexity(generated_text, tokenizer, model):
    if not generated_text.strip():
        return float("inf")  # Return a high perplexity for empty text
    # Encoding
    encodings = tokenizer(
        generated_text,
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
def fluency(generated_text, tokenizer, model, result, lock):
    """
    Fluency is a measures the grammatical fluency of the generated response.

    Parameters
        generated_tex (str): model generated text.
        tokenizer (Tokenizer type): Tokenizer model
        LLM Evaluator model (Model): LLM Evaluation model
        result (str): result dictionary
        lock (Thread): Thread

    Returns
    None: Coherence
    """
    ppl = perplexity(generated_text, tokenizer, model)
    min_ppl = 10
    max_ppl = 100
    norm_perplexity = max(min(ppl, max_ppl), min_ppl)
    fluency_ = (max_ppl - norm_perplexity) / (max_ppl - min_ppl)
    with lock:
        result["fluency"] = fluency_


# # Function to calculate latency
# def latency(start_time, end_time, result, lock):
#     """
#     Latency is the inference computational time

#     Parameters
#         start_time (time): start time.
#         end_time (time): end time.
#         result (str): result dictionary
#         lock (Thread): Thread

#     Returns (time): final inference time. The lower the better.
#     """
#     result_value = end_time - start_time
#     with lock:
#         result["latency"] = result_value


# Function to calculate coherence
def coherence(generated_text, embedding_model, result, lock):
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
    embeddings = embedding_model.encode(sentences, convert_to_tensor=True)
    coherence_scores = [
        cosine_similarity(
            [embeddings[i].cpu().numpy()], [embeddings[i + 1].cpu().numpy()]
        )[0][0]
        for i in range(len(sentences) - 1)
    ]
    coherence_value = sum(coherence_scores) / (len(coherence_scores) + 1e-8)
    with lock:
        result["coherence"] = coherence_value


# Function to calculate relevance
def relevance(question, generated_text, embedding_model, result, lock):
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
    question_embedding = embedding_model.encode(question, convert_to_tensor=True)
    response_embedding = embedding_model.encode(generated_text, convert_to_tensor=True)
    similarity = util.pytorch_cos_sim(question_embedding, response_embedding).item()
    with lock:
        result["relevance"] = similarity


# %% Factuality,  Consistency and HHEM require knowledge of source text --> We can use the document for this or tavily for search online
# Imagine if we have no idea of the source response (aka ground-truth)? Coin N-inputs from source document for evaluation. --> Tavily it.


# Function to calculate factuality
def factuality(generated_text, source_texts, nli_model, result, lock):
    """
    Consistency measures the factual alignment between the anwer and the context.

    Parameters
        generated_text (str): generated text
        source_texts (str): Source text
        nli (torch model): Natural Language inference model
        result (str): result dictionary
        lock (Thread): Thread

    Returns
    None: Factuality score, higher is better
    """
    nli_scores = []
    for source_text in source_texts:
        result_nli = nli_model(f"{generated_text} entails {source_text}")
        score = result_nli[0]["score"] if result_nli[0]["label"] == "entailment" else 0
        nli_scores.append(score)
    factuality_value = max(nli_scores) if len(nli_scores) > 0 else 0
    with lock:
        result["factuality"] = factuality_value


# Function to calculate consistency
def consistency(generated_text, source_texts, embedding_model, result, lock):
    """
    Consistency measures the factual alignment between the anwer and the context.

    Parameters
        generated_text (str): generated text
        source_texts (str): Source text
        embedding_model (torch model): Embedding model
        result (str): result dictionary
        lock (Thread): Thread

    Returns
    None: Consistency score, higher is better
    """
    generated_embedding = embedding_model.encode(generated_text, convert_to_tensor=True)
    source_embeddings = embedding_model.encode(source_texts, convert_to_tensor=True)
    similarities = [
        util.pytorch_cos_sim(generated_embedding, src_embed)
        for src_embed in source_embeddings
    ]
    consistency_value = max(similarities).item()
    with lock:
        result["consistency"] = consistency_value


# Function to calculate HHEM
def HHEM(generated_text, source_texts, nli_model, embedding_model, result, lock):
    """
    Computes the HHEM (Hallucination Evaluation Metric) for the generated text.

    Parameters:
        generated_text (str): The text generated by the model.
        source_texts (list of str): List of source documents to compare against.
        nli (torch model): Natural Language inference model
        embedding_model (torch model): Embedding model
        result (str): result dictionary
        lock (Thread): Thread

    Returns:
    None: The hallucination score between 0 and 1. The lower the better
    """
    nli_scores = []
    for s_text in source_texts:
        result_nli = nli_model(f"{generated_text} entails {s_text}")
        nli_scores.append(
            result_nli[0]["score"] if result_nli[0]["label"] == "entailment" else 0
        )
    mean_nli_score = torch.mean(torch.tensor(nli_scores), dtype=torch.float32).item()
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
    with lock:
        result["hhem"] = hhem_score


# Function to calculate Advanced HHEM
def Advance_HHEM(
    generated_text,
    source_texts,
    question,
    nli_model,
    embedding_model,
    qa_model,
    result,
    lock,
):
    """
    Computes the Advanced HHEM (Adv. Hallucination Evaluation Metric) for the generated text.

    Parameters:
        generated_text (str): The text generated by the model.
        source_texts (list of str): List of source documents to compare against.
        nli (torch model): Natural Language inference model
        QA model (torch model): Text2Text generaion model
        embedding_model (torch model): Embedding model
        result (str): result dictionary
        lock (Thread): Thread

    Returns:
    None: The hallucination score between 0 and 1. The lower the better
    """
    nli_scores = []
    for source_text in source_texts:
        result_nli = nli_model(
            inputs=generated_text,
        )
        entailment_score = (
            result_nli[0]["score"] if result_nli[0]["label"] == "entailment" else 0
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
    )
    with lock:
        result["adv_hhem"] = hhem_score


# %%


def Evaluatrix(
    generated_text,
    tokenizer,
    model,
    embedding_model,
    nli_model,
    qa_model,
    source_texts,
    question,
    start_time,
):
    result = {}
    lock = threading.Lock()

    # -- list of threaded metrics
    threads = [
        threading.Thread(
            target=fluency, args=(generated_text, tokenizer, model, result, lock)
        ),
        # threading.Thread(target = latency,
        #                  args = (start_time, end_time, result, lock)),
        threading.Thread(
            target=coherence, args=(generated_text, embedding_model, result, lock)
        ),
        threading.Thread(
            target=relevance,
            args=(question, generated_text, embedding_model, result, lock),
        ),
        threading.Thread(
            target=factuality,
            args=(generated_text, source_texts, nli_model, result, lock),
        ),
        threading.Thread(
            target=consistency,
            args=(generated_text, source_texts, embedding_model, result, lock),
        ),
        threading.Thread(
            target=HHEM,
            args=(
                generated_text,
                source_texts,
                nli_model,
                embedding_model,
                result,
                lock,
            ),
        ),
        # --
        # threading.Thread(target = Advance_HHEM,
        #                  args = (generated_text, source_texts, question, nli_model, embedding_model, qa_model, result, lock)),
    ]
    # -- Start thread
    for thread in threads:
        thread.start()
    # -- Parallelize
    for thread in threads:
        thread.join()

    end_timme = time.time()
    result["latency"] = end_timme - start_time
    # --
    return result


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
