class GraphOperations:
    def __init__(self):
        self.consistency_checkers = [
            'temporal_consistency',
            'logical_consistency',
            'factual_consistency'
        ]
    
    def validate_update(self, new_information, existing_graph):
        # Ejecutar validaciones de consistencia
        validation_results = {}
        for checker in self.consistency_checkers:
            validation_results[checker] = getattr(self, checker)(new_information, existing_graph)
        
        return validation_results