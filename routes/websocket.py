"""
WebSocket routes for OpenAI Realtime API integration.
"""

import os
import json
import logging
import asyncio
from fastapi import WebSocket, WebSocketDisconnect

from tools import tools
from config.systeme_prompt import agent_system_prompt
from realtime.client import RealtimeClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# OpenAI API configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
VOICE = 'alloy'

async def handle_media_stream(websocket: WebSocket, session_id: str, session: dict):
    """Handle the WebSocket connection for Twilio media streams."""
    await websocket.accept()
    logger.info("Client connected to media-stream")
    
    first_message = ""
    stream_sid = ""
    
    # Retrieve the caller number from the session
    caller_number = session.get("caller_number", "Unknown")
    logger.info(f"Caller Number: {caller_number}")
    
    # Set environment variable for tools to use
    os.environ["CALLER_NUMBER"] = caller_number
    
    # Create and configure the OpenAI Realtime client
    realtime_client = RealtimeClient(
        api_key=OPENAI_API_KEY,
        system_message=agent_system_prompt
    )
    realtime_client.set_voice(VOICE)
    
    # Register event handlers
    async def handle_audio_delta(event):
        if event.get("type") == "response.audio.delta" and event.get("delta"):
            await websocket.send_text(json.dumps({
                "event": "media",
                "streamSid": stream_sid,
                "media": {"payload": event["delta"]}
            }))
    
    async def handle_response_done(event):
        if event.get("type") == "response.done":
            try:
                output_items = event["response"]["output"]
                for item in output_items:
                    for content in item.get("content", []):
                        if content.get("transcript"):
                            agent_message = content["transcript"]
                            session["transcript"] += f"Agent: {agent_message}\n"
                            logger.info(f"Agent ({session_id}): {agent_message}")
            except (KeyError, IndexError) as e:
                logger.error(f"Error extracting agent message: {e}")
    
    async def handle_transcription(event):
        if event.get("type") == "conversation.item.input_audio_transcription.completed" and event.get("transcript"):
            user_message = event["transcript"].strip()
            session["transcript"] += f"User: {user_message}\n"
            logger.info(f"User ({session_id}): {user_message}")
    
    realtime_client.on("response.audio.delta", handle_audio_delta)
    realtime_client.on("response.done", handle_response_done)
    realtime_client.on("conversation.item.input_audio_transcription.completed", handle_transcription)
    
    # Register all tools
    for tool_def, tool_handler in tools:
        await realtime_client.add_tool(tool_def, tool_handler)
    
    try:
        # Connect to OpenAI
        await realtime_client.connect()
        
        # Process WebSocket messages from Twilio
        try:
            while True:
                data_str = await websocket.receive_text()
                data = json.loads(data_str)
                
                if data["event"] == "start":
                    stream_sid = data["start"]["streamSid"]
                    call_sid = data["start"]["callSid"]
                    custom_parameters = data["start"].get("customParameters", {})
                    
                    logger.info(f"CallSid: {call_sid}")
                    logger.info(f"StreamSid: {stream_sid}")
                    logger.info(f"Custom Parameters: {custom_parameters}")
                    
                    # Capture callerNumber and firstMessage from custom parameters
                    caller_number = custom_parameters.get("callerNumber", "Unknown")
                    session["caller_number"] = caller_number
                    first_message = custom_parameters.get("firstMessage", "Hello, how can I assist you?")
                    
                    logger.info(f"First Message: {first_message}")
                    logger.info(f"Caller Number: {caller_number}")
                    
                    # Send the first message to OpenAI
                    await realtime_client.send_user_message_content([
                        {"type": "input_text", "text": first_message}
                    ])
                    
                elif data["event"] == "media":
                    # Send audio data to OpenAI
                    await realtime_client.append_input_audio(data["media"]["payload"])
                    
        except WebSocketDisconnect:
            logger.info(f"Twilio WebSocket disconnected")
        except Exception as e:
            logger.error(f"Error processing Twilio messages: {e}")
            
    finally:
        # Disconnect from OpenAI
        await realtime_client.disconnect()