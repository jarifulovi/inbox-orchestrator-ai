from typing import Dict, Optional, Union

MODEL_REGISTRY: Dict[int, str] = {
    1: "gemini-3.5-flash-lite",
    2: "gemini-3.6-flash"
}

DEFAULT_MODEL_INDEX: int = 1
DEFAULT_MODEL_NAME: str = MODEL_REGISTRY[DEFAULT_MODEL_INDEX]


def get_model_name(model_input: Optional[Union[int, str]] = None) -> str:
    """
    Resolves an integer model index (1 or 2) into the exact Gemini API model name string.
    Defaults to Index 1 ('gemini-3.5-flash-lite') for background worker tasks if missing or invalid.
    """
    if model_input is None:
        return DEFAULT_MODEL_NAME

    if isinstance(model_input, int):
        return MODEL_REGISTRY.get(model_input, DEFAULT_MODEL_NAME)

    if isinstance(model_input, str):
        if model_input.isdigit():
            return MODEL_REGISTRY.get(int(model_input), DEFAULT_MODEL_NAME)
        # Support string matching for legacy settings migration
        for idx, name in MODEL_REGISTRY.items():
            if name == model_input:
                return name

    return DEFAULT_MODEL_NAME
