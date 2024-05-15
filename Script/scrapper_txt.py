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

data_path = '/Users/kennethezukwoke/Documents/Datategy/Kenneth/ragger/Data'

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
    response = requests.get(url)
    if response.status_code == 200:
        # Get the filename from the URL
        filename = os.path.join(folder_path, url.split("/")[-1])
        with open(filename, 'wb') as f:
            f.write(response.content)
        print("Downloaded PDF:", filename)
    else:
        print("Failed to download PDF from:", url)
        
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

def scrapper_url(url, http, main_com):
    all_links = set([url])
    visited_links = set()
    while all_links:
        link = all_links.pop()
        if link not in visited_links:
            visited_links.add(link)
            if link.endswith('.pdf'):
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
                    
if __name__ == "__main__":
    # website_url = "https://safengy.com/our-skills/environmental-french-regulation/"
    websites_ = ['https://www.diplomatie.gouv.fr/en/french-foreign-policy/climate-and-environment/',
                  'https://safengy.com/our-skills/environmental-french-regulation/',
                  'https://www.ecologie.gouv.fr',
                  'https://codes.droit.org/',
                  
                  ]
    for site in websites_:
        splitted = [i for i in site.split('/') if i!='']
        http = splitted[0]
        main_com = splitted[1].split('.')
        scrapper_url(site, http, main_com)


