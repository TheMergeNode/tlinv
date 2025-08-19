import re, os, json
from PIL import Image
import pytesseract

# Palabras guía para detectar un rasgo
TRAIT_HINTS = re.compile(
    r"(hit|critical|max health|cooldown|evasion|endurance|heavy attack|attack speed|buff|debuff|range|magic|melee|skill|side|front|collision|mana|stun)",
    re.IGNORECASE
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config.json")
CACHE_DIR = os.path.join(ROOT, "cache")
os.makedirs(CACHE_DIR, exist_ok=True)

def _load_cfg():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"language": "eng", "ocr_psm": 6, "ocr_preprocess": "none"}

def _preprocess(img: Image.Image, mode: str) -> Image.Image:
    """
    mode: 'binary' -> escala de grises + binarización Otsu
          'none'   -> sin cambios
    Siempre guarda una imagen en cache para depurar: last_input.png / last_preprocessed.png
    """
    # Guardar la imagen original para inspección
    try:
        img.save(os.path.join(CACHE_DIR, "last_input.png"))
    except Exception:
        pass

    if mode != "binary":
        # Aun si no hay preprocesado, guarda copia como 'last_preprocessed.png'
        try:
            img.save(os.path.join(CACHE_DIR, "last_preprocessed.png"))
        except Exception:
            pass
        return img

    # Si hay modo binario, requerimos cv2/np:
    try:
        import cv2
        import numpy as np
        arr = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)
        # Binarización Otsu
        _, th = cv2.threshold(arr, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        out = Image.fromarray(th)
        out.save(os.path.join(CACHE_DIR, "last_preprocessed.png"))
        return out
    except Exception as e:
        # Si falla cv2, volvemos a la original y dejamos traza mínima
        try:
            with open(os.path.join(CACHE_DIR, "last_preprocess_error.txt"), "w", encoding="utf-8") as f:
                f.write(str(e))
        except Exception:
            pass
        return img

def parse_tooltip(img_path: str, lang: str = "eng"):
    """
    Devuelve dict con 'item_name', 'trait' y 'raw'.
    Usa psm desde config y preprocesado opcional.
    (Mejora) Busca trait en TODAS las líneas si no aparece en las primeras.
    (Mejora) Elige nombre como la primera línea con letras y sin ser una línea numérica/monetaria.
    """
    cfg = _load_cfg()
    psm = cfg.get("ocr_psm", 6)
    preprocess = cfg.get("ocr_preprocess", "none")

    img = Image.open(img_path)
    img = _preprocess(img, preprocess)

    tconf = f"--psm {psm}"
    text = pytesseract.image_to_string(img, lang=lang, config=tconf)

    lines_raw = [l for l in text.splitlines()]
    lines = [l.strip() for l in lines_raw if l.strip()]

    # Heurística mejorada para nombre: línea con letras y no dominada por dígitos/símbolos
    name_candidate = None
    for l in lines[:8]:  # las primeras 8 líneas suelen contener el nombre
        has_letter = re.search(r"[A-Za-z]", l) is not None
        mostly_numbers = re.fullmatch(r"[\s\W\d]+", l) is not None
        if has_letter and not mostly_numbers:
            name_candidate = l
            break
    item_name = name_candidate or (lines[0] if lines else None)

    # Trait: primero busca en las primeras líneas; si no, en todas
    trait = None
    for l in lines[1:12]:
        if TRAIT_HINTS.search(l):
            trait = l
            break
    if trait is None:
        for l in lines:
            if TRAIT_HINTS.search(l):
                trait = l
                break

    return {"item_name": item_name, "trait": trait, "raw": text}