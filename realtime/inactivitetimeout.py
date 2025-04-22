# silence_detector.py
import time
import logging
import asyncio
from threading import Timer
from typing import Callable, Optional, Coroutine, Any

# Get a logger for this module
logger = logging.getLogger(__name__)

class SilenceDetector:
    """
    A class to detect user silence and trigger actions after a specified timeout period.
    Compatible with asyncio.
    """
    def __init__(self, 
                 timeout_seconds: int = 30, 
                 on_timeout_callback: Optional[Callable[[], Any]] = None,
                 on_timeout_coroutine: Optional[Coroutine] = None,
                 loop: Optional[asyncio.AbstractEventLoop] = None,
                 log_level: int = logging.INFO):
        """
        Initialize the silence detector.
        
        Args:
            timeout_seconds: Number of seconds of silence before triggering timeout
            on_timeout_callback: Function to call when timeout occurs (non-async)
            on_timeout_coroutine: Coroutine to schedule when timeout occurs (async)
            loop: Asyncio event loop to use for scheduling coroutines
            log_level: Logging level for this instance (default: INFO)
        """
        self.timeout_seconds = timeout_seconds
        self.on_timeout_callback = on_timeout_callback
        self.on_timeout_coroutine = on_timeout_coroutine
        self.loop = loop
        self.silence_timer = None
        self.last_activity_time = time.time()
        self.is_active = False
        
        # Configure logger
        self.logger = logger
        self.logger.setLevel(log_level)
        
        self.logger.info(f"SilenceDetector initialized with {timeout_seconds}s timeout")
    
    def start(self):
        """Start the silence detection."""
        self.is_active = True
        self.last_activity_time = time.time()
        self.logger.info("Silence detection started")
        self._schedule_timer()
    
    def stop(self):
        """Stop the silence detection."""
        self.is_active = False
        if self.silence_timer:
            self.silence_timer.cancel()
            self.silence_timer = None
            self.logger.info("Silence detection stopped")
        else:
            self.logger.debug("Silence detection stop called, but no active timer")
    
    def reset(self):
        """Reset the timer when user activity is detected."""
        if not self.is_active:
            self.logger.debug("Activity detected but silence detection is not active")
            return
            
        previous_time = self.last_activity_time
        self.last_activity_time = time.time()
        
        elapsed = self.last_activity_time - previous_time
        self.logger.debug(f"Activity detected after {elapsed:.2f}s of silence")
        
        if self.silence_timer:
            self.silence_timer.cancel()
            self.logger.debug("Previous silence timer canceled")
        
        self._schedule_timer()
    
    def _schedule_timer(self):
        """Schedule the silence timeout timer."""
        if self.is_active:
            self.silence_timer = Timer(self.timeout_seconds, self._handle_timeout)
            self.silence_timer.daemon = True
            self.silence_timer.start()
            self.logger.debug(f"Silence timer scheduled for {self.timeout_seconds}s from now")
    
    def _handle_timeout(self):
        """Handle the silence timeout event."""
        current_time = time.time()
        elapsed = current_time - self.last_activity_time
        
        if elapsed >= self.timeout_seconds and self.is_active:
            self.logger.info(f"Silence timeout triggered after {elapsed:.2f}s of inactivity")
            
            # Handle regular callback (non-async)
            if self.on_timeout_callback:
                self.logger.info("Executing timeout callback")
                try:
                    self.on_timeout_callback()
                except Exception as e:
                    self.logger.error(f"Error in timeout callback: {str(e)}", exc_info=True)
            
            # Handle async coroutine if provided
            if self.on_timeout_coroutine and self.loop:
                self.logger.info("Scheduling timeout coroutine on event loop")
                try:
                    # Use call_soon_threadsafe to safely schedule the coroutine from this thread
                    self.loop.call_soon_threadsafe(
                        lambda: asyncio.create_task(self.on_timeout_coroutine)
                    )
                except Exception as e:
                    self.logger.error(f"Error scheduling timeout coroutine: {str(e)}", exc_info=True)
        else:
            # If activity happened during timer execution, reschedule
            remaining = self.timeout_seconds - elapsed
            if remaining > 0:
                self.logger.debug(f"Activity occurred during timeout check, rescheduling timer for {remaining:.2f}s")
                self.silence_timer = Timer(remaining, self._handle_timeout)
                self.silence_timer.daemon = True
                self.silence_timer.start()
    
    def get_silence_duration(self):
        """Get the current duration of silence in seconds."""
        if not self.is_active:
            return 0
        
        current_time = time.time()
        elapsed = current_time - self.last_activity_time
        return elapsed
    
    def __str__(self):
        """String representation of the silence detector state."""
        status = "active" if self.is_active else "inactive"
        silence_duration = self.get_silence_duration()
        return f"SilenceDetector({status}, timeout={self.timeout_seconds}s, current_silence={silence_duration:.2f}s)"