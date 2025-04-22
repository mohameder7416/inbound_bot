from collections import defaultdict
import logging
from .utils import base64_to_array_buffer

logger = logging.getLogger(__name__)

class RealtimeConversation:
    default_frequency = 16000  # Default sample rate

    EventProcessors = {
        "conversation.item.created": lambda self, event: self._process_item_created(event),
        "conversation.item.truncated": lambda self, event: self._process_item_truncated(event),
        "conversation.item.deleted": lambda self, event: self._process_item_deleted(event),
        "conversation.item.input_audio_transcription.completed": lambda self, event: self._process_input_audio_transcription_completed(
            event
        ),
        "input_audio_buffer.speech_started": lambda self, event: self._process_speech_started(event),
        "input_audio_buffer.speech_stopped": lambda self, event, input_audio_buffer: self._process_speech_stopped(
            event, input_audio_buffer
        ),
        "response.created": lambda self, event: self._process_response_created(event),
        "response.output_item.added": lambda self, event: self._process_output_item_added(event),
        "response.output_item.done": lambda self, event: self._process_output_item_done(event),
        "response.content_part.added": lambda self, event: self._process_content_part_added(event),
        "response.audio_transcript.delta": lambda self, event: self._process_audio_transcript_delta(event),
        "response.audio.delta": lambda self, event: self._process_audio_delta(event),
        "response.text.delta": lambda self, event: self._process_text_delta(event),
        "response.function_call_arguments.delta": lambda self, event: self._process_function_call_arguments_delta(
            event
        ),
    }

    def __init__(self):
        self.clear()

    def clear(self):
        self.item_lookup = {}
        self.items = []
        self.response_lookup = {}
        self.responses = []
        self.queued_speech_items = {}
        self.queued_transcript_items = {}
        self.queued_input_audio = None

    def queue_input_audio(self, input_audio):
        self.queued_input_audio = input_audio

    def process_event(self, event, *args):
        event_processor = self.EventProcessors.get(event["type"])
        if not event_processor:
            raise Exception(f"Missing conversation event processor for {event['type']}")
        return event_processor(self, event, *args)

    def get_item(self, id):
        return self.item_lookup.get(id)

    def get_items(self):
        return self.items[:]

    def _process_item_created(self, event):
        item = event["item"]
        new_item = item.copy()
        if new_item["id"] not in self.item_lookup:
            self.item_lookup[new_item["id"]] = new_item
            self.items.append(new_item)
        new_item["formatted"] = {"audio": [], "text": "", "transcript": ""}
        if new_item["id"] in self.queued_speech_items:
            new_item["formatted"]["audio"] = self.queued_speech_items[new_item["id"]]["audio"]
            del self.queued_speech_items[new_item["id"]]
        if "content" in new_item:
            text_content = [c for c in new_item["content"] if c["type"] in ["text", "input_text"]]
            for content in text_content:
                new_item["formatted"]["text"] += content["text"]
        if new_item["id"] in self.queued_transcript_items:
            new_item["formatted"]["transcript"] = self.queued_transcript_items[new_item["id"]]["transcript"]
            del self.queued_transcript_items[new_item["id"]]
        if new_item["type"] == "message":
            if new_item["role"] == "user":
                new_item["status"] = "completed"
                if self.queued_input_audio:
                    new_item["formatted"]["audio"] = self.queued_input_audio
                    self.queued_input_audio = None
            else:
                new_item["status"] = "in_progress"
        elif new_item["type"] == "function_call":
            new_item["formatted"]["tool"] = {
                "type": "function",
                "name": new_item["name"],
                "call_id": new_item["call_id"],
                "arguments": "",
            }
            new_item["status"] = "in_progress"
        elif new_item["type"] == "function_call_output":
            new_item["status"] = "completed"
            new_item["formatted"]["output"] = new_item["output"]
        return new_item, None

    def _process_item_truncated(self, event):
        item_id = event["item_id"]
        audio_end_ms = event["audio_end_ms"]
        item = self.item_lookup.get(item_id)
        if not item:
            raise Exception(f'item.truncated: Item "{item_id}" not found')
        end_index = (audio_end_ms * self.default_frequency) // 1000
        item["formatted"]["transcript"] = ""
        item["formatted"]["audio"] = item["formatted"]["audio"][:end_index]
        return item, None

    def _process_item_deleted(self, event):
        item_id = event["item_id"]
        item = self.item_lookup.get(item_id)
        if not item:
            raise Exception(f'item.deleted: Item "{item_id}" not found')
        del self.item_lookup[item["id"]]
        self.items.remove(item)
        return item, None

    def _process_input_audio_transcription_completed(self, event):
        item_id = event["item_id"]
        content_index = event["content_index"]
        transcript = event["transcript"]
        formatted_transcript = transcript or " "
        item = self.item_lookup.get(item_id)
        if not item:
            self.queued_transcript_items[item_id] = {"transcript": formatted_transcript}
            return None, None
        item["content"][content_index]["transcript"] = transcript
        item["formatted"]["transcript"] = formatted_transcript
        return item, {"transcript": transcript}

    def _process_speech_started(self, event):
        item_id = event["item_id"]
        audio_start_ms = event["audio_start_ms"]
        self.queued_speech_items[item_id] = {"audio_start_ms": audio_start_ms}
        return None, None

    def _process_speech_stopped(self, event, input_audio_buffer):
        item_id = event["item_id"]
        audio_end_ms = event["audio_end_ms"]
        speech = self.queued_speech_items[item_id]
        speech["audio_end_ms"] = audio_end_ms
        if input_audio_buffer:
            start_index = (speech["audio_start_ms"] * self.default_frequency) // 1000
            end_index = (speech["audio_end_ms"] * self.default_frequency) // 1000
            speech["audio"] = input_audio_buffer[start_index:end_index]
        return None, None

    def _process_response_created(self, event):
        response = event["response"]
        if response["id"] not in self.response_lookup:
            self.response_lookup[response["id"]] = response
            self.responses.append(response)
        return None, None

    def _process_output_item_added(self, event):
        response_id = event["response_id"]
        item = event["item"]
        response = self.response_lookup.get(response_id)
        if not response:
            raise Exception(f'response.output_item.added: Response "{response_id}" not found')
        response["output"].append(item["id"])
        return None, None

    def _process_output_item_done(self, event):
        item = event["item"]
        if not item:
            raise Exception('response.output_item.done: Missing "item"')
        found_item = self.item_lookup.get(item["id"])
        if not found_item:
            raise Exception(f'response.output_item.done: Item "{item["id"]}" not found')
        found_item["status"] = item["status"]
        return found_item, None

    def _process_content_part_added(self, event):
        item_id = event["item_id"]
        part = event["part"]
        item = self.item_lookup.get(item_id)
        if not item:
            raise Exception(f'response.content_part.added: Item "{item_id}" not found')
        item["content"].append(part)
        return item, None

    def _process_audio_transcript_delta(self, event):
        item_id = event["item_id"]
        content_index = event["content_index"]
        delta = event["delta"]
        item = self.item_lookup.get(item_id)
        if not item:
            raise Exception(f'response.audio_transcript.delta: Item "{item_id}" not found')
        item["content"][content_index]["transcript"] += delta
        item["formatted"]["transcript"] += delta
        return item, {"transcript": delta}

    def _process_audio_delta(self, event):
        item_id = event["item_id"]
        content_index = event["content_index"]
        delta = event["delta"]
        item = self.item_lookup.get(item_id)
        if not item:
            logger.debug(f'response.audio.delta: Item "{item_id}" not found')
            return None, None
        array_buffer = base64_to_array_buffer(delta)
        append_values = array_buffer.tobytes()
        item["formatted"]["audio"] += [append_values]
        return item, {"audio": append_values}

    def _process_text_delta(self, event):
        item_id = event["item_id"]
        content_index = event["content_index"]
        delta = event["delta"]
        item = self.item_lookup.get(item_id)
        if not item:
            raise Exception(f'response.text.delta: Item "{item_id}" not found')
        item["content"][content_index]["text"] += delta
        item["formatted"]["text"] += delta
        return item, {"text": delta}

    def _process_function_call_arguments_delta(self, event):
        item_id = event["item_id"]
        delta = event["delta"]
        item = self.item_lookup.get(item_id)
        if not item:
            raise Exception(f'response.function_call_arguments.delta: Item "{item_id}" not found')
        item["arguments"] += delta
        item["formatted"]["tool"]["arguments"] += delta
        return item, {"arguments": delta}