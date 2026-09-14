"""Conversation intent gate that keeps obvious casual input out of retrieval."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Annotated, Literal, Self
import unicodedata

from pydantic import Field, StrictStr
from pydantic.functional_validators import model_validator

from app.llm.schemas import NonBlank, StrictSchema

if TYPE_CHECKING:
    from app.retrieval.scope import ManifestScopeIndex, MatchedAlias

ConversationIntent = Literal["document_review", "service_help", "out_of_scope", "casual_chat"]

SERVICE_GUIDANCE = (
    "DocReview analyzes the SEC and DART filings available in its corpus. "
    "Choose the company and period, then ask a question about those filings."
)
UNSUPPORTED_GUIDANCE = "Please ask a question about company filings or financial reports."

CANNED_RESPONSES: dict[str, str] = {
    "안녕": SERVICE_GUIDANCE,
    "하이": SERVICE_GUIDANCE,
    "안녕하세요": SERVICE_GUIDANCE,
    "hi": SERVICE_GUIDANCE,
    "hello": SERVICE_GUIDANCE,
    "helloworld": SERVICE_GUIDANCE,
    "뭐함": SERVICE_GUIDANCE,
    "뭐해": SERVICE_GUIDANCE,
    "고마워": SERVICE_GUIDANCE,
    "감사합니다": SERVICE_GUIDANCE,
    "thanks": SERVICE_GUIDANCE,
    "thankyou": SERVICE_GUIDANCE,
    "도움말": SERVICE_GUIDANCE,
    "사용법": SERVICE_GUIDANCE,
    "help": SERVICE_GUIDANCE,
}

FILING_CUES = re.compile(
    r"\b(?:10-k|sec|dart|filing|disclosure|revenue|risk|section|item)\b|"
    r"공시|사업보고서|매출|위험|실적|재무|원인|근거|수치|성장|\bgrowth\b",
    flags=re.IGNORECASE,
)


FOLLOWUP_CUES = re.compile(
    r"^(?:what about|how about|and\b|then\b|also\b|그럼|그러면|그것|이것|그거|이거)|"
    r"(?:는|은|년)(?:요)?[?？]?$|(?<!\d)(?:19|20)\d{2}(?!\d)",
    re.IGNORECASE,
)
CASUAL_CUES = re.compile(
    r"\b(?:weather|thanks|thank you|joke|roleplay|pretend|cat)\b|"
    r"날씨|고마워|감사합니다|농담|고양이|역할극",
    re.IGNORECASE,
)

ROLEPLAY_CUES = re.compile(
    r"\bpretend\b|\brole\s*-?\s*play\b|\bact\s+(?:as|like)\b|"
    r"역할극|인\s*척|처럼\s*(?:말|행동|대답)|"
    r"(?:고양이|강아지|동물|캐릭터|로봇)(?:와|과|처럼)?\s*대화",
    re.IGNORECASE,
)

RESTATEMENT_CUES = re.compile(
    r"\b(?:again|repeat|re-?explain|translate)\b|\bexplain\s+(?:that|this|it)\b|"
    r"\bin\s+(?:korean|english)\b|"
    r"다시|한글로|한국어로|영어로|방금|아까",
    re.IGNORECASE,
)

CORPUS_WIDE_CUES = re.compile(
    r"\b(?:all|every)\s+(?:[a-z]+\s+){0,2}(?:companies|issuers|firms|corporations)\b|"
    r"\bcompare\s+(?:all|every|across)\b|\bcorpus[\s-]?wide\b|"
    r"\bacross\s+(?:all\s+)?(?:the\s+)?(?:companies|issuers|corpus|filings)\b|"
    r"모든\s*(?:회사|기업|발행인)|전체\s*(?:회사|기업|발행인)|모두\s*비교",
    re.IGNORECASE,
)

_EN_TOPIC_WORDS = (
    r"revenues?|sales|income|earnings?|profits?|margins?|ebitda|ebit|growth|"
    r"risks?|performance|outlook|guidance|demand|supply|investments?|capex|opex|"
    r"debts?|liquidity|dividends?|buybacks?|valuations?|forecasts?|trends?|"
    r"declines?|increases?|decreases?|segments?|operations?|business|markets?|"
    r"shares?|stocks?|prices?|financials?|results?|exposure|concentration|"
    r"customers?|inventor(?:y|ies)|cashflows?|cash|spending|costs?|expenses?|"
    r"research|development|r&d|hbm|dram|nand|memory|semiconductors?|chips?|"
    r"foundry|batter(?:y|ies)|ev|ai|cloud|data|centers?|centres?|gaming|"
    r"automotive|mobile|networks?|displays?|gpus?|cpus?|servers?|storage|"
    r"profitability|returns?|assets?|liabilit(?:y|ies)|equity|cogs|fcf|eps|"
    r"drove|drive|driven|drivers?|compare|comparison|compared|filings?|"
    r"disclosures?|sec|dart|edgar|10-?k|10-?q|8-?k|forms?|items?|sections?|"
    r"reports?|reported|cite|cited|citations?|evidence|remained|remains|"
    r"remaining|changed|changes|unchanged|stable|flat|improved|improvements?|"
    r"worsened|grew|factors?|reasons?|summary|summaries|details?|mentioned|"
    r"mentions?|highlights?|noted|notes?|impacts?|effects?|pressures?|"
    r"headwinds?|tailwinds?|mix|volumes?|pricing|asps?|utilization|capacity|"
    r"backlogs?|orders?|bookings?|shipments?"
)
_EN_FILLER_WORDS = (
    r"what|why|how|when|which|who|whom|whose|did|does|do|is|are|was|were|"
    r"will|would|could|should|can|the|a|an|of|for|in|on|to|and|or|but|"
    r"between|with|without|about|into|over|under|by|from|at|as|its?|their|"
    r"they|them|tell|me|us|explain|describe|summari[sz]e|show|give|list|key|"
    r"main|major|primary|total|overall|biggest|largest|top|much|many|any|"
    r"some|all|each|every|available|per|company|companies|firms?|"
    r"corp(?:oration)?|inc|ltd|co|"
    r"please|years?|annual(?:ly)?|quarter(?:ly|s)?|q[1-4]|h[12]|fiscal|fy|"
    r"monthly|yoy|qoq|ytd|full|half|first|second|third|fourth|than|then|also|"
    r"too|that|this|these|those|it|s|both|respective|again|korean|english|"
    r"repeat|translate|rephrase|restate|elaborate|clarify|discuss|further|"
    r"more|deeper|detail|briefly|simply|according"
)
_KO_TOPIC_WORDS = (
    "매출",
    "수익",
    "영업이익",
    "순이익",
    "당기순이익",
    "이익",
    "마진",
    "성장률",
    "성장",
    "위험",
    "리스크",
    "실적",
    "전망",
    "수요",
    "공급",
    "투자",
    "사업",
    "재무제표",
    "재무",
    "부채",
    "현금흐름",
    "현금",
    "배당",
    "점유율",
    "시장",
    "반도체",
    "메모리",
    "동향",
    "원인",
    "근거",
    "수치",
    "비교",
    "공시",
    "사업보고서",
    "분기",
    "연간",
    "가이던스",
    "비용",
    "자본",
    "지출",
    "연구개발",
    "데이터센터",
    "서버",
    "하락",
    "상승",
    "증가",
    "감소",
    "변동",
    "부문",
    "판매",
    "영업",
    "파운드리",
    "배터리",
    "전장",
    "디스플레이",
    "스마트폰",
    "추이",
    "기여",
    "비중",
    "구조",
    "현황",
    "분석",
    "요인",
    "동력",
    "자산",
    "주가",
    "밸류에이션",
    "고대역폭",
    "hbm",
    "dram",
    "nand",
    "ai",
    "보고서",
    "보고",
    "언급",
    "인용",
    "유지",
    "변경",
    "변화",
    "개선",
    "악화",
    "영향",
    "내용",
    "항목",
    "섹션",
    "기재",
    "명시",
    "기록",
    "출하",
    "가동률",
    "수주",
    "잔고",
    "믹스",
    "가격",
    "단가",
    "물량",
)
_KO_FILLER_WORDS = (
    "무엇인가요",
    "무엇",
    "뭔가요",
    "뭐",
    "어떻게",
    "어떤가요",
    "어떤",
    "왜",
    "얼마나",
    "얼마",
    "어느",
    "어디",
    "언제",
    "누구",
    "알려주세요",
    "알려줄래",
    "알려줘",
    "알려",
    "설명해주세요",
    "설명해줄래",
    "설명해줘",
    "설명",
    "말해주세요",
    "말해줘",
    "말해",
    "보여줘",
    "정리해줘",
    "정리",
    "요약해줘",
    "요약",
    "인가요",
    "입니까",
    "습니까",
    "까요",
    "나요",
    "는가요",
    "은가요",
    "죠",
    "그러면",
    "그럼",
    "그리고",
    "그런데",
    "그러나",
    "하고",
    "및",
    "또는",
    "이랑",
    "랑",
    "좀",
    "제발",
    "대해서",
    "대한",
    "대해",
    "관해서",
    "관한",
    "관련",
    "중심",
    "위주",
    "전체",
    "각각",
    "각",
    "별",
    "다른",
    "또",
    "있나요",
    "있어요",
    "있어",
    "있나",
    "없나요",
    "없어",
    "궁금합니다",
    "궁금해요",
    "궁금",
    "모든",
    "모두",
    "주요",
    "총",
    "부분",
    "가장",
    "제일",
    "정도",
    "관점",
    "기준",
    "이유",
    "때문",
    "올해",
    "작년",
    "내년",
    "금년",
    "지난해",
    "연도별",
    "분기별",
    "회사",
    "기업",
    "발행인",
    "법인",
    "이야기",
    "말",
    "다시",
    "한글로",
    "한국어로",
    "영어로",
    "방금",
    "아까",
    "것",
    "거",
    "번역",
    "자세히",
    "간단히",
    "짧게",
)
_KO_PARTICLES = (
    "은",
    "는",
    "이",
    "가",
    "의",
    "을",
    "를",
    "에서",
    "에",
    "와",
    "과",
    "도",
    "만",
    "으로",
    "로",
    "부터",
    "까지",
    "보다",
    "처럼",
    "이며",
    "며",
    "이나",
    "나",
    "인",
    "된",
    "할",
    "한",
    "있는",
    "없는",
    "랑",
    "이랑",
    "하고",
    "에게",
    "한테",
    "라도",
    "든지",
    "야",
    "이야",
    "요",
    "조차",
    "마저",
    "마다",
    "밖에",
    "이요",
    "예요",
    "이에요",
    "네요",
    "군요",
    "구요",
    "고요",
    "해주세요",
    "해줄래",
    "해줘",
    "주세요",
    "줄래",
    "줘",
    "세요",
    "했는지",
    "었는지",
    "했나요",
    "었나요",
    "습니다",
    "입니다",
    "인가",
    "는지",
    "인지",
    "할지",
    "해",
    "액",
    "률",
    "율",
    "들",
    "해준거",
    "해준",
    "준거",
    "해준다",
    "한다",
    "된다",
)
_KO_TOPIC_SET = frozenset(_KO_TOPIC_WORDS)
_KO_BY_INITIAL: dict[str, tuple[str, ...]] = {}
for _word in (*_KO_TOPIC_WORDS, *_KO_FILLER_WORDS, *_KO_PARTICLES):
    _KO_BY_INITIAL[_word[0]] = (*_KO_BY_INITIAL.get(_word[0], ()), _word)

_NUMERIC_TOKEN = re.compile(
    rf"(?:fy\s?\d{{4}}|(?:19|20)\d{{2}}년?(?:{'|'.join(_KO_PARTICLES)})?|"
    rf"\d+(?:[.,]\d+)?%?|q[1-4]|h[12]|\d+분기)",
    re.IGNORECASE,
)
_EN_COVERED = re.compile(rf"(?:{_EN_TOPIC_WORDS}|{_EN_FILLER_WORDS})(?:'s)?", re.IGNORECASE)
_EN_TOPIC = re.compile(rf"(?:{_EN_TOPIC_WORDS})(?:'s)?", re.IGNORECASE)
_EDGE_PUNCTUATION = "?!.,;:~…'\"`()[]{}<>/-_+*&%$#@"


def _normalized_query(value: str) -> str:
    """Match the normalization app.retrieval.scope uses for alias comparison."""
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _mask_aliases(query: str, matches: tuple[MatchedAlias, ...]) -> str:
    """Blank matched aliases using index.match normalization and boundaries."""
    residual = _normalized_query(query)
    for match in matches:
        key = _normalized_query(match.alias)
        ascii_words = all(
            character.isascii() and (character.isalnum() or character.isspace())
            for character in key
        )
        pattern = rf"(?<![0-9a-z]){re.escape(key)}(?![0-9a-z])" if ascii_words else re.escape(key)
        residual = re.sub(pattern, " ", residual)
    return residual


def _ko_segment(token: str) -> tuple[bool, bool]:
    """Segment a token into whitelisted Korean words; return (covered, has_topic)."""
    covered = [False] * (len(token) + 1)
    topic = [False] * (len(token) + 1)
    covered[0] = True
    for position in range(len(token)):
        if not covered[position]:
            continue
        for word in _KO_BY_INITIAL.get(token[position], ()):
            if token.startswith(word, position):
                end = position + len(word)
                covered[end] = True
                topic[end] = topic[end] or topic[position] or word in _KO_TOPIC_SET
    return covered[-1], topic[-1]


def _covered_residual(residual: str) -> tuple[bool, bool]:
    """Return (fully covered, has finance topic) for alias-masked text."""
    covered = True
    has_topic = False
    for raw in _normalized_query(residual).split():
        token = raw.strip(_EDGE_PUNCTUATION)
        if not token:
            continue
        if _NUMERIC_TOKEN.fullmatch(token):
            continue
        if _EN_COVERED.fullmatch(token):
            has_topic = has_topic or _EN_TOPIC.fullmatch(token) is not None
            continue
        token_covered, token_topic = _ko_segment(token)
        if not token_covered:
            covered = False
            continue
        has_topic = has_topic or token_topic
    return covered, has_topic


def is_filing_turn(query: str, scope_index: ManifestScopeIndex | None = None) -> bool:
    """Whether a deterministic filing-review turn may seed bounded follow-up context."""
    if scope_index is None:
        return False
    decision = deterministic_decision(query, scope_index=scope_index)
    return decision is not None and decision.intent == "document_review"


def is_filing_followup(query: str, scope_index: ManifestScopeIndex | None = None) -> bool:
    """Bounded elliptical continuations: issuer pivot, year pivot, restatement."""
    if len(query) > 160 or len(query.split()) > 18:
        return False
    if CASUAL_CUES.search(query) or ROLEPLAY_CUES.search(query):
        return False
    matches = scope_index.match(query) if scope_index is not None else ()
    covered, has_topic = _covered_residual(_mask_aliases(query, matches))
    if not covered:
        return False
    if matches:
        return not has_topic
    return bool(RESTATEMENT_CUES.search(query) or FOLLOWUP_CUES.search(query.strip()))


def normalize_intent_text(value: str) -> str:
    """Normalize one full utterance for exact canned-intent matching."""
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    return re.sub(r"[\s!?.,~]+", "", normalized)


class ConversationTurn(StrictSchema):
    """One bounded prior browser conversation turn."""

    role: Literal["user", "assistant"]
    text: Annotated[StrictStr, Field(min_length=1, max_length=4_000)]

    @model_validator(mode="after")
    def reject_blank_text(self) -> Self:
        """Reject whitespace-only history text."""
        if not self.text.strip():
            raise ValueError("conversation turn text must not be blank")
        return self


class IntentClassification(StrictSchema):
    """Strict classifier output for an input the deterministic gate cannot decide."""

    intent: ConversationIntent
    reason: NonBlank


class RoutingClassification(StrictSchema):
    """Extract the request's domain and explicit targets without asserting corpus coverage."""

    intent: Literal["document_review", "service_help", "out_of_scope"]
    reason: NonBlank
    requested_issuers: Annotated[tuple[NonBlank, ...], Field(max_length=20)]
    target_scope: Literal["explicit", "context", "all", "unclear"]

    @model_validator(mode="after")
    def validate_targets(self) -> Self:
        """Require explicit targets and forbid contradictory target-free classifications."""
        if self.target_scope == "explicit" and not self.requested_issuers:
            raise ValueError("explicit target scope requires at least one issuer")
        if self.target_scope != "explicit" and self.requested_issuers:
            raise ValueError("issuer names require explicit target scope")
        return self


class ChatReply(StrictSchema):
    """One concise retrieval-free conversational answer."""

    answer: NonBlank


class ConversationDecision(StrictSchema):
    """Auditable deterministic or provider-backed conversation routing decision."""

    intent: ConversationIntent
    source: Literal["deterministic", "classifier"]
    matched_rule: NonBlank
    rationale: NonBlank
    canned_answer: NonBlank | None = None
    requested_issuers: tuple[NonBlank, ...] = ()
    target_scope: Literal["explicit", "context", "all", "unclear"] = "unclear"


def deterministic_decision(
    query: str,
    *,
    has_issuer_alias: bool = False,
    prior_filing_query: str | None = None,
    scope_index: ManifestScopeIndex | None = None,
    anchor_issuer: str | None = None,
) -> ConversationDecision | None:
    """Return only high-confidence exact casual, roleplay, or covered filing decisions."""
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must not be blank")
    normalized = normalize_intent_text(query)
    if answer := CANNED_RESPONSES.get(normalized):
        return ConversationDecision(
            intent="service_help",
            source="deterministic",
            matched_rule=f"canned:{normalized}",
            rationale="The complete normalized utterance matches a canned casual intent.",
            canned_answer=answer,
        )
    if ROLEPLAY_CUES.search(query) and not FILING_CUES.search(query):
        return ConversationDecision(
            intent="out_of_scope",
            source="deterministic",
            matched_rule="roleplay_request",
            rationale=(
                "The utterance is a roleplay or casual performance request, not filing analysis."
            ),
        )
    matches = scope_index.match(query) if scope_index is not None else ()
    if prior_filing_query and is_filing_followup(query, scope_index):
        return ConversationDecision(
            intent="document_review",
            source="deterministic",
            matched_rule="filing_followup",
            rationale="A short follow-up continues a filing question in the permitted history.",
            target_scope="all"
            if not matches and CORPUS_WIDE_CUES.search(prior_filing_query)
            else "context",
        )
    if matches:
        covered, has_topic = _covered_residual(_mask_aliases(query, matches))
        if covered and has_topic and not CORPUS_WIDE_CUES.search(query):
            return ConversationDecision(
                intent="document_review",
                source="deterministic",
                matched_rule="issuer_covered_finance",
                rationale="Every residual phrase is covered filing-analysis vocabulary.",
                requested_issuers=tuple(sorted({match.issuer for match in matches})),
                target_scope="explicit",
            )
    elif scope_index is not None:
        covered, has_topic = _covered_residual(query)
        if covered and has_topic:
            if CORPUS_WIDE_CUES.search(query):
                return ConversationDecision(
                    intent="document_review",
                    source="deterministic",
                    matched_rule="corpus_wide_comparison",
                    rationale="The utterance explicitly requests a corpus-wide comparison.",
                    target_scope="all",
                )
            if anchor_issuer and len(query) <= 160 and len(query.split()) <= 18:
                return ConversationDecision(
                    intent="document_review",
                    source="deterministic",
                    matched_rule="selected_issuer_anchor",
                    rationale="A unique selected issuer anchors the covered finance question.",
                    target_scope="context",
                )
    elif has_issuer_alias and FILING_CUES.search(query):
        return ConversationDecision(
            intent="document_review",
            source="deterministic",
            matched_rule="issuer_and_filing_cue",
            rationale="The query combines a known issuer with filing-review language.",
        )
    return None
