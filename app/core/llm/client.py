import os
from typing import Type, TypeVar, cast
from pydantic import BaseModel
from google import genai
from google.genai import types

T = TypeVar("T", bound=BaseModel)


class LLMClient:
    def __init__(self):
        # Automatically detects GEMINI_API_KEY from environment variables
        self.api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            raise ValueError("LLM Error: GEMINI_API_KEY or GOOGLE_API_KEY environment variable is missing.")

        # Initialize sync client (use context managers where possible)
        self.client = genai.Client()
        self.default_model = "gemini-3.5-flash"
        # print("Available models:", [model.name for model in self.client.models.list()])


    def generate_structured_json(self, prompt: str, response_schema: Type[T], model: str | None = None) -> T:
        """
        Sends a prompt to Gemini and enforces strict Pydantic structured output mapping.
        """
        target_model = model or self.default_model

        # Leverage the native google-genai SDK structured output options
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=response_schema,
            temperature=0.1,  # Keep it highly deterministic for structured data extraction
        )

        try:
            response = self.client.models.generate_content(
                model=target_model,
                contents=prompt,
                config=config
            )

            # The SDK handles Pydantic validation implicitly via response.parsed
            if response.parsed:
                return cast(T, response.parsed)
            # Check for text availability and raise a clear runtime error if it's missing
            if not response.text:
                raise ValueError("LLM Error: Received an empty text response from the API.")

            # Fallback if parsing didn't populate .parsed automatically
            return response_schema.model_validate_json(response.text)

        except Exception as e:
            raise RuntimeWarning(f"LLM Structure Extraction Failed: {str(e)}")

    def close(self):
        """Releases underlying HTTP client network connections."""
        self.client.close()



# test the LLMClient class
if __name__ == "__main__":
    from pydantic import BaseModel
    from dotenv import load_dotenv

    load_dotenv()

    class TestSchema(BaseModel):
        name: str
        age: int

    client = LLMClient()
    prompt = "Generate a JSON object with name and age."
    result = client.generate_structured_json(prompt, TestSchema)
    print(result)
    client.close()