import math


def apply_closeness_curve(current: float, delta: float, is_qualitative_leap: bool = False) -> float:
    """亲密感 S 形曲线转换
    - 0-60: 全量生效（刚认识/敏感期）
    - 60-85: 线性递减 (85-current)/25
    - 85+: 仅10%生效（除非质变事件）
    """
    if delta == 0:
        return current
    if delta > 0:
        if current < 60:
            effective = delta
        elif current < 85:
            factor = (85 - current) / 25
            effective = delta * factor
        else:
            if is_qualitative_leap:
                effective = delta
            else:
                effective = delta * 0.1
    else:
        effective = delta
    return max(0.0, min(100.0, current + effective))


def apply_trust_curve(current: float, delta: float, fragility_multiplier: float = 1.0) -> float:
    """信任易碎效应
    - 涨：按原值
    - 跌：×(1 + fragility_multiplier × 0.5)
    """
    if delta == 0:
        return current
    if delta > 0:
        effective = delta
    else:
        effective = delta * (1.0 + fragility_multiplier * 0.5)
    return max(0.0, min(100.0, current + effective))


def apply_exponential_decay(current: float, decay_rate: float, hours: float) -> float:
    """指数衰减：current × decayRate^hours"""
    if hours <= 0:
        return current
    return current * (decay_rate ** hours)


def apply_tension_decay(current: float, hours: float) -> float:
    """张力自然衰减：0.95^hours"""
    if hours <= 0:
        return current
    return max(0.0, current * (0.95 ** hours))
