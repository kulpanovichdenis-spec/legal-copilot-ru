"""Provider adapters available to the local Legal Overlay."""

from .base import ProviderAdapter
from .fas_search import FasSearchAdapter
from .local_curated import LocalCuratedAdapter
from .local_verified import LocalVerifiedAdapter
from .pravo_gov_ru import PravoGovRuAdapter

__all__ = [
    "ProviderAdapter",
    "FasSearchAdapter",
    "LocalCuratedAdapter",
    "LocalVerifiedAdapter",
    "PravoGovRuAdapter",
]
