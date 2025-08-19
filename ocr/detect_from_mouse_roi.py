import os, time, re
from PIL import ImageGrab, Image
import pyautogui, keyboard
import pytesseract

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(ROOT, "cache")
os.makedirs(CACHE_DIR, exist_ok=True)

# === Offsets del recorte grande relativo al mouse (ajústalos si hace falta) ===
OFFSET_LEFT   = 450   # hacia la izquierda del mouse
OFFSET_RIGHT  = 1    # pequeño margen a la derecha
OFFSET_TOP    = 600    # arriba
OFFSET_BOTTOM = 600    # abajo

def clamp(val, lo, hi): return max(lo, min(val, hi))

def grab_mouse_big_roi():
    x, y = pyautogui.position()
    sw, sh = pyautogui.size()
    x1 = clamp(x - OFFSET_LEFT, 0, sw)
    y1 = clamp(y - OFFSET_TOP,  0, sh)
    x2 = clamp(x + OFFSET_RIGHT, 0, sw)
    y2 = clamp(y + OFFSET_BOTTOM, 0, sh)
    if x2 <= x1: x2 = clamp(x1 + 10, 0, sw)
    if y2 <= y1: y2 = clamp(y1 + 10, 0, sh)
    bbox = (x1, y1, x2, y2)
    img = ImageGrab.grab(bbox=bbox)
    big_path = os.path.join(CACHE_DIR, "auto_big_roi.png")
    img.save(big_path)
    return img, big_path, bbox

def text_boxes(img):
    """Devuelve una lista de dicts de palabras con bounding boxes usando image_to_data."""
    data = pytesseract.image_to_data(img, lang="eng", config="--psm 6", output_type=pytesseract.Output.DICT)
    words = []
    n = len(data["text"])
    for i in range(n):
        txt = (data["text"][i] or "").strip()
        if not txt:
            continue
        x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
        conf = int(data.get("conf", ["-1"]*n)[i]) if data.get("conf") else -1
        words.append({"text": txt, "x": x, "y": y, "w": w, "h": h, "conf": conf, "line": data["line_num"][i], "block": data["block_num"][i]})
    return words

def detect_name_and_trait(img):
    words = text_boxes(img)
    if not words:
        return None, None, None, None

    # -------------------------
    # 1) TRAIT 
    # -------------------------
    trait_label = None
    for w in words:
        if re.fullmatch(r"(?i)trait", w["text"]):
            trait_label = w
            break

    trait_text, trait_box = None, None
    if trait_label:
        label_line = trait_label["line"]
        following = [w for w in words if w["line"] in {label_line+1, label_line+2}]
        if following:
            target_line = min(w["line"] for w in following)
            line_words = [w for w in following if w["line"] == target_line]
            line_words.sort(key=lambda r: r["x"])
            trait_text = " ".join(w["text"] for w in line_words)
            x1 = min(w["x"] for w in line_words); y1 = min(w["y"] for w in line_words)
            x2 = max(w["x"] + w["w"] for w in line_words); y2 = max(w["y"] + w["h"] for w in line_words)
            trait_box = (x1, y1, x2, y2)

    # ---------------------------------------------
    # 2) NOMBRE con doble ancla: Rareza + Tipo
    # ---------------------------------------------
    import re as _re
    RARITY_ANCHOR = _re.compile(r"(?i)\b(epic|heroic|legendary|rare|common)\b")
    TYPE_ANCHOR   = _re.compile(
        r"(?i)\b(gloves|headgear|chest|greatsword|sword|daggers|crossbow|longbow|staff|wand|"
        r"spear|legs|shoes|cloak|belt|necklace|ring|bracelet)\b"
    )

    anchors_r = [w for w in words if RARITY_ANCHOR.search(w["text"])]
    anchors_t = [w for w in words if TYPE_ANCHOR.search(w["text"])]

    name_text, name_box = None, None

    def _line_text(line_words):
        line_words.sort(key=lambda r: r["x"])
        return " ".join(w["text"] for w in line_words)

    if anchors_r and anchors_t:
        # elegimos: rareza más cercana al centro, y tipo más cercano horizontalmente a esa rareza
        cx = img.size[0] // 2
        a_r = sorted(anchors_r, key=lambda w: abs((w["x"] + w["w"]//2) - cx))[0]
        a_t = sorted(anchors_t, key=lambda w: abs(w["y"] - a_r["y"]) + abs((w["x"] - a_r["x"])) )[0]

        # ventana vertical entre rareza (arriba) y tipo (arriba también); el nombre suele quedar en medio
        top_limit    = min(a_r["y"] + a_r["h"], a_t["y"] + a_t["h"]) + 2
        bottom_limit = top_limit + 180  # altura razonable del nombre

        # descartar líneas con números/%, blacklist típica
        BLACKLIST = _re.compile(
            r"(?i)\b(melee\s+defense|ranged\s+defense|magic\s+defense|off-?hand|main-?hand|"
            r"locked|preview|max\s+enchantment\s+stats|set\s+effects|trait|blessing|lv\.?|level)\b"
        )

        # candidatos dentro de la franja
        by_line = {}
        for w in words:
            yc = w["y"] + w["h"] // 2
            if top_limit <= yc <= bottom_limit and _re.search(r"[A-Za-z]", w["text"]):
                by_line.setdefault(w["line"], []).append(w)

        best = None
        for ln, lw in by_line.items():
            txt = _line_text(lw)
            if BLACKLIST.search(txt): 
                continue
            if _re.fullmatch(r"[\W\d%.\-+ ]+", txt): 
                continue
            # exigir ≥ 2 palabras con letras
            alpha = [x for x in lw if _re.search(r"[A-Za-z]", x["text"])]
            if len(alpha) < 2:
                continue
            # score: línea más ancha + letra más alta
            total_w = sum(x["w"] for x in alpha)
            max_h   = max(x["h"] for x in alpha)
            score   = total_w + 3*max_h
            if best is None or score > best[0]:
                best = (score, ln, lw)

        if best:
            _, ln, lw = best
            name_text = _line_text(lw)
            x1 = min(w["x"] for w in lw); y1 = min(w["y"] for w in lw)
            x2 = max(w["x"] + w["w"] for w in lw); y2 = max(w["y"] + w["h"] for w in lw)
            name_box = (x1, y1, x2, y2)

    # -----------------------------------------------------------
    # 2.b) FALLBACK NUEVO: usar "Defense/Damage" como ancla inferior
    #     Toma la línea alfanumérica más larga justo por encima.
    # -----------------------------------------------------------
    if not name_text:
        LOWER_ANCHOR = _re.compile(r"(?i)\b(defense|damage|melee|range|magic|extraction)\b")
        lowers = [w for w in words if LOWER_ANCHOR.search(w["text"])]
        if lowers:
            y_anchor = min(w["y"] for w in lowers)

            # Palabras que NO pueden ser el nombre
            BLACKLIST = _re.compile(
                r"(?i)\b("
                r"melee\s+defense|ranged\s+defense|magic\s+defense|off-?hand|main-?hand|"
                r"locked|preview|max\s+enchantment\s+stats|set\s+effects|trait|blessing|"
                r"lv\.?|level|durability|weight"
                r")\b"
            )

            by_line = {}
            for w in words:
                by_line.setdefault(w["line"], []).append(w)

            best = None  # (score, line_num, line_words)
            for line_num, lw in by_line.items():
                # centro vertical de la línea
                y_top = min(x["y"] for x in lw)
                y_bot = max(x["y"] + x["h"] for x in lw)
                y_center = (y_top + y_bot) / 2

                # Solo líneas por ENCIMA del anchor y no demasiado lejos
                if y_center >= y_anchor:
                    continue
                if y_anchor - y_center > 260:  # ventana vertical
                    continue

                # Construir texto de línea y filtrar por blacklist / % / pocos caracteres
                lw_sorted = sorted(lw, key=lambda r: r["x"])
                line_text = " ".join(x["text"] for x in lw_sorted)
                if BLACKLIST.search(line_text):
                    continue
                if _re.fullmatch(r"[\W\d%.\-+ ]+", line_text):
                    continue  # casi todo números/símbolos
                if len(_re.sub(r"[^A-Za-z]", "", line_text)) < 6:
                    continue  # muy corta para ser nombre

                # Requerir al menos dos palabras con letras
                alpha_words = [x for x in lw_sorted if _re.search(r"[A-Za-z]", x["text"])]
                if len(alpha_words) < 2:
                    continue

                # Score: preferir líneas largas y con letra grande
                total_width = sum(x["w"] for x in alpha_words)
                max_height  = max(x["h"] for x in alpha_words)
                score = total_width + 3 * max_height

                if (best is None) or (score > best[0]):
                    best = (score, line_num, lw_sorted)

            if best:
                _, ln, lw_sorted = best
                name_text = " ".join(w["text"] for w in lw_sorted)
                x1 = min(w["x"] for w in lw_sorted); y1 = min(w["y"] for w in lw_sorted)
                x2 = max(w["x"] + w["w"] for w in lw_sorted); y2 = max(w["y"] + w["h"] for w in lw_sorted)
                name_box = (x1, y1, x2, y2)

    # Fallback final: línea más alta con letras
    if not name_text:
        candidates = [w for w in words if _re.search(r"[A-Za-z]", w["text"])]
        if candidates:
            top_line_y = min(w["y"] for w in candidates)
            line_candidates = [w for w in candidates if abs(w["y"] - top_line_y) < 10 + (w["h"]//2)]
            line_candidates.sort(key=lambda r: r["x"])
            name_text = " ".join(w["text"] for w in line_candidates)
            x1 = min(w["x"] for w in line_candidates)
            y1 = min(w["y"] for w in line_candidates)
            x2 = max(w["x"] + w["w"] for w in line_candidates)
            y2 = max(w["y"] + w["h"] for w in line_candidates)
            name_box = (x1, y1, x2, y2)

    return name_text, name_box, trait_text, trait_box

def save_crop(img, box, out_name):
    if not box:
        return None
    crop = img.crop(box)
    out_path = os.path.join(CACHE_DIR, out_name)
    crop.save(out_path)
    return out_path

def run_once():
    print("Capturando ROI grande relativo al mouse…")
    big_img, big_path, bbox = grab_mouse_big_roi()
    print(f"Guardado ROI grande: {big_path}  bbox_abs={bbox}")

    print("Detectando nombre y trait via OCR (cajas de texto)…")
    name_text, name_box, trait_text, trait_box = detect_name_and_trait(big_img)

    name_preview = save_crop(big_img, name_box, "auto_name_crop.png")
    trait_preview = save_crop(big_img, trait_box, "auto_trait_crop.png")

    print("\n=== RESULTADOS ===")
    print("Item Name:", name_text)
    print("Trait    :", trait_text)
    print("name_crop:", name_preview)
    print("trait_crop:", trait_preview)

def main():
    print("F12 = capturar-detectar una vez | Ctrl+F12 = salir")
    while True:
        if keyboard.is_pressed("f12"):
            run_once()
            time.sleep(0.5)
        if keyboard.is_pressed("ctrl+f12"):
            print("Saliendo…")
            break
        time.sleep(0.05)

if __name__ == "__main__":
    main()