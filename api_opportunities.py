from flask import Blueprint, jsonify
from db_opportunities import list_opportunities

api_opportunities = Blueprint("api_opportunities", __name__, url_prefix="/api")


@api_opportunities.get("/opportunities")
def api_opportunities_list():
    return jsonify(list_opportunities())
