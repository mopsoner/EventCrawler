from typing import List, Optional
from pydantic import BaseModel, Field


class Product(BaseModel):
    product_name: str
    category: Optional[str] = None
    price_text: Optional[str] = None
    numeric_price: Optional[float] = None
    is_free: bool = False
    is_available: Optional[bool] = None
    availability_text: Optional[str] = None
    buy_link: Optional[str] = None
    details: Optional[str] = None


class EventData(BaseModel):
    event_url: str
    region: str
    name: Optional[str] = None
    subtitle: Optional[str] = None
    event_date: Optional[str] = None
    city: Optional[str] = None
    address: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None
    contact_website: Optional[str] = None
    google_maps_url: Optional[str] = None
    flyers: List[str] = Field(default_factory=list)
    products: List[dict] = Field(default_factory=list)
    score: int = 0
    extraction_mode: Optional[str] = None
    extraction_confidence: int = 0
