"""
Main script for testing Chainlit with OpenAI Realtime API.
"""

import os
import asyncio
import logging
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

def main():
    """Main function to run the Chainlit application."""
    try:
        # Check if OpenAI API key is set
        if not os.getenv("OPENAI_API_KEY"):
            logger.error("OPENAI_API_KEY environment variable is not set")
            return
        
        # Run the Chainlit application
        os.system("chainlit run chainlit_app.py")
    except Exception as e:
        logger.error(f"Error running Chainlit application: {e}")

if __name__ == "__main__":
    main()