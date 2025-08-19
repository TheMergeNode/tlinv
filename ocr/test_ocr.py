import sys
from parse_tooltip import parse_tooltip

def main():
    if len(sys.argv) < 2:
        print("Uso: python ocr\\test_ocr.py <ruta_a_tooltip.png>")
        return

    img_path = sys.argv[1]
    result = parse_tooltip(img_path, lang="eng")

    print("=== OCR RESULT ===")
    print("Item Name:", result["item_name"])
    print("Trait    :", result["trait"])
    # Para ver el texto crudo reconocido, descomenta la siguiente línea:
    # print("\n--- RAW TEXT ---\n", result["raw"])

if __name__ == "__main__":
    main()