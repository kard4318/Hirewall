# Configuration for the summarizer service

from dataclasses import dataclass


@dataclass(frozen=True)
class ClassifierConfig:
    max_email_chars: int = 6000
    max_subject_chars: int = 200
    max_reason_chars: int = 200
    # A local model can take well over a minute to load on its first call.
    llm_timeout_s: float = 180.0
    prompt_version: str = "classifier_system_v2"
    internal_email_domains: tuple[str, ...] = ("hirewall.example",)
    # A stranger's "unrelated" email matching these reaches a person, so impersonation and data requests are kept.
    stranger_request_patterns: tuple[str, ...] = (
        r"candidates?",
        r"applicants?",
        r"employees?",
        r"staff",
        r"personnel",
        r"payroll",
        r"records?",
        r"files?",
        r"passwords?",
        r"credentials?",
        r"bank",
        r"invoice",
        r"wire transfer",
        r"(?:send|forward|share|give|email) me",
        r"i am (?:the|your|a) (?:\w+ ){0,2}(?:ceo|cfo|director|manager|president|owner|head|admin\w*|lawyer|auditor)",
        r"on behalf of",
    )
    # Emails on these topics always reach a person, whatever the model suggests.
    human_topic_patterns: tuple[str, ...] = (
        r"salar(?:y|ies)",
        r"pay(?:ment)?",
        r"wages?",
        r"benefits?",
        r"contract",
        r"remote",
        r"full[- ]time",
        r"part[- ]time",
        r"visa",
        r"relocat\w+",
    )
    # These also become high urgency, because a late answer could cause real harm.
    serious_topic_patterns: tuple[str, ...] = (
        r"discriminat\w+",
        r"harass\w*",
        r"lawyer",
        r"legal action",
        r"formal complaint",
        r"unfair(?:ly)?",
    )


DEFAULT_CONFIG = ClassifierConfig()
