import os
import asyncio
import uuid
import json
import websockets
from datetime import datetime
import logging
from .event_handler import RealtimeEventHandler
from websockets.http import Headers
logger = logging.getLogger(__name__)

class RealtimeAPI(RealtimeEventHandler):
    def __init__(
        self,
        url=None,
        api_key=None,
        api_version="2024-12-17-preview",
        deployment=None,
    ):
        super().__init__()
        self.use_azure = os.getenv("USE_AZURE", "false").lower() == "true"

        if self.use_azure:
            self.url = url or os.getenv("AZURE_OPENAI_URL")
            self.api_key = api_key or os.getenv("AZURE_OPENAI_API_KEY")
            self.api_version = api_version
            self.deployment = deployment or os.getenv("OPENAI_DEPLOYMENT_NAME_REALTIME", "gpt-4o-mini-realtime")
            self.user_agent = "ms-rtclient-0.4.3"
            self.request_id = uuid.uuid4()
        else:
            self.default_url = "wss://api.openai.com/v1/realtime"
            self.url = url or self.default_url
            self.api_key = api_key or os.getenv("OPENAI_API_KEY")

        self.ws = None

    def is_connected(self):
        return self.ws is not None

    def log(self, *args):
        logger.debug(f"[Websocket/{datetime.utcnow().isoformat()}]", *args)

    async def connect(self, model="gpt-4o-mini-realtime-preview-2024-12-17"):
        if self.is_connected():
            raise Exception("Already connected")

        if self.use_azure:
            if not self.url:
                raise ValueError("Azure OpenAI URL is required")

            url = f"wss://{self.url}/openai/realtime?api-version={self.api_version}&deployment={self.deployment}"
            self.ws = await websockets.connect(
                url,
                extra_headers={
                    "api-key": self.api_key,
                    "User-Agent": self.user_agent,
                    "x-ms-client-request-id": str(self.request_id),
                },
            )
        else:
            self.ws = await websockets.connect(
                f"{self.url}?model={model}",
                extra_headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "OpenAI-Beta": "realtime=v1",
                }
            )

        self.log(f"Connected to {self.url}")
        asyncio.create_task(self._receive_messages())

    async def _receive_messages(self):
        async for message in self.ws:
            event = json.loads(message)
            if event["type"] == "error":
                logger.error("ERROR", event)
            self.log("received:", event)
            self.dispatch(f"server.{event['type']}", event)
            self.dispatch("server.*", event)

    async def send(self, event_name, data=None):
        if not self.is_connected():
            raise Exception("RealtimeAPI is not connected")
        data = data or {}
        if not isinstance(data, dict):
            raise Exception("data must be a dictionary")
        event = {"event_id": self._generate_id("evt_"), "type": event_name, **data}
        self.dispatch(f"client.{event_name}", event)
        self.dispatch("client.*", event)
        self.log("sent:", event)
        await self.ws.send(json.dumps(event))

    def _generate_id(self, prefix):
        return f"{prefix}{int(datetime.utcnow().timestamp() * 1000)}"

    async def disconnect(self):
        if self.ws:
            await self.ws.close()
            self.ws = None
            self.log(f"Disconnected from {self.url}")