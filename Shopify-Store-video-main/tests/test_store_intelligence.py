import os
import sys
import asyncio
from datetime import date

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import compose as compose_mod, db
from app.crawler import audit_product_page, crawl_store, extract_products


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
                "url": "https://northlinegoods.com/products/copper-core-saute-pan",
                "presentation_audit": {
                    "page_checked": True,
                    "source_url": "https://northlinegoods.com/products/copper-core-saute-pan",
                    "image_count": 4,
                    "video_detected": False,
                },
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

    assert result["quality_control"]["video_opportunity_found"] is False
    assert result["product_selection"]["selection_status"] == "no_candidate"


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
    assert intelligence["diagnosis"]["opportunity_category"] == "real_world_appearance"
    assert intelligence["product_selection"]["selection_status"] == "review_candidate"
    assert 5 <= intelligence["product_selection"]["score"] < 8
    assert message
    assert "UR AN WIZARD HARRY hat" in message
    assert result["manual_review_required"] is False
    assert result["manual_review_recommended"] is True


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
            "presentation_audit": {
                "page_checked": True,
                "source_url": "https://brightworkshop.example/products/clamp-on-task-light",
                "image_count": 3,
                "video_detected": False,
            },
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
            "presentation_audit": {
                "page_checked": True,
                "source_url": "https://eveningritual.example/products/dusk-candle",
                "image_count": 4,
                "video_detected": False,
            },
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


def test_existing_video_can_use_audited_distinct_angle():
    facts = {
        "store_name": "Motion Gear",
        "domain": "motiongear.example",
        "url": "https://motiongear.example",
        "product_types": ["Drinkware"],
        "products": [{
            "title": "Trail Bottle",
            "url": "https://motiongear.example/products/trail-bottle",
            "type": "Drinkware",
            "description": "Insulated bottle with a locking lid for hiking.",
            "image": True,
            "video_assets": [{"url": "https://motiongear.example/cdn/trail-bottle-demo.mp4", "type": "demonstration"}],
            "video_audit": {
                "distinct_opportunity": "Create a short hiking-pack clip focused on carrying and access.",
                "finding": "The existing product demo does not show the bottle being carried on a hike.",
                "source_url": "https://motiongear.example/products/trail-bottle",
                "confidence": 0.8,
            },
        }],
    }

    result = asyncio.run(compose_mod.compose(facts, {"use_ai": False}))

    assert result["manual_review_required"] is False
    assert result["intelligence"]["product_selection"]["score"] >= 8
    assert result["intelligence"]["diagnosis"]["opportunity_category"] == "existing_video_fresh_angle"
    assert "hiking-pack clip" in result["intelligence"]["video_brief"]["concept"]


def test_social_video_opportunity_requires_a_real_content_audit():
    facts = {
        "store_name": "Bright Workshop",
        "domain": "brightworkshop.example",
        "url": "https://brightworkshop.example",
        "product_types": ["Lighting"],
        "social_content_audit": {
            "active": True,
            "posts_reviewed": 6,
            "video_posts": 0,
            "source_url": "https://social.example/brightworkshop",
        },
        "products": [{
            "title": "Clamp-On Task Light",
            "url": "https://brightworkshop.example/products/clamp-on-task-light",
            "type": "Lighting",
            "description": "Clamp the light onto a shelf or desk edge and angle the arm over your workspace.",
            "image": True,
            "presentation_audit": {"page_checked": True, "video_detected": False},
        }],
    }

    result = compose_mod.compose_store_intelligence(facts, {})

    assert result["diagnosis"]["opportunity_category"] == "social_content_variety"
    assert result["product_selection"]["score"] >= 8
    assert any(
        evidence["source_url"] == "https://social.example/brightworkshop"
        and evidence["evidence_type"] == "observed"
        for evidence in result["diagnosis"]["evidence"]
    )


def test_premium_presentation_requires_explicit_brand_positioning():
    facts = {
        "store_name": "Form House",
        "domain": "formhouse.example",
        "tagline": "Premium objects for considered homes",
        "product_types": ["Furniture"],
        "products": [{
            "title": "Walnut Side Table",
            "url": "https://formhouse.example/products/walnut-side-table",
            "type": "Furniture",
            "description": "Solid walnut side table with a hand-finished surface.",
            "image": True,
            "presentation_audit": {"page_checked": True, "video_detected": False},
        }],
    }

    result = compose_mod.compose_store_intelligence(facts, {})

    assert result["diagnosis"]["opportunity_category"] == "premium_product_presentation"
    assert result["product_selection"]["score"] >= 8
    assert "premium" in result["store_profile"]["brand_positioning"].lower()


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


def test_weak_candidate_is_deprioritized_below_five_points():
    facts = {
        "store_name": "Everyday Goods",
        "domain": "everyday.example",
        "products": [{
            "title": "Basic Mug",
            "description": "A ceramic mug designed for everyday coffee at home.",
        }],
    }

    result = compose_mod.compose_store_intelligence(facts, {})

    assert result["product_selection"]["score"] < 5
    assert result["product_selection"]["selection_status"] == "deprioritized"
    assert result["quality_control"]["manual_review_required"] is True


def test_five_to_seven_candidate_gets_reviewable_local_draft():
    facts = {
        "store_name": "Everyday Goods",
        "domain": "everyday.example",
        "url": "https://everyday.example",
        "products": [{
            "title": "Everyday Canvas Tote Bag",
            "url": "https://everyday.example/products/tote",
            "description": "",
            "image": True,
        }],
    }

    result = asyncio.run(compose_mod.compose(facts, {"use_ai": False}))

    assert result["body"]
    assert "Everyday Canvas Tote Bag" in result["body"]
    assert result["manual_review_required"] is False
    assert result["manual_review_recommended"] is True
    assert result["intelligence"]["product_selection"]["selection_status"] == "review_candidate"


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


def test_quality_gate_rejects_copied_description_and_optout_is_preserved():
    facts = {
        "products": [{
            "title": "Caramel Coffee",
            "type": "Coffee",
            "description": "Medium roast coffee with caramel flavor made for everyday brewing and serving at home.",
        }],
    }
    product = facts["products"][0]
    brief = {"concept": "Show the coffee being brewed and served in a morning ritual.", "format": "coffee ritual"}
    copied = compose_mod.validate_outreach_personalization(
        {
            "subject": "Coffee video idea",
            "message": "Caramel Coffee could be shown in a morning ritual. Medium roast coffee with caramel flavor made for everyday brewing and serving at home. Would you like to see it?",
        },
        facts,
        product,
        brief,
    )
    assert copied["manual_review_required"] is True
    assert "message copies a long phrase from the product description" in copied["review_reasons"]

    generated = compose_mod.generate_outreach_message(
        {"store_name": "Morning House"},
        {"brand_name": "Morning House"},
        {"primary_opportunity": "A coffee ritual", "opportunity_category": "food_drink_ritual"},
        product,
        {"optout": True, "optout_line": "Reply no if you would rather not hear from me."},
        {"concept": brief["concept"], "seasonal_context": "", "format": "coffee ritual"},
    )
    assert generated["message"].endswith("Reply no if you would rather not hear from me.")
    assert generated["message"].count("Reply no if you would rather not hear from me.") == 1


def test_quality_gate_rejects_unverified_christmas_delivery_promise():
    product = {
        "title": "Arcana Collector Card Pack",
        "type": "Collectible Cards",
        "description": "Pre-order. Expected to ship November 18, 2026.",
    }
    result = compose_mod.validate_outreach_personalization(
        {
            "subject": "Card pack video idea",
            "message": "Arcana Collector Card Pack could have a fun reveal. I pictured a close shot of the pack, then a quick look through the cards, with the date on screen. It could arrive by Christmas and make a great gift. Would you like to see the concept?",
        },
        {"products": [product]},
        product,
        {"concept": "Hold on the card pack, then reveal the cards.", "seasonal_context": "Christmas"},
    )

    assert result["manual_review_required"] is True
    assert "message contains unsupported or performance claims" in result["review_reasons"]


def test_local_outreach_uses_distinct_seasonal_product_concepts():
    scenarios = [
        ({
            "store_name": "Arcana Cards",
            "domain": "arcana.example",
            "product_types": ["Collectible Cards"],
            "products": [{
                "title": "Arcana Collector Card Pack",
                "type": "Collectible Cards",
                "description": "Pre-order now. Expected to ship November 18, 2026. Includes a collection of illustrated cards.",
                "image": True,
                "image_urls": ["https://cdn.example/cards.jpg"],
            }],
        }, ["pack", "cards", "november", "christmas"]),
        ({
            "store_name": "Morning House",
            "domain": "morning.example",
            "product_types": ["Coffee"],
            "products": [{
                "title": "Medium Roast Caramel Coffee",
                "type": "Coffee",
                "description": "Medium roast coffee with caramel flavor, made for everyday brewing and serving.",
                "image": True,
            }],
        }, ["caramel", "pour", "christmas"]),
        ({
            "store_name": "Night Sky",
            "domain": "nightsky.example",
            "product_types": ["Lighting"],
            "products": [{
                "title": "Star Projector Night Light",
                "type": "Lighting",
                "description": "Projects stars across the ceiling as a soft night light for a bedroom.",
                "image": True,
            }],
        }, ["ceiling", "stars", "christmas"]),
        ({
            "store_name": "Black Chapel",
            "domain": "blackchapel.example",
            "product_types": ["Clothing"],
            "products": [{
                "title": "Gothic Graphic Hoodie",
                "type": "Clothing",
                "description": "",
                "image": True,
            }],
        }, ["gothic", "graphic", "outfit", "christmas"]),
    ]
    messages = []
    banned_phrases = (
        "i saw ", "its page says", "that gave me an idea", "premium product showcase",
        "i create short, product-specific videos", "would a short storyboard be useful",
    )

    for facts, required_terms in scenarios:
        result = asyncio.run(compose_mod.compose(
            facts,
            {"use_ai": False, "seasonal_context": "Christmas"},
        ))
        message = result["body"]
        lowered = message.lower()
        messages.append(message)
        assert result["manual_review_required"] is False
        assert 40 <= len(message.split()) <= 95
        assert all(term in lowered for term in required_terms)
        assert not any(phrase in lowered for phrase in banned_phrases)
        description = facts["products"][0].get("description", "")
        assert not description or description not in message

    assert len(set(messages)) == 4
    assert "deliver by christmas" not in messages[0].lower()
    assert "arrive by christmas" not in messages[0].lower()


def test_seasonal_context_can_be_disabled_for_local_outreach():
    facts = {
        "store_name": "Morning House",
        "domain": "morning.example",
        "product_types": ["Coffee"],
        "products": [{
            "title": "Medium Roast Caramel Coffee",
            "type": "Coffee",
            "description": "Medium roast coffee with caramel flavor, made for everyday brewing and serving.",
            "image": True,
        }],
    }

    result = asyncio.run(compose_mod.compose(facts, {"use_ai": False, "seasonal_context": "off"}))

    assert result["manual_review_required"] is False
    assert "christmas" not in result["body"].lower()

    card_facts = {
        "store_name": "Arcana Cards",
        "domain": "arcana.example",
        "product_types": ["Collectible Cards"],
        "products": [{
            "title": "Arcana Collector Card Pack",
            "type": "Collectible Cards",
            "description": "Pre-order. Expected to ship November 18, 2026.",
            "image": True,
        }],
    }
    card_result = asyncio.run(compose_mod.compose(card_facts, {"use_ai": False, "seasonal_context": "off"}))
    assert "november 18, 2026" in card_result["body"].lower()
    assert "christmas" not in card_result["body"].lower()


def test_product_minimum_score_is_configurable_for_skip_results():
    facts = {
        "store_name": "Everyday Goods",
        "domain": "everyday.example",
        "products": [{
            "title": "Everyday Canvas Tote Bag",
            "url": "https://everyday.example/products/tote",
            "description": "",
            "image": True,
        }],
    }

    result = asyncio.run(compose_mod.compose(
        facts,
        {"use_ai": False, "min_product_score": 10},
    ))

    assert result["body"] == ""
    assert result["manual_review_required"] is True
    assert result["intelligence"]["product_selection"]["selection_status"] == "deprioritized"


def test_automatic_seasonal_context_is_date_aware_and_configurable():
    assert compose_mod.seasonal_context_for({}, date(2026, 10, 22)) == "Christmas"
    assert compose_mod.seasonal_context_for({}, date(2026, 9, 30)) == ""
    assert compose_mod.seasonal_context_for({"seasonal_context": "off"}, date(2026, 12, 1)) == ""
    assert compose_mod.seasonal_context_for({"seasonal_context": "Spring"}, date(2026, 12, 1)) == "Spring"


def test_intelligent_prompt_includes_variants_but_not_image_urls():
    facts = {
        "products": [{
            "title": "Graphic Hoodie",
            "image": True,
            "image_urls": ["https://cdn.example/private-image.jpg"],
            "variants": [{"title": "Black / Large", "options": ["Black", "Large"]}],
        }],
    }

    prompt = compose_mod.build_intelligent_outreach_prompt(
        facts,
        {},
        {},
        {"product_name": "Graphic Hoodie"},
        {},
        {},
    )

    assert "Black" in prompt and "Large" in prompt
    assert '"image_reference_available": true' in prompt
    assert "private-image.jpg" not in prompt
    assert "not visually analyzed" in prompt


def test_explicit_sample_video_is_used_instead_of_a_hypothetical_offer():
    facts = {
        "store_name": "Morning House",
        "sample_video_url": "https://samples.example/caramel-coffee.mp4",
        "products": [{
            "title": "Caramel Coffee",
            "type": "Coffee",
            "description": "Medium roast coffee with caramel flavor.",
        }],
    }
    product = facts["products"][0]
    prompt = compose_mod.build_intelligent_outreach_prompt(
        facts, {}, {}, {"product_name": "Caramel Coffee"}, {}, {},
    )
    generated = compose_mod.generate_outreach_message(
        facts,
        {"brand_name": "Morning House"},
        {"primary_opportunity": "A coffee ritual", "opportunity_category": "food_drink_ritual"},
        product,
        {},
        {"concept": "Show the coffee being brewed and served.", "format": "coffee ritual"},
    )

    assert '"sample_video_reference": "https://samples.example/caramel-coffee.mp4"' in prompt
    assert "https://samples.example/caramel-coffee.mp4" in generated["message"]
    assert "Would you like to see the sample?" in generated["message"]
    assert "storyboard" not in generated["message"].lower()
    assert compose_mod._sample_video_reference({}, {"sample_video_url": "javascript:alert(1)"}) == ""


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


def test_product_page_audit_records_media_without_inventing_customer_problems():
    product = {"title": "Clamp-On Task Light", "url": "https://shop.example/products/light"}

    audit = audit_product_page(
        product,
        '<main class="product-gallery"><img src="/light.jpg">'
        '<video><source src="/light-demo.mp4"></video></main>',
        "https://shop.example/products/light",
    )

    assert audit["page_checked"] is True
    assert audit["image_count"] == 1
    assert audit["video_detected"] is True
    assert product["video_assets"] == [{"type": "product_page_video", "url": "/light-demo.mp4"}]


@pytest.mark.parametrize(("max_pages", "expected_audits"), [(5, 1), (7, 3)])
def test_shopify_crawl_audits_products_within_page_limit(max_pages, expected_audits):
    origin = "https://shop.example"
    products_payload = [
        {
            "title": f"Task Light {index}",
            "handle": f"task-light-{index}",
            "body_html": "<p>Clamp the light onto a shelf and angle it over a desk.</p>",
            "product_type": "Lighting",
            "variants": [{"title": "Default", "price": "30.00"}],
            "images": [{"src": f"https://cdn.example/light-{index}.jpg"}],
        }
        for index in range(3)
    ]

    class FakeFetcher:
        def __init__(self):
            self.page_requests = []

        async def get_json(self, url):
            if url.endswith("/meta.json"):
                return {"myshopify_domain": "shop.myshopify.com", "name": "Example Lighting"}, 200
            if "/products.json" in url:
                return {"products": products_payload}, 200
            if "/collections.json" in url:
                return {"collections": []}, 200
            return None, 404

        async def get(self, url):
            self.page_requests.append(url)
            if url == origin:
                return 200, '<html><script src="https://cdn.shopify.com/theme.js"></script></html>', url
            if "/products/" in url:
                return 200, '<main class="product__media"><img src="https://cdn.example/light-0.jpg"></main>', url
            return 200, "<html><body><p>We make useful lighting for everyday work.</p></body></html>", url

    fetcher = FakeFetcher()
    result = asyncio.run(crawl_store(fetcher, {"domain": "shop.example"}, {"max_pages": max_pages}))
    audited = [product for product in result["facts"]["products"] if product.get("presentation_audit")]
    product_requests = [url for url in fetcher.page_requests if "/products/" in url]

    assert result["ok"] is True
    assert len(product_requests) == expected_audits
    assert len(audited) == expected_audits
    assert all(product["presentation_audit"]["page_checked"] for product in audited)


def test_local_fallback_runs_without_api_key(monkeypatch):
    facts = {
        "store_name": "Bright Workshop",
        "domain": "brightworkshop.example",
        "url": "https://brightworkshop.example",
        "product_types": ["Lighting"],
        "products": [{
            "title": "Clamp-On Task Light",
            "url": "https://brightworkshop.example/products/clamp-on-task-light",
            "type": "Lighting",
            "description": "Clamp the light onto a shelf or desk edge and angle the arm over your workspace.",
            "image": True,
            "presentation_audit": {"page_checked": True, "video_detected": False},
        }],
    }

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("AI should not be called without an API key")

    monkeypatch.setattr(compose_mod, "compose_intelligent_ai", fail_if_called)
    result = asyncio.run(compose_mod.compose(facts, {"use_ai": True}))

    assert result["manual_review_required"] is False
    assert result["engine"] == "evidence-template"
    assert result["writing_mode"] == "local-no-key"
    assert result["body"]
    assert "Clamp-On Task Light" in result["body"]
    assert "clamp" in result["body"].lower()
    assert "i create short, product-specific videos" not in result["body"].lower()
    assert "short concept around it" not in result["body"].lower()
    assert "its page says" not in result["body"].lower()
    assert "that gave me an idea" not in result["body"].lower()
    assert result["subjects"] == ["a video idea for Clamp-On Task Light"]


def test_ai_failure_uses_local_fallback_and_exposes_reason(monkeypatch):
    facts = {
        "store_name": "Bright Workshop",
        "domain": "brightworkshop.example",
        "url": "https://brightworkshop.example",
        "product_types": ["Lighting"],
        "products": [{
            "title": "Clamp-On Task Light",
            "url": "https://brightworkshop.example/products/clamp-on-task-light",
            "type": "Lighting",
            "description": "Clamp the light onto a shelf or desk edge and angle the arm over your workspace.",
            "image": True,
            "presentation_audit": {"page_checked": True, "video_detected": False},
        }],
    }

    async def fail_ai(*args, **kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(compose_mod, "compose_intelligent_ai", fail_ai)
    result = asyncio.run(compose_mod.compose(facts, {"use_ai": True, "api_key": "test-key"}))

    assert result["manual_review_required"] is False
    assert result["writing_mode"] == "ai-fallback"
    assert result["fallback_reason"] == "provider unavailable"
    assert "Clamp-On Task Light" in result["body"]


def test_new_defaults_and_legacy_default_migration(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_conn", None)
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "settings.db"))

    initial = db.load_settings()

    assert initial["offer"] == ""
    assert initial["video_line"] == ""
    assert initial["cta"] == "auto"
    assert initial["subject_hint"] == "a short video idea for {product}"
    assert initial["seasonal_context"] == "auto"
    assert initial["min_product_score"] == 5
    assert initial["tone"].startswith("Warm, concise, specific")
    assert initial["max_pages"] == 10
    assert initial["concurrency"] == 3
    assert initial["request_delay"] == 0.75

    db.save_settings({
        "offer": db.LEGACY_DEFAULTS["offer"][0],
        "video_line": db.LEGACY_DEFAULTS["video_line"][0],
        "cta": db.LEGACY_DEFAULTS["cta"][0],
        "subject_hint": db.LEGACY_DEFAULTS["subject_hint"][0],
    })
    migrated = db.load_settings()

    assert migrated["offer"] == db.DEFAULTS["offer"]
    assert migrated["video_line"] == db.DEFAULTS["video_line"]
    assert migrated["cta"] == db.DEFAULTS["cta"]
    assert migrated["subject_hint"] == db.DEFAULTS["subject_hint"]

    db.save_settings({"seasonal_context": "off", "min_product_score": 7})
    configured = db.load_settings()
    assert configured["seasonal_context"] == "off"
    assert configured["min_product_score"] == 7

    db.save_settings({"offer": "I produce short documentary-style product films."})
    assert db.load_settings()["offer"] == "I produce short documentary-style product films."

    db.save_settings({
        "offer": db.LEGACY_DEFAULTS["offer"][1],
        "video_line": db.LEGACY_DEFAULTS["video_line"][1],
        "cta": db.LEGACY_DEFAULTS["cta"][1],
        "subject_hint": db.LEGACY_DEFAULTS["subject_hint"][1],
    })
    migrated_recent = db.load_settings()

    assert migrated_recent["offer"] == db.DEFAULTS["offer"]
    assert migrated_recent["video_line"] == db.DEFAULTS["video_line"]
    assert migrated_recent["cta"] == db.DEFAULTS["cta"]
    assert migrated_recent["subject_hint"] == db.DEFAULTS["subject_hint"]
