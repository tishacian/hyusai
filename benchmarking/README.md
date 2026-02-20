# README #

This README is on using the benchmarking pipeline to reproduce the results in the internal report.

### What is this repository for? ###

* Quick summary
* Version
* [Learn Markdown](https://bitbucket.org/tutorials/markdowndemo)

### How do I get set up? ###

For security reasons, you must clone this repo using an SSH key. You can follow [this guide](https://support.atlassian.com/bitbucket-cloud/docs/configure-ssh-and-two-step-verification/) from Atlassian to generate and add the SSH key to your account.

Once set up, you can safely clone this repository on your computer.

```
git clone —-branch bench/benchmark git@bitbucket.org:neuropolisteam/rag.git
```

#### Folder structure
The arrangment of files in the benchmarking folder

```
📜 benchmarking
├── 📄 README.md
├── 📜 benchmarking.py
├── 📜 customchain_hah.py
├── 📜 customchain_hybrid.py
├── 📜 customchain_naive.py
├── 📜 extrametrics.py
├── 📂 requirements
│   └── 📄 requirements.txt
└── 📜 resourcemonitor.py
```

#### Bash installation
Run command
```
bash install.sh
```
Activate virtaul environment
```
source .venv/bin/activate
```
Launch the webapp on localhost:
```
python main.py
```

#### Scratch installation
Install python3.12 using [brew](https://docs.brew.sh/Installation) for MacOS for example:
```
brew install python@3.12
```

Create a virtual environment and install the dependencies:

```
python3.12 -m venv venv
source venv/bin/activate
pip install -r benchmarking/requirements/requirements.txt
```


### Running benchmarking and reproducing results ###
Depending on the RAG method of interest, Update the following in the part of the ```benchmarking.py``` script.

- For Naive RAG
```
from customchain_naive import CustomLLMChain  # change this for different pipeline [1]
```
- For Hybrid RAG
```
from customchain_hybrid import CustomLLMChain  # change this for different pipeline [1]
```
- For HAH RAG
```
from customchain_hah import CustomLLMChain  # change this for different pipeline [1]
```

Run the script to reproduce the results
```
python benchmarking.py
```

#### Average Evaluation Metrics of different RAG Methods

| Metric | HAH RAG | Hybrid RAG | Naive RAG |
|--------|---------|------------|------------|
| Latency (s) | **4.47 ± 2.28** | 12.60 ± 5.27 | 12.25 ± 3.73 |
| NDCG | 0.821 ± 0.178 | 0.821 ± 0.178 | 0.821 ± 0.178 |
| ROUGE-1 | 0.246 ± 0.397 | 0.452 ± 0.521 | 0.291 ± 0.483 |
| ROUGE-2 | 0.194 ± 0.389 | 0.431 ± 0.499 | 0.274 ± 0.483 |
| ROUGE-L | 0.246 ± 0.397 | 0.452 ± 0.521 | 0.291 ± 0.483 |
| Fluency | **0.895 ± 0.031** | 0.821 ± 0.067 | **0.923 ± 0.030** |
| Coherence | 0.198 ± 0.051 | **0.295 ± 0.027** | **0.321 ± 0.019** |
| Relevance | **0.715 ± 0.032** | 0.610 ± 0.073 | **0.729 ± 0.029** |
| Factuality | **0.745 ± 0.071** | 0.629 ± 0.030 | 0.554 ± 0.080 |
| Correctness | **0.645 ± 0.075** | 0.467 ± 0.024 | 0.360 ± 0.051 |
| HHEM | **0.354 ± 0.043** | 0.284 ± 0.019 | 0.236 ± 0.050 |
| Adv. HHEM | **0.047 ± 0.014** | 0.058 ± 0.009 | 0.055 ± 0.009 |

*Note: Bold values indicate best performing metrics. Values are presented as mean ± standard deviation.*

Datasets used: NQ [Kwiatkowski et al., 2019], TriviaQA [Joshi et al., 2017], HotpotQA [Yang et al., 2018], and NarrativeQA [Kociský et al., 2018]

#### Resource Usage Comparison of Different RAG Methods

| Method | CPU Usage (%) | Memory Usage (%) | CPU Power (W) | Energy Total (kWh) | CO2 Emissions (kg) | Carbon Intensity | GPU Util. (%) | GPU Mem. Used (MB) | GPU Mem. Max (MB) | GPU Mem. Total (MB) | GPU Power (W) |
|--------|--------------|-----------------|--------------|-------------------|-------------------|-----------------|--------------|------------------|-----------------|-------------------|--------------|
| **HAH RAG** | **6.73 ± 0.07** | **4.16 ± 0.04** | 4.25 ± 0.04 | **0.0097 ± 0.006** | **0.00068 ± 0.0004** | 70 | **80.96 ± 4.12** | 40408 ± 252 | 40425 | 46068 | **202.83 ± 9.51** |
| **Hybrid RAG** | 6.74 ± 0.01 | 4.19 ± 0.02 | **4.22 ± 0.05** | 0.0290 ± 0.017 | 0.00203 ± 0.001 | 70 | 85.78 ± 2.16 | **40389 ± 239** | **40399** | 46068 | 214.75 ± 5.12 |
| **Naive RAG** | 6.76 ± 0.03 | 4.19 ± 0.01 | 4.29 ± 0.06 | 0.0271 ± 0.013 | 0.00190 ± 0.001 | 70 | 86.31 ± 0.91 | 40399 ± 225 | 40409 | 46068 | 215.99 ± 2.44 |

*Note:*
- **Bold** values indicate best performing metrics. Values are presented as mean ± standard deviation
- Carbon Intensity measured in g CO2/kWh

*Datasets used:* NQ [Kwiatkowski et al., 2019], TriviaQA [Joshi et al., 2017], HotpotQA [Yang et al., 2018], and NarrativeQA [Kociský et al., 2018]
