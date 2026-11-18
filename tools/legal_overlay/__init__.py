"""Local provider-neutral Legal Knowledge Overlay gateway."""

from .config import ConnectionsConfig, ProviderConnection, load_connections

__all__ = ["ConnectionsConfig", "ProviderConnection", "load_connections"]
__version__ = "0.11.2"
