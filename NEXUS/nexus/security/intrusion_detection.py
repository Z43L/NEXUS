from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
import numpy as np
from sklearn.ensemble import IsolationForest
from prometheus_client import Counter, Gauge
import asyncio

class AnomalyDetector:
    """Sistema de detección de anomalías para seguridad"""
    
    def __init__(self):
        self.models = {}
        self.normal_behavior_profiles = {}
        self.anomaly_scores = {}
        
        # Métricas Prometheus
        self.anomaly_counter = Counter(
            'nexus_security_anomalies_total',
            'Total security anomalies detected',
            ['type', 'severity']
        )
        
        self.threshold_gauge = Gauge(
            'nexus_security_anomaly_threshold',
            'Current anomaly detection threshold'
        )
    
    async def train_model(self, data_type: str, normal_data: List[float]):
        """Entrena un modelo de detección de anomalías"""
        if len(normal_data) < 100:
            # No hay suficientes datos para entrenar
            return
        
        # Entrenar Isolation Forest
        model = IsolationForest(
            contamination=0.01,  # 1% de anomalías esperadas
            random_state=42
        )
        
        X = np.array(normal_data).reshape(-1, 1)
        model.fit(X)
        
        self.models[data_type] = model
        self.normal_behavior_profiles[data_type] = {
            'mean': np.mean(normal_data),
            'std': np.std(normal_data),
            'min': np.min(normal_data),
            'max': np.max(normal_data)
        }
    
    async def detect_anomalies(self, data_type: str, values: List[float]) -> List[Dict]:
        """Detecta anomalías en los datos"""
        if data_type not in self.models:
            return []
        
        anomalies = []
        model = self.models[data_type]
        profile = self.normal_behavior_profiles[data_type]
        
        for value in values:
            # Detección estadística básica
            z_score = abs((value - profile['mean']) / profile['std']) if profile['std'] > 0 else 0
            
            if z_score > 3:  # 3 sigma
                anomaly_score = 1.0
            else:
                # Usar el modelo de ML
                anomaly_score = -model.score_samples([[value]])[0]
            
            if anomaly_score > 0.7:  # Threshold para anomalía
                severity = 'high' if anomaly_score > 0.9 else 'medium'
                
                anomaly = {
                    'type': data_type,
                    'value': value,
                    'score': anomaly_score,
                    'severity': severity,
                    'timestamp': datetime.utcnow().isoformat(),
                    'normal_range': (profile['mean'] - 2*profile['std'], profile['mean'] + 2*profile['std'])
                }
                
                anomalies.append(anomaly)
                
                # Registrar métrica
                self.anomaly_counter.labels(type=data_type, severity=severity).inc()
        
        return anomalies
    
    async def monitor_continuous(self, data_stream, check_interval: int = 60):
        """Monitorización continua de un stream de datos"""
        buffer = []
        
        while True:
            try:
                # Leer datos del stream
                data = await data_stream.read()
                buffer.extend(data)
                
                # Procesar en lotes
                if len(buffer) >= 100:
                    anomalies = await self.detect_anomalies(data_stream.type, buffer[-100:])
                    
                    for anomaly in anomalies:
                        await self.handle_anomaly(anomaly)
                    
                    # Mantener buffer manejable
                    buffer = buffer[-1000:]
                
                await asyncio.sleep(check_interval)
                
            except Exception as e:
                print(f"Error en monitorización: {e}")
                await asyncio.sleep(5)
    
    async def handle_anomaly(self, anomaly: Dict):
        """Maneja una anomalía detectada"""
        # Acciones de respuesta (alertar, bloquear, investigar, etc.)
        print(f"⚠️  Anomalía detectada: {anomaly}")
        
        if anomaly['severity'] == 'high':
            # Acciones inmediatas para anomalías graves
            await self.trigger_incident_response(anomaly)