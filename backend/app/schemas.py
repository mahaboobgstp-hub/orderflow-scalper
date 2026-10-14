from pydantic import BaseModel, Field, model_validator


class MarketSnapshot(BaseModel):
    symbol: str = "IDFCFIRSTB"
    last_price: float = Field(gt=0)
    bid_price: float = Field(gt=0)
    ask_price: float = Field(gt=0)
    bid_quantity: int = Field(ge=0)
    ask_quantity: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_prices(self):
        if self.ask_price < self.bid_price:
            raise ValueError(
                "ask_price must be greater than or equal to bid_price"
            )
        return self

