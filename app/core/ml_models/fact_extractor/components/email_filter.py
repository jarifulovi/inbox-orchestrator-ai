from typing import List, Dict, Any

class EmailFilter:
    # Maps email category to list of allowed fact types.
    # If a category is not present, all fact types are allowed by default.
    CATEGORY_FACT_POLICIES = {
        "spam": [],  # Block-all approach: completely bypasses extraction
        "work_professional": ["task", "commitment", "decision", "question", "fact"],  # Full extraction allowed
        "financial": ["task", "commitment", "decision", "question", "fact"],  # Full extraction allowed
        "system_automated": ["task", "decision", "question"],  # Only actionable tasks, decisions, questions
        "others": [],  # Block-all approach: completely bypasses extraction for general noise/promotions
    }

    @classmethod
    def should_bypass_extraction(cls, category: str | None, label_ids: List[str] | None = None) -> bool:
        # If Gmail labels explicitly flag this email as spam, bypass extraction immediately
        if label_ids and any(lid in label_ids for lid in {"SPAM", "CATEGORY_SPAM"}):
            return True
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
