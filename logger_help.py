import logging
import os
import time
import json
from datetime import datetime
from typing import Any, Optional, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp, Message

class RequestResponseLogger(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp):
        super().__init__(app)
        self.logger = self._configure_logging()

    def _configure_logging(self):
        log_dir = "/app/host_mount/logs"
        os.makedirs(log_dir, exist_ok=True)
        
        log_file = os.path.join(log_dir, "api_requests.log")
        logger = logging.getLogger("api-logger")
        logger.setLevel(logging.INFO)
        
        if logger.hasHandlers():
            logger.handlers.clear()
        
        file_handler = logging.FileHandler(log_file)
        formatter = logging.Formatter('%(message)s')
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        
        return logger

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path in ["/docs", "/openapi.json", "/redoc", "/favicon.ico"]:
            return await call_next(request)

        # Capture request body
        request_body = await self._get_request_body(request)
        start_time = time.time()

        # Get the response
        response = await call_next(request)
        
        # Capture response body
        response_body, response = await self._capture_response_body(response, start_time)

        # Log the data
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "method": request.method,
            "url": str(request.url),
            "status_code": response.status_code,
            "processing_time": time.time() - start_time,
            "client_ip": request.client.host if request.client else None,
            "request_body": request_body,
            "response_body": response_body
        }
        
        self.logger.info(json.dumps(log_data, default=str) + "\n")
        self.logger.handlers[0].flush()

        return response

    async def _get_request_body(self, request: Request) -> Optional[Any]:
        try:
            return await request.json()
        except:
            try:
                return (await request.body()).decode()
            except:
                return None

    async def _capture_response_body(self, response: Response, start_time: float):
        content = b""
        new_body = []
        
        async def logging_wrapper(body_iterator):
            nonlocal content
            async for chunk in body_iterator:
                content += chunk
                new_body.append(chunk)
                yield chunk
            # Log after all chunks are processed
            log_data = {
                "timestamp": datetime.utcnow().isoformat(),
                "processing_time": time.time() - start_time,
                "response_body": self._decode_content(content)
            }
            self.logger.info(json.dumps(log_data, default=str) + "\n")
            self.logger.handlers[0].flush()

        if hasattr(response, "body_iterator"):
            # Wrap the original iterator for streaming responses
            response.body_iterator = logging_wrapper(response.body_iterator)
            return ("<streaming response>", response)
        
        # For non-streaming responses
        try:
            body = response.body
            decoded_body = self._decode_content(body)
            return (decoded_body, response)
        except AttributeError:
            return (None, response)

    def _decode_content(self, content: bytes) -> Any:
        try:
            return json.loads(content.decode())
        except json.JSONDecodeError:
            return content.decode()
        except UnicodeDecodeError:
            return "<binary content>"