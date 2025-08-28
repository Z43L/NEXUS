import psycopg2
from psycopg2 import sql
from psycopg2.extras import Json
from typing import Dict, List, Any, Optional
import logging

class AGEKnowledgeGraph:
    """Gestor de grafos de conocimiento usando Apache AGE"""
    
    def __init__(self, db_config: Dict[str, str], graph_name: str = "nexus_knowledge"):
        self.db_config = db_config
        self.graph_name = graph_name
        self.connection = None
        self.logger = logging.getLogger(__name__)
        self._connect()
        self._initialize_graph()
    
    def _connect(self):
        """Establece conexión con PostgreSQL/AGE"""
        try:
            self.connection = psycopg2.connect(
                host=self.db_config['host'],
                database=self.db_config['database'],
                user=self.db_config['user'],
                password=self.db_config['password'],
                port=self.db_config.get('port', 5432)
            )
            self.connection.autocommit = True
            
            with self.connection.cursor() as cursor:
                cursor.execute("LOAD 'age';")
                cursor.execute("SET search_path = ag_catalog, '$user', public;")
                
        except Exception as e:
            self.logger.error(f"Error conectando a AGE: {e}")
            raise
    
    def _initialize_graph(self):
        """Inicializa el grafo si no existe"""
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM ag_graph WHERE name = %s", (self.graph_name,))
            if cursor.fetchone()[0] == 0:
                cursor.execute(sql.SQL("SELECT * FROM ag_catalog.create_graph(%s)"), (self.graph_name,))
    
    def add_entity(self, label: str, properties: Dict[str, Any]) -> str:
        """Añade una nueva entidad al grafo"""
        with self.connection.cursor() as cursor:
            query = sql.SQL("SELECT * FROM ag_catalog.cypher(%s, %s, %s)")
            cypher_query = "CREATE (n:{label} $properties) RETURN n".format(label=label)
            
            cursor.execute(query, [self.graph_name, cypher_query, Json({'properties': properties})])
            result = cursor.fetchone()
            if result and result[0]:
                return result[0]['id']
            raise Exception("Error añadiendo entidad")
    
    def query_knowledge(self, cypher_query: str, params: Optional[Dict] = None) -> List[Dict]:
        """Ejecuta una consulta Cypher personalizada"""
        with self.connection.cursor() as cursor:
            query = sql.SQL("SELECT * FROM ag_catalog.cypher(%s, %s, %s)")
            cursor.execute(query, [self.graph_name, cypher_query, Json(params or {})])
            results = cursor.fetchall()
            return [result[0] for result in results if result[0]]