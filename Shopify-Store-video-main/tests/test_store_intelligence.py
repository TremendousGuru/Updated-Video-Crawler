import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import compose as compose_mod


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
                "url": "https://brightformstudio.com/products/halo-desk-lamp"
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

    assert result["quality_control"]["video_opportunity_found"] in {False, None}
    assert result["video_brief"]["format"] in {"", None}
