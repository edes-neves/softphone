"""Paletas de cores (claro/escuro). Apenas dados; sem globais mutaveis."""

THEMES = {
    "light": {
        "bg": "#F8FAFC",
        "card": "#FFFFFF",
        "border": "#E2E8F0",
        "primary_dark": "#2563EB",
        "text": "#1E293B",
        "muted": "#64748B",
        "list_even": "#FFFFFF",
        "list_odd": "#F1F5F9",
        "header": "#3B82F6",
        "header_chip": "#2563EB",
        "keypad_bg": "#0F172A",
        "keypad_fg": "#FFFFFF",
        "tooltip_bg": "#1F2937",
        "tooltip_fg": "#FFFFFF",
        "btn_disabled_bg": "#C1CAD4",
        "btn_disabled_fg": "#3E4A58",
    },
    "dark": {
        "bg": "#161A23",
        "card": "#1E2430",
        "border": "#2C3444",
        "primary_dark": "#7CA6F8",
        "text": "#E7EAF2",
        "muted": "#98A3B8",
        "list_even": "#1E2430",
        "list_odd": "#232A39",
        "header": "#2563EB",
        "header_chip": "#3B82F6",
        "keypad_bg": "#242B3B",
        "keypad_fg": "#F2F5FB",
        "tooltip_bg": "#2A3242",
        "tooltip_fg": "#EEF1F8",
        "btn_disabled_bg": "#2A3242",
        "btn_disabled_fg": "#8B94A6",
    },
}

# Paleta de cores da interface (mutadas por set_theme)
