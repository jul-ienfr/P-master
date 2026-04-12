import argparse
import json
from pathlib import Path

import cv2

from src.vision.ocr import PokerOCR


def main() -> int:
    parser = argparse.ArgumentParser(description="Run OCR probe on a local image")
    parser.add_argument("--image", required=True, help="Path to the image file")
    parser.add_argument("--field", choices=["text", "amount"], default="amount")
    parser.add_argument("--engines", default="doctr", help="Comma-separated OCR engines")
    parser.add_argument("--mode", default="consensus_amounts")
    parser.add_argument("--parallel", action="store_true")
    args = parser.parse_args()

    image_path = Path(args.image)
    image = cv2.imread(str(image_path))
    if image is None:
        raise SystemExit(json.dumps({"success": False, "message": f"Unable to read image: {image_path}"}))

    engines = [engine.strip() for engine in args.engines.split(",") if engine.strip()]
    ocr = PokerOCR(enabled_engines=engines, mode=args.mode, parallel=args.parallel)

    if args.field == "text":
        result = ocr.read_text(image)
    else:
        result = ocr.read_and_parse_amount(image)

    payload = {
        "success": True,
        "field": args.field,
        "result": result,
        "metadata": ocr.get_metadata(),
    }
    print(json.dumps(payload, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
