import psycopg2
from psycopg2 import sql
from psycopg2.extras import Json
import networkx as nx
from typing import Dict, List, Any, Optional
import json
from datetime import datetime

class DynamicKnowledgeGraph:
    def __init__(self, db_config: Dict[str, str]):
        self.connection = psycopg2.connect(
            host=db_config['host'],
            database=db_config['database'],
            user=db_config['user'],
            password=db_config['password'],
            port=db_config['port']
        )
        self.connection.autocommit = True
        self.setup_graph_extension()
    
    def setup_graph_extension(self):
        """Configura la extensión Apache AGE"""
        with self.connection.cursor() as cursor:
            cursor.execute("LOAD 'age';")
            cursor.execute("SET search_path = ag_catalog, '$user', public;")
    
    def create_knowledge_graph(self, graph_name: str):
        """Crea un nuevo grafo de conocimiento"""
        with self.connection.cursor() as cursor:
            # Primero intenta detectar si el grafo ya existe para evitar errores en el arranque
            try:
                cursor.execute(
                    "SELECT 1 FROM ag_catalog.ag_graph WHERE name = %s LIMIT 1",
                    [graph_name]
                )
                if cursor.fetchone():
                    return  # Ya existe, no hacer nada
            except Exception:
                # Si no podemos chequear, seguimos e intentamos crear y capturar "already exists"
                pass

            try:
                cursor.execute(
                    sql.SQL("SELECT * FROM ag_catalog.create_graph(%s)"),
                    [graph_name]
                )
            except psycopg2.errors.InvalidSchemaName as e:
                # AGE devuelve InvalidSchemaName si el grafo ya existe
                if 'already exists' in str(e).lower():
                    return
                raise
    
    def add_entity(self, graph_name: str, label: str, properties: Dict[str, Any]) -> str:
        """Añade una nueva entidad al grafo"""
        with self.connection.cursor() as cursor:
            query = sql.SQL("""
                SELECT * FROM ag_catalog.cypher(%s, %s, %s)
            """)
            cypher_query = f"CREATE (n:{label} $properties) RETURN n"
            cursor.execute(query, [graph_name, cypher_query, Json({'properties': properties})])
            result = cursor.fetchone()
            return result[0]['n']['id']
    
    def add_relationship(self, graph_name: str, from_id: str, to_id: str, 
                        rel_type: str, properties: Dict[str, Any]) -> str:
        """Añade una relación entre entidades"""
        with self.connection.cursor() as cursor:
            query = sql.SQL("""
                SELECT * FROM ag_catalog.cypher(%s, %s, %s)
            """)
            cypher_query = f"""
                MATCH (a), (b) 
                WHERE id(a) = {from_id} AND id(b) = {to_id}
                CREATE (a)-[r:{rel_type} $properties]->(b)
                RETURN r
            """
            cursor.execute(query, [graph_name, cypher_query, Json({'properties': properties})])
            result = cursor.fetchone()
            return result[0]['r']['id']
    
    def update_entity(self, graph_name: str, entity_id: str, new_properties: Dict[str, Any]):
        """Actualiza las propiedades de una entidad"""
        with self.connection.cursor() as cursor:
            query = sql.SQL("""
                SELECT * FROM ag_catalog.cypher(%s, %s, %s)
            """)
            cypher_query = f"""
                MATCH (n) 
                WHERE id(n) = {entity_id}
                SET n += $properties
                RETURN n
            """
            cursor.execute(query, [graph_name, cypher_query, Json({'properties': new_properties})])