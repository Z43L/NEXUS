import numpy as np
from typing import Dict, List, Any
import json
from dataclasses import dataclass
from math import exp, log
import random

@dataclass
class PrivacyBudget:
    epsilon: float
    delta: float = 1e-5
    used_epsilon: float = 0.0
    
    def spend(self, amount: float) -> bool:
        if self.used_epsilon + amount <= self.epsilon:
            self.used_epsilon += amount
            return True
        return False

class DifferentialPrivacyEngine:
    """Motor de privacidad diferencial para NEXUS"""
    
    def __init__(self, default_epsilon: float = 1.0, default_delta: float = 1e-5):
        self.default_budget = PrivacyBudget(default_epsilon, default_delta)
        self.sensitivity_cache = {}
    
    def add_laplace_noise(self, value: float, sensitivity: float, epsilon: float) -> float:
        """Añade ruido de Laplace para privacidad diferencial"""
        if not self.default_budget.spend(epsilon):
            raise ValueError("Privacy budget exhausted")
        
        scale = sensitivity / epsilon
        noise = np.random.laplace(0, scale)
        return value + noise
    
    def add_gaussian_noise(self, value: float, sensitivity: float, epsilon: float, delta: float) -> float:
        """Añade ruido Gaussiano para privacidad diferencial"""
        if not self.default_budget.spend(epsilon):
            raise ValueError("Privacy budget exhausted")
        
        sigma = sensitivity * (2 * log(1.25 / delta)) ** 0.5 / epsilon
        noise = np.random.normal(0, sigma)
        return value + noise
    
    def private_count(self, data: List[Any], epsilon: float) -> float:
        """Conteo con privacidad diferencial"""
        true_count = len(data)
        sensitivity = 1  # El conteo tiene sensibilidad 1
        return self.add_laplace_noise(true_count, sensitivity, epsilon)
    
    def private_sum(self, data: List[float], bounds: tuple, epsilon: float) -> float:
        """Suma con privacidad diferencial"""
        true_sum = sum(data)
        min_val, max_val = bounds
        sensitivity = max_val - min_val  # Sensibilidad basada en los límites
        return self.add_laplace_noise(true_sum, sensitivity, epsilon)
    
    def private_mean(self, data: List[float], bounds: tuple, epsilon: float) -> float:
        """Media con privacidad diferencial"""
        private_sum = self.private_sum(data, bounds, epsilon / 2)
        private_count = self.private_count(data, epsilon / 2)
        return private_sum / private_count if private_count != 0 else 0
    
    def apply_to_dataset(self, dataset: List[Dict], config: Dict) -> List[Dict]:
        """Aplica privacidad diferencial a un dataset completo"""
        result = []
        remaining_budget = self.default_budget.epsilon - self.default_budget.used_epsilon
        
        for column, col_config in config.items():
            if col_config['method'] == 'laplace':
                values = [row[column] for row in dataset]
                noisy_values = self.add_laplace_noise(
                    values, 
                    col_config['sensitivity'], 
                    col_config['epsilon']
                )
                
                for i, row in enumerate(dataset):
                    if i not in result:
                        result.append(row.copy())
                    result[i][column] = noisy_values[i]
        
        return result