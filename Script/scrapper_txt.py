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



