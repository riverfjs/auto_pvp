"""Nature and IV mappings."""

# Nature → (boost_stat, reduce_stat). Empty strings = neutral.
NATURE_MOD: dict[str, tuple[str, str]] = {
    "固执": ("atk_phys", "atk_mag"),
    "开朗": ("speed", "atk_mag"),
    "胆小": ("speed", "atk_phys"),
    "保守": ("atk_mag", "atk_phys"),
    "沉默": ("atk_mag", "speed"),
    "淘气": ("def_phys", "atk_mag"),
    "稳重": ("def_mag", "atk_phys"),
    "急躁": ("speed", "def_phys"),
    "勇敢": ("atk_phys", "speed"),
    "大胆": ("def_phys", "atk_phys"),
    "悠闲": ("def_phys", "speed"),
    "慎重": ("def_mag", "atk_mag"),
    "马虎": ("atk_mag", "def_mag"),
    "天真": ("speed", "def_mag"),
    "冷静": ("atk_mag", "speed"),
    "狂妄": ("def_mag", "speed"),
    "沉着": ("def_mag", "atk_phys"),
    "调皮": ("atk_phys", "def_mag"),
    "孤僻": ("atk_phys", "def_phys"),
    "温和": ("def_mag", "atk_phys"),
    "温顺": ("def_mag", "def_phys"),
    "浮躁": ("", ""),
    "害羞": ("", ""),
    "认真": ("", ""),
    "平和": ("", ""),
    "实干": ("", ""),
}

# IV stat name → pet stat key
IV_STAT_MAP: dict[str, str] = {
    "生命": "hp",
    "物攻": "atk_phys",
    "魔攻": "atk_mag",
    "物防": "def_phys",
    "魔防": "def_mag",
    "速度": "speed",
}
