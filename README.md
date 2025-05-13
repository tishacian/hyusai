# README #

This README would normally document whatever steps are necessary to get your application up and running.

### What is this repository for? ###

* Quick summary
* Version
* [Learn Markdown](https://bitbucket.org/tutorials/markdowndemo)

### How do I get set up? ###

For security reasons, you must clone this repo using an SSH key. You can follow [this guide](https://support.atlassian.com/bitbucket-cloud/docs/configure-ssh-and-two-step-verification/) from Atlassian to generate and add the SSH key to your account.

Once set up, you can safely clone this repository on your computer.

```
git clone git@bitbucket.org:neuropolisteam/rag.git
```

#### Folder structure
The arrangment of files in the RAGGER folder

```
📦 RAG
├── 📜 README.md
├── 📂 benchmarking
├── 📂 data
│   ├── 📜 hkunlp_embeddings.npy
│   └── 📜 url_suffixes.npy
├── 📂 image
│   ├── 🖼 aitubo.jpg
│   └── 🖼 datategy_logo.png
├── 📜 install.sh
├── 📜 main.py
├── 📂 requirements
│   ├── 📄 shared.txt
│   ├── 📄 gpu.txt
│   ├── 📄 cpu.txt
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
│   ├── 📜 customdocloader.py
│   ├── 📜 docloader.py
│   ├── 📜 embedding.py
│   ├── 📜 embeddingloader.py
│   ├── 📜 ensembleretriever.py
│   ├── 📜 flashreranker.py
│   ├── 📜 globalvariables.py
│   ├── 📜 markdownpdfloader.py
│   ├── 📜 metrics.py
│   ├── 📜 modeltokenizer.py
│   ├── 📜 ragger.py
│   ├── 📜 ragger_css.py
│   ├── 📜 reasoningmetrics.py
│   └── 📜 scrapper.py
└── 📂 vector_store (created upon indexing)
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

### Contribution guidelines ###

The following are some guidelines on how new code should be written. Following these rules when submitting new code makes the review easier so new code can be integrated in less time.

#### While you are coding ####

- We follow the [PEP8](https://peps.python.org/pep-0008/) standard. Read it thoroughly.
- Use the [numpy docstring standard](https://numpydoc.readthedocs.io/en/latest/format.html#docstring-standard) in all your docstrings.
- Prefix your branch so that its content is clear. Read the [confluence page](https://datategy.atlassian.net/wiki/spaces/PAPAI/pages/294913/Git+Flow+Updates#Branch-naming-convention) on branch naming convention.
- Use the [conventional commit standard](https://www.conventionalcommits.org/en/v1.0.0/) in all your commits.

#### After you finished developing ####

- Create a Pull Request from your branch to `main`.
- Give a clear title to your PR. You can use the same prefix as for your branch.

### Who do I talk to? ###

* Repo owner or admin
* Other community or team contact