# HotpotQA distractor subset

`hotpotqa_distractor_200.json` holds the first 200 questions of the HotpotQA
validation split (distractor setting) with their ten context paragraphs each
(1,991 distinct paragraphs) and the supporting facts.

- Dataset: HotpotQA — Zhilin Yang, Peng Qi, Saizheng Zhang, Yoshua Bengio,
  William W. Cohen, Ruslan Salakhutdinov, Christopher D. Manning.
  *HotpotQA: A Dataset for Diverse, Explainable Multi-hop Question Answering*,
  EMNLP 2018. <https://hotpotqa.github.io/>
- Paragraphs are excerpts of English Wikipedia articles.
- License: [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
  This subset is redistributed under the same license. The only change is the
  `file` field added to each paragraph (the document name used at ingestion).

The subset is frozen in the repository: the bench never downloads data at run
time.
