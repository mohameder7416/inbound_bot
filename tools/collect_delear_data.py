import json
import os
import logging
import asyncio
from typing import Dict, Any
from datetime import datetime

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Define the data collection tool definition
collect_dealers_data_def = {
    "name": "collect_dealers_data",
    "description": "Collect dealer information and save it to a JSON file , call this function when you detect all the dealer information",
    "parameters": {
        "type": "object",
        "properties": {
            "first_name": {"type": "string"},
            "last_name": {"type": "string"},
            "dealer_id": {"type": "string"},
            "dealership_name": {"type": "string"},
            "phone_number": {"type": "string"}
        },
        "required": ["first_name", "last_name", "dealer_id", "dealership_name", "phone_number"],
    },
}

async def collect_dealers_data_handler(
    first_name: str,
    last_name: str,
    dealer_id: str,
    dealership_name: str,
    phone_number: str
) -> Dict[str, Any]:
    """
    Collects dealer information and saves it to a JSON file, overriding any existing data.
    
    Args:
        first_name: Dealer's first name
        last_name: Dealer's last name
        dealer_id: Dealer ID
        dealership_name: Name of the dealership
        phone_number: Contact phone number
        
    Returns:
        Dictionary with status of the operation
    """
    try:
        logger.info(f"🔄 Collecting dealer data for {first_name} {last_name} from {dealership_name}")
        
        # Validate input data
        if not all([first_name, last_name, dealer_id, dealership_name, phone_number]):
            logger.error("❌ Missing required dealer information")
            return {
                "status": "error",
                "message": "All fields are required"
            }
        
        # Create data directory if it doesn't exist
        data_dir = "data"
        if not os.path.exists(data_dir):
            os.makedirs(data_dir)
            logger.info(f"✅ Created data directory: {data_dir}")
        
        # Prepare dealer data with timestamp
        now = datetime.now()
        dealer_data = {
            "first_name": first_name,
            "last_name": last_name,
            "dealer_id": dealer_id,
            "dealership_name": dealership_name,
            "phone_number": phone_number,
            "timestamp": now.strftime("%Y-%m-%d %H:%M:%S")
        }
        
        # Path to the JSON file
        json_file_path = os.path.join(data_dir, "data.json")
        
        # Save only this dealer data to JSON file, overriding any existing data
        with open(json_file_path, 'w') as file:
            json.dump(dealer_data, file, indent=4)
        
        logger.info(f"✅ Dealer data saved successfully to {json_file_path}")
        return {
            "status": "success",
            "message": f"Dealer data for {first_name} {last_name} saved successfully",
            "file_path": json_file_path
        }
        
    except Exception as e:
        logger.error(f"❌ Error saving dealer data: {str(e)}")
        return {
            "status": "error",
            "message": f"Failed to save dealer data: {str(e)}"
        }
collect_dealers_data_tool = (collect_dealers_data_def, collect_dealers_data_handler)    