#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sun Mar  2 06:21:51 2025

@author: kennethezukwoke
"""
from typing import List
from langchain.docstore.document import Document
from langchain.document_loaders import UnstructuredEmailLoader


# %% custom loaders


class MyEmlLoader(UnstructuredEmailLoader):
    """Wrapper to fallback to text/plain when default does not work"""

    def load(self) -> List[Document]:
        try:
            try:
                doc = UnstructuredEmailLoader.load(self)
            except ValueError as e:
                if "text/html content not found in email" in str(e):
                    self.unstructured_kwargs["content_source"] = "text/plain"
                    doc = UnstructuredEmailLoader.load(self)
                else:
                    raise
        except Exception as e:
            raise type(e)(f"{self.file_path}: {e}") from e
        return doc
