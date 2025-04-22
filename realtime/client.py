# realtime/client.py

import os
import asyncio
import time
import logging
from threading import Timer
from .event_handler import RealtimeEventHandler
from .api import RealtimeAPI
from .conversation import RealtimeConversation
from .utils import get_realtime_instructions, array_buffer_to_base64
from datetime import datetime
import numpy as np
import json
from config.systeme_prompt import agent_system_prompt
# Import the global END_CALL variable
from . import globals



# Configure logger
logger = logging.getLogger(__name__)

class RealtimeClient(RealtimeEventHandler):
    def __init__(self, url=None, api_key=None, system_message=None, silence_timeout=30):
        super().__init__()
        self.default_session_config = {
            "modalities": ["text", "audio"],
            "instructions": agent_system_prompt,
            "voice": 'alloy',
            "input_audio_format": "pcm16",
            "output_audio_format": "pcm16",
            "input_audio_transcription": {"model": "whisper-1"},
            "turn_detection": {"type": "server_vad"},
            "tools": [],
            "tool_choice": "auto",
            "temperature": 0.8,
            "max_response_output_tokens": 4096,
        }
        self.session_config = {}
        self.transcription_models = [{"model": "whisper-1"}]
        self.default_server_vad_config = {
            "type": "server_vad",
            "threshold": 0.5,
            "prefix_padding_ms": 300,
            "silence_duration_ms": 200,
        }
        self.realtime = RealtimeAPI(
            url=url,
            api_key=api_key,
        )
        self.conversation = RealtimeConversation()
        
        # Silence detection attributes
        self.silence_timeout = silence_timeout
        self.silence_timer = None
        self.last_activity_time = time.time()
        self.silence_detection_active = False
        self.timeout_triggered = False
        self.loop = None
        
        # Start a background task to check the END_CALL flag
        self.end_call_check_task = None
        
        self._reset_config()
        self._add_api_event_handlers()
        
        logger.info(f"RealtimeClient initialized with {silence_timeout}s silence timeout")

    def _reset_config(self):
        self.session_created = False
        self.tools = {}
        self.session_config = self.default_session_config.copy()
        self.input_audio_buffer = bytearray()
        return True

    def _add_api_event_handlers(self):
        self.realtime.on("client.*", self._log_event)
        self.realtime.on("server.*", self._log_event)
        self.realtime.on("server.session.created", self._on_session_created)
        self.realtime.on("server.response.created", self._process_event)
        self.realtime.on("server.response.output_item.added", self._process_event)
        self.realtime.on("server.response.content_part.added", self._process_event)
        self.realtime.on("server.input_audio_buffer.speech_started", self._on_speech_started)
        self.realtime.on("server.input_audio_buffer.speech_stopped", self._on_speech_stopped)
        self.realtime.on("server.conversation.item.created", self._on_item_created)
        self.realtime.on("server.conversation.item.truncated", self._process_event)
        self.realtime.on("server.conversation.item.deleted", self._process_event)
        self.realtime.on(
            "server.conversation.item.input_audio_transcription.completed",
            self._process_event,
        )
        self.realtime.on("server.response.audio_transcript.delta", self._process_event)
        self.realtime.on("server.response.audio.delta", self._process_event)
        self.realtime.on("server.response.text.delta", self._process_event)
        self.realtime.on("server.response.function_call_arguments.delta", self._process_event)
        self.realtime.on("server.response.output_item.done", self._on_output_item_done)

    # Add a method to check the END_CALL flag
    async def _check_end_call_flag(self):
        """Background task to check the END_CALL flag and disconnect if it's True."""
        try:
            while self.is_connected():
                # Check if the END_CALL flag is True
                if globals.END_CALL:
                    logger.info("🔄 END_CALL flag detected, ending the call")
                    
                    # Reset the flag
                    globals.END_CALL = False
                    
                    # Disconnect
                    await self._handle_end_call_disconnect()
                    
                    # Exit the loop
                    break
                
                # Sleep for a short time before checking again
                await asyncio.sleep(0.5)
                
        except Exception as e:
            logger.error(f"Error in _check_end_call_flag: {str(e)}", exc_info=True)
    
    async def _handle_end_call_disconnect(self):
        """Handle disconnection when END_CALL flag is True."""
        logger.info("Handling end_call disconnection")
        
        # Stop silence detection
        self._stop_silence_detection()
        
        # Dispatch the event
        self.dispatch("conversation.ended", {
            "reason": "end_call_tool", 
            "timestamp": time.time()
        })
        
        # Disconnect if connected
        if self.is_connected():
            logger.info("Disconnecting due to end_call")
            try:
                # Update session state
                self.session_created = False
                self.conversation.clear()
                
                # Disconnect from OpenAI
                await self.realtime.disconnect()
                logger.info("Disconnected due to end_call")
            except Exception as e:
                logger.error(f"Error disconnecting: {str(e)}", exc_info=True)

    def _log_event(self, event):
        realtime_event = {
            "time": datetime.utcnow().isoformat(),
            "source": "client" if event["type"].startswith("client.") else "server",
            "event": event,
        }
        self.dispatch("realtime.event", realtime_event)
        
        # Reset silence timer on any event
        self._reset_silence_timer()

    def _on_session_created(self, event):
        self.session_created = True
        
        # Start silence detection when session is created
        self._start_silence_detection()
        
        # Start the END_CALL flag checking task
        if self.loop and not self.end_call_check_task:
            self.end_call_check_task = asyncio.create_task(self._check_end_call_flag())
        
        if self.loop :
            asyncio.create_task(self.send_initial_conversation_item())    

    def _process_event(self, event, *args):
        # Reset silence timer on any event
        self._reset_silence_timer()
        
        item, delta = self.conversation.process_event(event, *args)
        if item:
            self.dispatch("conversation.updated", {"item": item, "delta": delta})
        return item, delta

    def _on_speech_started(self, event):
        self._process_event(event)
        self.dispatch("conversation.interrupted", event)
        
        # Reset silence timer when speech starts
        self._reset_silence_timer()

    def _on_speech_stopped(self, event):
        self._process_event(event, self.input_audio_buffer)
        
        # Reset silence timer when speech stops
        self._reset_silence_timer()

    def _on_item_created(self, event):
        item, delta = self._process_event(event)
        self.dispatch("conversation.item.appended", {"item": item})
        if item and item["status"] == "completed":
            self.dispatch("conversation.item.completed", {"item": item})
            
        # Reset silence timer when an item is created
        self._reset_silence_timer()
    
    
    async def send_initial_conversation_item(self):
        """Send initial conversation item to make AI speak first."""
        initial_conversation_item = {
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": "Greet the user with hello and ask how you can help them.",
                    }
                ]
            }
        }
        await self.realtime.send("conversation.item.create", {"item": initial_conversation_item["item"]})
        await self.realtime.send("response.create")
        logger.info("Sent initial greeting to start the conversation")
    
    
    
    
    
    
    
    
    async def _on_output_item_done(self, event):
        item, delta = self._process_event(event)
        if item and item["status"] == "completed":
            self.dispatch("conversation.item.completed", {"item": item})
        if item and item.get("formatted", {}).get("tool"):
            await self._call_tool(item["formatted"]["tool"])
            
        # Reset silence timer when an output item is done
        self._reset_silence_timer()

    # Silence detection methods
    def _start_silence_detection(self):
        """Start the silence detection."""
        if self.silence_detection_active:
            return
            
        # Store the event loop for later use
        try:
            self.loop = asyncio.get_event_loop()
        except RuntimeError:
            logger.warning("No event loop found in _start_silence_detection")
            return
            
        self.silence_detection_active = True
        self.timeout_triggered = False
        self.last_activity_time = time.time()
        self._schedule_silence_timer()
        logger.info(f"Silence detection started with {self.silence_timeout}s timeout")

    def _stop_silence_detection(self):
        """Stop the silence detection."""
        self.silence_detection_active = False
        if self.silence_timer:
            self.silence_timer.cancel()
            self.silence_timer = None
            logger.info("Silence detection stopped")

    def _reset_silence_timer(self):
        """Reset the timer when user activity is detected."""
        if not self.silence_detection_active or self.timeout_triggered:
            return
            
        self.last_activity_time = time.time()
        
        if self.silence_timer:
            self.silence_timer.cancel()
            
        self._schedule_silence_timer()

    def _schedule_silence_timer(self):
        """Schedule the silence timeout timer."""
        if self.silence_detection_active and not self.timeout_triggered:
            self.silence_timer = Timer(self.silence_timeout, self._handle_silence_timeout)
            self.silence_timer.daemon = True
            self.silence_timer.start()

    def _handle_silence_timeout(self):
        """Handle the silence timeout event."""
        if not self.silence_detection_active or self.timeout_triggered:
            return
            
        current_time = time.time()
        elapsed = current_time - self.last_activity_time
        
        if elapsed >= self.silence_timeout:
            logger.info(f"Silence timeout triggered after {elapsed:.2f}s of inactivity")
            
            # Set the flag immediately to prevent multiple timeouts
            self.timeout_triggered = True
            self.silence_detection_active = False
            
            # Cancel the timer
            if self.silence_timer:
                self.silence_timer.cancel()
                self.silence_timer = None
            
            # Schedule the disconnect on the event loop
            if self.loop and self.loop.is_running():
                try:
                    # Use call_soon_threadsafe to safely schedule from this thread
                    self.loop.call_soon_threadsafe(
                        lambda: asyncio.create_task(self._handle_silence_disconnect())
                    )
                except Exception as e:
                    logger.error(f"Error scheduling disconnect: {str(e)}", exc_info=True)
                    # Fallback: try to create a new event loop
                    try:
                        new_loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(new_loop)
                        new_loop.run_until_complete(self._handle_silence_disconnect())
                    except Exception as e2:
                        logger.error(f"Fallback disconnect also failed: {str(e2)}", exc_info=True)

    async def _handle_silence_disconnect(self):
        """Coroutine to handle the disconnection after silence timeout."""
        logger.info("Handling silence timeout disconnection")
        
        # Dispatch the event first
        self.dispatch("conversation.timeout", {
            "reason": "user_silence", 
            "duration": self.silence_timeout,
            "timestamp": time.time()
        })
        
        # Then disconnect if connected
        if self.is_connected():
            logger.info("Disconnecting due to silence timeout")
            try:
                await self.disconnect()
                logger.info("Disconnected due to silence timeout")
            except Exception as e:
                logger.error(f"Error disconnecting: {str(e)}", exc_info=True)
                
        # Make sure the session is properly terminated
        self.session_created = False
        self.conversation.clear()
        
        # Force disconnect if still connected
        if self.realtime.is_connected():
            try:
                await self.realtime.disconnect()
                logger.info("Force disconnected from OpenAI Realtime API")
            except Exception as e:
                logger.error(f"Error force disconnecting: {str(e)}", exc_info=True)

    # Original methods with silence detection integration
    async def _call_tool(self, tool):
        try:
            json_arguments = json.loads(tool["arguments"])
            tool_config = self.tools.get(tool["name"])
            if not tool_config:
                raise Exception(f'Tool "{tool["name"]}" has not been added')
            result = await tool_config["handler"](**json_arguments)
            await self.realtime.send(
                "conversation.item.create",
                {
                    "item": {
                        "type": "function_call_output",
                        "call_id": tool["call_id"],
                        "output": json.dumps(result),
                    }
                },
            )
        except Exception as e:
            logger.error("Tool call error: " + json.dumps({"error": str(e)}))
            await self.realtime.send(
                "conversation.item.create",
                {
                    "item": {
                        "type": "function_call_output",
                        "call_id": tool["call_id"],
                        "output": json.dumps({"error": str(e)}),
                    }
                },
            )
        await self.create_response()
        
        # Reset silence timer after tool call
        self._reset_silence_timer()

    def is_connected(self):
        return self.realtime.is_connected()

    def reset(self):
        self._stop_silence_detection()
        
        # Cancel the END_CALL check task if it exists
        if self.end_call_check_task:
            self.end_call_check_task.cancel()
            self.end_call_check_task = None
            
        self.disconnect()
        self.realtime.clear_event_handlers()
        self._reset_config()
        self._add_api_event_handlers()
        return True

    async def connect(self):
        if self.is_connected():
            raise Exception("Already connected, use .disconnect() first")
            
        # Store the event loop for later use
        try:
            self.loop = asyncio.get_event_loop()
        except RuntimeError:
            logger.warning("No event loop found in connect()")
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            
        await self.realtime.connect()
        await self.update_session()
        
        # Reset timeout flags
        self.timeout_triggered = False
        
        # Start silence detection will be called when session is created
        return True

    async def wait_for_session_created(self):
        if not self.is_connected():
            raise Exception("Not connected, use .connect() first")
        while not self.session_created:
            await asyncio.sleep(0.001)
        return True

    async def disconnect(self):
        # Stop silence detection
        self._stop_silence_detection()
        
        # Cancel the END_CALL check task if it exists
        if self.end_call_check_task:
            self.end_call_check_task.cancel()
            self.end_call_check_task = None
        
        # Update session state
        self.session_created = False
        self.conversation.clear()
        
        # Disconnect from OpenAI
        if self.realtime.is_connected():
            await self.realtime.disconnect()

    def get_turn_detection_type(self):
        return self.session_config.get("turn_detection", {}).get("type")

    async def add_tool(self, definition, handler):
        if not definition.get("name"):
            raise Exception("Missing tool name in definition")
        name = definition["name"]
        if name in self.tools:
            raise Exception(
                f'Tool "{name}" already added. Please use .removeTool("{name}") before trying to add again.'
            )
        if not callable(handler):
            raise Exception(f'Tool "{name}" handler must be a function')
        self.tools[name] = {"definition": definition, "handler": handler}
        await self.update_session()
        return self.tools[name]

    def remove_tool(self, name):
        if name not in self.tools:
            raise Exception(f'Tool "{name}" does not exist, can not be removed.')
        del self.tools[name]
        return True

    async def delete_item(self, id):
        await self.realtime.send("conversation.item.delete", {"item_id": id})
        return True

    async def update_session(self, **kwargs):
        self.session_config.update(kwargs)
        use_tools = [
            {**tool_definition, "type": "function"} for tool_definition in self.session_config.get("tools", [])
        ] + [{**self.tools[key]["definition"], "type": "function"} for key in self.tools]
        session = {**self.session_config, "tools": use_tools}
        if self.realtime.is_connected():
            await self.realtime.send("session.update", {"session": session})
        return True

    async def create_conversation_item(self, item):
        await self.realtime.send("conversation.item.create", {"item": item})
        self._reset_silence_timer()

    async def send_user_message_content(self, content=[]):
        self._reset_silence_timer()
        if content:
            for c in content:
                if c["type"] == "input_audio":
                    if isinstance(c["audio"], (bytes, bytearray)):
                        c["audio"] = array_buffer_to_base64(c["audio"])
            await self.realtime.send(
                "conversation.item.create",
                {
                    "item": {
                        "type": "message",
                        "role": "user",
                        "content": content,
                    }
                },
            )
        await self.create_response()
        return True

    async def append_input_audio(self, array_buffer):
        if len(array_buffer) > 0:
            self._reset_silence_timer()
            await self.realtime.send(
                "input_audio_buffer.append",
                {
                    "audio": array_buffer_to_base64(np.array(array_buffer)),
                },
            )
            self.input_audio_buffer.extend(array_buffer)
        return True

    async def create_response(self):
        self._reset_silence_timer()
        if self.get_turn_detection_type() is None and len(self.input_audio_buffer) > 0:
            await self.realtime.send("input_audio_buffer.commit")
            self.conversation.queue_input_audio(self.input_audio_buffer)
            self.input_audio_buffer = bytearray()
        await self.realtime.send("response.create")
        return True

    async def cancel_response(self, id=None, sample_count=0):
        self._reset_silence_timer()
        if not id:
            await self.realtime.send("response.cancel")
            return {"item": None}
        else:
            item = self.conversation.get_item(id)
            if not item:
                raise Exception(f'Could not find item "{id}"')
            if item["type"] != "message":
                raise Exception('Can only cancelResponse messages with type "message"')
            if item["role"] != "assistant":
                raise Exception('Can only cancelResponse messages with role "assistant"')
            await self.realtime.send("response.cancel")
            audio_index = next((i for i, c in enumerate(item["content"]) if c["type"] == "audio"), -1)
            if audio_index == -1:
                raise Exception("Could not find audio on item to cancel")
            await self.realtime.send(
                "conversation.item.truncate",
                {
                    "item_id": id,
                    "content_index": audio_index,
                    "audio_end_ms": int((sample_count / self.conversation.default_frequency) * 1000),
                },
            )
            return {"item": item}

    async def wait_for_next_item(self):
        event = await self.wait_for_next("conversation.item.appended")
        return {"item": event["item"]}

    async def wait_for_next_completed_item(self):
        event = await self.wait_for_next("conversation.item.completed")
        return {"item": event["item"]}