import re
from itertools import chain
from os import makedirs
from urllib.parse import urljoin

import numpy as np
import pandas as pd
import requests
from bs4 import BeautifulSoup

from globalvariables import DATA_PATH

# %% Download domain names from wiki tables


def download_tables_from_wiki(url, table_class):
    table_ = []
    response = requests.get(url)
    if response.status_code == 200:
        soup = BeautifulSoup(response.text, "html.parser")
        tables = soup.find_all("table", {"class": table_class})
        for i, table in enumerate(tables):
            df = pd.read_html(str(table))
            df = pd.DataFrame(df[0])
            table_.append(df)
    return table_


def extractwebsite_links(
    wikiurl,
    table_class,
):
    tables = download_tables_from_wiki(wikiurl, table_class)
    exatract_urls = list(
        chain(*[tables[i].iloc[:, 0].values for i in range(len(tables))])
    )
    exatract_urls = [str(i).replace(".", "") for i in exatract_urls]
    return exatract_urls


# wikiurl = "https://en.wikipedia.org/wiki/List_of_Internet_top-level_domains"
# table_class = "wikitable"
# urls = extractwebsite_links(wikiurl, table_class,)
# np.save(join(data_path, "url_suffixes.npy"), urls)

# %% utilities for web scrapping...


def extract_data_from_site(url):
    response = requests.get(url)
    if response.status_code == 200:
        soup = BeautifulSoup(response.content, "html.parser")
        # Extracting text from the webpage
        text = soup.get_text()
        return text
    else:
        print("Failed to retrieve page:", url)
        return None


def download_pdf(url, folder_path):
    output_counter, ignore_couter = 0, 0
    response = requests.get(url)
    soup = BeautifulSoup(response.text, "html.parser")
    for link in soup.select("a[href$='.pdf']"):
        # Name the pdf files using the last portion of each link which are unique in this case
        filename = folder_path / link["href"].split("/")[-1]
        if "environnement" in filename:
            with open(filename, "wb") as f:
                f.write(requests.get(urljoin(url, link["href"])).content)
            print("Downloaded PDF:", filename)
            output_counter += 1
        else:
            ignore_couter += 1
            print("Not interested in pdf", url)
    print("-" * 50)
    print(f"PDF downloaded: {output_counter}\nPDF ignored: {ignore_couter}")


def get_all_links(url, http, main_com):
    response = requests.get(url)
    if response.status_code == 200:
        soup = BeautifulSoup(response.content, "html.parser")
        links = soup.find_all("a", href=True)
        abs_links = [link["href"] for link in links]
        # Filter out only the links within the domain
        abs_links = [
            link
            for link in abs_links
            if re.match(rf"^{http}?://{main_com[0]}\.{main_com[1]}/", link)
        ]
        return abs_links
    else:
        print("Failed to retrieve page:", url)
        return []


def scrapper_url(url, http, main_com, pdf=False):
    all_links = set([url])
    visited_links = set()
    while all_links:
        link = all_links.pop()
        if link not in visited_links:
            visited_links.add(link)
            if pdf:
                download_pdf(link, DATA_PATH / "pdfs")
            else:
                text = extract_data_from_site(link)
                if text:
                    with open(
                        DATA_PATH / f"{main_com[0]}.txt", "a", encoding="utf-8"
                    ) as f:
                        f.write(text)
                        f.write("\n\n")
                    print("Scraped:", link)
                    new_links = get_all_links(link, http, main_com)
                    all_links.update(new_links)


# %% scrap all text format types and pdf from websites...

if __name__ == "__main__":
    # website_url = "https://safengy.com/our-skills/environmental-french-regulation/"
    domain = list(
        np.load(DATA_PATH / "url_suffixes.npy", allow_pickle=True)
    ) + [
        "www",
        "gouv",
        "fr",
    ]
    websites_ = [
        "https://www.diplomatie.gouv.fr/en/french-foreign-policy/climate-and-environment/",
        "https://safengy.com/our-skills/environmental-french-regulation/",
        "https://www.ecologie.gouv.fr",
        "https://codes.droit.org/",
    ]
    pdf = False
    for site in websites_:
        splitted = [i for i in site.split("/") if i != ""]
        http = splitted[0]
        main_com = splitted[1].split(".")
        main_com_sep = "".join([i for i in main_com if i not in domain])
        main_com_inc = ".".join(
            [i for i in main_com if i in domain if i != "www"]
        )
        main_ = (main_com_sep, main_com_inc)
        scrapper_url(site, http, main_, pdf=pdf)

# %%

# websites_ = ['https://www.diplomatie.gouv.fr/en/french-foreign-policy/climate-and-environment/',
#               'https://safengy.com/our-skills/environmental-french-regulation/',
#               'https://www.ecologie.gouv.fr',
#               'https://codes.droit.org/',
#               ]
# index = 3
# splitted = [i for i in websites_[index].split('/') if i!='']
# http = splitted[0]
# main_com = splitted[1].split('.')
# main_com_sep = ''.join([i for i in main_com if not i in domain])
# main_com_inc = '.'.join([i for i in main_com if i in domain if i != 'www'])
# main_ = (main_com_sep, main_com_inc)

# print(f'http: {http}\n{main_}')


# %% Scrap the pdf --> Save pdf based on codes title L. 101- et al.

import tika

tika.initVM()
from tika import parser  # extract text from pdf

PDF_PATH = DATA_PATH / "pdfs"


def method_scrap_all(path, filename: str = None):
    assert path.exists(), "File path does not exist"
    if filename == None:
        return
    if filename.endswith(".pdf"):
        filename = "Code de l'environnement.pdf"
        raw = parser.from_file(path, filename)
        text = raw["content"]
        text = text.replace("\n", " ")
    elif filename.endswith(".txt"):
        with open(path / filename, "r+", encoding="utf8") as st:
            text = st.read()
        text = text.replace("\n", " ")
    else:
        raise ValueError("Unknown file type", filename)
    return text


text = method_scrap_all(PDF_PATH, "Code de l'environnement.pdf")

with open(PDF_PATH / "extracted_text.txt", "w") as text_file:
    text_file.write(text)


# %%

samp_text = """
L. 110-5     Legif. Plan   Jp.C.Cass.   Jp.Appel   Jp.Admin.   Juricaf La République française réaffirme l'importance première de la contribution des territoires d'outre-mer à ses
caractéristiques propres, à sa richesse environnementale, à sa biodiversité ainsi qu'à son assise géostratégique. L'action de l'Etat concourt à la reconnaissance, à la préservation et à la mise en valeur des richesses biologiques, environnementales et patrimoniales des territoires d'outre-mer.
L. 110-6     Legif.   Plan   Jp.C.Cass.   Jp.Appel   Jp.Admin.   Juricaf En vue de mettre fin à l'importation de matières premières et de produits transformés dont la production a
contribué, directement ou indirectement, à la déforestation, à la dégradation des forêts ou à la dégradation d'écosystèmes naturels en dehors du territoire national, l'Etat élabore et met en œuvre une stratégie nationale de lutte contre la déforestation importée, actualisée au moins tous les cinq ans.
La plateforme nationale de lutte contre la déforestation importée mise en place dans le cadre de la stratégie mentionnée au premier alinéa vise à assister les entreprises et les acheteurs publics dans la transformation de leurs chaînes d'approvisionnement au profit de matières plus durables, traçables et plus respectueuses des forêts tropicales et des écosystèmes naturels, ainsi que des communautés locales et des populations autochtones qui en vivent.
L. 110-7     Legif.   Plan   Jp.C.Cass.   Jp.Appel   Jp.Admin.   Juricaf Dans le cadre de la stratégie nationale mentionnée à l'article L. 110-6, l'Etat se donne pour objectif de ne plus
acheter de biens ayant contribué directement à la déforestation, à la dégradation des forêts ou à la dégradation d'écosystèmes naturels en dehors du territoire national.
Cet objectif est décliné par décret, pour la période 2022-2026 puis pour chaque période de cinq ans.
R. 131-34-1-1     Legif.   Plan   Jp.C.Cass.   Jp.Appel   Jp.Admin.   Juricaf Nul ne peut être commissionné s'il n'est reconnu apte à un service actif et pénible et s'il n'a suivi préalablement
une formation spécialisée définie par le directeur général de l'Office français de la biodiversité et répondant notamment aux exigences de l'article R. 172-2.
R. 131-34-1-2   Legif.   Plan   Jp.C.Cass.   Jp.Appel   Jp.Admin.   Juricaf Les agents commissionnés et assermentés ayant définitivement cessé leurs fonctions peuvent recevoir
l'honorariat de leur dernier grade par décision du directeur général de l'office.
R. 131-34-1-3   Legif. Plan   Jp.C.Cass.   Jp.Appel   Jp.Admin.   Juricaf A titre exceptionnel, les agents commissionnés et assermentés peuvent, après avis de la commission
consultative paritaire ou de la commission administrative paritaire, faire l'objet des mesures suivantes
L. 594-2 au moins sur les dix années suivantes. La projection est réalisée selon un scénario de référence, des scénarios dégradés représentant des conditions détériorées de marché et des scénarios dégradés portant sur le montant ou l'échéancier des charges nucléaires. Au titre de la revue des risques identifiés prévue au premier alinéa, en ce qui concerne les risques relatifs à des événements ou conditions susceptibles d'affecter le montant ou l'échéancier des charges nucléaires correspondant à un groupe d'opérations donné, l'exploitant peut s'appuyer sur la réalisation d'une revue dédiée à ces risques durant les trois précédentes années à condition qu'il n'y ait pas eu de changement significatif de ces risques depuis ladite revue dédiée. Dans ce cas, l'exploitant réalise néanmoins une revue des risques identifiés associés aux interdépendances avec ce groupe d'opérations. A l'issue de l'évaluation interne des risques, l'exploitant analyse ses résultats, détermine et programme les actions appropriées pour améliorer la maîtrise des risques et les met en œuvre. 
R. 181-15 Décret n°2017-81 du 26 janvier 2017 - art. 1     Legif.   Plan   Jp.C.Cass.   Jp.Appel   Jp.Admin.   Juricaf Le dossier de demande d'autorisation environnementale est complété par les pièces, documents et informations
propres aux activités, installations, ouvrages et travaux prévus par le projet pour lequel l'autorisation est sollicitée ainsi qu'aux espaces et espèces faisant l'objet de mesures de protection auxquels il est susceptible de porter atteinte.
D. 594-11  Décret n°2020-830 du 1er juillet 2020 - art. 1      Legif.    Plan    Jp.C.Cass.    Jp.Appel    Jp.Admin.    Juricaf  I.-L'exploitant tient à jour un inventaire des actifs de couverture qui assure la traçabilité de chaque mouvement d'actif et est aisément consultable par l'autorité administrative. II.-L'exploitant transmet à l'autorité une synthèse de cet inventaire selon la périodicité suivante : -une fois tous les douze mois si la base de dispersion est inférieure à 100 millions d'euros ou si les actifs de couverture comprennent principalement des actifs mentionnés au 1° ou au 2° du II de l'article
D. 594-6 ; -une fois tous les trois mois dans les autres cas. En cas de recours à des instruments financiers à terme, cette transmission comprend également une synthèse du relevé mentionné à l'article R. 336-4 du code des assurances ainsi qu'une indication du nombre d'opérations à terme effectuées durant la période considérée et du montant notionnel cumulé correspondant, en les distinguant par catégorie d'instruments financiers à terme. L'autorité précise à l'exploitant la forme et le contenu de cette transmission. 
D. 594-12  Décret n°2020-830 du 1er juillet 2020 - art. 1      Legif.    Plan    Jp.C.Cass.    Jp.Appel    Jp.Admin.    Juricaf  I.-Pour l'établissement des documents comptables mentionnés à la section 2 du chapitre III du titre II du livre Ier du code de commerce et aux articles.
""".replace(
    "\n", ""
)


# %% Testing code extraction...

parts = re.split(
    r"(L\. \d+-\d+ |R\. \d+-\d+-\d+-\d+| L\. \d+-\d+|D\. \d+-\d+-\d+-\d+|R\. \d+-\d+|D\. \d+-\d+)",
    samp_text,
)
# parts = r'(L\. \d+-\d+|R\. \d+-\d+-\d+-\d+|D\. \d+-\d+)'

# Remove empty strings and leading/trailing whitespaces from parts
parts = [part.strip() for part in parts if part.strip()]

articles = []
for i, j in enumerate((parts)):
    if j.startswith("L. ") or j.startswith("R. ") or j.startswith("D. "):
        if len(parts[i + 1]) < 20:
            if len(articles) > 1:
                articles.append(articles[-1] + " " + j)
                del articles[-2]
            else:
                env_codes_ = ""
                pass
        else:
            env_codes_ = " ".join([parts[i], parts[i + 1]])
            articles.append(env_codes_)
    print(f"Part {i}:")
    print(j)
    print()

# %% Extract the codes..

save_env_codes_txt = PDF_PATH / "environmental_codes_fr"

with open(PDF_PATH / "extracted_text.txt", "r+") as text_file:
    text_file_r = text_file.read()


def extractEnvCodes(text, save_dir, save=False):
    """
    Function to exatract environmental French codes from the text file.

    Parameters
    ----------
    text : str
        complete text scrapped from the PDF.
    save_dir : str
        directory to save environmental codes.
    save : bool, optional
        Save environmental codes or not. The default is False.

    Returns
    -------
    articles : TYPE
        DESCRIPTION.

    """
    pattern = r"(L\. \d+-\d+ |R\. \d+-\d+-\d+-\d+| L\. \d+-\d+|D\. \d+-\d+-\d+-\d+|R\. \d+-\d+|D\. \d+-\d+)"
    parts = re.split(pattern, text)
    parts = [part.strip() for part in parts if part.strip()]
    articles = []
    for i, j in enumerate((parts)):
        if j.startswith("L. ") or j.startswith("R. ") or j.startswith("D. "):
            # -- check unavoidable abnormal splitting here..given the pattern
            if len(parts[i + 1]) < 20:
                if len(articles) > 1:
                    env_codes_ = articles[-1] + " " + j
                    articles.append(env_codes_)
                    del articles[-2]
                else:
                    env_codes_ = ""
                    pass
            else:
                env_codes_ = " ".join([parts[i], parts[i + 1]])
                articles.append(env_codes_)
        # -- check if directory exists
        if not save_dir.exists():
            makedirs(save_dir)
        # -- Save env codes
        if save:
            if len(env_codes_) > 0:
                with open(save_dir / f"{i}.txt", "w") as txt_file:
                    txt_file.write(env_codes_)
    return articles


# %% create blocks of environmental codes and save in respective txt file.

articles = extractEnvCodes(text_file_r, save_env_codes_txt, save=True)

# %% Load articles from local

articles = []

for files_ in list(save_env_codes_txt.iterdir()):
    with open(save_env_codes_txt / f"{files_}", "r+") as txt_file:
        articles.append(txt_file.read())

# %% Translate environmental codes from French to English

import nltk
from deep_translator import GoogleTranslator  # TODO: add to requirements


def googleTranslator(env_codes, g_translator):
    # translate sentence-by-sentence to avoid maximum token error...if avoidable for split
    # otherwise, call chunk function
    splitted_env_codes = nltk.tokenize.sent_tokenize(env_codes)
    translated = [g_translator.translate(i) for i in splitted_env_codes]
    translated = [i if i != None else "" for i in translated]
    return " ".join(translated)


def chunk_text(article, n, g_translator):
    chunk_size = len(article) // n
    chunks = [
        article[i : i + chunk_size] for i in range(0, len(article), chunk_size)
    ]
    chunked_translation = []
    for chk in chunks:
        splitted_env_codes = nltk.tokenize.sent_tokenize(chk)
        translated = [g_translator.translate(i) for i in splitted_env_codes]
        translated = [i if i != None else "" for i in translated]
        # print(type(translated))
        chunked_translation.append(
            " ".join(translated if translated != None else "")
        )
    return " ".join(chunked_translation if translated != None else "")


def translatee(
    articles,
    save_dir,
    source_lang="fr",
    target_lang="en",
    chunk_size=3,
    max_tok_size=2000,
    save=False,
):
    # --
    g_translator = GoogleTranslator(source=source_lang, target=target_lang)
    translated_articles = [
        (
            googleTranslator(i, g_translator)
            if len(i) < max_tok_size
            else chunk_text(i, chunk_size, g_translator)
        )
        for i in articles
    ]
    # -- check if directory exists
    if not save_dir.exists():
        makedirs(save_dir)
    # -- Save env codes
    if save:
        print(">>> saving... >>>")
        for i, translated_ in enumerate(translated_articles, 1):
            with open(save_dir, f"{i}.txt", "w") as txt_file:
                txt_file.write(translated_)
    return translated_articles


# %% Begin translation..

save_translated_art = PDF_PATH / "environmental_codes_en_all"
# maximum token size for Google translate is 3900, we use 3500 to avoid unnecessary errors
translated_articles = translatee(
    articles,
    save_translated_art,
    source_lang="fr",
    target_lang="en",
    chunk_size=3,
    max_tok_size=3500,
    save=True,
)

# %% Combine all translated codes in one code-book

translated_articles_joined = "\n".join(translated_articles)
with open(PDF_PATH / "environmental_code_en.txt", "w") as txt_file:
    txt_file.write(translated_articles_joined)

# %% scrap Hong-Kong University embeddings for all model names

import time

from selenium import webdriver  # TODO: add to requirements
from selenium.webdriver.common.by import By

url = "https://huggingface.co/hkunlp"


def hkuNLP(website):
    driver = webdriver.Chrome()
    driver.get(url)
    time.sleep(5)
    # Click on the "Expand" button
    expand_buttons = driver.find_elements(
        By.XPATH, '//button[contains(text(), "Expand")]'
    )
    for button in expand_buttons:
        driver.execute_script("arguments[0].click();", button)
        time.sleep(1)

    page_source = driver.page_source
    # --
    driver.quit()
    soup = BeautifulSoup(page_source, "html.parser")
    h4_tags = soup.find_all("h4")
    # -- extract model names...
    model_name = []
    for tag in h4_tags:
        print(model_name.append(tag.get_text()))
    model_name = [mod_ for mod_ in model_name if mod_.startswith("hkunlp")]
    return model_name


model_name_ = hkuNLP(url)

# %% save models from hkuNLP

np.save(DATA_PATH / "hkunlp_embeddings.npy", model_name_)

# %% load again..

model_name_ = list(
    np.load(DATA_PATH / "hkunlp_embeddings.npy", allow_pickle=True)
)

# %%
