from typing import List, Dict, Any

class EmailFilter:
    # Maps email category to list of allowed fact types.
    # If a category is not present, all fact types are allowed by default.
    CATEGORY_FACT_POLICIES = {
        "spam": [],  # Block-all approach: completely bypasses extraction
        "work/prof": ["task", "commitment", "decision", "question", "fact"],  # Full extraction allowed
        "financial": ["task", "commitment", "decision", "question", "fact"],  # Full extraction allowed
        "system/service": ["task", "decision", "question"],  # Only actionable tasks, decisions, questions
        "others": ["question", "decision"],  # Selective approach: ignore casual/noise tasks and commitments
    }

    @classmethod
    def should_bypass_extraction(cls, category: str | None) -> bool:
        if not category:
            return False
        # If the allowed list for the category is empty, we completely bypass extraction.
        if category in cls.CATEGORY_FACT_POLICIES and len(cls.CATEGORY_FACT_POLICIES[category]) == 0:
            return True
        return False

    @classmethod
    def filter_extracted_facts(cls, category: str | None, facts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not category or not facts:
            return facts

        allowed_types = cls.CATEGORY_FACT_POLICIES.get(category)
        if allowed_types is None:
            return facts

        return [f for f in facts if f.get("fact_type") in allowed_types]
