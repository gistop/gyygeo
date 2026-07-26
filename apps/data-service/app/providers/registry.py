from __future__ import annotations

from typing import Dict, Iterable

from app.providers.base import ProviderNotFoundError, RasterProvider


class ProviderRegistry:
    def __init__(self, providers: Iterable[RasterProvider]) -> None:
        self._providers: Dict[str, RasterProvider] = {
            provider.provider_id: provider for provider in providers
        }

    def get(self, provider_id: str) -> RasterProvider:
        provider = self._providers.get(provider_id)
        if provider is None:
            raise ProviderNotFoundError(f"Provider not found: {provider_id}")
        return provider

    def list(self) -> list[RasterProvider]:
        return list(self._providers.values())

