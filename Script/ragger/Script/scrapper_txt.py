#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed May 15 11:21:38 2024

@author: kennethezukwoke
"""
import os
from os.path import join
import requests
from bs4 import BeautifulSoup
import re
import pandas as pd
import numpy as np
from itertools import chain
from urllib.parse import urljoin

data_path = '/Users/kennethezukwoke/Documents/Datategy/Kenneth/ragger/Data'

#%% Download domain names from wiki tables

def download_tables_from_wiki(url, table_class):
    table_ = []
    response = requests.get(url)
    if response.status_code == 200:
        soup = BeautifulSoup(response.text, 'html.parser')
        tables = soup.find_all('table', {'class': table_class})
        for i, table in enumerate(tables):
            df = pd.read_html(str(table))
            df = pd.DataFrame(df[0])
            table_.append(df)
    return table_

def extractwebsite_links(wikiurl, table_class,):
    tables = download_tables_from_wiki(wikiurl, table_class)
    exatract_urls = list(chain(*[tables[i].iloc[:, 0].values for i in range(len(tables))]))
    exatract_urls = [str(i).replace(".", '') for i in exatract_urls]
    return exatract_urls


# wikiurl = "https://en.wikipedia.org/wiki/List_of_Internet_top-level_domains"
# table_class = "wikitable"
# urls = extractwebsite_links(wikiurl, table_class,)
# np.save(join(data_path, 'url.npy'), urls)
        
#%% utilities for web scrapping...

def extract_data_from_site(url):
    response = requests.get(url)
    if response.status_code == 200:
        soup = BeautifulSoup(response.content, 'html.parser')
        # Extracting text from the webpage
        text = soup.get_text()
        return text
    else:
        print("Failed to retrieve page:", url)
        return None

def download_pdf(url, folder_path):
    output_counter, ignore_couter = 0, 0
    response = requests.get(url)
    soup= BeautifulSoup(response.text, "html.parser")     
    for link in soup.select("a[href$='.pdf']"):
        #Name the pdf files using the last portion of each link which are unique in this case
        filename = os.path.join(folder_path, link['href'].split('/')[-1])
        if 'environnement' in filename:
            with open(filename, 'wb') as f:
                f.write(requests.get(urljoin(url, link['href'])).content)
            print("Downloaded PDF:", filename)
            output_counter += 1
        else:
            ignore_couter += 1
            print("Not interested in pdf", url)
    print("-"*50)
    print(f'PDF downloaded: {output_counter}\nPDF ignored: {ignore_couter}')
    
def get_all_links(url, http, main_com):
    response = requests.get(url)
    if response.status_code == 200:
        soup = BeautifulSoup(response.content, 'html.parser')
        links = soup.find_all('a', href=True)
        abs_links = [link['href'] for link in links]
        # Filter out only the links within the domain
        abs_links = [link for link in abs_links if re.match(fr'^{http}?://{main_com[0]}\.{main_com[1]}/', link)]
        return abs_links
    else:
        print("Failed to retrieve page:", url)
        return []

def scrapper_url(url, http, main_com, pdf = False):
    all_links = set([url])
    visited_links = set()
    while all_links:
        link = all_links.pop()
        if link not in visited_links:
            visited_links.add(link)
            if pdf:
                download_pdf(link, join(data_path, 'pdfs'))
            else:
                text = extract_data_from_site(link)
                if text:
                    with open(join(data_path, f'{main_com[0]}.txt'), 'a', encoding = 'utf-8') as f:
                        f.write(text)
                        f.write('\n\n')
                    print("Scraped:", link)
                    new_links = get_all_links(link, http, main_com)
                    all_links.update(new_links)
               
#%% scrap all text format types and pdf from websites...

if __name__ == "__main__":
    # website_url = "https://safengy.com/our-skills/environmental-french-regulation/"
    domain = list(np.load(join(data_path, 'url.npy'), allow_pickle = True)) + ['www', 'gouv', 'fr']
    websites_ = ['https://www.diplomatie.gouv.fr/en/french-foreign-policy/climate-and-environment/',
                  'https://safengy.com/our-skills/environmental-french-regulation/',
                  'https://www.ecologie.gouv.fr',
                  'https://codes.droit.org/',
                  ]
    pdf = False
    for site in websites_:
        splitted = [i for i in site.split('/') if i!='']
        http = splitted[0]
        main_com = splitted[1].split('.')
        main_com_sep = ''.join([i for i in main_com if not i in domain])
        main_com_inc = '.'.join([i for i in main_com if i in domain if i != 'www'])
        main_ = (main_com_sep, main_com_inc)
        scrapper_url(site, http, main_, pdf = pdf)

#%%

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


#%% Scrap the pdf --> Save pdf based on codes title L. 101- et al. 

import fitz
import string
import tika
tika.initVM()
from tika import parser #extract text from pdf


pdf_path = '/Users/kennethezukwoke/Documents/Datategy/Kenneth/ragger/Data/pdfs'
    
    
def method_scrap_all(path, filename:str = None):
    assert os.path.exists(path), "File path does not exist"
    if filename == None:
        return
    if filename.endswith(".pdf"):
        filename = "Code de l'environnement.pdf"
        filename = filename
        raw = parser.from_file(join(pdf_path, filename))
        text = raw['content']
        text = text.replace('\n', ' ')
    elif filename.endswith(".txt"):
        filename = filename
        with open(join(path, filename), 'r+', encoding = "utf8") as st:
            text = st.read()
        text = text.replace('\n', ' ')
    else:
        raise ValueError("Unknown file type", filename)
    return text

text = method_scrap_all(pdf_path, "Code de l'environnement.pdf")

with open(join(pdf_path, "extracted_text.txt"), "w") as text_file:
    text_file.write(text)
    
                
#%%             
                
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
""".replace('\n', '')


#%%

parts = re.split(r'(L\. \d+-\d+ |R\. \d+-\d+-\d+-\d+)', samp_text)

# Remove empty strings and leading/trailing whitespaces from parts
parts = [part.strip() for part in parts if part.strip()]

articles = []
# Print each part separately
for i, part in enumerate(parts, 1):
    # articles.append((i,part))
    print(f"Part {i}:")
    print(part)
    print()
#%%
articles = []
for i, j in enumerate((parts)):
    if j.startswith('L. ') or j.startswith('R. '):
        env_codes_ = ' '.join([parts[i], parts[i+1]])
        articles.append(env_codes_)
    print(f"Part {i}:")
    print(part)
    print()
    
#%% Extract the codes..

save_env_codes_txt = '/Users/kennethezukwoke/Documents/Datategy/Kenneth/ragger/Data/pdfs/environmental_codes'

with open(join(pdf_path, "extracted_text.txt"), "r+") as text_file:
    text_file_r = text_file.read()
    
def extractEnvCodes(text, save_dir):
    parts = re.split(r'(L\. \d+-\d+ |R\. \d+-\d+-\d+-\d+)', text)
    parts = [part.strip() for part in parts if part.strip()]
    articles = []
    for i, j in enumerate((parts)):
        if j.startswith('L. ') or j.startswith('R. '):
            env_codes_ = ' '.join([parts[i], parts[i+1]])
            articles.append(env_codes_)
        #--check if directory exists
        if not os.path.exists(save_dir):
            os.makedirs(save_dir)
        #--Save env codes
        with open(join(save_dir, f"{i}.txt"), "w") as text_file:
            text_file.write(env_codes_)
    return articles
            
#%%

articles = extractEnvCodes(text_file_r, save_env_codes_txt)
    