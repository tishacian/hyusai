# Generative-AI-Question-Answer-End-to-End-LLM-Project

This LLM project is based on google-flan-t5-base (https://huggingface.co/google/flan-t5-base) and it is utilized for answering questions given any document context. By running the App, you can upload any pdf document then getting a reply for any question that is related to your document. I utilized the following packages: LangChain , FAISS, HuggingFace, Docker, AWS EC2, GitHub action, and Streamlit.

# To use
1. Lunch and connect your AWS EC2 instance, add the following context to the secrects actions: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION
2. Install docker on your EC2 instance as follows:
```bash
    sudo apt-get update -y
    sudo apt-get upgrade
```
```bash
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    sudo usermod -aG docker ubuntu
    newgrp docker
```
3. Add the self-hosted runner commands from Github to your EC2 instance.
4. Add the port number in the .ymal file (here 5000)  to your EC2 instance.
5. Run the github actions and then access the web-app using the Public IPv4 address of your EC2 instance followed by the port number (e.g. 55.55.555.55:5000).
