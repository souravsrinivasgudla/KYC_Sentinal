from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    # Accept several common env names for the HuggingFace token.
    hf_token: str = Field(
        default="",
        validation_alias=AliasChoices(
            "HF_TOKEN", "hf_token", "hugging_face", "huggingface_token", "HUGGINGFACE_TOKEN"
        ),
    )

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
