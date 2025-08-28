import pytest
import asyncio
import time
from datetime import datetime
from nexus.core.memory.memory_manager import MemoryManager

class TestLoadPerformance:
    """Suite de pruebas de carga y rendimiento"""
    
    @pytest.fixture
    async def memory_manager(self):
        """Fixture con configuración para pruebas de carga"""
        config = {
            "nodes": ["http://localhost:8080"],
            "sharding": {"total_shards": 4, "replicas_per_shard": 2},
            "cache_size": 10000
        }
        manager = MemoryManager(config)
        await manager.initialize()
        return manager
    
    @pytest.mark.load
    @pytest.mark.asyncio
    async def test_high_concurrency_storage(self, memory_manager):
        """Prueba almacenamiento bajo alta concurrencia"""
        concurrent_tasks = 1000
        experiences_to_store = 10000
        
        async def store_experience_task(task_id):
            experience = NexusExperience(
                content=f"Test experience from task {task_id}",
                embedding=[0.1 * task_id, 0.2, 0.3],
                memory_type=MemoryType.KNOWLEDGE_UPDATE
            )
            return await memory_manager.store_experience(experience)
        
        # Ejecutar tareas concurrentes
        start_time = time.time()
        
        tasks = []
        for i in range(concurrent_tasks):
            task = asyncio.create_task(store_experience_task(i))
            tasks.append(task)
        
        results = await asyncio.gather(*tasks)
        end_time = time.time()
        
        # Verificar que todas se completaron
        assert len(results) == concurrent_tasks, "Debería completar todas las tareas"
        assert all(result is not None for result in results), "Todas deberían retornar IDs"
        
        # Verificar rendimiento
        total_time = end_time - start_time
        ops_per_second = concurrent_tasks / total_time
        
        print(f"Operaciones por segundo: {ops_per_second:.2f}")
        assert ops_per_second > 100, "Debería manejar al menos 100 ops/segundo"
    
    @pytest.mark.load
    @pytest.mark.asyncio
    async def test_large_scale_search(self, memory_manager):
        """Prueba búsquedas a gran escala"""
        # Primero poblar con datos de prueba
        for i in range(1000):
            experience = NexusExperience(
                content=f"Knowledge item {i} about artificial intelligence",
                embedding=[0.01 * i, 0.02 * i, 0.03 * i],
                memory_type=MemoryType.KNOWLEDGE_UPDATE
            )
            await memory_manager.store_experience(experience)
        
        # Test de búsqueda bajo carga
        search_times = []
        successful_searches = 0
        
        for i in range(100):
            start_time = time.time()
            
            results = await memory_manager.search_similar_experiences(
                query_embedding=[0.5, 0.6, 0.7],
                limit=10,
                min_confidence=ConfidenceLevel.MEDIUM
            )
            
            end_time = time.time()
            search_time = end_time - start_time
            search_times.append(search_time)
            
            if results and len(results) > 0:
                successful_searches += 1
        
        # Estadísticas de rendimiento
        avg_search_time = sum(search_times) / len(search_times)
        max_search_time = max(search_times)
        min_search_time = min(search_times)
        
        print(f"Tiempo promedio de búsqueda: {avg_search_time:.3f}s")
        print(f"Tiempo máximo de búsqueda: {max_search_time:.3f}s")
        print(f"Tiempo mínimo de búsqueda: {min_search_time:.3f}s")
        print(f"Búsquedas exitosas: {successful_searches}/100")
        
        assert avg_search_time < 0.5, "Búsquedas deberían ser rápidas"
        assert successful_searches >= 95, "La mayoría de búsquedas deberían ser exitosas"