from pydantic import BaseModel, Field


class RessourcesConfig(BaseModel):
    tessdata: str = Field(default="./data/assets/tessdata")
    nltk_data: str = Field(default="./data/assets/nltk_data")
    custom: str = Field(default="./data/assets/custom")
