import os, time
from dataclasses import dataclass
from typing import Optional, Tuple

import cv2
import numpy as np
import pyautogui, keyboard
from PIL import ImageGrab, Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(ROOT, "cache")
os.makedirs(CACHE_DIR, exist_ok=True)

# --- ROI grande relativo al mouse (ajustable) ---
OFFSET_LEFT   = 450
OFFSET_RIGHT  = 160   # margen mayor para no cortar el borde del tooltip
OFFSET_TOP    = 600
OFFSET_BOTTOM = 800

# --- Heurísticas para elegir el tooltip ---
MIN_AREA_RATIO = 0.015  # más permisivo (antes 0.03)
MAX_AREA_RATIO = 0.95
RECT_TOLERANCE = 0.08
PREF_ASPECT_MIN = 0.45
PREF_ASPECT_MAX = 1.80

def clamp(v, lo, hi): 
    return max(lo, min(hi, v))

def grab_big_roi():
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
    path = os.path.join(CACHE_DIR, "cv_big_roi.png")
    img.save(path)
    return img, bbox, (x, y), path

@dataclass
class Candidate:
    box: Tuple[int,int,int,int]  # x1,y1,x2,y2 (coords del ROI)
    area: float
    aspect: float
    score: float

def find_tooltip_rect(roi_img: Image.Image, mouse_abs, bbox_abs) -> Optional[Candidate]:
    """
    Detecta el rectángulo del tooltip con:
      - Canny + contornos para proponer candidatos
      - Filtro por OCR: el candidato debe contener texto suficiente y, de ser posible, anclas (Epic/Heroic… y/o Trait)
    Se descartan candidatos a la derecha del mouse.
    """
    import pytesseract, re

    img = np.array(roi_img.convert("RGB"))
    h, w = img.shape[:2]
    area_img = w * h

    # límite: solo a la IZQUIERDA del mouse (coords del ROI)
    mouse_x_rel = mouse_abs[0] - bbox_abs[0]
    max_x_allowed = mouse_x_rel - 6

    # --- 1) Bordes + contornos (propuestas) ---
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    gray = cv2.medianBlur(gray, 3)
    med = np.median(gray)
    lower = int(max(0, 0.66 * med))
    upper = int(min(255, 1.33 * med))
    edges = cv2.Canny(gray, lower, upper)
    edges = cv2.dilate(edges, np.ones((3,3), np.uint8), iterations=1)

    cnts, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    # --- 2) Evaluar candidatos con OCR ---
    RARITY = re.compile(r"(?i)\b(epic|heroic|legendary|rare|common)\b")
    TRAIT  = re.compile(r"(?i)\btrait\b")

    best: Optional[Candidate] = None
    cand_list = []  # para volcar top-3 a disco

    def score_candidate(x, y, cw, ch) -> Optional[Candidate]:
        x2, y2 = x + cw, y + ch

        # completamente a la izquierda del mouse
        if x2 > max_x_allowed:
            return None

        # área razonable
        r = (cw * ch) / (area_img + 1e-6)
        if r < MIN_AREA_RATIO or r > MAX_AREA_RATIO:
            return None

        # aspecto típico
        aspect = cw / (ch + 1e-6)
        if not (PREF_ASPECT_MIN <= aspect <= PREF_ASPECT_MAX):
            aspect_penalty = 0.6
        else:
            aspect_penalty = 1.0

        # OCR dentro del rectángulo (upsample para mejor lectura)
        crop = roi_img.crop((x, y, x2, y2))
        nw, nh = int(crop.width * 1.5), int(crop.height * 1.5)
        crop_up = crop.resize((nw, nh), Image.BICUBIC)

        data = pytesseract.image_to_data(
            crop_up, lang="eng", config="--psm 6", output_type=pytesseract.Output.DICT
        )

        words = [(data["text"][i] or "").strip() for i in range(len(data["text"])) if (data["text"][i] or "").strip()]
        text  = " ".join(words)

        has_rarity = bool(RARITY.search(text))
        has_trait  = bool(TRAIT.search(text))
        word_count = len(words)

        # si hay poco texto, penaliza (pero no descartes)
        text_penalty = 1.0 if word_count >= 6 else 0.6

        # anclas (si no hay, el score será menor pero no cero)
        anchors_score = 0.0
        if has_rarity: anchors_score += 0.6
        if has_trait:  anchors_score += 0.6

        # cercanía al borde derecho (más cerca del mouse = mejor)
        dist_x = abs(x2 - max_x_allowed)
        proximity = 1.0 / (1.0 + dist_x / 120.0)

        score = text_penalty * ((0.45 * anchors_score) + (0.30 * proximity) + (0.25 * aspect_penalty))
        return Candidate(box=(x, y, x2, y2), area=cw*ch, aspect=aspect, score=score)

    for c in cnts:
        x, y, cw, ch = cv2.boundingRect(c)
        cand = score_candidate(x, y, cw, ch)
        if cand:
            cand_list.append((cand.score, cand.box))
            if (best is None) or (cand.score > best.score):
                best = cand

    # Guardar top-3 candidatos para inspección
    cand_list.sort(reverse=True, key=lambda t: t[0])
    for i, (sc, box) in enumerate(cand_list[:3], start=1):
        x1,y1,x2,y2 = box
        crop = roi_img.crop((x1,y1,x2,y2))
        outp = os.path.join(CACHE_DIR, f"cv_cand_{i}.png")
        crop.save(outp)

    return best

def save_debug(roi_img: Image.Image, candidate: Optional[Candidate]):
    dbg = np.array(roi_img.convert("RGB")).copy()
    if candidate:
        x1, y1, x2, y2 = candidate.box
        cv2.rectangle(dbg, (x1,y1), (x2,y2), (0,255,0), 2)
    out = os.path.join(CACHE_DIR, "cv_big_roi_debug.png")
    Image.fromarray(dbg).save(out)
    return out

def run_once():
    big_img, bbox, mouse_abs, big_path = grab_big_roi()
    print(f"[+] ROI grande guardado: {big_path}  bbox={bbox}")

    cand = find_tooltip_rect(big_img, mouse_abs, bbox)
    dbg_path = save_debug(big_img, cand)
    print(f"[+] Debug contornos: {dbg_path}")

    if not cand:
        print("[-] No se detectó un rectángulo de tooltip (ajusta heurísticas).")
        return

    x1,y1,x2,y2 = cand.box
    tip = big_img.crop((x1,y1,x2,y2))
    out = os.path.join(CACHE_DIR, "cv_tooltip_crop.png")
    tip.save(out)
    print(f"[✓] Tooltip recortado: {out}  (score={cand.score:.2f}, aspect={cand.aspect:.2f})")

def main():
    print("F12 = detectar y recortar tooltip | Ctrl+F12 = salir")
    while True:
        if keyboard.is_pressed("f12"):
            run_once()
            time.sleep(0.5)
        if keyboard.is_pressed("ctrl+f12"):
            print("Saliendo…"); break
        time.sleep(0.05)

if __name__ == "__main__":
    main()