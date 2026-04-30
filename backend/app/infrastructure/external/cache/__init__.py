from functools import lru_cache

from app.infrastructure.external.cache.in_memory_cache import InMemoryCache


@lru_cache()
def get_cache():
    return InMemoryCache()


__all__ = ["get_cache", "InMemoryCache"]
