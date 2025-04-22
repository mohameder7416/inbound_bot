import logging
import smtplib
import os
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, Any
from dotenv import load_dotenv
import asyncio
import openai

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Set OpenAI API key
openai.api_key = os.getenv("OPENAI_API_KEY")

# Email configuration
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECIPIENT = os.getenv("EMAIL_RECIPIENT", "dev-team@example.com")
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))

# Issue categories
ISSUE_CATEGORIES = {
    "FBMP": "Facebook Marketplace",
    "INV": "Inventory",
    "Website": "Website",
    "Sales Docs": "Sales Docs",
    "CL": "Craigslist",
    "DA": "Digital Ads",
    "CRM": "CRM",
    "SMM": "SMM",
    "LD": "Local Dominance",
    "SA": "Social Automation"
}

# Function to load dealer data from JSON
def load_dealer_data(dealer_id: str) -> Dict[str, Any]:
    """
    Load dealer information from data/data.json file based on dealer_id.
    
    Args:
        dealer_id: ID of the dealer to look up
        
    Returns:
        Dictionary containing dealer information or empty dict if not found
    """
    try:
        with open("data/data.json", "r") as file:
            data = json.load(file)
            
        # Find dealer with matching ID
        for dealer in data:
            if dealer.get("dealer_id") == dealer_id:
                return dealer
                
        logger.warning(f"⚠️ Dealer with ID {dealer_id} not found in data.json")
        return {}
        
    except FileNotFoundError:
        logger.error("❌ data/data.json file not found")
        return {}
    except json.JSONDecodeError:
        logger.error("❌ Invalid JSON format in data/data.json")
        return {}
    except Exception as e:
        logger.error(f"❌ Error loading dealer data: {str(e)}")
        return {}

# Define the tool definition
send_support_email_def = {
    "name": "send_support_email",
    "description": "Send a support ticket email to the dev team with details about customer issues call this function when you detect the customer has an issue",
    "parameters": {
        "type": "object",
        "properties": {
            "dealer_id": {
                "type": "string",
                "description": "ID of the dealer reporting the issue"
            },
            "issue_category": {
                "type": "string",
                "description": "Category code of the issue (e.g., FBMP, INV, Website)"
            },
            "issue_description": {
                "type": "string",
                "description": "Detailed description of the issue"
            }
        },
        "required": ["dealer_id", "issue_category", "issue_description"]
    },
}

def call_openai_llm(system_prompt, user_prompt, model="gpt-4"):
    """
    Calls OpenAI's chat completion API with a system and user prompt.
    """
    try:
        response = openai.ChatCompletion.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
        )
        return response.choices[0].message['content'].strip()
    except Exception as e:
        logger.error(f"❌ Error calling OpenAI API: {e}")
        return f"Error: {e}"

def generate_email_content(dealer_info: Dict[str, Any], issue_data: Dict[str, Any]) -> str:
    """
    Generate email content based on dealer info and issue data using OpenAI.
    """
    # Get full category name
    category_code = issue_data.get("issue_category", "")
    category_name = ISSUE_CATEGORIES.get(category_code, category_code)
    
    system_prompt = """
    You are an assistant who creates formal support ticket emails. 
    Create a concise, professional email that summarizes the issue to the development team.
    The email should be signed from "Cindy AI".
    """
    
    user_prompt = f"""
    Create a support ticket email with these details:
    - Dealership Name: {dealer_info.get('dealership_name')}
    - Phone Number: {dealer_info.get('phone_number')}
    - Customer ID: {dealer_info.get('dealer_id')}
    - Issue Category: {category_name}
    - Issue Description: {issue_data.get('issue_description')}
    
    The email should request that the issue be addressed within 24 to 48 hours.
    """
    
    # If OpenAI API fails, use a fallback template
    try:
        email_content = call_openai_llm(system_prompt, user_prompt)
        if email_content.startswith("Error:"):
            raise Exception(email_content)
        return email_content
    except Exception as e:
        logger.warning(f"⚠️ Using fallback email template due to API error: {e}")
        
        # Fallback template
        return f"""Hello Dev Team,

A new support ticket has been created for an issue with the {category_name} App.

Here are the details:
- Dealership Name: {dealer_info.get('dealership_name')}
- Phone Number: {dealer_info.get('phone_number')}
- Customer ID: {dealer_info.get('dealer_id')}
- Issue Description: {issue_data.get('issue_description')}

Please address this issue within 24 to 48 hours.

Best regards,
Cindy AI
"""

async def send_support_email_handler(
    dealer_id: str,
    issue_category: str,
    issue_description: str
) -> Dict[str, Any]:
    """
    Sends a support ticket email to the dev team with the provided issue details.
    Loads dealer information from data/data.json file.
    
    Args:
        dealer_id: ID of the dealer reporting the issue
        issue_category: Category code of the issue (e.g., FBMP, INV, Website)
        issue_description: Detailed description of the issue
        
    Returns:
        Dictionary with status of the operation
    """
    try:
        logger.info(f"🔄 Processing support ticket for dealer ID: {dealer_id}")
        
        # Load dealer information from data.json
        dealer_info = load_dealer_data(dealer_id)
        
        if not dealer_info:
            return {
                "status": "error",
                "message": f"Dealer with ID {dealer_id} not found in data.json"
            }
        
        dealership_name = dealer_info.get('dealership_name', 'Unknown Dealership')
        logger.info(f"🔄 Preparing to send support email for {dealership_name}...")
        
        # Prepare issue data
        issue_data = {
            "issue_category": issue_category,
            "issue_description": issue_description
        }
        
        # Generate email content
        email_content = generate_email_content(dealer_info, issue_data)
        
        # Create subject line
        category_name = ISSUE_CATEGORIES.get(issue_category, issue_category)
        subject = f"Support Ticket: {category_name} Issue - {dealership_name}"
        
        # Simulate a short delay for processing
        await asyncio.sleep(1)
        
        # Send email
        if not all([EMAIL_SENDER, EMAIL_PASSWORD, SMTP_SERVER, SMTP_PORT]):
            logger.error("❌ Email configuration missing in environment variables")
            return {
                "status": "error",
                "message": "Email configuration missing in environment variables"
            }
        
        try:
            # Create message
            msg = MIMEMultipart()
            msg['From'] = EMAIL_SENDER
            msg['To'] = EMAIL_RECIPIENT
            msg['Subject'] = subject
            
            # Attach body
            msg.attach(MIMEText(email_content, 'plain'))
            
            # Connect to SMTP server
            with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
                server.starttls()
                server.login(EMAIL_SENDER, EMAIL_PASSWORD)
                server.send_message(msg)
                
            logger.info(f"✅ Support ticket email sent successfully for {dealership_name}")
            return {
                "status": "success",
                "message": f"Support ticket email sent for {dealership_name}",
                "email_subject": subject,
                "recipient": EMAIL_RECIPIENT
            }
        
        except Exception as e:
            logger.error(f"❌ Failed to send email: {e}")
            return {
                "status": "error",
                "message": f"Failed to send email: {str(e)}"
            }
            
    except Exception as e:
        logger.error(f"❌ Error processing support ticket email: {str(e)}")
        return {
            "status": "error",
            "message": f"Failed to process support ticket: {str(e)}"
        }

# Export the tool
send_support_email_tool = (send_support_email_def, send_support_email_handler)

