from abc import ABC, abstractmethod

from pydantic import BaseModel


class LLMProvider(ABC):
    @abstractmethod
    def structured(
        self, system: str, user: str, schema: type[BaseModel]
    ) -> BaseModel: ...


class MockProvider(LLMProvider):
    model_name = "mock"
    input_tokens = 0
    output_tokens = 0

    def __init__(self, report: BaseModel | None = None):
        self._report = report

    def structured(self, system: str, user: str, schema: BaseModel) -> BaseModel:
        return self._report or schema(
            label="NOT_IN_DOCS", citations=[], rationale="mock default"
        )


class OpenAIProvider(LLMProvider):
    def __init__(self, model: str, api_key: str):
        from langchain_openai import ChatOpenAI

        self.model_name = model
        self.llm = ChatOpenAI(model=model, api_key=api_key, temperature=0)
        self.input_tokens = 0
        self.output_tokens = 0

    def structured(self, system: str, user: str, schema: BaseModel):
        result = self.llm.with_structured_output(schema, include_raw=True).invoke(
            [("system", system), ("human", user)]
        )
        usage = getattr(result["raw"], "usage_metadata", None) or {}
        self.input_tokens += usage.get("input_tokens", 0)
        self.output_tokens += usage.get("output_tokens", 0)
        return result["parsed"]


def get_provider(settings) -> LLMProvider:
    if settings.primary_llm_provider == "mock":
        return MockProvider()
    return OpenAIProvider(settings.llm_model, settings.openai_api_key)


class FallbackProvider(LLMProvider):
    def __init__(self, primary: LLMProvider, secondary: LLMProvider):
        self.primary = primary
        self.secondary = secondary
        self.model_name = primary.model_name
        self.used_fallback = False

    def structured(self, system, user, schema):
        try:
            result = self.primary.structured(system, user, schema)
            self.model_name = self.primary.model_name
        except Exception:
            self.used_fallback = True
            result = self.secondary.structured(system, user, schema)
            self.model_name = self.secondary.model_name
        # 토큰은 실제 돈 쪽에서 합산 (하나는 0)
        self.input_tokens = self.primary.input_tokens + self.secondary.input_tokens
        self.output_tokens = self.primary.output_tokens + self.secondary.output_tokens
        return result
