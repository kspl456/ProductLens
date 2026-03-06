from flask import Flask, render_template, request, jsonify
import traceback

from data_ingestion.serp_fetcher import fetch_product_details
from processing.cleaner import clean_reviews
from processing.aspect_extraction import extract_aspects_bulk
from processing.sentiment import analyze_reviews_overall, analyze_aspects_sentiment
from authenticity.rari import calc_rari, filter_reviews_if_needed
from scoring.scorer import (
    score_price, score_rating, score_sentiment,
    score_aspects, score_rari, compute_total_score, rank_products
)
from database.mongo import get_cached_product, save_product

app = Flask(__name__)


def process_product(url: str, all_prices_ref: list) -> dict:
    """Full pipeline for one product URL."""
    from data_ingestion.serp_fetcher import extract_asin
    asin = extract_asin(url)
    if not asin:
        return {"error": f"Could not extract ASIN from URL: {url}", "url": url}

    # --- Cache check ---
    cached = get_cached_product(asin)
    if cached:
        raw = cached
        raw["_from_cache"] = True
    else:
        raw = fetch_product_details(url)
        raw["_from_cache"] = False

    # --- Clean reviews ---
    cleaned_reviews = clean_reviews(raw.get("reviews", []))

    # --- RARI ---
    rari_result = calc_rari(cleaned_reviews)

    # --- Filter reviews if needed ---
    analysis_reviews = filter_reviews_if_needed(cleaned_reviews, rari_result)

    # --- Aspect extraction + sentiment ---
    category = raw.get("category", "general")
    aspect_texts = extract_aspects_bulk(analysis_reviews, category)
    aspect_sentiments = analyze_aspects_sentiment(aspect_texts)

    # --- Overall sentiment ---
    overall_sentiment = analyze_reviews_overall(analysis_reviews)

    # --- Save to DB (raw + processed summary) ---
    save_doc = dict(raw)
    save_doc["reviews"] = raw.get("reviews", [])  # store original
    save_doc["rari"] = rari_result
    save_doc["overall_sentiment"] = overall_sentiment
    save_doc["aspect_sentiments"] = aspect_sentiments
    if not raw.get("_from_cache"):
        save_product(save_doc)

    # Collect price for cross-product scoring (filled later)
    price = raw.get("price")
    if price:
        all_prices_ref.append(price)

    return {
        "asin": asin,
        "url": url,
        "title": raw.get("title", "Unknown"),
        "price": price,
        "seller": raw.get("seller", "Unknown"),
        "rating": raw.get("rating"),
        "category": category,
        "rari": rari_result,
        "overall_sentiment": overall_sentiment,
        "aspect_sentiments": aspect_sentiments,
        "_from_cache": raw.get("_from_cache", False),
    }


def apply_scores(products: list[dict], all_prices: list[float]) -> list[dict]:
    """Compute and attach scoring to each product dict."""
    for p in products:
        if "error" in p:
            p["scoring"] = {"total_trust_score": 0, "components": {}, "weights": {}}
            continue
        ps = score_price(p.get("price"), all_prices)
        rs = score_rating(p.get("rating"))
        ss = score_sentiment(p.get("overall_sentiment", {}))
        as_ = score_aspects(p.get("aspect_sentiments", {}))
        rari_trust = score_rari(p.get("rari", {}).get("score", 0))
        p["scoring"] = compute_total_score(ps, rs, ss, as_, rari_trust)
    return products


@app.route("/", methods=["GET"])
def home():
    return render_template("index.html")


@app.route("/analyze", methods=["POST"])
def analyze():
    data = request.get_json()
    urls = data.get("urls", [])

    if not urls or len(urls) < 2 or len(urls) > 5:
        return jsonify({"error": "Please provide between 2 and 5 Amazon product URLs."}), 400

    all_prices = []
    products = []
    errors = []

    for url in urls:
        try:
            result = process_product(url.strip(), all_prices)
            products.append(result)
        except Exception as e:
            errors.append({"url": url, "error": str(e), "trace": traceback.format_exc()})
            products.append({"error": str(e), "url": url})

    # Scoring requires all prices for relative comparison
    products = apply_scores(products, all_prices)

    # Rank
    ranked = rank_products(products)

    return jsonify({
        "products": ranked,
        "errors": errors,
    })


if __name__ == "__main__":
    app.run(debug=True, port=5000)