from db import list_events, list_free_products
from opportunities import build_opportunity_rows


def list_opportunities():
    return build_opportunity_rows(list_events(), list_free_products())
