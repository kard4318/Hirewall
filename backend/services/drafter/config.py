# Configuration for the drafter service

from dataclasses import dataclass, field

_DECISION_PHRASES_EN: dict[str, tuple[str, ...]] = {
    "hire": (
        r"you(?:'ve| have)? been hired",
        r"you(?: a|')re hired",
        r"you got the (?:job|position|role)",
        r"welcome to the team",
        r"hire you",
    ),
    "offer": (
        r"job offer",
        r"offer letter",
        r"offer of employment",
        r"extend(?:ing)? (?:you )?an offer",
        r"offer you the (?:position|role|job)",
        r"pleased to offer",
    ),
    "reject": (
        r"regret to inform",
        r"not (?:be )?(?:moving|going) forward",
        r"not to (?:move|go|proceed)(?: forward)?",
        r"not (?:be )?proceed(?:ing)?",
        r"won't be (?:moving|going) forward",
        r"not (?:been )?selected",
        r"unsuccessful",
        r"reject(?:ed|ion)?",
        r"other candidates",
        r"position has been filled",
    ),
    "advance": (
        r"next (?:stage|round)",
        r"(?<!not )(?<!not be )(?<!not to )(?<!won't be )mov(?:e|ed|ing) forward with your application",
        r"advanc(?:e|ed|ing) to",
        r"shortlisted",
        r"selected for",
    ),
    "salary": (
        r"salary",
        r"compensation",
        r"remuneration",
        r"pay range",
        r"wages?",
        r"bonus",
        r"equity",
    ),
    # Allowed when any human decision is recorded.
    "outcome": (
        r"congratulations",
        r"you passed",
        r"(?:not|\w+n't) (?:yet )?(?:made|reached|taken) (?:a |any |the )?(?:final )?decision",
        r"no (?:final )?decision",
        r"(?:looks?|sounds?)(?: like an?)? (?:very )?(?:strong|great|impressive|solid|excellent|promising|good)",
        r"(?:strong|solid|impressive|excellent) (?:candidate|background|profile|experience|application)",
        r"good fit",
    ),
}

_INTERNAL_PHRASES_EN: tuple[str, ...] = (
    r"scor(?:e|es|ed|ing)",
    r"rank(?:ed|ing|ings)?",
    r"screen(?:ing|er) (?:result|results|system|tool)",
    r"internal notes?",
    r"recruiter notes?",
    r"rasch",
    r"trusted context",
    r"algorithm",
    r"\bage\b",
    r"gender",
    r"religio(?:n|us)",
    r"ethnic(?:ity)?",
    r"\brace\b",
    r"nationality",
    r"disabilit(?:y|ies)",
    r"pregnan(?:t|cy)",
    r"marital status",
)


_PROMISE_PHRASES_EN: tuple[str, ...] = (
    r"shortly",
    r"soon",
    r"be in touch",
    r"get back to you",
    r"calendar invit\w*",
    r"we will (?:send|contact|call|email|follow up|update)",
    r"we'll (?:send|contact|call|email|follow up|update)",
)


_COMPLETE_PHRASES_EN: tuple[str, ...] = (
    r"all we need",
    r"everything we need",
    r"(?:nothing|no(?:thing)?) (?:else|more|further)",
    r"no (?:other|additional|further|more) (?:documents?|information|materials?)",
    r"(?:file|application) is complete",
    r"(?:don't|do not) need anything",
    r"(?:don't|do not) (?:require|need) (?:any|additional|further|more|other)",
    r"(?:is|are) (?:sufficient|enough)",
    r"have everything",
)

# A sentence naming a missing document with one of these, and none of the negations, says it arrived.
_RECEIVED_PHRASES_EN: tuple[str, ...] = (r"arrived", r"received", r"came through", r"got", r"have your", r"on file")
_NOT_RECEIVED_PHRASES_EN: tuple[str, ...] = (
    r"not",
    r"\w+n't",
    r"missing",
    r"still",
    r"yet",
    r"need",
    r"waiting",
    r"awaiting",
    r"please",
    r"outstanding",
)


@dataclass(frozen=True)
class DrafterConfig:
    max_email_chars: int = 8000
    max_thread_messages: int = 10
    max_subject_chars: int = 200
    max_body_chars: int = 4000
    max_human_message_chars: int = 500
    max_revisions: int = 3
    # A local model can take well over a minute to load on its first call.
    llm_timeout_s: float = 180.0
    prompt_version: str = "drafter_system_v3"
    supported_languages: tuple[str, ...] = ("en",)
    allowed_link_domains: tuple[str, ...] = ("careers.hirewall.example",)
    allowed_email_domains: tuple[str, ...] = ("hirewall.example",)
    decision_phrases: dict[str, dict[str, tuple[str, ...]]] = field(
        default_factory=lambda: {"en": _DECISION_PHRASES_EN}
    )
    internal_phrases: dict[str, tuple[str, ...]] = field(default_factory=lambda: {"en": _INTERNAL_PHRASES_EN})
    promise_phrases: dict[str, tuple[str, ...]] = field(default_factory=lambda: {"en": _PROMISE_PHRASES_EN})
    complete_phrases: dict[str, tuple[str, ...]] = field(default_factory=lambda: {"en": _COMPLETE_PHRASES_EN})
    received_phrases: dict[str, tuple[str, ...]] = field(default_factory=lambda: {"en": _RECEIVED_PHRASES_EN})
    not_received_phrases: dict[str, tuple[str, ...]] = field(default_factory=lambda: {"en": _NOT_RECEIVED_PHRASES_EN})


DEFAULT_CONFIG = DrafterConfig()
