class ReasoningAgent:
    def __init__(self, llm, memory, knowledge_graph):
        self.llm = llm
        self.memory = memory
        self.knowledge = knowledge_graph
        
    def execute_task(self, objective, constraints=None):
        # Planificación de tareas
        plan = self.formulate_plan(objective, constraints)
        
        # Ejecución iterativa con monitoreo
        results = []
        for step in plan:
            step_result = self.execute_step(step)
            results.append(step_result)
            
            # Aprendizaje en tiempo real
            self.learn_from_execution(step, step_result)
            
        return self.synthesize_results(results)