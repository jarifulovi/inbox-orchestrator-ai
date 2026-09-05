import os
from typing import Type, TypeVar, cast
from pydantic import BaseModel
from google import genai
from google.genai import types

from app.core.services.utils.llm_context_recorder import LLMContextRecorder

T = TypeVar("T", bound=BaseModel)


class LLMClient:
    def __init__(self):
        # Automatically detects GEMINI_API_KEY from environment variables
        self.api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            raise ValueError("LLM Error: GEMINI_API_KEY or GOOGLE_API_KEY environment variable is missing.")

        # Initialize sync client (use context managers where possible)
        self.client = genai.Client()
        self.default_model = "gemini-3.6-flash"
        self.recorder = LLMContextRecorder()
        # print("Available models:", [model.name for model in self.client.models.list()])


    def generate_structured_json(self, prompt: str, response_schema: Type[T], model: str | None = None) -> T:
        """
        Sends a prompt to Gemini and enforces strict Pydantic structured output mapping.
        Automatically records the input prompt and output response to local context storage.
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

            result = None
            # The SDK handles Pydantic validation implicitly via response.parsed
            if response.parsed:
                result = cast(T, response.parsed)
            elif not response.text:
                raise ValueError("LLM Error: Received an empty text response from the API.")
            else:
                result = response_schema.model_validate_json(response.text)

            # Record LLM context asynchronously/safely without blocking execution
            self.recorder.record_context(prompt=prompt, response_data=result, model=target_model)
            return result

        except Exception as e:
            raise RuntimeWarning(f"LLM Structure Extraction Failed: {str(e)}")

    def generate_text(self, prompt: str, model: str | None = None, temperature: float = 0.7) -> str:
        """
        Sends a prompt to Gemini and returns raw string response text.
        Automatically records input prompt and output response to local context storage.
        """
        target_model = model or self.default_model
        config = types.GenerateContentConfig(
            temperature=temperature,
        )
        try:
            response = self.client.models.generate_content(
                model=target_model,
                contents=prompt,
                config=config
            )
            result_text = response.text or ""
            self.recorder.record_context(prompt=prompt, response_data=result_text, model=target_model)
            return result_text
        except Exception as e:
            raise RuntimeError(f"LLM Text Generation Failed: {str(e)}")

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