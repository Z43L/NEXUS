from datetime import datetime
from typing import List, Dict, Any
import asyncio
from datasets import Dataset
from transformers import TrainingArguments, Trainer
import numpy as np

class ContinuousFineTuningEngine:
    """Motor de fine-tuning continuo para el LLM extendido"""
    
    def __init__(self, model, tokenizer):
        self.model = model
        self.tokenizer = tokenizer
        self.training_queue = asyncio.Queue()
        self.is_training = False
        
    async def schedule_training(self, training_data: Dict[str, Any], priority: int = 1):
        """Programa una tarea de training en la cola de prioridad"""
        await self.training_queue.put({
            'data': training_data,
            'priority': priority,
            'timestamp': datetime.now()
        })
        
        if not self.is_training:
            asyncio.create_task(self.process_training_queue())
    
    async def process_training_queue(self):
        """Procesa la cola de training de forma continua"""
        self.is_training = True
        
        while not self.training_queue.empty():
            try:
                task = await self.training_queue.get()
                
                # Ejecutar fine-tuning incremental
                await self._execute_incremental_training(task['data'])
                
                self.training_queue.task_done()
                
            except Exception as e:
                print(f"Error en training: {e}")
                # Reintentar después
                await asyncio.sleep(60)
        
        self.is_training = False
    
    async def _execute_incremental_training(self, training_data: Dict[str, Any]):
        """Ejecuta fine-tuning incremental con los nuevos datos"""
        # Preparar dataset
        dataset = self._prepare_dataset(training_data)
        
        # Configurar argumentos de training
        training_args = TrainingArguments(
            output_dir="./nexus-adaptations",
            overwrite_output_dir=True,
            num_train_epochs=1,
            per_device_train_batch_size=2,
            gradient_accumulation_steps=4,
            learning_rate=2e-5,
            fp16=True,
            logging_steps=10,
            save_steps=500,
            save_total_limit=2
        )
        
        # Crear trainer
        trainer = Trainer(
            model=self.model,
            args=training_args,
            train_dataset=dataset,
            data_collator=self._data_collator
        )
        
        # Ejecutar training
        trainer.train()
        
        # Guardar adaptación
        trainer.save_model()
        
        # Actualizar estadísticas
        self._update_training_metrics(trainer)