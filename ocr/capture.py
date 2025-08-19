import os
import time
import csv
from datetime import datetime
import keyboard
from PIL import ImageGrab  # viene con Pillow
import pyautogui
import threading
import json
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ocr.parse_tooltip import parse_tooltip  # importar nuestro OCR

# --- Rutas ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE_DIR)              # carpeta tlinv
SNAPS_DIR = os.path.join(ROOT, "data", "snaps")
INV_CSV = os.path.join(ROOT, "data", "inventory.csv")
CONFIG_PATH = os.path.join(ROOT, "config.json")

def load_config():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"language": "eng"}

os.makedirs(SNAPS_DIR, exist_ok=True)

def timestamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S")

def now_iso():
    return datetime.now().isoformat(timespec="seconds")

def screenshot_full(prefix: str) -> str:
    """Captura de pantalla completa (luego recortaremos si hace falta)."""
    path = os.path.join(SNAPS_DIR, f"{prefix}_{timestamp()}.png")
    img = ImageGrab.grab()
    img.save(path)
    return path

def append_inventory_row(tooltip_img_path: str):
    """Agrega una fila al inventario usando OCR para item_name y trait."""
    cfg = load_config()
    lang = cfg.get("language", "eng")

    # Asegurar cabecera si no existe
    if not os.path.exists(INV_CSV):
        with open(INV_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["item_name", "trait", "qty", "slot_img", "tooltip_img", "last_seen"])

    # OCR básico (sin ROI por ahora)
    ocr = parse_tooltip(tooltip_img_path, lang=lang)
    item_name = ocr.get("item_name") or ""
    trait = ocr.get("trait") or ""

    row = [item_name, trait, 1, "", tooltip_img_path, now_iso()]
    with open(INV_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(row)

def main():
    print("[F12] Capturar TOOLTIP (agrega fila al inventario)")
    print("[Ctrl+F12] Salir")
    print("Nota: si las teclas no responden, ejecuta PowerShell como Administrador o pon el juego en modo ventana.")

    stop_event = threading.Event()

    def on_tooltip():
        path = screenshot_full("tooltip")
        append_inventory_row(path)
        print(f"Tooltip capturado y agregado a inventario: {path}")

    def on_exit():
        print("Saliendo...")
        stop_event.set()

    keyboard.add_hotkey('f12', on_tooltip)
    keyboard.add_hotkey('ctrl+f12', on_exit)

    # Espera hasta que presiones Ctrl+F12
    while not stop_event.is_set():
        time.sleep(0.1)

if __name__ == "__main__":
    main()
