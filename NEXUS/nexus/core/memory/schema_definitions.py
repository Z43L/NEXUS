class MemorySchema:
    def __init__(self):
        self.experience_template = {
            'id': 'hash_identifier',
            'embedding': 'vector_representation',
            'metadata': {
                'type': 'experience_type',
                'source': 'data_origin',
                'confidence': 'verification_level'
            },
            'context': 'temporal_context',
            'relationships': ['knowledge_graph_links'],
            'timestamp': 'creation_time'
        }