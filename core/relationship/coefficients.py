from dataclasses import dataclass
import random


@dataclass
class DerivedCoefficients:
    """从依恋维度推导的关系变化系数"""
    tension_growth_multiplier: float = 1.0
    energy_decay_rate: float = 0.90
    trust_fragility_multiplier: float = 1.0
    closeness_threshold: float = 70.0
    tension_pressure_base: float = 0.05
    initiative_acceleration: float = 1.0


class CoefficientStrategy:
    """依恋策略基类"""
    def derive(self) -> DerivedCoefficients:
        raise NotImplementedError


class AnxiousStrategy(CoefficientStrategy):
    """焦虑型依恋策略：张力增长快、信任极脆、能量衰减慢、亲密阈值低"""
    def derive(self) -> DerivedCoefficients:
        return DerivedCoefficients(
            tension_growth_multiplier=random.uniform(1.15, 1.50),
            energy_decay_rate=random.uniform(0.95, 0.98),
            trust_fragility_multiplier=random.uniform(1.3, 1.8),
            closeness_threshold=random.uniform(60.0, 70.0),
            tension_pressure_base=random.uniform(0.08, 0.15),
            initiative_acceleration=random.uniform(1.3, 1.8),
        )


class AvoidantStrategy(CoefficientStrategy):
    """回避型依恋策略：张力增长慢、能量衰减快、亲密阈值高"""
    def derive(self) -> DerivedCoefficients:
        return DerivedCoefficients(
            tension_growth_multiplier=random.uniform(0.25, 0.50),
            energy_decay_rate=random.uniform(0.74, 0.80),
            trust_fragility_multiplier=random.uniform(0.9, 1.0),
            closeness_threshold=random.uniform(72.5, 80.0),
            tension_pressure_base=random.uniform(0.01, 0.03),
            initiative_acceleration=random.uniform(0.3, 0.6),
        )


class SecureStrategy(CoefficientStrategy):
    """安全型依恋策略：基准线参数"""
    def derive(self) -> DerivedCoefficients:
        return DerivedCoefficients(
            tension_growth_multiplier=random.uniform(0.80, 1.05),
            energy_decay_rate=random.uniform(0.85, 0.95),
            trust_fragility_multiplier=random.uniform(0.8, 1.2),
            closeness_threshold=random.uniform(65.0, 80.0),
            tension_pressure_base=random.uniform(0.03, 0.06),
            initiative_acceleration=random.uniform(0.8, 1.2),
        )


class CoefficientDeriver:
    """从 Persona 依恋维度自动选择策略并推导系数"""

    def __init__(self):
        self._strategies = {
            'anxious': AnxiousStrategy(),
            'avoidant': AvoidantStrategy(),
            'secure': SecureStrategy(),
        }
        self._cache = {}

    def select_strategy(self, attachment_anxiety: float, attachment_avoidance: float) -> str:
        """选择依恋策略，焦虑优先于回避"""
        if attachment_anxiety >= 0.5:
            return 'anxious'
        elif attachment_avoidance >= 0.5:
            return 'avoidant'
        else:
            return 'secure'

    def derive(self, persona_id: str, attachment_anxiety: float, attachment_avoidance: float) -> DerivedCoefficients:
        """推导系数（带缓存，同一 Persona 只推导一次）"""
        if persona_id in self._cache:
            return self._cache[persona_id]
        strategy_name = self.select_strategy(attachment_anxiety, attachment_avoidance)
        strategy = self._strategies[strategy_name]
        coeffs = strategy.derive()
        self._cache[persona_id] = coeffs
        return coeffs

    def invalidate(self, persona_id: str):
        """清除缓存（Persona 配置变更时调用）"""
        self._cache.pop(persona_id, None)
