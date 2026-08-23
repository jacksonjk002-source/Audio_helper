from pydantic import BaseModel, Field


class ExtractRequest(BaseModel):
    text: str = Field(..., min_length=1)


class ExtractResponse(BaseModel):
    address_a: str
    address_b: str
    category: str


class SearchRequest(BaseModel):
    address_a: str = Field(..., min_length=1)
    address_b: str = Field(..., min_length=1)
    category: str = Field(..., min_length=1)


class Midpoint(BaseModel):
    lng: float
    lat: float


class PoiItem(BaseModel):
    name: str
    address: str


class SearchResponse(BaseModel):
    midpoint: Midpoint
    pois: list[PoiItem]


class FinalizeRequest(BaseModel):
    midpoint: Midpoint
    pois: list[PoiItem] = Field(..., min_length=1)
    address_a: str | None = None
    address_b: str | None = None
    category: str | None = None
