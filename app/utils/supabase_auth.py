import os
from typing import Optional, Dict, Any

import jwt
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientError
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

bearer_scheme = HTTPBearer(auto_error=False)

def require_supabase_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> Dict[str, Any]:
    if creds is None or creds.scheme.lower() != "bearer" or not creds.credentials:
        raise HTTPException(status_code=401, detail="Missing bearer token")

    token = creds.credentials

    # ✅ Read env at runtime (NOT at import time)
    SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
    SUPABASE_JWT_AUDIENCE = os.getenv("SUPABASE_JWT_AUDIENCE", "authenticated")
    SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "")

    if not SUPABASE_URL:
        raise HTTPException(status_code=500, detail="SUPABASE_URL not set")

    ISSUER = f"{SUPABASE_URL}/auth/v1"

    try:
        header = jwt.get_unverified_header(token)
        alg = header.get("alg")

        if alg == "HS256":
            if not SUPABASE_JWT_SECRET:
                raise HTTPException(status_code=500, detail="SUPABASE_JWT_SECRET not set")

            return jwt.decode(
                token,
                SUPABASE_JWT_SECRET,
                algorithms=["HS256"],
                audience=SUPABASE_JWT_AUDIENCE,
                issuer=ISSUER,
                options={"require": ["exp", "sub"]},
            )

        # RS256/ES256 path (JWKS)
        jwks_url = f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json"
        jwk_client = PyJWKClient(jwks_url)

        signing_key = jwk_client.get_signing_key_from_jwt(token).key
        return jwt.decode(
            token,
            signing_key,
            algorithms=[alg] if alg else ["RS256"],
            audience=SUPABASE_JWT_AUDIENCE,
            issuer=ISSUER,
            options={"require": ["exp", "sub"]},
        )

    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except (jwt.InvalidTokenError, PyJWKClientError) as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")
