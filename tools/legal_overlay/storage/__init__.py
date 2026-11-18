"""Local durable stores used by the Legal Overlay."""

from .knowledge_store import KnowledgeStore, KnowledgeStoreError

__all__ = ["KnowledgeStore", "KnowledgeStoreError"]
