from typing import Dict, Optional
from datetime import datetime, timedelta
from decimal import Decimal
import redis
from fastapi import HTTPException, status

class AdaptiveRateLimiter:
    """Sistema de rate limiting adaptativo basado en reputación"""
    
    def __init__(self, redis_url: str, reputation_system):
        self.redis = redis.from_url(redis_url)
        self.reputation_system = reputation_system
        self.base_limits = {
            "free": 100,        # 100 requests/day
            "basic": 1000,      # 1000 requests/day
            "premium": 10000,   # 10000 requests/day
            "enterprise": 100000 # 100000 requests/day
        }
    
    async def check_rate_limit(self, user_id: str, endpoint: str) -> bool:
        """Verifica si un usuario puede realizar una request"""
        current_usage = await self.get_current_usage(user_id)
        user_limit = await self.calculate_user_limit(user_id)
        
        if current_usage >= user_limit:
            return False
        
        # Registrar uso
        await self.record_usage(user_id, endpoint)
        return True
    
    async def calculate_user_limit(self, user_id: str) -> int:
        """Calcula el límite de rate basado en reputación y tipo de usuario"""
        base_limit = self.base_limits["free"]
        reputation = await self.reputation_system.get_reputation(user_id)
        user_tier = await self.get_user_tier(user_id)
        
        # Ajustar límite basado en reputación
        reputation_multiplier = 1.0 + float(reputation) * 2.0  # 1x to 3x
        
        # Límite base por tier
        tier_limit = self.base_limits.get(user_tier, 100)
        
        return int(tier_limit * reputation_multiplier)
    
    async def get_current_usage(self, user_id: str) -> int:
        """Obtiene el uso actual del usuario"""
        key = f"rate_limit:{user_id}:{datetime.now().strftime('%Y%m%d')}"
        return int(self.redis.get(key) or 0)
    
    async def record_usage(self, user_id: str, endpoint: str):
        """Registra el uso de un endpoint"""
        key = f"rate_limit:{user_id}:{datetime.now().strftime('%Y%m%d')}"
        self.redis.incr(key)
        
        # Expirar al final del día
        self.redis.expireat(key, self._end_of_day())
    
    def _end_of_day(self) -> int:
        """Calcula el timestamp del final del día"""
        now = datetime.now()
        end = datetime(now.year, now.month, now.day, 23, 59, 59)
        return int(end.timestamp())
    
    async def get_rate_limit_info(self, user_id: str) -> Dict:
        """Obtiene información de rate limit para el usuario"""
        current_usage = await self.get_current_usage(user_id)
        user_limit = await self.calculate_user_limit(user_id)
        
        return {
            "current_usage": current_usage,
            "limit": user_limit,
            "remaining": max(0, user_limit - current_usage),
            "reset_time": self._end_of_day(),
            "user_tier": await self.get_user_tier(user_id)
        }

# Middleware de rate limiting
async def rate_limit_middleware(request, call_next):
    """Middleware para aplicar rate limiting"""
    user_id = request.state.user.get("user_id", "anonymous")
    endpoint = request.url.path
    
    rate_limiter = get_rate_limiter()
    
    if not await rate_limiter.check_rate_limit(user_id, endpoint):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
            headers={
                "X-RateLimit-Limit": str(await rate_limiter.calculate_user_limit(user_id)),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(rate_limiter._end_of_day())
            }
        )
    
    response = await call_next(request)
    
    # Añadir headers de rate limiting
    limit_info = await rate_limiter.get_rate_limit_info(user_id)
    response.headers["X-RateLimit-Limit"] = str(limit_info["limit"])
    response.headers["X-RateLimit-Remaining"] = str(limit_info["remaining"])
    response.headers["X-RateLimit-Reset"] = str(limit_info["reset_time"])
    
    return response