# OmniRAG

In this project, you will find a full-stack independant app called OmniRAG that enables its users to build knowledge bases from documents and to perform RAG (Retrival Augmented Generation) on them.
This product should be considered as a standalone, but compatibility to integrate operations to papAI should be kept in mind for middle term objective.

## How do I get set up?

For security reasons, you must clone this repo using an SSH key. You can follow [this guide](https://support.atlassian.com/bitbucket-cloud/docs/configure-ssh-and-two-step-verification/) from Atlassian to generate and add the SSH key to your account.

Once set up, you can safely clone this repository on your computer.

```
git clone git@bitbucket.org:datategy-root/omnirag.git
```

Check the [CONTRIBUTING.md](CONTRIBUTING.md) guide for to setup your dev environment as well as [docker/README.md](./docker/README.md) on how to start the stack.

## Contribution guidelines

Read the [CONTRIBUTING.md](CONTRIBUTING.md) file.

## Who do I talk to?

- RAG engine : [Kenneth](mailto:kenneth.ezukwoke@datategy.net)
- LLM as a Service : [Ahmed](mailto:ahmed.benmessaoud@datategy.net)
- Docker services, API : [Enzo](mailto:enzo.damion@datategy.net)

## Folder structure
The arrangment of files in the RAGGER folder :

```
📦 OmniRAG
├── 📜 README.md
├── 📂 benchmarking
│   ├── 📜 ...
│   ├── 📂 requirements
│   │   └── 📄 requirements.txt
│   └── 📜 resourcemonitor.py
├── 📂 configuration
│   ├── 📜 __init__.py
│   ├── 📜 backend.py
│   ├── 📜 general.py
│   ├── 📜 readme.md
│   ├── 📜 standalone_interface.py
│   └── 📜 vlm.py
├── 📂 data
│   ├── 📜 hkunlp_embeddings.npy
│   └── 📜 url_suffixes.npy
├── 📂 docker
│   ├── 💼 Dockerfile
│   ├── 📜 README.md
│   └── 📄 example.env
├── 📂 image
│   ├── 🖼 aitubo.jpg
│   └── 🖼 datategy_logo.png
├── 📜 install.sh
├── 📜 main.py
├── 📂 requirements
│   ├── 📄 cpu.txt
│   ├── 📄 gpu.txt
│   ├── 📄 shared.txt
│   └── 📄 standalone_interface.txt
├── 📂 src
│   ├── 📜 __init__.py
│   ├── 📜 cache.py
│   ├── 📜 chunker.py
│   ├── 📜 contextcompressor.py
│   ├── 📜 conversationmemorybuffer.py
│   ├── 📜 crossencembeddingmodel.py
│   ├── 📜 customchain.py
│   ├── 📜 customchain_naive.py
│   ├── 📜 customchainmixedhah.py
│   ├── 📜 customdocloader.py
│   ├── 📜 docloader.py
│   ├── 📜 embedding.py
│   ├── 📜 embeddingloader.py
│   ├── 📜 ensembleretriever.py
│   ├── 📜 flashreranker.py
│   ├── 📜 globalvariables.py
│   ├── 📜 hughes.py
│   ├── 📜 markdownconverter.py
│   ├── 📂 metadata_extraction
│   │   ├── 📜 README.md
│   │   ├── 📂 docmeta
│   │   │   ├── 📜 __init__.py
│   │   │   ├── 📂 core
│   │   │   │   ├── 📜 ...
│   │   │   ├── 📂 extractors
│   │   │   │   ├── 📜 ...
│   │   │   └── 📂 utils
│   │   │       ├── 📜 ...
│   │   └── 📜 manually_test_pdf.py
│   ├── 📜 metrics.py
│   ├── 📜 modeltokenizer.py
│   ├── 📜 ragger.py
│   ├── 📜 ragger_css.py
│   ├── 📂 reasoning_instructions
│   │   ├── 📜 __init__.py
│   │   ├── 📜 en.py
│   │   └── 📜 fr.py
│   ├── 📜 reasoningmetrics.py
│   ├── 📜 retrievalplan.py
│   ├── 📜 scrapper.py
│   ├── 📜 utils.py
│   └── 📜 vlmprocessor.py
└── 📂 vector_store (created upon indexing)
```
