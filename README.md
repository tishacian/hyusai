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
pip install -r requirements/requirements.txt
```

Launch the webapp on localhost:
```
python main.py
```

### Contribution guidelines ###

* Writing tests
* Code review
* Other guidelines

### Who do I talk to? ###

* Repo owner or admin
* Other community or team contact