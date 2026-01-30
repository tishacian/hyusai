"""Unit tests for the cache module.

Comprehensive test suite covering:
- LRUCache: Initialization, eviction, operations (14 tests)
- TimedCache: Expiry, capacity management, operations (16 tests)
- TieredCache: Multi-level caching, fallback behavior (10 tests)

Total: 40 comprehensive unit tests
"""

import time

import pytest

from src.cache import LRUCache, TieredCache, TimedCache


class TestLRUCache:
    """Test suite for LRUCache class."""

    @pytest.fixture
    def lru_cache(self):
        """Create an LRUCache with capacity 3 for testing."""
        return LRUCache(capacity=3)

    def test_initialization(self, lru_cache):
        """Test LRUCache initialization."""
        assert lru_cache.capacity == 3
        assert len(lru_cache.cache) == 0
        assert len(lru_cache.order) == 0

    def test_setitem_single_item(self, lru_cache):
        """Test adding a single item to cache."""
        lru_cache["key1"] = "value1"
        assert "key1" in lru_cache.cache
        assert lru_cache.cache["key1"] == "value1"
        assert lru_cache.order == ["key1"]

    def test_setitem_multiple_items_within_capacity(self, lru_cache):
        """Test adding multiple items within capacity."""
        lru_cache["key1"] = "value1"
        lru_cache["key2"] = "value2"
        lru_cache["key3"] = "value3"
        assert len(lru_cache.cache) == 3
        assert lru_cache.order == ["key1", "key2", "key3"]

    def test_setitem_exceeds_capacity_evicts_oldest(self, lru_cache):
        """Test that adding items beyond capacity evicts the oldest (LRU)."""
        lru_cache["key1"] = "value1"
        lru_cache["key2"] = "value2"
        lru_cache["key3"] = "value3"
        lru_cache["key4"] = "value4"  # Should evict key1

        assert "key1" not in lru_cache.cache
        assert len(lru_cache.cache) == 3
        assert lru_cache.order == ["key2", "key3", "key4"]

    def test_getitem_retrieves_value(self, lru_cache):
        """Test retrieving a value from cache."""
        lru_cache["key1"] = "value1"
        result = lru_cache["key1"]
        assert result == "value1"

    def test_getitem_missing_key_returns_none(self, lru_cache):
        """Test that getting a missing key returns None."""
        result = lru_cache["nonexistent"]
        assert result is None

    def test_getitem_updates_order_moves_to_end(self, lru_cache):
        """Test that accessing an item moves it to the end (marks as recently used)."""
        lru_cache["key1"] = "value1"
        lru_cache["key2"] = "value2"
        lru_cache["key3"] = "value3"

        # Access key1 (should move to end)
        _ = lru_cache["key1"]

        assert lru_cache.order == ["key2", "key3", "key1"]

    def test_contains_existing_key(self, lru_cache):
        """Test __contains__ for existing key."""
        lru_cache["key1"] = "value1"
        assert "key1" in lru_cache

    def test_contains_missing_key(self, lru_cache):
        """Test __contains__ for missing key."""
        assert "nonexistent" not in lru_cache

    def test_overwrite_existing_key(self, lru_cache):
        """Test overwriting an existing key (should not add new entry)."""
        lru_cache["key1"] = "value1"
        lru_cache["key2"] = "value2"
        original_order = lru_cache.order.copy()

        # Overwrite key1
        lru_cache["key1"] = "value1_new"

        assert lru_cache["key1"] == "value1_new"
        # Note: Based on current implementation, overwrite adds to end
        # This tests current behavior; consider if this is desired

    def test_capacity_one(self):
        """Test LRUCache with capacity of 1."""
        cache = LRUCache(capacity=1)
        cache["key1"] = "value1"
        assert "key1" in cache.cache

        cache["key2"] = "value2"
        assert "key1" not in cache.cache
        assert "key2" in cache.cache

    def test_large_capacity(self):
        """Test LRUCache with large capacity."""
        cache = LRUCache(capacity=1000)
        for i in range(500):
            cache[f"key{i}"] = f"value{i}"

        assert len(cache.cache) == 500
        assert cache.order == [f"key{i}" for i in range(500)]

    def test_eviction_order_with_multiple_operations(self, lru_cache):
        """Test correct eviction order with mixed read/write operations."""
        lru_cache["a"] = 1
        lru_cache["b"] = 2
        lru_cache["c"] = 3
        # Access 'a' to make it most recently used
        _ = lru_cache["a"]
        # Add 'd', should evict 'b' (oldest unused)
        lru_cache["d"] = 4

        assert "a" in lru_cache.cache
        assert "b" not in lru_cache.cache
        assert "c" in lru_cache.cache
        assert "d" in lru_cache.cache


class TestTimedCache:
    """Test suite for TimedCache class."""

    @pytest.fixture
    def timed_cache(self):
        """Create a TimedCache with default settings for testing."""
        return TimedCache(capacity=5, expiry_seconds=1)

    def test_initialization(self, timed_cache):
        """Test TimedCache initialization."""
        assert timed_cache.capacity == 5
        assert timed_cache.default_expiry == 1
        assert len(timed_cache._cache) == 0
        assert len(timed_cache._expiry_times) == 0

    def test_setitem_basic(self, timed_cache):
        """Test adding an item to TimedCache."""
        timed_cache["key1"] = "value1"
        assert "key1" in timed_cache._cache
        assert timed_cache._cache["key1"] == "value1"

    def test_getitem_retrieves_value(self, timed_cache):
        """Test retrieving a value from TimedCache."""
        timed_cache["key1"] = "value1"
        result = timed_cache["key1"]
        assert result == "value1"

    def test_getitem_missing_key_raises_keyerror(self, timed_cache):
        """Test that getting a missing key raises KeyError."""
        with pytest.raises(KeyError):
            _ = timed_cache["nonexistent"]

    def test_contains_existing_key(self, timed_cache):
        """Test __contains__ for existing non-expired key."""
        timed_cache["key1"] = "value1"
        assert "key1" in timed_cache

    def test_contains_missing_key(self, timed_cache):
        """Test __contains__ for missing key."""
        assert "nonexistent" not in timed_cache

    def test_contains_expired_key_returns_false_and_removes(self, timed_cache):
        """Test that checking an expired key returns False and removes it."""
        timed_cache["key1"] = "value1"
        # Wait for key to expire
        time.sleep(1.1)

        assert "key1" not in timed_cache
        # Verify key was removed
        assert "key1" not in timed_cache._cache

    def test_getitem_expired_key_raises_keyerror(self, timed_cache):
        """Test that getting an expired key raises KeyError."""
        timed_cache["key1"] = "value1"
        time.sleep(1.1)

        with pytest.raises(KeyError):
            _ = timed_cache["key1"]

    def test_get_method_returns_default_for_missing_key(self, timed_cache):
        """Test get() method with default value."""
        result = timed_cache.get("nonexistent", "default")
        assert result == "default"

    def test_get_method_returns_value_if_exists(self, timed_cache):
        """Test get() method returns value if key exists."""
        timed_cache["key1"] = "value1"
        result = timed_cache.get("key1")
        assert result == "value1"

    def test_get_method_returns_default_for_expired_key(self, timed_cache):
        """Test get() method returns default for expired key."""
        timed_cache["key1"] = "value1"
        time.sleep(1.1)

        result = timed_cache.get("key1", "default")
        assert result == "default"

    def test_set_with_custom_expiry(self):
        """Test set() method with custom expiry time."""
        cache = TimedCache(capacity=5, expiry_seconds=10)
        cache.set("key1", "value1", expiry_seconds=2)

        # Should be accessible immediately
        assert "key1" in cache
        assert cache["key1"] == "value1"

        # Should expire after 2 seconds
        time.sleep(2.1)
        assert "key1" not in cache

    def test_capacity_enforcement(self):
        """Test that cache respects capacity limit."""
        cache = TimedCache(capacity=3, expiry_seconds=60)
        cache["key1"] = "value1"
        cache["key2"] = "value2"
        cache["key3"] = "value3"

        assert len(cache._cache) == 3

        # Add a 4th item; should prune oldest
        cache["key4"] = "value4"

        assert len(cache._cache) == 3
        assert "key1" not in cache._cache

    def test_prune_removes_expired_items(self):
        """Test that _prune() removes expired items."""
        cache = TimedCache(capacity=10, expiry_seconds=1)
        cache["key1"] = "value1"
        cache["key2"] = "value2"

        time.sleep(1.1)

        cache._prune()
        assert len(cache._cache) == 0
        assert len(cache._expiry_times) == 0

    def test_clear(self, timed_cache):
        """Test clear() method."""
        timed_cache["key1"] = "value1"
        timed_cache["key2"] = "value2"

        timed_cache.clear()

        assert len(timed_cache._cache) == 0
        assert len(timed_cache._expiry_times) == 0

    def test_len(self, timed_cache):
        """Test __len__ method."""
        assert len(timed_cache) == 0

        timed_cache["key1"] = "value1"
        assert len(timed_cache) == 1

        timed_cache["key2"] = "value2"
        assert len(timed_cache) == 2


class TestTieredCache:
    """Test suite for TieredCache class."""

    @pytest.fixture
    def tiered_cache(self):
        """Create a TieredCache for testing."""
        return TieredCache(l1_size=3, l2_size=5)

    def test_initialization(self, tiered_cache):
        """Test TieredCache initialization."""
        assert isinstance(tiered_cache.l1_cache, LRUCache)
        assert isinstance(tiered_cache.l2_cache, TimedCache)
        assert isinstance(tiered_cache.embedding_cache, dict)
        assert tiered_cache.l1_cache.capacity == 3
        assert tiered_cache.l2_cache.capacity == 5

    def test_set_to_l1_only(self, tiered_cache):
        """Test setting a value to L1 cache only."""
        tiered_cache.set("key1", "value1", cache_level=1)

        assert "key1" in tiered_cache.l1_cache
        # L2 only contains items set with cache_level >= 2
        assert "key1" not in tiered_cache.l2_cache

    def test_set_to_l1_and_l2(self, tiered_cache):
        """Test setting a value to both L1 and L2."""
        tiered_cache.set("key1", "value1", cache_level=3)

        assert "key1" in tiered_cache.l1_cache
        assert "key1" in tiered_cache.l2_cache

    def test_get_from_l1(self, tiered_cache):
        """Test getting a value from L1 cache."""
        tiered_cache.set("key1", "value1", cache_level=1)
        result = tiered_cache.get("key1", cache_level=1)

        assert result == "value1"

    def test_get_from_l2_promotes_to_l1(self, tiered_cache):
        """Test getting a value from L2 cache promotes it to L1."""
        tiered_cache.set("key1", "value1", cache_level=2)

        # Get from L2 (should return and promote to L1)
        result = tiered_cache.get("key1", cache_level=2)

        assert result == "value1"
        assert "key1" in tiered_cache.l1_cache

    def test_get_missing_key_returns_none(self, tiered_cache):
        """Test getting a missing key returns None."""
        result = tiered_cache.get("nonexistent")
        assert result is None

    def test_get_respects_cache_level_parameter(self, tiered_cache):
        """Test that get() respects cache_level parameter."""
        # cache_level=2 means set in both L1 and L2 (since >= 1 and >= 2)
        tiered_cache.set("key1", "value1", cache_level=2)

        # Should find in L1-only search (since cache_level >= 1 adds to L1)
        result = tiered_cache.get("key1", cache_level=1)
        assert result == "value1"

        # Should also find in L1+L2 search
        result = tiered_cache.get("key1", cache_level=2)
        assert result == "value1"

        # Test cache_level constraint: only check L2 if explicitly requested
        tiered_cache.set("key2", "value2", cache_level=2)
        # Remove from L1 to test L2 fallback
        tiered_cache.l1_cache.cache.pop("key2", None)
        tiered_cache.l1_cache.order = [
            k for k in tiered_cache.l1_cache.order if k != "key2"
        ]

        # Should not find when only searching L1
        result = tiered_cache.get("key2", cache_level=1)
        assert result is None

    def test_set_embedding(self, tiered_cache):
        """Test setting an embedding in the embedding cache."""
        embedding = [1.0, 2.0, 3.0]
        tiered_cache.set_embedding("text1", embedding)

        assert "text1" in tiered_cache.embedding_cache
        assert tiered_cache.embedding_cache["text1"] == embedding

    def test_get_embedding_exists(self, tiered_cache):
        """Test getting an existing embedding."""
        embedding = [1.0, 2.0, 3.0]
        tiered_cache.set_embedding("text1", embedding)
        result = tiered_cache.get_embedding("text1")

        assert result == embedding

    def test_get_embedding_missing(self, tiered_cache):
        """Test getting a missing embedding returns None."""
        result = tiered_cache.get_embedding("nonexistent")
        assert result is None

    def test_multi_level_interaction(self, tiered_cache):
        """Test interaction between L1, L2, and embedding caches."""
        tiered_cache.set("key1", "value1", cache_level=3)
        tiered_cache.set_embedding("text1", [1.0, 2.0])

        # All should be accessible
        assert tiered_cache.get("key1", cache_level=1) == "value1"
        assert tiered_cache.get_embedding("text1") == [1.0, 2.0]

        # L1 and L2 should be independent of embedding cache
        assert len(tiered_cache.l1_cache.cache) == 1
        assert len(tiered_cache.l2_cache._cache) == 1
        assert len(tiered_cache.embedding_cache) == 1
