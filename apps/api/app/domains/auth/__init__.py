"""Authentication and OAuth domain services."""

from .providers import (
    GoogleOAuthProvider,
    MockOAuthProvider,
    OAuthProviderConfig,
    OAuthUserInfo,
    ProviderName,
    ProviderRegistry,
)
from .service import AuthResult, AuthService, OAuthStart, OAuthStateStore

__all__ = [
    "AuthResult",
    "AuthService",
    "GoogleOAuthProvider",
    "MockOAuthProvider",
    "OAuthProviderConfig",
    "OAuthStart",
    "OAuthStateStore",
    "OAuthUserInfo",
    "ProviderName",
    "ProviderRegistry",
]
