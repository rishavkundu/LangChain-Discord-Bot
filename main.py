# main.py
import os
import sys

# Add the project root directory to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.bot import run_bot

def main():
    try:
        run_bot()
    except Exception as e:
        print(f"Error running bot: {e}")
        raise

if __name__ == "__main__":
    main()