import asyncio
import cv2
import json
import logging
from src.vision.auto_annotator import AutoAnnotator

logging.basicConfig(level=logging.INFO)

async def test():
    with open('config.json', 'r', encoding='utf-8') as f:
        config = json.load(f)
        
    providers = config.get('auto_annotator', {}).get('providers', [])
    annotator = AutoAnnotator(providers=providers)
    
    img_path = r'dataset\PokerStars_NLHE_6Max\images\0229ecfa-9b2c-4993-a31f-7e43efd6f2f3.png'
    frame = cv2.imread(img_path)
    if frame is None:
        print('Erreur: impossible de charger image', img_path)
        return
        
    h, w = frame.shape[:2]
    
    import time
    start = time.perf_counter()
    print('Testing ask_ai_with_fallbacks API on real poker frame...')
    boxes = annotator.ask_ai_with_fallbacks('', w, h, frame=frame)
    end = time.perf_counter()
    
    print(f'\nTEMPS DE REPONSE: {end - start:.2f} secondes')
    
    print('\nRESULTAT DU LLM (Parsé):')
    if boxes:
        for b in boxes:
            print('Card:', b.get('class', 'N/A'), '| Coords:', round(b.get('xmin', 0), 3), round(b.get('ymin', 0), 3))
    else:
        print('Le LLM na rien trouve ou a echoue.')

if __name__ == '__main__':
    asyncio.run(test())
