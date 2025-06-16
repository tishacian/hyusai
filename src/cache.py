#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Feb 14 17:42:17 2025

@author: kennethezukwoke
"""
import sys
import time
import logging

# --
logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


class LRUCache:
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

    def clear(self):
        self.cache.clear()
        self.order.clear()
        logging.info("LRU cache cleared")


class TimedCache:
    def __init__(self, capacity: int = 1000, expiry_seconds: int = 3600):
        """Initialize TimedCache with capacity and expiration

        Parameters
        ----------
        capacity : int, optional
            Maximum number of items in the cache, by default 1000
        expiry_seconds : int, optional
            Default time in seconds before items expire, by default 3600
        """
        self.capacity = capacity
        self.default_expiry = expiry_seconds
        self._cache = {}
        self._expiry_times = {}

    def __contains__(self, key):
        """Check if key exists in cache and is not expired

        Parameters
        ----------
        key : str
            Key value to check

        Returns
        -------
        bool
            True if key exists and is not expired, False otherwise
        """
        if key not in self._cache:
            return False

        if time.time() > self._expiry_times.get(key, 0):
            del self._cache[key]
            del self._expiry_times[key]
            return False

        return True

    def __getitem__(self, key):
        """Extract item from cache if it exists and is not expired

        Parameters
        ----------
        key : str
            Key value to retrieve

        Raises
        ------
        KeyError
            If key does not exist or has expired

        Returns
        -------
        Any
            Cached value associated with the key
        """
        if key not in self:
            raise KeyError(key)

        value = self._cache.pop(key)
        self._cache[key] = value
        return value

    def __setitem__(self, key, value):
        """Add item to cache with default expiry time

        Parameters
        ----------
        key : str
            Key value
        value : Any
            Value to cache
        """
        self.set(key, value)

    def get(self, key, default=None):
        """Get an item from the cache, default if not found.

        Parameters
        ----------
        key : Any
            Key to retrieve
        default : Any, optional
            Default value to return if key not found, by default None

        Returns
        -------
        Any
            Cached value or default value
        """
        try:
            return self[key]
        except KeyError:
            return default

    def set(self, key, value, expiry_seconds=None):
        """Add an item to the cache with a specific expiry time

        Parameters
        ----------
        key : str
            The key to store the value under
        value : Any
            The value to store
        expiry_seconds : int, optional
            Time in seconds before this item expires, by default None
        """
        if key in self._cache:
            del self._cache[key]

        self._cache[key] = value

        actual_expiry = (
            expiry_seconds
            if expiry_seconds is not None
            else self.default_expiry
        )
        self._expiry_times[key] = time.time() + actual_expiry

        self._prune()

    def _prune(self):
        current_time = time.time()
        expired_keys = [
            key
            for key, expiry in self._expiry_times.items()
            if current_time > expiry
        ]

        for key in expired_keys:
            del self._cache[key]
            del self._expiry_times[key]

        while len(self._cache) > self.capacity:
            oldest_key = next(iter(self._cache))
            del self._cache[oldest_key]
            del self._expiry_times[oldest_key]

    def clear(self):
        self._cache.clear()
        self._expiry_times.clear()

    def __len__(self):
        """Return the number of items in the cache

        Returns
        -------
        int
            Number of items in cache
        """
        return len(self._cache)


class TieredCache:
    def __init__(self, l1_size=1000, l2_size=10000):
        """Initialize tiered cache w/ L1 and L2 cache sizes

        Parameters
        ----------
        l1_size : int, optional
            Size of L1 cache, by default 1000
        l2_size : int, optional
            Size of L2 cache, by default 10000
        """
        self.l1_cache = LRUCache(l1_size)
        self.l2_cache = TimedCache(l2_size)
        self.embedding_cache = {}

    def get(self, key, cache_level=1):
        """Get item from cache, trying L1 first then L2

        Parameters
        ----------
        key : Any
            Key to retrieve
        cache_level : int, optional
            Cache level to search, by default 1

        Returns
        -------
        Any
            Cached value or None if not found
        """
        if cache_level >= 1 and key in self.l1_cache:
            return self.l1_cache[key]
        if cache_level >= 2 and key in self.l2_cache:
            value = self.l2_cache[key]
            self.l1_cache[key] = value
            return value
        return None

    def set(self, key, value, cache_level=3):
        """Set item in cache(s)

        Parameters
        ----------
        key : Any
            Key to store
        value : Any
            Value to store
        cache_level : int, optional
            Cache level to store in, by default 3
        """
        if cache_level >= 1:
            self.l1_cache[key] = value
        if cache_level >= 2:
            self.l2_cache[key] = value

    def get_embedding(self, text_key):
        """Get embedding from cache

        Parameters
        ----------
        text_key : str
            Text key for embedding

        Returns
        -------
        Any
            Cached embedding or None if not found
        """
        return self.embedding_cache.get(text_key)

    def set_embedding(self, text_key, embedding):
        """Cache embedding

        Parameters
        ----------
        text_key : str
            Text key for embedding
        embedding : Any
            Embedding to cache
        """
        self.embedding_cache[text_key] = embedding

    def clear(self):
        """Clear all caches (L1, L2, and embedding cache)
        
        Returns
        -------
        None
        """
        self.l1_cache.cache.clear()
        self.l1_cache.order.clear()
        self.l2_cache.clear()
        self.embedding_cache.clear()
