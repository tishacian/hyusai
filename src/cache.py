#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Feb 14 17:42:17 2025

@author: kennethezukwoke
"""
import sys
import warnings
import logging

warnings.simplefilter(action="ignore", category=FutureWarning)

# --
logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


class LRUCache:
    """Simple LRU Cache implementation for context caching"""

    def __init__(self, capacity):
        self.cache = {}
        self.capacity = capacity
        self.order = []

    def __contains__(self, key):
        return key in self.cache

    def __getitem__(self, key):
        if key not in self.cache:
            return None
        self.order.remove(key)
        self.order.append(key)
        return self.cache[key]

    def __setitem__(self, key, value):
        if len(self.cache) >= self.capacity:
            oldest = self.order.pop(0)
            del self.cache[oldest]
        self.cache[key] = value
        self.order.append(key)
