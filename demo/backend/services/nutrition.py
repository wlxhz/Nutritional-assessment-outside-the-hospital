from __future__ import annotations

from dataclasses import dataclass, asdict

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


def f(
    key: str,
    name: str,
    category: str,
    density: float,
    density_std: float,
    kcal: float,
    protein: float,
    carbs: float,
    fat: float,
    fiber: float = 0,
    sodium: float = 0,
) -> FoodProfile:
    return FoodProfile(key, name, category, density, density_std, kcal, protein, carbs, fat, fiber, sodium)


# Nutrition values are approximate per-100g entries for product validation.
# They are seeded from public food-composition references such as USDA FoodData
# Central and China Food Composition Table categories, then normalized for this
# MVP's density -> weight -> nutrition pipeline.
FOOD_PROFILES: dict[str, FoodProfile] = {
    # Staples
    "rice": f("rice", "米饭", "主食", 0.72, 0.08, 116, 2.6, 25.9, 0.3, 0.4, 1),
    "brown_rice": f("brown_rice", "糙米饭", "主食", 0.74, 0.08, 111, 2.6, 23.0, 0.9, 1.8, 5),
    "millet_porridge": f("millet_porridge", "小米粥", "主食", 0.98, 0.05, 46, 1.4, 9.4, 0.4, 0.5, 3),
    "porridge": f("porridge", "白粥", "主食", 0.99, 0.04, 38, 0.8, 8.4, 0.1, 0.2, 2),
    "wheat_noodles": f("wheat_noodles", "面条", "主食", 0.78, 0.08, 138, 4.5, 25.0, 2.1, 1.2, 5),
    "rice_noodles": f("rice_noodles", "米粉", "主食", 0.76, 0.08, 109, 1.8, 24.9, 0.2, 0.8, 4),
    "steamed_bun": f("steamed_bun", "馒头", "主食", 0.45, 0.07, 223, 7.0, 47.0, 1.1, 1.7, 190),
    "dumpling": f("dumpling", "饺子", "主食", 0.82, 0.12, 197, 8.2, 26.0, 6.6, 1.8, 420),
    "wonton": f("wonton", "馄饨", "主食", 0.88, 0.10, 165, 7.0, 22.0, 5.5, 1.1, 390),
    "potato": f("potato", "土豆", "主食", 0.77, 0.08, 77, 2.0, 17.0, 0.1, 2.2, 6),
    "sweet_potato": f("sweet_potato", "红薯", "主食", 0.82, 0.09, 86, 1.6, 20.1, 0.1, 3.0, 55),
    "corn": f("corn", "玉米", "主食", 0.72, 0.09, 96, 3.4, 21.0, 1.5, 2.4, 1),
    "pumpkin": f("pumpkin", "南瓜", "蔬菜", 0.75, 0.08, 26, 1.0, 6.5, 0.1, 0.5, 1),
    "taro": f("taro", "芋头", "主食", 0.86, 0.09, 112, 1.5, 26.5, 0.2, 4.1, 11),
    "lotus_root": f("lotus_root", "莲藕", "蔬菜", 0.75, 0.08, 74, 2.6, 17.2, 0.1, 4.9, 40),
    # Proteins
    "chicken": f("chicken", "鸡胸肉", "蛋白质", 1.02, 0.06, 165, 31.0, 0, 3.6, 0, 74),
    "chicken_thigh": f("chicken_thigh", "鸡腿肉", "蛋白质", 1.02, 0.07, 209, 26.0, 0, 10.9, 0, 86),
    "duck": f("duck", "鸭肉", "蛋白质", 1.00, 0.08, 240, 19.0, 0, 18.0, 0, 74),
    "pork_lean": f("pork_lean", "瘦猪肉", "蛋白质", 1.04, 0.06, 143, 20.3, 0, 6.2, 0, 57),
    "pork_belly": f("pork_belly", "五花肉", "蛋白质", 0.96, 0.10, 518, 9.3, 0, 53.0, 0, 32),
    "beef": f("beef", "牛肉", "蛋白质", 1.05, 0.07, 250, 26.0, 0, 15.0, 0, 72),
    "lamb": f("lamb", "羊肉", "蛋白质", 1.04, 0.08, 258, 25.6, 0, 16.5, 0, 72),
    "fish": f("fish", "鱼肉", "蛋白质", 1.02, 0.07, 120, 20.0, 0, 4.0, 0, 70),
    "salmon": f("salmon", "三文鱼", "蛋白质", 1.01, 0.07, 208, 20.4, 0, 13.4, 0, 59),
    "shrimp": f("shrimp", "虾仁", "蛋白质", 1.03, 0.06, 99, 24.0, 0.2, 0.3, 0, 111),
    "egg": f("egg", "鸡蛋", "蛋白质", 0.95, 0.08, 143, 12.6, 1.1, 9.5, 0, 142),
    "tofu": f("tofu", "豆腐", "豆制品", 0.92, 0.08, 76, 8.1, 1.9, 4.8, 0.3, 7),
    "dried_tofu": f("dried_tofu", "豆干", "豆制品", 0.86, 0.08, 140, 16.2, 5.0, 7.0, 1.2, 380),
    "soybean": f("soybean", "黄豆", "豆制品", 0.78, 0.10, 173, 16.6, 9.9, 9.0, 6.0, 2),
    "edamame": f("edamame", "毛豆", "豆制品", 0.72, 0.09, 121, 11.9, 8.9, 5.2, 5.2, 6),
    # Leafy and green vegetables
    "broccoli": f("broccoli", "西兰花", "蔬菜", 0.40, 0.10, 34, 2.8, 6.6, 0.4, 2.6, 33),
    "cauliflower": f("cauliflower", "花菜", "蔬菜", 0.45, 0.10, 25, 1.9, 5.0, 0.3, 2.0, 30),
    "bok_choy": f("bok_choy", "小白菜", "蔬菜", 0.48, 0.10, 13, 1.5, 2.2, 0.2, 1.0, 65),
    "spinach": f("spinach", "菠菜", "蔬菜", 0.50, 0.10, 23, 2.9, 3.6, 0.4, 2.2, 79),
    "napa_cabbage": f("napa_cabbage", "大白菜", "蔬菜", 0.48, 0.10, 16, 1.2, 3.2, 0.2, 1.2, 18),
    "cabbage": f("cabbage", "卷心菜", "蔬菜", 0.50, 0.10, 25, 1.3, 5.8, 0.1, 2.5, 18),
    "lettuce": f("lettuce", "生菜", "蔬菜", 0.42, 0.10, 15, 1.4, 2.9, 0.2, 1.3, 28),
    "celery": f("celery", "芹菜", "蔬菜", 0.52, 0.10, 16, 0.7, 3.0, 0.2, 1.6, 80),
    "garlic_chive": f("garlic_chive", "韭菜", "蔬菜", 0.45, 0.10, 30, 2.4, 4.6, 0.4, 2.4, 25),
    "green_bean": f("green_bean", "四季豆", "蔬菜", 0.58, 0.10, 31, 1.8, 7.0, 0.1, 3.4, 6),
    "snow_pea": f("snow_pea", "荷兰豆", "蔬菜", 0.56, 0.10, 42, 2.8, 7.6, 0.2, 2.6, 4),
    "bean_sprout": f("bean_sprout", "豆芽", "蔬菜", 0.55, 0.10, 30, 3.0, 5.9, 0.2, 1.8, 6),
    # Other vegetables
    "tomato": f("tomato", "番茄", "蔬菜", 0.60, 0.08, 18, 0.9, 3.9, 0.2, 1.2, 5),
    "cucumber": f("cucumber", "黄瓜", "蔬菜", 0.55, 0.08, 15, 0.7, 3.6, 0.1, 0.5, 2),
    "carrot": f("carrot", "胡萝卜", "蔬菜", 0.70, 0.08, 41, 0.9, 9.6, 0.2, 2.8, 69),
    "eggplant": f("eggplant", "茄子", "蔬菜", 0.58, 0.10, 25, 1.0, 5.9, 0.2, 3.0, 2),
    "winter_melon": f("winter_melon", "冬瓜", "蔬菜", 0.62, 0.08, 13, 0.4, 3.0, 0.2, 0.9, 2),
    "bitter_melon": f("bitter_melon", "苦瓜", "蔬菜", 0.58, 0.10, 17, 1.0, 3.7, 0.2, 2.8, 5),
    "bell_pepper": f("bell_pepper", "彩椒", "蔬菜", 0.50, 0.10, 31, 1.0, 6.0, 0.3, 2.1, 4),
    "onion": f("onion", "洋葱", "蔬菜", 0.62, 0.08, 40, 1.1, 9.3, 0.1, 1.7, 4),
    "mushroom": f("mushroom", "蘑菇", "菌菇", 0.55, 0.10, 22, 3.1, 3.3, 0.3, 1.0, 5),
    "shiitake": f("shiitake", "香菇", "菌菇", 0.45, 0.10, 34, 2.2, 6.8, 0.5, 2.5, 9),
    "enoki": f("enoki", "金针菇", "菌菇", 0.42, 0.10, 37, 2.7, 7.8, 0.3, 2.7, 3),
    "wood_ear": f("wood_ear", "木耳", "菌菇", 0.35, 0.10, 25, 1.5, 6.8, 0.2, 5.0, 9),
    "bamboo_shoot": f("bamboo_shoot", "笋", "蔬菜", 0.55, 0.10, 27, 2.6, 5.2, 0.3, 2.2, 4),
    # Fruits
    "apple": f("apple", "苹果", "水果", 0.60, 0.08, 52, 0.3, 13.8, 0.2, 2.4, 1),
    "banana": f("banana", "香蕉", "水果", 0.66, 0.08, 89, 1.1, 22.8, 0.3, 2.6, 1),
    "orange": f("orange", "橙子", "水果", 0.62, 0.08, 47, 0.9, 11.8, 0.1, 2.4, 0),
    "watermelon": f("watermelon", "西瓜", "水果", 0.58, 0.08, 30, 0.6, 7.6, 0.2, 0.4, 1),
    # Common mixed dishes for fallback reports
    "tomato_egg": f("tomato_egg", "番茄炒蛋", "混合菜", 0.78, 0.14, 98, 6.2, 4.2, 6.5, 0.8, 220),
    "mapo_tofu": f("mapo_tofu", "麻婆豆腐", "混合菜", 0.88, 0.16, 128, 8.0, 5.0, 8.5, 1.2, 420),
    "stir_fried_greens": f("stir_fried_greens", "炒青菜", "混合菜", 0.62, 0.14, 55, 2.2, 5.0, 3.2, 2.0, 260),
    "fried_rice": f("fried_rice", "炒饭", "混合菜", 0.78, 0.15, 188, 5.5, 28.0, 6.0, 1.2, 420),
    "unknown_food": f("unknown_food", "未知食物", "待确认", 0.70, 0.18, 120, 6.0, 15.0, 3.5, 1.5, 30),
}


def profile_for_key(key: str) -> FoodProfile:
    return FOOD_PROFILES.get(key, FOOD_PROFILES["unknown_food"])


def all_profiles() -> list[dict[str, object]]:
    return [asdict(profile) for profile in FOOD_PROFILES.values()]


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
