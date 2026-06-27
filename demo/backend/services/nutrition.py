from __future__ import annotations

from dataclasses import dataclass

from backend.models.schemas import Nutrition


@dataclass(frozen=True)
class FoodProfile:
    key: str
    display_name: str
    category: str
    density_g_per_ml: float
    density_std_g_per_ml: float
    calories_kcal_per_100g: float
    protein_g_per_100g: float
    carbs_g_per_100g: float
    fat_g_per_100g: float
    fiber_g_per_100g: float = 0
    sodium_mg_per_100g: float = 0


FOOD_PROFILES: dict[str, FoodProfile] = {
    "rice": FoodProfile("rice", "米饭", "主食", 0.72, 0.08, 116, 2.6, 25.9, 0.3, 0.4, 1),
    "chicken": FoodProfile("chicken", "鸡胸肉", "蛋白质", 1.02, 0.06, 165, 31.0, 0, 3.6, 0, 74),
    "broccoli": FoodProfile("broccoli", "西兰花", "蔬菜", 0.40, 0.10, 34, 2.8, 6.6, 0.4, 2.6, 33),
    "egg": FoodProfile("egg", "鸡蛋", "蛋白质", 0.95, 0.08, 143, 12.6, 1.1, 9.5, 0, 142),
    "beef": FoodProfile("beef", "牛肉", "蛋白质", 1.05, 0.07, 250, 26.0, 0, 15.0, 0, 72),
    "potato": FoodProfile("potato", "土豆", "主食", 0.77, 0.08, 77, 2.0, 17.0, 0.1, 2.2, 6),
    "sweet_potato": FoodProfile("sweet_potato", "红薯", "主食", 0.82, 0.09, 86, 1.6, 20.1, 0.1, 3.0, 55),
    "corn": FoodProfile("corn", "玉米", "主食", 0.72, 0.09, 96, 3.4, 21.0, 1.5, 2.4, 1),
    "apple": FoodProfile("apple", "苹果块", "水果", 0.60, 0.08, 52, 0.3, 13.8, 0.2, 2.4, 1),
    "unknown_food": FoodProfile("unknown_food", "未知食物", "待确认", 0.70, 0.18, 120, 6.0, 15.0, 3.5, 1.5, 30),
}


def profile_for_key(key: str) -> FoodProfile:
    return FOOD_PROFILES.get(key, FOOD_PROFILES["unknown_food"])


def nutrition_for_weight(profile: FoodProfile, weight_g: float) -> Nutrition:
    factor = max(weight_g, 0) / 100
    return Nutrition(
        calories_kcal=round(profile.calories_kcal_per_100g * factor, 1),
        protein_g=round(profile.protein_g_per_100g * factor, 1),
        carbs_g=round(profile.carbs_g_per_100g * factor, 1),
        fat_g=round(profile.fat_g_per_100g * factor, 1),
        fiber_g=round(profile.fiber_g_per_100g * factor, 1),
        sodium_mg=round(profile.sodium_mg_per_100g * factor, 1),
    )
