from typing import Optional, Dict, List
from datetime import datetime, timedelta
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader
from pydantic import BaseModel
import secrets
import hashlib

class APIKeyManager:
    """Gestor de API Keys y permisos"""
    
    def __init__(self, secret_key: str, algorithm: str = "HS256"):
        self.secret_key = secret_key
        self.algorithm = algorithm
        self.api_keys: Dict[str, Dict] = {}
        self.key_roles: Dict[str, List[str]] = {}
    
    def generate_api_key(self, user_id: str, permissions: List[str], 
                       rate_limit: int = 100) -> str:
        """Genera una nueva API key con permisos específicos"""
        raw_key = secrets.token_urlsafe(32)
        hashed_key = hashlib.sha256(raw_key.encode()).hexdigest()
        
        self.api_keys[hashed_key] = {
            "user_id": user_id,
            "permissions": permissions,
            "rate_limit": rate_limit,
            "created_at": datetime.now(),
            "last_used": None,
            "is_active": True
        }
        
        return raw_key  # Devuelve la key sin hashear para el usuario
    
    async def validate_api_key(self, api_key: str) -> Optional[Dict]:
        """Valida una API key y devuelve la información del usuario"""
        hashed_key = hashlib.sha256(api_key.encode()).hexdigest()
        
        if hashed_key not in self.api_keys:
            return None
        
        key_info = self.api_keys[hashed_key]
        
        if not key_info["is_active"]:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API key inactive"
            )
        
        # Actualizar último uso
        key_info["last_used"] = datetime.now()
        
        return key_info
    
    def revoke_api_key(self, api_key: str) -> bool:
        """Revoca una API key existente"""
        hashed_key = hashlib.sha256(api_key.encode()).hexdigest()
        
        if hashed_key in self.api_keys:
            self.api_keys[hashed_key]["is_active"] = False
            return True
        
        return False
    
    def check_permission(self, api_key_info: Dict, required_permission: str) -> bool:
        """Verifica si una API key tiene un permiso específico"""
        permissions = api_key_info.get("permissions", [])
        return required_permission in permissions

# Dependencia de autenticación
async def authenticate_user(api_key: str = Depends(APIKeyHeader(name="X-API-Key"))) -> Dict:
    """Dependencia FastAPI para autenticación"""
    key_manager = get_key_manager()  # Singleton instance
    
    user_info = await key_manager.validate_api_key(api_key)
    if not user_info:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "API-Key"},
        )
    
    return user_info

# Dependencia de permisos
def require_permission(permission: str):
    """Factory para dependencias de permisos"""
    async def permission_dependency(user: Dict = Depends(authenticate_user)):
        key_manager = get_key_manager()
        
        if not key_manager.check_permission(user, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing permission: {permission}"
            )
        
        return user
    
    return permission_dependency