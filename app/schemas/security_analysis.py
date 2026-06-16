from pydantic import BaseModel, Field
from datetime import datetime
from typing import List, Dict, Optional



class PreSecurityPrediction(BaseModel):
    """Output of Pass 1 (Rule/Regex Engine) running inside model/security/"""
    pre_security_passed: bool
    security_risks: List[str] = Field(default_factory=list)  # ['abuse', 'financial_risk', 'scam']
    # New Extended Fields for Downstream/Post-Security consumption
    extracted_spam_score: Optional[float] = None
    has_reply_to_mismatch: bool = False
    is_possible_prompt_injection: bool = False
    raw_spf_result: Optional[str] = None
    raw_dkim_result: Optional[str] = None
    pass1_computed_score: float = 1.00  # Baseline markdown calculated here


class PostSecurityPrediction(BaseModel):
    """Output of Pass 2 (Context Engine) running inside model/security/"""
    is_phishing_anomaly: bool
    context_records_evaluated: int
    security_trust_score: float  # 0.00 to 1.00
    security_trust_level: str    # 'trusted', 'neutral', 'suspicious'


class SecurityAnalysisUpdate(BaseModel):
    """
    Payload used by the ML background worker to update the
    pre-existing email_security_analysis record.
    """
    pre_security_passed: bool
    security_risks: List[str]
    is_phishing_anomaly: bool
    context_records_evaluated: int
    security_trust_score: float
    security_trust_level: str
    post_security_analyzed_at: datetime

