import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
from kpis import SuccessMetrics

class ExecutiveDashboard:
    """Dashboard ejecutivo para monitorización de alto nivel"""
    
    def __init__(self):
        self.metrics = SuccessMetrics()
    
    def display_network_health(self):
        """Muestra métricas de salud de la red"""
        health_data = self.metrics.calculate_network_health()
        
        st.header("🌐 Salud de la Red")
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric("Disponibilidad", f"{health_data['availability']}%", "0.05%")
        with col2:
            st.metric("Throughput", f"{health_data['throughput']} TPS", "500")
        with col3:
            st.metric("Latencia", f"{health_data['latency']}ms", "-50ms")
    
    def display_knowledge_quality(self):
        """Muestra métricas de calidad del conocimiento"""
        quality_data = self.metrics.calculate_knowledge_quality()
        
        st.header("🧠 Calidad del Conocimiento")
        fig = px.bar(
            x=list(quality_data.keys()),
            y=list(quality_data.values()),
            labels={'x': 'Métrica', 'y': 'Valor'},
            title="Métricas de Calidad del Conocimiento"
        )
        st.plotly_chart(fig)
    
    def display_ecosystem_growth(self):
        """Muestra métricas de crecimiento del ecosistema"""
        growth_data = self.metrics.calculate_ecosystem_growth()
        
        st.header("📈 Crecimiento del Ecosistema")
        growth_df = pd.DataFrame({
            'Metrica': list(growth_data.keys()),
            'Valor': list(growth_data.values())
        })
        
        fig = px.line(
            growth_df,
            x='Metrica',
            y='Valor',
            title="Tendencia de Crecimiento",
            markers=True
        )
        st.plotly_chart(fig)
    
    def display_risk_metrics(self):
        """Muestra métricas de riesgo"""
        from risk_management.risk_matrix import get_critical_risks
        
        st.header("⚠️ Riesgos Críticos")
        critical_risks = get_critical_risks()
        
        for risk in critical_risks:
            with st.expander(f"{risk.id}: {risk.description}"):
                st.write(f"**Categoría**: {risk.category.value}")
                st.write(f"**Severidad**: {risk.severity.name}")
                st.write("**Plan de Mitigación**:")
                for mitigation in risk.mitigation_plan:
                    st.write(f"- {mitigation}")

# Ejemplo de uso del dashboard
if __name__ == "__main__":
    dashboard = ExecutiveDashboard()
    dashboard.display_network_health()
    dashboard.display_knowledge_quality()
    dashboard.display_ecosystem_growth()
    dashboard.display_risk_metrics()