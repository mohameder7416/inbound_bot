"""
Chainlit application for OpenAI Realtime API integration.
"""

import os
import asyncio
import traceback
import chainlit as cl
from uuid import uuid4
from chainlit.logger import logger
from dotenv import load_dotenv

from realtime.client import RealtimeClient
from realtime.utils import get_realtime_instructions
from config.systeme_prompt import agent_system_prompt
from tools import tools

# Load environment variables
load_dotenv()

# Global variable to track client connection status
client_connected = False

async def setup_openai_realtime():
    """Instantiate and configure the OpenAI Realtime Client"""
    global client_connected
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.error("OPENAI_API_KEY not found in environment variables")
        return None

    openai_realtime = RealtimeClient(
        api_key=api_key,
        system_message=agent_system_prompt
    )
    cl.user_session.set("track_id", str(uuid4()))

    async def handle_conversation_updated(event):
        """Currently used to stream audio back to the client."""
        delta = event.get("delta")
        if delta:
            if "audio" in delta:
                audio = delta["audio"]
                await cl.context.emitter.send_audio_chunk(
                    cl.OutputAudioChunk(
                        mimeType="pcm16",
                        data=audio,
                        track=cl.user_session.get("track_id"),
                    )
                )
            
    async def handle_item_completed(item):
        # Don't log the full item details
        logger.info("Item completed")

    async def handle_conversation_interrupt(event):
        cl.user_session.set("track_id", str(uuid4()))
        await cl.context.emitter.send_audio_interrupt()

    async def handle_error(event):
        # Don't log the full error details if it contains transcript data
        if isinstance(event, dict) and "transcript" in str(event):
            logger.error("OpenAI Realtime error occurred (transcript details omitted)")
        else:
            logger.error("OpenAI Realtime error occurred")

    openai_realtime.on("conversation.updated", handle_conversation_updated)
    openai_realtime.on("conversation.item.completed", handle_item_completed)
    openai_realtime.on("conversation.interrupted", handle_conversation_interrupt)
    openai_realtime.on("error", handle_error)

    # Register all tools
    try:
        coros = [
            openai_realtime.add_tool(tool_def, tool_handler)
            for tool_def, tool_handler in tools
        ]
        await asyncio.gather(*coros)
    except Exception as e:
        logger.error(f"Error registering tools: {str(e)}")
        return None

    return openai_realtime

@cl.on_chat_start
async def start():
    await cl.Message(content="Hello! I'm here. Press `P` to talk!").send()
    # We no longer initialize the client here
    # Instead, we'll initialize it when the user actually starts audio
    cl.user_session.set("openai_realtime", None)
    logger.info("Chat session started. OpenAI Realtime client will be initialized when audio starts.")

@cl.on_message
async def on_message(message: cl.Message):
    openai_realtime: RealtimeClient = cl.user_session.get("openai_realtime")
    if openai_realtime and client_connected:
        await openai_realtime.send_user_message_content(
            [{"type": "input_text", "text": message.content}]
        )
    else:
        await cl.Message(
            content="Please activate voice mode before sending messages!"
        ).send()

@cl.on_audio_start
async def on_audio_start():
    global client_connected
    
    # Get the current client if it exists
    openai_realtime: RealtimeClient = cl.user_session.get("openai_realtime")
    
    # If client doesn't exist yet, create it
    if not openai_realtime:
        logger.info("Initializing OpenAI Realtime client on first audio input")
        openai_realtime = await setup_openai_realtime()
        if not openai_realtime:
            await cl.ErrorMessage(
                content="Failed to initialize OpenAI Realtime client"
            ).send()
            return False
        cl.user_session.set("openai_realtime", openai_realtime)
    
    # Connect the client if it's not already connected
    if not client_connected:
        try:
            await openai_realtime.connect()
            client_connected = True
            logger.info("Connected to OpenAI realtime")
        except Exception as e:
            logger.error(f"Failed to connect to OpenAI realtime: {str(e)}")
            await cl.ErrorMessage(
                content="Failed to connect to OpenAI realtime"
            ).send()
            return False
    
    return client_connected

@cl.on_audio_chunk
async def on_audio_chunk(chunk: cl.InputAudioChunk):
    global client_connected
    openai_realtime: RealtimeClient = cl.user_session.get("openai_realtime")
    if openai_realtime and client_connected:
        await openai_realtime.append_input_audio(chunk.data)
    else:
        # Don't log the audio chunk details
        logger.debug("Skipping audio chunk: RealtimeClient is not connected or not initialized")

@cl.on_audio_end
@cl.on_chat_end
@cl.on_stop
async def on_end():
    global client_connected
    openai_realtime: RealtimeClient = cl.user_session.get("openai_realtime")
    if openai_realtime:
        if client_connected:
            await openai_realtime.disconnect()
            client_connected = False
        cl.user_session.set("openai_realtime", None)
    logger.info("OpenAI Realtime session ended")