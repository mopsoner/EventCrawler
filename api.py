from flask import Blueprint, jsonify
from db import list_events, list_free_products, list_patterns, list_extraction_runs

api = Blueprint("api", __name__, url_prefix="/api")


@api.get("/events")
def api_events():
    return jsonify(list_events())


@api.get("/free")
def api_free():
    return jsonify(list_free_products())


@api.get("/new")
def api_new():
    rows = [r for r in list_free_products() if r.get("is_available") == 1]
    return jsonify(rows)


@api.get("/patterns")
def api_patterns():
    return jsonify(list_patterns())


@api.get("/runs")
def api_runs():
    return jsonify(list_extraction_runs())
