import re
from datetime import datetime
from serpapi import GoogleSearch
from config import SERP_API_KEY


def extract_asin(url: str) -> str | None:
    """Extract Amazon ASIN from product URL."""
    patterns = [
        r"/dp/([A-Z0-9]{10})",
        r"/gp/product/([A-Z0-9]{10})",
        r"asin=([A-Z0-9]{10})",
        r"/([A-Z0-9]{10})(?:/|\?|$)",
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    return None


def fetch_product_details(amazon_url: str) -> dict:
    asin = extract_asin(amazon_url)
    if not asin:
        raise ValueError(f"Could not extract ASIN from URL: {amazon_url}")

    params = {
        "engine": "amazon_product",
        "asin": asin,
        "amazon_domain": "amazon.in",
        "api_key": SERP_API_KEY,
    }

    # Use GoogleSearch exactly like the working test script
    search = GoogleSearch(params)
    results = search.get_dict()

    if "product_results" not in results:
        raise ValueError(f"SerpAPI error: {results.get('error', 'No product_results')}")

    product = results.get("product_results", {})

    # Title
    title = product.get("title", "Unknown Product")

    # Price — same multi-tier logic as working test
    price = _extract_price(product)

    # Rating
    rating = product.get("rating")
    if rating:
        try:
            rating = float(rating)
        except (ValueError, TypeError):
            rating = None

    # Total review count — product.reviews is the Amazon integer (e.g. 22836)
    total_reviews = product.get('reviews', 0)
    print("review count:", total_reviews)

    # Seller / brand
    seller = product.get("brand", "Amazon / Unknown").replace("Brand: ", "").strip()

    # Category — same logic as working test
    category = _extract_category(product, results)

    # Thumbnail
    thumbnail = product.get("thumbnail") or None

    # Review objects — for analysis pipeline
    review_list = _extract_reviews(results)

    return {
        "asin": asin,
        "url": amazon_url,
        "title": title,
        "price": price,
        "seller": seller,
        "rating": rating,
        "category": category,
        "reviews": review_list,
        "total_reviews": total_reviews,
        "thumbnail": thumbnail,
    }


def _extract_price(product: dict) -> float | None:
    """Multi-tier price extraction — same as working test script."""
    # 1. Direct extracted price
    if product.get("extracted_price"):
        return float(product["extracted_price"])

    # 2. Buybox winner
    buybox = product.get("buybox_winner", {})
    if buybox.get("price", {}).get("value"):
        return float(buybox["price"]["value"])

    # 3. Offers list
    for offer in product.get("offers", []):
        if offer.get("price", {}).get("value"):
            return float(offer["price"]["value"])

    # 4. Variant price fallback
    for variant in product.get("variants", []):
        for item in variant.get("items", []):
            if item.get("price", {}).get("value"):
                return float(item["price"]["value"])

    # 5. Raw price string
    raw = product.get("price")
    if raw:
        return _parse_price(raw)

    return None


def _extract_category(product: dict, results: dict) -> str:
    """Category extraction — same as working test script."""
    # 1. Breadcrumb categories
    categories = product.get("categories", [])
    if categories:
        return categories[-1].get("name", "General")

    # 2. Best sellers rank (most specific sub-category)
    product_details = results.get("product_details", {})
    bsr = product_details.get("best_sellers_rank", [])
    if bsr:
        return bsr[-1].get("link_text") or bsr[0].get("link_text") or "General"

    # 3. Infer from title keywords
    title = product.get("title", "").lower()
    keyword_map = {
        "mobile": "Mobile Phones",
        "laptop": "Computers",
        "headphone": "Audio",
        "earphone": "Audio",
        "earring": "Jewellery",
        "watch": "Watches",
        "coffee": "Grocery",
        "charger": "Electronics Accessories",
        "shoe": "Footwear",
        "shirt": "Clothing",
        "saree": "Clothing",
    }
    for key, cat in keyword_map.items():
        if key in title:
            return cat

    return "General"


def _extract_reviews(results: dict) -> list[dict]:
    """Extract reviews from amazon_product response."""
    reviews = []
    authors_reviews = results.get("reviews_information", {}).get("authors_reviews", [])
    for r in authors_reviews:
        reviews.append({
            "title": r.get("title", ""),
            "content": r.get("text", ""),
            "rating": r.get("rating"),
            "verified": "Verified Purchase" in r.get("author", ""),
            "date": r.get("date", ""),
        })
    return reviews


def _parse_price(raw) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    cleaned = re.sub(r"[^\d.]", "", str(raw))
    try:
        return float(cleaned)
    except ValueError:
        return None