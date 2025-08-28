from typing import Dict, List, Any
from datetime import datetime
import asyncio
from enum import Enum

class IncidentSeverity(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class IncidentType(Enum):
    UNAUTHORIZED_ACCESS = "unauthorized_access"
    DATA_BREACH = "data_breach"
    DOS_ATTACK = "dos_attack"
    MALWARE = "malware"
    CONFIGURATION_ERROR = "configuration_error"

class IncidentResponse:
    """Sistema de respuesta a incidentes de seguridad"""
    
    def __init__(self, notification_service, backup_service):
        self.notification_service = notification_service
        self.backup_service = backup_service
        self.incident_log = []
        self.response_plans = self._load_response_plans()
    
    async def handle_incident(self, incident_data: Dict):
        """Maneja un incidente de seguridad"""
        incident_id = f"incident_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        
        incident = {
            'id': incident_id,
            'type': incident_data['type'],
            'severity': incident_data['severity'],
            'timestamp': datetime.utcnow().isoformat(),
            'status': 'open',
            'details': incident_data
        }
        
        self.incident_log.append(incident)
        
        # Ejecutar plan de respuesta
        response_plan = self.response_plans.get(incident['type'], {})
        await self.execute_response_plan(incident, response_plan)
        
        # Notificar stakeholders
        await self.notify_stakeholders(incident)
        
        # Iniciar investigación
        asyncio.create_task(self.investigate_incident(incident))
        
        return incident_id
    
    async def execute_response_plan(self, incident: Dict, plan: Dict):
        """Ejecuta el plan de respuesta para el incidente"""
        severity = incident['severity']
        
        if severity in [IncidentSeverity.HIGH, IncidentSeverity.CRITICAL]:
            # Acciones inmediatas para incidentes graves
            await self.isolate_affected_systems(incident)
            await self.preserve_evidence(incident)
            
            if incident['type'] == IncidentType.DATA_BREACH:
                await self.activate_backup_systems()
        
        # Otras acciones específicas según el plan
        for action in plan.get('actions', []):
            if severity.value >= action['min_severity']:
                await getattr(self, action['method'])(incident)
    
    async def isolate_affected_systems(self, incident: Dict):
        """Aísla los sistemas afectados"""
        print(f"🔒 Aislando sistemas afectados por incidente {incident['id']}")
        # Implementar lógica de aislamiento real aquí
    
    async def preserve_evidence(self, incident: Dict):
        """Preserva evidencia forense"""
        print(f"📋 Preservando evidencia para incidente {incident['id']}")
        # Implementar preservación de evidencia
    
    async def activate_backup_systems(self):
        """Activa sistemas de backup"""
        print("🔄 Activando sistemas de backup")
        await self.backup_service.activate_failover()
    
    async def notify_stakeholders(self, incident: Dict):
        """Notifica a los stakeholders del incidente"""
        recipients = self._get_notification_recipients(incident['severity'])
        message = self._create_notification_message(incident)
        
        for recipient in recipients:
            await self.notification_service.send(
                recipient=recipient,
                subject=f"Security Incident: {incident['id']}",
                message=message,
                priority=incident['severity']
            )
    
    def _load_response_plans(self) -> Dict:
        """Carga los planes de respuesta predefinidos"""
        return {
            IncidentType.UNAUTHORIZED_ACCESS: {
                'actions': [
                    {'method': 'block_suspicious_ips', 'min_severity': 'low'},
                    {'method': 'force_password_reset', 'min_severity': 'medium'},
                    {'method': 'disable_affected_accounts', 'min_severity': 'high'}
                ]
            },
            IncidentType.DATA_BREACH: {
                'actions': [
                    {'method': 'encrypt_sensitive_data', 'min_severity': 'medium'},
                    {'method': 'notify_authorities', 'min_severity': 'high'},
                    {'method': 'initiate_recovery_procedure', 'min_severity': 'critical'}
                ]
            }
        }