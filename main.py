# main.py
import asyncio
from bot import run_bot

def main():
    try:
        run_bot()
    except Exception as e:
        print(f"Error running bot: {e}")
        raise

if __name__ == "__main__":
    main()