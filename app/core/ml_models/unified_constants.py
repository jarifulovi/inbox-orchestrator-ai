# app/core/config/model_manifest.py

CLASSIFIER_MODEL_NAME = "intent_classifier"
CLASSIFIER_MODEL_VERSION = "v1.0"
FACT_EXTRACTOR_MODEL_NAME = "fact_extractor"
FACT_EXTRACTOR_MODEL_VERSION = "fact_extractor_v1"

# =====================================================================
# 1. INTENT CLASSIFIER MANIFEST (Index-Locked Single Source of Truth)
# =====================================================================
INTENT_MANIFEST = {
    0: {"label": "financial", "penalty_score": 0.9, "is_high_risk": True, "is_actionable": True},
    1: {"label": "others", "penalty_score": 0.3, "is_high_risk": False, "is_actionable": False},
    2: {"label": "system_automated", "penalty_score": 0.7, "is_high_risk": True, "is_actionable": True},
    3: {"label": "work_professional", "penalty_score": 0.1, "is_high_risk": False, "is_actionable": True},
}

# Derived Utilities for Classifier Internal Mapping (Maintains O(1) Compatibility)
CLASSIFIER_LABELS = {idx: meta["label"] for idx, meta in INTENT_MANIFEST.items()}
HIGH_RISK_INTENT_INDICES = [idx for idx, meta in INTENT_MANIFEST.items() if meta["is_high_risk"]]
ACTIONABLE_INTENT_LABELS = {meta["label"] for idx, meta in INTENT_MANIFEST.items() if meta["is_actionable"]}

# =====================================================================
# 2. ACTION LINGUISTIC PRIMITIVES MANIFEST (Extensible Security Flags)
# =====================================================================
ACTION_SECURITY_MANIFEST = {
    # High-Concern Verbs (Triggers downstream deep history/context verification checks)
    "high_concern_verbs": ["send", "post", "submit", "email", "reply", "schedule"],

    # High-Risk/Destructive Verbs (Directly penalizes or flags suspicious workflows)
    "high_risk_verbs": ["spam", "unsubscribe", "delete", "block"],

    # Future Extensibility Targets (Objects/Tokens to inspect for behavior anomalies)
    "high_concern_objects": ["invoice", "bank", "routing", "credentials", "password", "payment"],

    # Global Linguistic Modifier Penalties
    "multipliers": {
        "high_concern_anomaly_penalty": 0.50,
        "high_risk_action_penalty": 0.30
    }
}

# =====================================================================
# 3. Security Tracking Engine Manifest (Flat Index-Locked)
# =====================================================================
# Valid output statuses for the global security tracking engine
SECURITY_TRUST_LEVELS = ["unverified", "trusted", "neutral", "suspicious"]

# Flat index tracking for localized contextual anomalies
SECURITY_RISK_CATEGORIES = [
    "subscription_overhead",
    "financial_anomaly",
    "marketing_phish_vector",
    "bulk_spam",
    "spoofing_target"
]