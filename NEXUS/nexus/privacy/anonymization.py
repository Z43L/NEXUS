import hashlib
import re
from typing import Dict, List, Any, Optional
import pandas as pd
from faker import Faker

class AnonymizationEngine:
    """Motor de anonimización y seudonimización"""
    
    def __init__(self, secret_key: str):
        self.faker = Faker()
        self.secret_key = secret_key
        self.pseudonym_mapping = {}
    
    def pseudonymize_field(self, value: str, field_type: str) -> str:
        """Seudonimiza un campo según su tipo"""
        if field_type == 'email':
            return self._pseudonymize_email(value)
        elif field_type == 'phone':
            return self._pseudonymize_phone(value)
        elif field_type == 'name':
            return self._pseudonymize_name(value)
        elif field_type == 'identifier':
            return self._pseudonymize_identifier(value)
        else:
            return self._generic_pseudonymization(value)
    
    def anonymize_field(self, value: Any, field_type: str) -> Any:
        """Anonimiza completamente un campo"""
        if pd.isna(value):
            return value
        
        if field_type == 'datetime':
            return self._anonymize_datetime(value)
        elif field_type == 'location':
            return self._anonymize_location(value)
        elif field_type == 'numeric':
            return self._anonymize_numeric(value)
        else:
            return self._generic_anonymization(value)
    
    def _pseudonymize_email(self, email: str) -> str:
        """Seudonimiza una dirección de email"""
        if '@' not in email:
            return email
        
        local_part, domain = email.split('@', 1)
        pseudonym_local = hashlib.blake2s(
            (local_part + self.secret_key).encode(),
            key=self.secret_key.encode()
        ).hexdigest()[:10]
        
        return f"{pseudonym_local}@{domain}"
    
    def _pseudonymize_identifier(self, identifier: str) -> str:
        """Seudonimiza un identificador"""
        return hashlib.blake2s(
            (identifier + self.secret_key).encode(),
            key=self.secret_key.encode()
        ).hexdigest()[:16]
    
    def _anonymize_datetime(self, dt_value) -> str:
        """Anonimiza una fecha/hora"""
        # Generalizar a nivel de mes o trimestre
        if isinstance(dt_value, str):
            dt_value = pd.to_datetime(dt_value)
        
        # Generalizar al primer día del mes
        generalized = dt_value.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return generalized.isoformat()
    
    def _anonymize_location(self, location: str) -> str:
        """Anonimiza una ubicación"""
        # Generalizar a nivel de ciudad o región
        parts = location.split(',')
        if len(parts) > 1:
            return parts[-1].strip()  # Devolver solo la ciudad o región
        return "Redacted Area"
    
    def process_dataset(self, df: pd.DataFrame, config: Dict) -> pd.DataFrame:
        """Procesa un dataset completo con las configuraciones de anonimización"""
        result_df = df.copy()
        
        for column, col_config in config.items():
            if column not in result_df.columns:
                continue
            
            if col_config['method'] == 'pseudonymize':
                result_df[column] = result_df[column].apply(
                    lambda x: self.pseudonymize_field(x, col_config['type'])
                )
            elif col_config['method'] == 'anonymize':
                result_df[column] = result_df[column].apply(
                    lambda x: self.anonymize_field(x, col_config['type'])
                )
            elif col_config['method'] == 'redact':
                result_df[column] = '[REDACTED]'
            elif col_config['method'] == 'generalize':
                result_df[column] = self._generalize_column(result_df[column], col_config)
        
        return result_df