"""
FastAPI application for Twilio integration with OpenAI Realtime API.
"""

import os
import json
import logging
import asyncio
from fastapi import FastAPI, WebSocket, Request, WebSocketDisconnect
from fastapi.responses import JSONResponse, XMLResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, Any
from uuid import uuid4

# Import your existing modules
from tools import tools
from config.systeme_prompt import agent_system_prompt
from realtime.client import RealtimeClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(title="Twilio OpenAI Realtime API")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# OpenAI API configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
VOICE = os.getenv("OPENAI_VOICE", "alloy")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")

# Session storage
sessions: Dict[str, Dict[str, Any]] = {}

@app.get("/")
async def root():
    """Root endpoint to check if the server is running."""
    return {"status": "success", "message": "Twilio OpenAI Realtime API is running!"}

@app.post("/incoming-call")
async def incoming_call(request: Request):
    """Handle incoming Twilio voice calls."""
    form_data = await request.form()
    
    # Extract call information
    call_sid = form_data.get("CallSid", "unknown")
    caller_number = form_data.get("From", "unknown")
    
    # Create a new session
    session_id = call_sid
    sessions[session_id] = {
        "caller_number": caller_number,
        "transcript": "",
        "stream_sid": None
    }
    
    logger.info(f"Incoming call from {caller_number} with SID {call_sid}")
    
    # Generate TwiML response to establish WebSocket connection
    host = request.headers.get("host", "localhost")
    greeting = "Hello, thank you for calling. How can I help you today?"
    
    twiml = f"""
    <?xml version="1.0" encoding="UTF-8"?>
    <Response>
        <Say>{greeting}</Say>
        <Connect>
            <Stream url="wss://{host}/media-stream">
                <Parameter name="callerNumber" value="{caller_number}" />
                <Parameter name="callSid" value="{call_sid}" />
                <Parameter name="firstMessage" value="{greeting}" />
            </Stream>
        </Connect>
    </Response>
    """
    
    return XMLResponse(content=twiml)

@app.websocket("/media-stream")
async def media_stream(websocket: WebSocket):
    """Handle WebSocket connection for Twilio media streams."""
    await websocket.accept()
    logger.info("Client connected to media-stream")
    
    session_id = "session_" + str(uuid4())
    stream_sid = ""
    
    # Initialize session if not exists
    if session_id not in sessions:
        sessions[session_id] = {
            "caller_number": "Unknown",
            "transcript": "",
            "stream_sid": None
        }
    
    session = sessions[session_id]
    
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
                    
                    # Update session ID to match call SID
                    if call_sid:
                        new_session_id = call_sid
                        if new_session_id != session_id:
                            sessions[new_session_id] = session
                            session_id = new_session_id
                    
                    logger.info(f"CallSid: {call_sid}")
                    logger.info(f"StreamSid: {stream_sid}")
                    logger.info(f"Custom Parameters: {custom_parameters}")
                    
                    # Capture callerNumber and firstMessage from custom parameters
                    caller_number = custom_parameters.get("callerNumber", "Unknown")
                    session["caller_number"] = caller_number
                    first_message = custom_parameters.get("firstMessage", "Hello, how can I assist you?")
                    session["stream_sid"] = stream_sid
                    
                    # Set environment variable for tools to use
                    os.environ["CALLER_NUMBER"] = caller_number
                    
                    logger.info(f"First Message: {first_message}")
                    logger.info(f"Caller Number: {caller_number}")
                    
                    # Send the first message to OpenAI
                    await realtime_client.send_user_message_content([
                        {"type": "input_text", "text": first_message}
                    ])
                    
                elif data["event"] == "media":
                    # Send audio data to OpenAI
                    await realtime_client.append_input_audio(data["media"]["payload"])
                    
                elif data["event"] == "stop":
                    logger.info(f"Media stream stopped for {stream_sid}")
                    break
                
        except WebSocketDisconnect:
            logger.info(f"Twilio WebSocket disconnected for session {session_id}")
        except Exception as e:
            logger.error(f"Error processing Twilio messages: {e}")
            logger.error(traceback.format_exc())
            
    finally:
        # Disconnect from OpenAI
        await realtime_client.disconnect()
        
        # Process transcript and send to webhook if configured
        if WEBHOOK_URL and session_id in sessions:
            await process_transcript_and_send(session_id)
        
        logger.info(f"Session {session_id} complete. Full transcript:\n{session['transcript']}")

async def process_transcript_and_send(session_id: str):
    """Process the transcript and send to webhook."""
    if not WEBHOOK_URL:
        return
    
    if session_id not in sessions:
        logger.warning(f"Session {session_id} not found")
        return
    
    session = sessions[session_id]
    transcript = session["transcript"]
    caller_number = session["caller_number"]
    
    try:
        # Use OpenAI to extract structured data from transcript
        # (You would implement this part based on your needs)
        extracted_data = {
            "sessionId": session_id,
            "callerNumber": caller_number,
            "transcript": transcript,
            # Add more structured data as needed
        }
        
        # Send to webhook
        import aiohttp
        async with aiohttp.ClientSession() as http_session:
            async with http_session.post(
                WEBHOOK_URL,
                json=extracted_data,
                headers={"Content-Type": "application/json"}
            ) as response:
                if response.status == 200:
                    logger.info(f"Successfully sent data to webhook for session {session_id}")
                else:
                    logger.error(f"Failed to send data to webhook: {response.status}")
                    
    except Exception as e:
        logger.error(f"Error processing transcript for webhook: {e}")
        logger.error(traceback.format_exc())

@app.post("/status-callback")
async def status_callback(request: Request):
    """Handle Twilio status callbacks."""
    form_data = await request.form()
    call_sid = form_data.get("CallSid")
    call_status = form_data.get("CallStatus")
    
    logger.info(f"Call {call_sid} status: {call_status}")
    
    if call_status == "completed" and call_sid in sessions:
        # Process the completed call if needed
        logger.info(f"Call {call_sid} completed")
    
    return JSONResponse({"status": "success"})

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)