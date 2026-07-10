from __future__ import annotations

from .messages import ChatRequest, ChatResponse
from .provider import ChatProvider, ProviderError


class ProviderPool:
    def __init__(self, providers: dict[str, ChatProvider]):
        if not providers:
            raise ValueError("provider pool requires at least one provider")
        self._providers = dict(providers)

    @classmethod
    def single(cls, provider: ChatProvider) -> ProviderPool:
        return cls({"default": provider})

    def complete(self, provider_id: str, request: ChatRequest) -> ChatResponse:
        try:
            provider = self._providers[provider_id]
        except KeyError as error:
            raise ProviderError(f"provider is not configured: {provider_id}") from error
        return provider.complete(request)

    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._providers))
