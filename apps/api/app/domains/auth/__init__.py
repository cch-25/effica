"""Authentication and OAuth domain services."""

from .providers import (
    GoogleOAuthProvider,
    GoogleProvider,
    KakaoOAuthProvider,
    KakaoProvider,
    MockOAuthProvider,
    NaverOAuthProvider,
    NaverProvider,
    OAuthProviderConfig,
    OAuthUserInfo,
    ProviderName,
    ProviderRegistry,
    build_provider_registry,
)
from .service import AuthResult, AuthService, OAuthStart, OAuthStateStore

__all__ = [
    "AuthResult",
    "AuthService",
    "GoogleOAuthProvider",
    "GoogleProvider",
    "KakaoOAuthProvider",
    "KakaoProvider",
    "MockOAuthProvider",
    "NaverOAuthProvider",
    "NaverProvider",
    "OAuthProviderConfig",
    "OAuthStart",
    "OAuthStateStore",
    "OAuthUserInfo",
    "ProviderName",
    "ProviderRegistry",
    "build_provider_registry",
]
