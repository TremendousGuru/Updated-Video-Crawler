import os
import sys
import asyncio

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import compose as compose_mod
from app.crawler import extract_products


def make_demo_store_facts():
    return {
        "store_name": "Northline Goods",
        "domain": "northlinegoods.com",
        "platform": "shopify",
        "tagline": "Thoughtful kitchen tools for everyday cooks",
        "location": "Portland, Oregon",
        "collections": ["Cookware", "Kitchen Essentials"],
        "product_types": ["Cookware", "Prep Tools"],
        "about_snippet": "We design durable, practical cookware for busy home cooks.",
        "home_snippet": "Our cookware is built to last and make everyday cooking simpler.",
        "products": [
            {
                "title": "Copper Core Sauté Pan",
                "price": "89",
                "currency": "USD",
                "type": "Cookware",
                "image": False,
                "tags": ["kitchen", "cookware"],
                "description": "A stovetop pan with an even-heating copper core.",
                "url": "https://northlinegoods.com/products/copper-core-saute-pan"
            },
            {
                "title": "Walnut Cutting Board",
                "price": "48",
                "currency": "USD",
                "type": "Prep Tools",
                "image": True,
                "tags": ["kitchen", "wood"],
                "description": "A solid walnut board designed for daily kitchen prep.",
                "url": "https://northlinegoods.com/products/walnut-cutting-board"
            },
        ],
        "signals": ["handmade", "small-batch", "made to order"],
    }


def make_effective_product_store():
    return {
        "store_name": "Bright Form Studio",
        "domain": "brightformstudio.com",
        "platform": "shopify",
        "tagline": "Minimal home objects for calmer living",
        "location": "Austin, Texas",
        "collections": ["Lighting", "Living"],
        "product_types": ["Lighting"],
        "about_snippet": "We make modern lighting with detailed product photography and clear installation guidance.",
        "home_snippet": "Every product is shown in context with close-ups and installation detail.",
        "products": [
            {
                "title": "Halo Desk Lamp",
                "price": "185",
                "currency": "USD",
                "type": "Lighting",
                "image": True,
                "tags": ["lighting", "desk"],
                "description": "Minimal desk lamp with clear product closeups and installation instruction.",
                "url": "https://brightformstudio.com/products/halo-desk-lamp",
                "video_assets": [{"type": "demonstration", "url": "https://brightformstudio.com/halo-demo.mp4"}],
            }
        ],
        "signals": ["small-batch"],
    }


def test_compose_store_intelligence_flags_real_demo_opportunity():
    facts = make_demo_store_facts()

    result = compose_mod.compose_store_intelligence(facts, {})

    assert result["store_profile"]["brand_name"] == "Northline Goods"
    assert result["quality_control"]["video_opportunity_found"] is True
    assert result["diagnosis"]["primary_opportunity"]
    assert result["product_selection"]["product_name"] == "Copper Core Sauté Pan"
    assert result["video_brief"]["format"]
    assert result["outreach"]["message"]


def test_compose_store_intelligence_rejects_weak_opportunity():
    facts = make_effective_product_store()

    result = compose_mod.compose_store_intelligence(facts, {})

    assert result["quality_control"]["video_opportunity_found"] in {False, None}
    assert result["diagnosis"]["primary_opportunity"] in {"", None}


def test_missing_or_invalid_ai_payload_is_handled_without_crash():
    parsed = compose_mod.safe_parse_json("not valid json")
    assert parsed == {}

    result = compose_mod.validate_generated_output({
        "store_profile": {"brand_name": "Example"},
        "diagnosis": {"primary_opportunity": ""},
        "product_selection": {"product_name": "Example Product"},
        "video_brief": {"format": "Product demonstration"},
        "outreach": {"subject": "Quick question", "message": "This product doubles sales overnight."},
    })

    assert result["manual_review_required"] is True
    assert any("unsupported" in reason.lower() for reason in result["review_reasons"])


def test_product_scoring_and_breakdown_are_numeric():
    facts = make_demo_store_facts()
    result = compose_mod.compose_store_intelligence(facts, {})

    assert isinstance(result["product_selection"]["score"], int)
    assert result["product_selection"]["score"] >= 0
    assert isinstance(result["product_selection"]["score_breakdown"], dict)


def test_no_opportunity_case_is_properly_abstained():
    facts = {
        "store_name": "Clear View Co.",
        "domain": "clearviewco.com",
        "products": [
            {
                "title": "Glass Tabletop",
                "price": "140",
                "currency": "USD",
                "type": "Home",
                "image": True,
                "description": "Glass tabletop shown from several angles with scale and fit clearly presented.",
                "url": "https://clearviewco.com/products/glass-tabletop"
            }
        ],
        "about_snippet": "We show our product clearly in use and explain sizing, materials, and installation.",
        "home_snippet": "The product is shown in realistic context and the page answers fit and material questions.",
        "product_types": ["Home"],
    }

    result = compose_mod.compose_store_intelligence(facts, {})

    assert result["quality_control"]["video_opportunity_found"] is True
    assert result["video_brief"]["format"]
    assert not any(word in result["diagnosis"]["primary_opportunity"].lower() for word in ("lack", "unclear", "cannot", "weak"))


def test_batch_compose_uses_evidence_based_1legacy_hat_concept():
    facts = {
        "store_name": "1LEGACY",
        "domain": "1legacy.com",
        "url": "https://1legacy.com",
        "products": [{
            "title": "UR AN WIZARD HARRY hat",
            "url": "https://1legacy.com/products/ur-an-wizard-harry-hat",
            "description": "",
            "image": True,
        }],
    }

    result = asyncio.run(compose_mod.compose(facts, {"use_ai": False}))

    intelligence = result["intelligence"]
    message = result["body"]
    assert intelligence["product_selection"]["product_name"] == "UR AN WIZARD HARRY hat"
    assert "UR AN WIZARD HARRY hat" in message
    assert "styling" in message.lower() or "outfit" in message.lower()
    assert "specific creative direction" not in message.lower()
    assert "materials" not in message.lower()
    assert "short product videos for shopify stores" not in message.lower()
    assert intelligence["outreach_evidence"]["product_facts"] == ["UR AN WIZARD HARRY hat", ""]
    assert "category" not in message.lower()
    assert intelligence["quality_control"]["personalization_verified"] is True


def test_practical_product_concept_uses_description_evidence():
    facts = {
        "store_name": "Bright Workshop",
        "domain": "brightworkshop.example",
        "url": "https://brightworkshop.example",
        "products": [{
            "title": "Clamp-On Task Light",
            "url": "https://brightworkshop.example/products/clamp-on-task-light",
            "type": "Lighting",
            "description": "Clamp the light onto a shelf or desk edge and angle the arm over your workspace.",
            "image": True,
        }],
    }

    result = asyncio.run(compose_mod.compose(facts, {"use_ai": False}))
    intelligence = result["intelligence"]

    assert "demonstration" in intelligence["video_brief"]["format"].lower()
    assert "clamp" in intelligence["video_brief"]["concept"].lower()
    assert "clamp" in result["body"].lower()
    assert intelligence["outreach_evidence"]["observations"]


def test_lifestyle_product_gets_a_relevant_emotional_concept():
    facts = {
        "store_name": "Evening Ritual",
        "domain": "eveningritual.example",
        "url": "https://eveningritual.example",
        "products": [{
            "title": "Dusk Candle",
            "url": "https://eveningritual.example/products/dusk-candle",
            "type": "Candles",
            "description": "A candle for an unhurried evening routine, with a warm cedar scent.",
            "image": True,
        }],
    }

    result = asyncio.run(compose_mod.compose(facts, {"use_ai": False}))
    intelligence = result["intelligence"]

    assert "lifestyle" in intelligence["video_brief"]["format"].lower()
    assert "evening routine" in intelligence["video_brief"]["concept"].lower()
    assert "evening routine" in result["body"].lower()


def test_existing_product_video_prevents_duplicate_pitch():
    facts = {
        "store_name": "Motion Gear",
        "domain": "motiongear.example",
        "url": "https://motiongear.example",
        "products": [{
            "title": "Trail Bottle",
            "url": "https://motiongear.example/products/trail-bottle",
            "type": "Drinkware",
            "description": "Insulated bottle with a locking lid for hiking.",
            "image": True,
            "video_assets": [{"url": "https://motiongear.example/cdn/trail-bottle-demo.mp4", "type": "demonstration"}],
        }],
    }

    result = asyncio.run(compose_mod.compose(facts, {"use_ai": False}))

    assert result["body"] == ""
    assert result["intelligence"]["quality_control"]["manual_review_required"] is True
    assert "already has" in " ".join(result["intelligence"]["diagnosis"]["limitations"]).lower()


def test_insufficient_product_evidence_abstains_from_confident_recommendation():
    facts = {
        "store_name": "Unknown Goods",
        "domain": "unknown.example",
        "url": "https://unknown.example",
        "products": [{"title": "NOVA", "image": True}],
    }

    result = asyncio.run(compose_mod.compose(facts, {"use_ai": False}))

    assert result["body"] == ""
    assert result["intelligence"]["quality_control"]["manual_review_required"] is True
    assert not result["intelligence"]["diagnosis"]["primary_opportunity"]


def test_quality_gate_rejects_generic_message_with_only_product_name():
    facts = {"products": [{"title": "Clamp-On Task Light", "description": "Clamp onto a desk edge.", "type": "Lighting"}]}
    product = facts["products"][0]
    brief = {"concept": "Show the clamp attaching to the desk edge.", "format": "product demonstration"}
    result = compose_mod.validate_outreach_personalization(
        {"subject": "Quick question", "message": "Hi there, Clamp-On Task Light looks nice. I make videos. Want one?"},
        facts,
        product,
        brief,
    )

    assert result["manual_review_required"] is True
    assert "message does not explain the selected concept" in result["review_reasons"]


def test_shopify_product_extraction_keeps_details_and_video_source():
    products = extract_products([{
        "title": "Clamp-On Task Light",
        "handle": "clamp-on-task-light",
        "body_html": "<p>Clamp this light to a desk edge.</p>",
        "product_type": "Lighting",
        "variants": [{"title": "Black", "options": ["Black"], "price": "39.00", "available": True}],
        "images": [{"src": "https://cdn.example/light.jpg"}],
        "media": [{"media_type": "video", "sources": [{"url": "https://cdn.example/light.mp4"}]}],
    }], store_url="https://shop.example")

    product = products[0]
    assert product["url"] == "https://shop.example/products/clamp-on-task-light"
    assert product["description"] == "Clamp this light to a desk edge."
    assert product["variants"][0]["title"] == "Black"
    assert product["video_evidence"] == "present"
    assert product["video_assets"][0]["url"] == "https://cdn.example/light.mp4"
