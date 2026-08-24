import json
import os
import re
from typing import Any, Dict, List, Optional

import requests

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
OPENAI_TIMEOUT = int(os.getenv("OPENAI_TIMEOUT", "45"))


def openai_enabled() -> bool:
    return bool(OPENAI_API_KEY)


def _safe_json_parse(text: str) -> Optional[dict]:
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return None
    return None


def _responses_json(system_prompt: str, user_payload: dict) -> Optional[dict]:
    if not openai_enabled():
        return None
    try:
        r = requests.post(
            "https://api.openai.com/v1/responses",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": OPENAI_MODEL,
                "input": [
                    {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
                    {"role": "user", "content": [{"type": "input_text", "text": json.dumps(user_payload, ensure_ascii=False)}]},
                ],
            },
            timeout=OPENAI_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        output_text = data.get("output_text") or ""
        return _safe_json_parse(output_text)
    except Exception:
        return None


def heuristic_event_labels(event: Dict[str, Any]) -> Dict[str, Any]:
    text = " ".join(
        [
            str(event.get("name") or ""),
            str(event.get("subtitle") or ""),
            str(event.get("description") or ""),
        ]
    ).strip()
    low = text.lower()
    language = "fr" if any(x in low for x in ["soirée", "réservation", "pré", "événement", "billet", "guadeloupe"]) else "en"
    event_type = "party"
    if any(x in low for x in ["boat", "boatride", "cruise"]):
        event_type = "boat_party"
    elif any(x in low for x in ["jouvert", "j'ouvert"]):
        event_type = "jouvert"
    elif any(x in low for x in ["breakfast", "brunch"]):
        event_type = "breakfast_fete"
    elif any(x in low for x in ["parade", "carnaval de rue", "street parade"]):
        event_type = "parade"
    genres: List[str] = []
    for label, keys in {
        "soca": ["soca"],
        "dancehall": ["dancehall"],
        "afro": ["afro", "afrobeats", "amapiano"],
        "bouyon": ["bouyon"],
        "kompa": ["kompa"],
        "zouk": ["zouk"],
        "shatta": ["shatta"],
    }.items():
        if any(k in low for k in keys):
            genres.append(label)
    audience_tags: List[str] = []
    for label, keys in {
        "all_white": ["all white", "tout en blanc", "white party"],
        "free_ticket": ["free", "gratuit"],
        "early_bird": ["early bird", "presale", "pre-sale", "phase 1", "tier 1"],
        "carnival": ["carnival", "carnaval"],
    }.items():
        if any(k in low for k in keys):
            audience_tags.append(label)
    summary_source = str(event.get("description") or event.get("subtitle") or event.get("name") or "").strip()
    summary_short = re.sub(r"\s+", " ", summary_source)[:220]
    return {
        "language": language,
        "summary_short": summary_short,
        "event_type": event_type,
        "genres_json": genres,
        "audience_tags_json": audience_tags,
        "confidence": 0.45,
    }


def enrich_event_labels(event: Dict[str, Any]) -> Dict[str, Any]:
    fallback = heuristic_event_labels(event)
    prompt = (
        "Return ONLY JSON with keys language, summary_short, event_type, genres_json, audience_tags_json, confidence. "
        "Keep summary_short under 220 characters. genres_json and audience_tags_json must be arrays of short strings."
    )
    payload = {
        "name": event.get("name"),
        "subtitle": event.get("subtitle"),
        "description": event.get("description"),
        "event_date": event.get("event_date"),
        "region": event.get("region"),
        "products": event.get("products", []),
    }
    result = _responses_json(prompt, payload)
    if not isinstance(result, dict):
        return fallback
    return {
        "language": str(result.get("language") or fallback["language"]),
        "summary_short": str(result.get("summary_short") or fallback["summary_short"])[:220],
        "event_type": str(result.get("event_type") or fallback["event_type"]),
        "genres_json": result.get("genres_json") if isinstance(result.get("genres_json"), list) else fallback["genres_json"],
        "audience_tags_json": result.get("audience_tags_json") if isinstance(result.get("audience_tags_json"), list) else fallback["audience_tags_json"],
        "confidence": float(result.get("confidence") or fallback["confidence"]),
    }


def heuristic_selector_repair(failure: Dict[str, Any]) -> Dict[str, Any]:
    step = str(failure.get("step_name") or "").lower()
    intent = str(failure.get("intent") or "").lower()
    low = " ".join([
        step,
        intent,
        str(failure.get("error_text") or "").lower(),
        str(failure.get("visible_text_excerpt") or "").lower(),
    ])
    if "quantity" in low or "plus" in low or "ticket" in low:
        return {
            "failure_type": "selector_miss",
            "intent": "quantity_plus",
            "candidate_selectors": [".qty-btn.qty-plus", ".qty-plus", "button:has-text('+')", "button:has-text('Ajouter')", "button:has-text('Add')"],
            "confidence": 0.42,
            "reason": "Fallback quantity selectors",
        }
    if "checkout" in low or "continue booking" in low:
        return {
            "failure_type": "selector_miss",
            "intent": "checkout",
            "candidate_selectors": ["button:has-text('Continue booking')", "button:has-text('Continuer la réservation')", "button:has-text('Proceed to checkout')", "button:has-text('Book now')", "button:has-text('Commander')"],
            "confidence": 0.44,
            "reason": "Fallback checkout selectors",
        }
    if "confirm" in low or "submit" in low or "advance" in low or "payment" in low:
        return {
            "failure_type": "selector_miss",
            "intent": "advance",
            "candidate_selectors": ["button:has-text('Continue')", "button:has-text('Continuer')", "button:has-text('Suivant')", "button:has-text('Confirmer')", "button:has-text('Confirm')", "button[type='submit']"],
            "confidence": 0.4,
            "reason": "Fallback advance selectors",
        }
    return {
        "failure_type": "unknown",
        "intent": "success",
        "candidate_selectors": ["text=Commande confirmée", "text=Order confirmed", "text=Référence de commande", "text=Order number"],
        "confidence": 0.31,
        "reason": "Fallback confirmation signals",
    }


def suggest_selector_repair(failure: Dict[str, Any]) -> Dict[str, Any]:
    fallback = heuristic_selector_repair(failure)
    prompt = (
        "You diagnose Playwright booking failures. Return ONLY JSON with keys failure_type, intent, candidate_selectors, confidence, reason. "
        "candidate_selectors must be an array of CSS/text Playwright selectors. Keep 3 to 8 selectors max."
    )
    payload = {
        "step_name": failure.get("step_name"),
        "intent": failure.get("intent"),
        "error_text": failure.get("error_text"),
        "page_url": failure.get("page_url"),
        "page_title": failure.get("page_title"),
        "visible_text_excerpt": failure.get("visible_text_excerpt"),
        "html_excerpt": failure.get("html_excerpt"),
        "tried_selectors": failure.get("tried_selectors_json") or failure.get("tried_selectors") or "[]",
    }
    result = _responses_json(prompt, payload)
    if not isinstance(result, dict):
        return fallback
    return {
        "failure_type": str(result.get("failure_type") or fallback["failure_type"]),
        "intent": str(result.get("intent") or fallback["intent"]),
        "candidate_selectors": result.get("candidate_selectors") if isinstance(result.get("candidate_selectors"), list) and result.get("candidate_selectors") else fallback["candidate_selectors"],
        "confidence": float(result.get("confidence") or fallback["confidence"]),
        "reason": str(result.get("reason") or fallback["reason"]),
    }
