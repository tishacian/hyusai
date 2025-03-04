#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Mar  4 07:43:14 2025

@author: kennethezukwoke
"""

import re
import string


class Preprocess:
    """
    Preprocessing handles document cleaning and formatting with markdown.
    """

    def __init__(self, document: str):
        """
        Initialize with document content

        Parameters:
            document (str): Raw document content
        """
        self.document = document

    def sentence_boundary(self, text, pos):
        """
        Determine if position is a semantic sentence boundary

        Paramerter
                text (str): input string
                pos (str): pos

        Returns:
                Preprocessed text
        """
        if pos > 0 and text[pos - 1] in ".!?":
            if pos > 2 and text[pos - 2 : pos].lower() in [
                "mr",
                "ms",
                "dr",
                "jr",
                "sr",
            ]:
                return False

            abbrs = [
                "inc.",
                "ltd.",
                "co.",
                "corp.",
                "vs.",
                "e.g.",
                "i.e.",
                "etc.",
                "fig.",
                "ca.",
                "cf.",
                "pg.",
                "pp.",
                "vol.",
                "rev.",
                "eq.",
                "no.",
            ]

            for abbr in abbrs:
                if (
                    pos >= len(abbr)
                    and text[pos - len(abbr) : pos].lower() == abbr
                ):
                    return False

            return True

        return False

    def break_sentences(self, text):
        """
        Split text into sentences

        Paramerter
                text (str): input string

        Returns:
                Preprocessed text
        """
        sentences = []
        current_sentence = []
        buffer = ""

        words = text.split()
        for i, word in enumerate(words):
            buffer += word + " "
            if (
                any(word.endswith(p) for p in [".", "!", "?", ":", ";"])
                and i < len(words) - 1
            ):
                if not any(
                    word.lower().endswith(abbr)
                    for abbr in [
                        "mr.",
                        "ms.",
                        "mrs.",
                        "dr.",
                        "jr.",
                        "sr.",
                        "inc.",
                        "ltd.",
                        "co.",
                        "corp.",
                        "vs.",
                        "e.g.",
                        "i.e.",
                        "etc.",
                        "fig.",
                        "ca.",
                        "cf.",
                        "pg.",
                        "pp.",
                        "vol.",
                        "rev.",
                        "eq.",
                        "no.",
                    ]
                ):
                    current_sentence.append(buffer.strip())
                    buffer = ""
                    if current_sentence:
                        sentences.append(" ".join(current_sentence))
                        current_sentence = []

        if buffer.strip():
            current_sentence.append(buffer.strip())

        if current_sentence:
            sentences.append(" ".join(current_sentence))

        return sentences

    def join_sentences(self, sentences):
        """
        Join sentences that were incorrectly split

        Paramerter
                text (str): input string

        Returns:
                Preprocessed text
        """
        if not sentences:
            return []

        result = [sentences[0]]

        for i in range(1, len(sentences)):
            current = sentences[i]
            previous = result[-1]
            if (
                current
                and current[0].islower()
                and previous
                and not previous.rstrip().endswith((".", "!", "?"))
            ):
                result[-1] = previous + " " + current
            else:
                result.append(current)

        return result

    def paragraph_formating(self, sentences):
        """
        Group sentences into logical paragraphs

        Paramerter
                text (str): input string

        Returns:
                Preprocessed text
        """
        if not sentences:
            return ""

        paragraphs = []
        current_paragraph = [sentences[0]]

        for i in range(1, len(sentences)):
            current = sentences[i]
            para_starters = [
                "however",
                "moreover",
                "furthermore",
                "in addition",
                "nevertheless",
                "therefore",
                "thus",
                "finally",
                "in conclusion",
                "to summarize",
                "consequently",
            ]

            is_new_para = False
            if any(
                current.lower().startswith(starter)
                for starter in para_starters
            ):
                is_new_para = True

            if (
                len(current.split()) < 8
                and current.rstrip()[-1] not in string.punctuation
            ):
                is_new_para = True

            if current.lstrip().startswith(("•", "*", "-", "1.", "2.", "3.")):
                is_new_para = True

            if is_new_para:
                paragraphs.append(" ".join(current_paragraph))
                current_paragraph = [current]
            else:
                current_paragraph.append(current)

        if current_paragraph:
            paragraphs.append(" ".join(current_paragraph))

        return "\n\n".join(paragraphs)

    def headers_formating(self, text):
        """
        Identify and format potential headers with markdown

        Paramerter
                text (str): input string

        Returns:
                Preprocessed text
        """
        lines = text.split("\n")
        formatted_lines = []

        for i, line in enumerate(lines):
            line = line.strip()
            if not line:
                formatted_lines.append(line)
                continue

            words = line.split()
            is_header = False
            if len(words) <= 7 and not line.endswith("."):
                is_header = True

            if any(
                line.lower().startswith(prefix)
                for prefix in [
                    "chapter",
                    "section",
                    "part",
                    "introduction",
                    "conclusion",
                    "overview",
                    "summary",
                    "appendix",
                ]
            ):
                is_header = True

            if (
                len(words) <= 10
                and (line.isupper() or line.istitle())
                and not line.endswith(".")
            ):
                is_header = True

            if is_header:
                if len(words) <= 3:
                    formatted_lines.append(f"## {line}")
                else:
                    formatted_lines.append(f"### {line}")
            else:
                formatted_lines.append(line)

        return "\n".join(formatted_lines)

    def OCR_artefacts(self, text):
        """
        Fix common OCR artifacts while preserving semantic meaning

        Paramerter
                text (str): input string

        Returns:
                Preprocessed text
        """
        text = re.sub(
            r"[^\w\s\.\,\;\:\!\?\-\'\"\(\)\[\]\{\}\/\\\&\@\#\$\%\^\*\+\=\_\~\`\|]",
            "",
            text,
        )
        text = re.sub(r"(\w+)-\s*\n\s*(\w+)", r"\1\2", text)
        text = re.sub(r"(?m)^\s*\d+\s*$", "", text)
        text = re.sub(r"(?m)^Page \d+ of \d+$", "", text)
        return text

    def prep(self) -> str:
        """
        Process document text using semantic analysis to maintain logical structure

        Returns:
            str: Cleaned and formatted document text
        """
        if not self.document:
            return ""

        original = self.document

        try:
            text = self.OCR_artefacts(self.document)
            text = re.sub(r"[ \t]+", " ", text)
            sentences = self.break_sentences(text)
            fixed_sentences = self.join_sentences(sentences)
            paragraphed_text = self.paragraph_formating(fixed_sentences)
            final_format = self.headers_formating(paragraphed_text)
            if not final_format.strip():
                print(
                    "Warning: processing resulted in empty content, returning original text"
                )
                return original

            return final_format

        except Exception as e:
            print(f"Error during preprocessing: {str(e)}")
            return original
