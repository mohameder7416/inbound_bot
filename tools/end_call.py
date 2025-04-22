import logging
from typing import Dict, Any
import asyncio

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Import the global END_CALL variable
from realtime import globals

# Define the tool definition
end_call_def = {
    "name": "end_call",
    "description": "End the call, use this function when you detect you should end the call: if the customer says any GOODBYE PHRASES, or if it keeps silent for long time",
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}

async def end_call_handler() -> Dict[str, Any]:
    """
    Ends the OpenAI realtime connection by setting the global END_CALL flag to True after a 5-second delay.
    
    Returns:
        Dictionary with status of the operation
    """
    try:
        logger.info("🔄 Preparing to end the call in 5 seconds...")
        
        # Wait for 5 seconds before ending the call
        await asyncio.sleep(4)
        
        # Set the global END_CALL flag to True
        globals.END_CALL = True
        
        logger.info("✅ END_CALL flag set to True, connection will be ended")
        return {
            "status": "success",
            "message": "END_CALL flag set to True after 5-second delay, connection will be ended"
        }
        
    except Exception as e:
        logger.error(f"❌ Error setting END_CALL flag: {str(e)}")
        return {
            "status": "error",
            "message": f"Failed to set END_CALL flag: {str(e)}"
        }

# Export the tool
end_call_tool = (end_call_def, end_call_handler)