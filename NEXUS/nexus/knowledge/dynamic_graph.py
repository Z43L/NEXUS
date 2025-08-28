class KnowledgeGraphEngine:
    def __init__(self, memory_manager):
        self.graph = DynamicGraphDB()
        self.memory = memory_manager
        
    def update_knowledge(self, new_information):
        # Extraer entidades y relaciones
        entities, relationships = self.extract_entities_and_relations(new_information)
        
        # Integrar con el grafo existente
        with self.graph.transaction():
            for entity in entities:
                self.graph.merge_entity(entity)
            for relation in relationships:
                self.graph.create_relationship(relation)
                
        # Validar consistencia del grafo
        consistency_report = self.validate_consistency()
        if consistency_report.is_valid:
            self.commit_transaction()
        else:
            self.resolve_inconsistencies(consistency_report)