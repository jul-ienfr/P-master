import os
import sys
import time
import argparse
from pathlib import Path
import cv2

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.vision.capture import ScreenCapture

try:
    import win32gui
    WIN32_AVAILABLE = True
except ImportError:
    WIN32_AVAILABLE = False


def get_poker_window():
    if not WIN32_AVAILABLE:
        return None
        
    keywords = ["NLHE", "Hold'em No Limit", "Connecté en tant que", "PokerStars", "Winamax"]
    ignore_words = ["lobby"]
    
    found_hwnd = None
    
    def callback(hwnd, extra):
        nonlocal found_hwnd
        if found_hwnd:  # Si on a déjà trouvé, on passe
            return
            
        if not win32gui.IsWindowVisible(hwnd): 
            return
            
        title = win32gui.GetWindowText(hwnd)
        if not title: 
            return
            
        title_lower = title.lower()
        
        # Ignorer les lobby et menus
        if any(w in title_lower for w in ignore_words):
            return
            
        for k in keywords:
            if k.lower() in title_lower:
                found_hwnd = hwnd
                return

    win32gui.EnumWindows(callback, None)
    return found_hwnd

def extract_table_info_from_title(title: str):
    import re
    title_lower = title.lower()
    
    # 1. Site
    site = "UnknownSite"
    if "pokerstars" in title_lower: site = "PokerStars"
    elif "winamax" in title_lower: site = "Winamax"
    elif "partypoker" in title_lower: site = "PartyPoker"
    
    # 2. Variante
    variant = "UnknownVariant"
    if "nlhe" in title_lower or "hold'em" in title_lower or "holdem" in title_lower: variant = "NLHE"
    elif "plo" in title_lower or "omaha" in title_lower: variant = "PLO"
    
    # 3. Format
    format_table = "UnknownFormat"
    if "6 max" in title_lower or "6-max" in title_lower or "6max" in title_lower: format_table = "6Max"
    elif "9 max" in title_lower or "9-max" in title_lower or "9max" in title_lower: format_table = "9Max"
    elif "heads-up" in title_lower or "heads up" in title_lower or " hu " in title_lower: format_table = "HeadsUp"
    elif "8 max" in title_lower or "8-max" in title_lower: format_table = "8Max"
    
    return site, variant, format_table

def main():
    parser = argparse.ArgumentParser(description="Capture automatique des tables de Poker pour creer un Dataset YOLO")
    parser.add_argument("--interval", type=float, default=5.0, help="Intervalle en secondes")
    parser.add_argument("--max-images", type=int, default=100, help="Nombre max")
    args = parser.parse_args()

    hwnd = get_poker_window()
    if not hwnd:
        print("\n❌ Table de Poker introuvable. Assurez-vous d'avoir ouvert la fenêtre du jeu cible.")
        return
        
    window_title = win32gui.GetWindowText(hwnd)
    site, variant, format_table = extract_table_info_from_title(window_title)
    
    print("\n" + "="*60)
    print("  📸 DETECTION AUTOMATIQUE DE LA TABLE")
    print("="*60)
    print(f"🌍 Site détecté   : {site}")
    print(f"🃏 Variante       : {variant}")
    print(f"🪑 Format         : {format_table}")
    print(f"Titre source      : '{window_title}'\n")
        
    rect = win32gui.GetWindowRect(hwnd)
    
    cap = ScreenCapture(target_fps=2)
    started = cap.start(region=rect, hwnd=hwnd)
    if not started:
        print("\n❌ Echec du demarrage de la capture DXcam/PIL.")
        return
    
    # 📂 Creation hierarchique du dossier de Dataset
    dataset_name = f"{site}_{variant}_{format_table}"
    out_dir = ROOT / "dataset" / dataset_name / "images"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    count = 0
    print(f"\n📸 Démarrage de la capture automatique.")
    print(f"Intervalle: {args.interval}s | Cible: {args.max_images} images.")
    print(f"Dossier de destination : {out_dir}")
    print("Appuyez sur Ctrl+C dans le terminal pour arreter plus tot.\n")
    
    try:
        while count < args.max_images:
            # Attend le temps demandé
            time.sleep(args.interval)
            
            # Essaye d'obtenir une image récente
            frame = cap.get_latest_frame()
            if frame is not None:
                filename = f"table_{int(time.time())}.jpg"
                filepath = out_dir / filename
                cv2.imwrite(str(filepath), frame)
                count += 1
                print(f"[{count}/{args.max_images}] Capture sauvegardée : {filename}")
            else:
                print("⏳ En attente de fenêtre visible...")
                
    except KeyboardInterrupt:
        print("\n⏹️ Capture interrompue par l'utilisateur.")
    finally:
        cap.stop()
        print(f"✅ Terminé. {count} images récoltées dans {out_dir}")
        print("-> Prochaine étape : Utiliser src/vision/auto_annotator.py pour annoter ces images.")

if __name__ == "__main__":
    main()
