from datetime import datetime, timezone

_cache = {}

def get_cached_product(asin: str) -> dict | None:
    doc = _cache.get(asin)
    if not doc:
        return None
    fetched_at = doc.get("fetched_at")
    if fetched_at:
        age = (datetime.now(timezone.utc) - fetched_at).days
        if age < 7:
            return doc
    return None

def save_product(data: dict) -> None:
    data["fetched_at"] = datetime.now(timezone.utc)
    _cache[data["asin"]] = data

def get_product_by_asin(asin: str) -> dict | None:
    return _cache.get(asin)