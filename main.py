import logging
import sys
from src.main import run_bot


logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("MainLoop")


def main() -> None:
    logger.info("Le launcher racine delegue maintenant au runtime V2 src/main.py")
    run_bot()


if __name__ == "__main__":
    main()
