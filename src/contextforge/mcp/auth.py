"""
MCP Authentication Module

OAuth 2.1 with PKCE implementation for MCP Gateway.
Supports Clerk (dev) and Cognito (prod) as identity providers.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from pydantic import BaseModel, Field, field_validator

from contextforge.config import settings


class AuthProvider(str, Enum):
    """Supported OAuth providers."""

    CLERK = "clerk"
    COGNITO = "cognito"
    DEV = "dev"  # Development mode with mock auth


class TokenType(str, Enum):
    """OAuth token types."""

    BEARER = "Bearer"
    MAC = "MAC"


@dataclass
class PKCEChallenge:
    """PKCE code challenge and verifier."""

    code_verifier: str
    code_challenge: str
    code_challenge_method: str = "S256"
    created_at: float = Field(default_factory=time.time)

    @classmethod
    def generate(cls) -> PKCEChallenge:
        """Generate a new PKCE challenge pair."""
        code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("utf-8").rstrip("=")
        code_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode("utf-8")).digest()
        ).decode("utf-8").rstrip("=")
        return cls(code_verifier=code_verifier, code_challenge=code_challenge)

    def verify(self, code_verifier: str) -> bool:
        """Verify a code verifier against the challenge."""
        expected_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode("utf-8")).digest()
        ).decode("utf-8").rstrip("=")
        return hmac.compare_digest(expected_challenge, self.code_challenge)

    def is_expired(self, max_age_seconds: int = 600) -> bool:
        """Check if challenge is expired (default 10 minutes)."""
        return time.time() - self.created_at > max_age_seconds


class OAuth21Config(BaseModel):
    """OAuth 2.1 configuration."""

    provider: AuthProvider = AuthProvider.DEV
    client_id: str = ""
    client_secret: str = ""
    issuer_url: str = ""
    authorization_endpoint: str = ""
    token_endpoint: str = ""
    jwks_uri: str = ""
    scopes: list[str] = Field(default_factory=lambda: ["openid", "profile", "email", "mcp:read", "mcp:write"])
    redirect_uri: str = ""
    pkce_required: bool = True
    token_expiry_seconds: int = 3600
    refresh_token_expiry_days: int = 30

    @field_validator("provider", mode="before")
    @classmethod
    def validate_provider(cls, v: str | AuthProvider) -> AuthProvider:
        if isinstance(v, str):
            return AuthProvider(v.lower())
        return v


class TokenPayload(BaseModel):
    """JWT token payload."""

    sub: str
    iss: str
    aud: str | list[str]
    exp: int
    iat: int
    scope: str = ""
    client_id: str = ""
    permissions: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AccessToken(BaseModel):
    """OAuth access token response."""

    access_token: str
    token_type: TokenType = TokenType.BEARER
    expires_in: int
    refresh_token: str | None = None
    scope: str = ""
    id_token: str | None = None


class AuthorizationCode(BaseModel):
    """Authorization code grant."""

    code: str
    client_id: str
    redirect_uri: str
    scopes: list[str]
    pkce_challenge: PKCEChallenge | None = None
    user_id: str = ""
    created_at: float = Field(default_factory=time.time)
    expires_at: float = Field(default_factory=lambda: time.time() + 600)  # 10 min

    def is_expired(self) -> bool:
        return time.time() > self.expires_at


class RefreshToken(BaseModel):
    """Refresh token."""

    token: str
    client_id: str
    user_id: str
    scopes: list[str]
    created_at: float = Field(default_factory=time.time)
    expires_at: float = Field(default_factory=lambda: time.time() + 30 * 24 * 3600)  # 30 days

    def is_expired(self) -> bool:
        return time.time() > self.expires_at


class MCPAuth:
    """
    MCP Authentication handler.

    Implements OAuth 2.1 with PKCE for secure MCP server access.
    Supports multiple identity providers (Clerk, Cognito, Dev mock).
    """

    def __init__(self, config: OAuth21Config | None = None):
        self.config = config or self._default_config()
        self._pkce_challenges: dict[str, PKCEChallenge] = {}
        self._auth_codes: dict[str, AuthorizationCode] = {}
        self._refresh_tokens: dict[str, RefreshToken] = {}
        self._jwks_cache: dict[str, Any] = {}
        self._jwks_cache_time: float = 0
        self._http_client = httpx.AsyncClient(timeout=30.0)

    def _default_config(self) -> OAuth21Config:
        """Create default configuration based on environment."""
        env = settings.APP_ENV

        if env == "production":
            return OAuth21Config(
                provider=AuthProvider.COGNITO,
                client_id=settings.get("COGNITO_CLIENT_ID", ""),
                client_secret=settings.get("COGNITO_CLIENT_SECRET", ""),
                issuer_url=f"https://cognito-idp.{settings.AWS_REGION}.amazonaws.com/{settings.COGNITO_USER_POOL_ID}",
                redirect_uri=settings.get("MCP_REDIRECT_URI", "http://localhost:8001/callback"),
            )
        elif env == "staging":
            return OAuth21Config(
                provider=AuthProvider.CLERK,
                client_id=settings.get("CLERK_CLIENT_ID", ""),
                client_secret=settings.get("CLERK_CLIENT_SECRET", ""),
                issuer_url=settings.get("CLERK_ISSUER_URL", ""),
                redirect_uri=settings.get("MCP_REDIRECT_URI", "http://localhost:8001/callback"),
            )
        else:
            # Development mode - mock auth
            return OAuth21Config(
                provider=AuthProvider.DEV,
                client_id="dev-client",
                client_secret="dev-secret",
                issuer_url="http://localhost:8001",
                redirect_uri="http://localhost:8001/callback",
                pkce_required=False,
            )

    async def get_authorization_url(
        self,
        state: str | None = None,
        code_challenge: str | None = None,
        code_challenge_method: str = "S256",
    ) -> str:
        """Generate OAuth authorization URL."""
        if self.config.provider == AuthProvider.DEV:
            # Dev mode - redirect directly to callback with mock code
            mock_code = f"dev-code-{uuid.uuid4().hex[:16]}"
            self._auth_codes[mock_code] = AuthorizationCode(
                code=mock_code,
                client_id=self.config.client_id,
                redirect_uri=self.config.redirect_uri,
                scopes=self.config.scopes,
                user_id="dev-user",
            )
            params = {"code": mock_code}
            if state:
                params["state"] = state
            return f"{self.config.redirect_uri}?{urlencode(params)}"

        params = {
            "response_type": "code",
            "client_id": self.config.client_id,
            "redirect_uri": self.config.redirect_uri,
            "scope": " ".join(self.config.scopes),
        }

        if state:
            params["state"] = state

        if self.config.pkce_required and code_challenge:
            params["code_challenge"] = code_challenge
            params["code_challenge_method"] = code_challenge_method

        auth_url = self.config.authorization_endpoint or f"{self.config.issuer_url}/oauth2/authorize"
        return f"{auth_url}?{urlencode(params)}"

    async def exchange_code_for_token(
        self,
        code: str,
        code_verifier: str | None = None,
        redirect_uri: str | None = None,
    ) -> AccessToken:
        """Exchange authorization code for access token."""
        # Look up auth code
        auth_code = self._auth_codes.get(code)
        if not auth_code:
            raise ValueError("Invalid or expired authorization code")

        if auth_code.is_expired():
            del self._auth_codes[code]
            raise ValueError("Authorization code expired")

        # Verify PKCE if required
        if self.config.pkce_required and auth_code.pkce_challenge:
            if not code_verifier:
                raise ValueError("PKCE code_verifier required")
            if not auth_code.pkce_challenge.verify(code_verifier):
                raise ValueError("Invalid PKCE code_verifier")

        # Verify redirect URI
        if redirect_uri and redirect_uri != auth_code.redirect_uri:
            raise ValueError("Redirect URI mismatch")

        # Generate tokens
        access_token = await self._create_access_token(auth_code.user_id, auth_code.scopes)
        refresh_token = await self._create_refresh_token(auth_code.user_id, auth_code.scopes)

        # Clean up auth code
        del self._auth_codes[code]

        return AccessToken(
            access_token=access_token,
            token_type=TokenType.BEARER,
            expires_in=self.config.token_expiry_seconds,
            refresh_token=refresh_token.token,
            scope=" ".join(auth_code.scopes),
        )

    async def refresh_access_token(self, refresh_token: str) -> AccessToken:
        """Refresh an access token using a refresh token."""
        token_data = self._refresh_tokens.get(refresh_token)
        if not token_data:
            raise ValueError("Invalid refresh token")

        if token_data.is_expired():
            del self._refresh_tokens[refresh_token]
            raise ValueError("Refresh token expired")

        # Generate new access token
        access_token = await self._create_access_token(token_data.user_id, token_data.scopes)

        return AccessToken(
            access_token=access_token,
            token_type=TokenType.BEARER,
            expires_in=self.config.token_expiry_seconds,
            refresh_token=refresh_token,
            scope=" ".join(token_data.scopes),
        )

    async def validate_token(self, token: str) -> TokenPayload:
        """Validate and decode an access token."""
        if self.config.provider == AuthProvider.DEV:
            # Dev mode - decode mock token
            try:
                payload = jwt.decode(
                    token,
                    self.config.client_secret,
                    algorithms=["HS256"],
                    audience=self.config.client_id,
                    issuer=self.config.issuer_url,
                )
                return TokenPayload(**payload)
            except jwt.PyJWTError as e:
                raise ValueError(f"Invalid token: {e}")

        # Production - validate against JWKS
        return await self._validate_jwt_token(token)

    async def revoke_token(self, token: str) -> bool:
        """Revoke a token (access or refresh)."""
        # For refresh tokens
        if token in self._refresh_tokens:
            del self._refresh_tokens[token]
            return True
        return False

    async def create_pkce_challenge(self) -> PKCEChallenge:
        """Create a new PKCE challenge."""
        challenge = PKCEChallenge.generate()
        challenge_id = secrets.token_urlsafe(16)
        self._pkce_challenges[challenge_id] = challenge
        return challenge

    async def get_pkce_challenge(self, challenge_id: str) -> PKCEChallenge | None:
        """Get PKCE challenge by ID."""
        challenge = self._pkce_challenges.get(challenge_id)
        if challenge and challenge.is_expired():
            del self._pkce_challenges[challenge_id]
            return None
        return challenge

    async def _create_access_token(self, user_id: str, scopes: list[str]) -> str:
        """Create a signed access token."""
        now = int(time.time())
        payload = TokenPayload(
            sub=user_id,
            iss=self.config.issuer_url,
            aud=self.config.client_id,
            exp=now + self.config.token_expiry_seconds,
            iat=now,
            scope=" ".join(scopes),
            client_id=self.config.client_id,
            permissions=scopes,
        )

        if self.config.provider == AuthProvider.DEV:
            return jwt.encode(payload.model_dump(), self.config.client_secret, algorithm="HS256")

        # Production: use RS256 with private key from Secrets Manager
        # This is a placeholder - actual implementation would fetch key from AWS Secrets Manager
        private_key = await self._get_private_key()
        return jwt.encode(payload.model_dump(), private_key, algorithm="RS256")

    async def _create_refresh_token(self, user_id: str, scopes: list[str]) -> RefreshToken:
        """Create a refresh token."""
        token = RefreshToken(
            token=secrets.token_urlsafe(32),
            client_id=self.config.client_id,
            user_id=user_id,
            scopes=scopes,
        )
        self._refresh_tokens[token.token] = token
        return token

    async def _validate_jwt_token(self, token: str) -> TokenPayload:
        """Validate JWT token against JWKS."""
        # Get JWKS
        jwks = await self._get_jwks()

        # Decode header to get kid
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as e:
            raise ValueError(f"Invalid token header: {e}")

        kid = header.get("kid")
        if not kid:
            raise ValueError("Token missing kid")

        # Find matching key
        key = None
        for k in jwks.get("keys", []):
            if k.get("kid") == kid:
                key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(k))
                break

        if not key:
            raise ValueError("No matching key found in JWKS")

        # Decode and validate
        try:
            payload = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                audience=self.config.client_id,
                issuer=self.config.issuer_url,
            )
            return TokenPayload(**payload)
        except jwt.PyJWTError as e:
            raise ValueError(f"Token validation failed: {e}")

    async def _get_jwks(self) -> dict[str, Any]:
        """Fetch JWKS from provider."""
        now = time.time()
        if now - self._jwks_cache_time < 3600 and self._jwks_cache:  # Cache for 1 hour
            return self._jwks_cache

        jwks_url = self.config.jwks_uri or f"{self.config.issuer_url}/.well-known/jwks.json"
        response = await self._http_client.get(jwks_url)
        response.raise_for_status()
        self._jwks_cache = response.json()
        self._jwks_cache_time = now
        return self._jwks_cache

    async def _get_private_key(self) -> str:
        """Get private key for signing (from Secrets Manager in production)."""
        # Placeholder - in production, fetch from AWS Secrets Manager
        # import boto3
        # client = boto3.client('secretsmanager', region_name=settings.AWS_REGION)
        # response = client.get_secret_value(SecretId='contextforge/mcp/jwt-private-key')
        # return response['SecretString']
        return "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQD...\n-----END PRIVATE KEY-----"

    async def close(self):
        """Close HTTP client."""
        await self._http_client.aclose()


class OAuth21Provider:
    """
    OAuth 2.1 Provider metadata for MCP clients.

    Exposes .well-known/oauth-authorization-server endpoint.
    """

    def __init__(self, auth: MCPAuth):
        self.auth = auth

    def get_metadata(self) -> dict[str, Any]:
        """Get OAuth 2.1 authorization server metadata."""
        config = self.auth.config
        base_url = config.issuer_url.rstrip("/")

        return {
            "issuer": base_url,
            "authorization_endpoint": config.authorization_endpoint or f"{base_url}/oauth2/authorize",
            "token_endpoint": config.token_endpoint or f"{base_url}/oauth2/token",
            "jwks_uri": config.jwks_uri or f"{base_url}/.well-known/jwks.json",
            "registration_endpoint": f"{base_url}/oauth2/register",
            "revocation_endpoint": f"{base_url}/oauth2/revoke",
            "introspection_endpoint": f"{base_url}/oauth2/introspect",
            "scopes_supported": config.scopes,
            "response_types_supported": ["code"],
            "response_modes_supported": ["query", "fragment"],
            "grant_types_supported": ["authorization_code", "refresh_token", "client_credentials"],
            "token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post", "none"],
            "code_challenge_methods_supported": ["S256"],
            "pkce_required": config.pkce_required,
            "service_documentation": f"{base_url}/docs",
            "ui_locales_supported": ["en"],
        }

    def get_client_metadata(self, client_id: str) -> dict[str, Any] | None:
        """Get registered client metadata (placeholder)."""
        # In production, fetch from client registry
        if client_id == self.auth.config.client_id:
            return {
                "client_id": client_id,
                "client_name": "ContextForge MCP Client",
                "redirect_uris": [self.auth.config.redirect_uri],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "scope": " ".join(self.auth.config.scopes),
                "token_endpoint_auth_method": "client_secret_basic",
            }
        return None


# Dependency injection
_auth_instance: MCPAuth | None = None


def get_auth() -> MCPAuth:
    """Get or create MCP auth instance."""
    global _auth_instance
    if _auth_instance is None:
        _auth_instance = MCPAuth()
    return _auth_instance


async def close_auth():
    """Close auth instance."""
    global _auth_instance
    if _auth_instance:
        await _auth_instance.close()
        _auth_instance = None
