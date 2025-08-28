from typing import Dict, List, Any
import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta

class ReasoningDashboard:
    """Dashboard para visualización del desempeño del agente razonador"""
    
    def __init__(self, monitor):
        self.monitor = monitor
        self.metrics_data = self._load_metrics_data()
    
    def display_performance_overview(self):
        """Muestra visión general del desempeño"""
        st.header("📊 Visión General del Desempeño")
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Tareas Exitosas", self.metrics_data['successful_tasks'])
        with col2:
            st.metric("Tareas Fallidas", self.metrics_data['failed_tasks'])
        with col3:
            st.metric("Tiempo Promedio", f"{self.metrics_data['avg_time']:.2f}s")
        with col4:
            st.metric("Tasa de Éxito", f"{self.metrics_data['success_rate']:.1%}")
    
    def display_task_breakdown(self):
        """Muestra desglose de tareas por tipo"""
        st.header("🧩 Desglose de Tareas por Tipo")
        
        task_data = self.metrics_data['task_breakdown']
        fig = px.pie(
            task_data, 
            values='count', 
            names='task_type',
            title="Distribución de Tipos de Tarea"
        )
        st.plotly_chart(fig)
    
    def display_execution_timeline(self):
        """Muestra línea de tiempo de ejecución"""
        st.header("⏰ Línea de Tiempo de Ejecución")
        
        timeline_data = self.metrics_data['execution_timeline']
        
        fig = px.timeline(
            timeline_data,
            x_start="start_time",
            x_end="end_time",
            y="task_type",
            color="success",
            title="Línea de Tiempo de Ejecución de Tareas"
        )
        st.plotly_chart(fig)
    
    def display_tool_usage(self):
        """Muestra uso de herramientas"""
        st.header("🛠️ Uso de Herramientas")
        
        tool_data = self.metrics_data['tool_usage']
        fig = px.bar(
            tool_data,
            x='tool_name',
            y='usage_count',
            color='status',
            title="Uso de Herramientas por Estado"
        )
        st.plotly_chart(fig)
    
    def display_learning_insights(self):
        """Muestra insights de aprendizaje"""
        st.header("🎓 Insights de Aprendizaje")
        
        learning_data = self.metrics_data['learning_insights']
        
        for insight in learning_data:
            with st.expander(insight['title']):
                st.write(insight['description'])
                st.metric("Confianza", f"{insight['confidence']:.0%}")
    
    def _load_metrics_data(self) -> Dict[str, Any]:
        """Carga datos de métricas para el dashboard"""
        # Esta sería una implementación real que consulta las métricas
        # Para el ejemplo, devolvemos datos de muestra
        return {
            'successful_tasks': 142,
            'failed_tasks': 18,
            'avg_time': 2.34,
            'success_rate': 0.887,
            'task_breakdown': [
                {'task_type': 'analysis', 'count': 45},
                {'task_type': 'planning', 'count': 32},
                {'task_type': 'execution', 'count': 58},
                {'task_type': 'validation', 'count': 25}
            ],
            'execution_timeline': [
                {'task_type': 'analysis', 'start_time': datetime.now() - timedelta(minutes=30), 'end_time': datetime.now() - timedelta(minutes=25), 'success': True},
                {'task_type': 'planning', 'start_time': datetime.now() - timedelta(minutes=25), 'end_time': datetime.now() - timedelta(minutes=20), 'success': True},
                {'task_type': 'execution', 'start_time': datetime.now() - timedelta(minutes=20), 'end_time': datetime.now() - timedelta(minutes=10), 'success': True},
                {'task_type': 'validation', 'start_time': datetime.now() - timedelta(minutes=10), 'end_time': datetime.now() - timedelta(minutes=5), 'success': True}
            ],
            'tool_usage': [
                {'tool_name': 'http_request', 'usage_count': 56, 'status': 'success'},
                {'tool_name': 'database_query', 'usage_count': 34, 'status': 'success'},
                {'tool_name': 'file_operations', 'usage_count': 22, 'status': 'success'},
                {'tool_name': 'http_request', 'usage_count': 8, 'status': 'failure'},
                {'tool_name': 'database_query', 'usage_count': 3, 'status': 'failure'}
            ],
            'learning_insights': [
                {
                    'title': 'Optimización de Consultas HTTP',
                    'description': 'Las consultas a APIs externas son más eficientes cuando se agrupan en lotes',
                    'confidence': 0.92
                },
                {
                    'title': 'Patrón de Planificación Exitosa',
                    'description': 'Las tareas con planificación detallada tienen 40% más tasa de éxito',
                    'confidence': 0.87
                }
            ]
        }