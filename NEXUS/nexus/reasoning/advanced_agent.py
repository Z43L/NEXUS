from langchain.agents import AgentExecutor, Tool, create_react_agent
from langchain import hub
from langchain.chains import LLMChain
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, AIMessage
from datetime import datetime
from typing import List, Dict, Any, Optional
import json

class NexusReasoningAgent:
    def __init__(self, llm, tools: List[Tool], memory_manager, knowledge_graph):
        self.llm = llm
        self.tools = tools
        self.memory = memory_manager
        self.knowledge_graph = knowledge_graph
        self.agent = self._create_agent()
    
    def _create_agent(self):
        """Crea el agente con capacidades de razonamiento avanzado"""
        
        # Usar el prompt estándar de ReAct desde el hub (incluye {tools}, {tool_names}, {input}, {agent_scratchpad})
        prompt = hub.pull("hwchase17/react")
        agent = create_react_agent(
            llm=self.llm,
            tools=self.tools,
            prompt=prompt,
        )
        
        return AgentExecutor(agent=agent, tools=self.tools, verbose=True)
    
    async def execute_complex_task(self, task_description: str, context: Optional[Dict] = None):
        """Ejecuta una tarea compleja con planificación y razonamiento"""
        
        # Recuperar contexto relevante de la memoria
        relevant_memories = await self.memory.retrieve_relevant_experiences(
            task_description, 
            limit=10,
            min_confidence=0.7
        )
        
        # Consultar el grafo de conocimiento para información estructurada
        knowledge_context = self._query_knowledge_graph(task_description)
        
        # Construir entrada única (el agente ReAct por defecto espera solo {input})
        context_snippets = []
        if relevant_memories:
            context_snippets.append(f"Memories: {self._format_memories(relevant_memories)}")
        if knowledge_context:
            context_snippets.append(f"Knowledge: {json.dumps(knowledge_context)})")
        if context:
            context_snippets.append(f"External: {json.dumps(context)})")

        merged_input = task_description
        if context_snippets:
            merged_input += "\n\nContext:\n" + "\n".join(context_snippets)

        # Ejecutar el agente
        result = await self.agent.ainvoke({"input": merged_input})
        
        # Almacenar la experiencia para aprendizaje futuro
        await self._store_learning_experience(
            task_description,
            result,
            {
                "memories": relevant_memories,
                "knowledge_context": knowledge_context,
                "external_context": context or {},
                "merged_input": merged_input,
            },
        )
        
        return result
    
    def _query_knowledge_graph(self, query: str) -> Dict[str, Any]:
        """Consulta el grafo de conocimiento para información relevante"""
        # TODO: Implementar consultas semánticas al grafo
        return {}
    
    async def _store_learning_experience(self, task: str, result: Any, context: Dict[str, Any]):
        """Almacena la experiencia para aprendizaje futuro"""
        experience_data = {
            "task": task,
            "result": result,
            "context": context,
            "timestamp": datetime.now().isoformat(),
            "metadata": {
                "type": "learning_experience",
                "success_metrics": self._calculate_success_metrics(result),
                "complexity_score": self._assess_complexity(task)
            }
        }
        
        await self.memory.store_experience(experience_data)