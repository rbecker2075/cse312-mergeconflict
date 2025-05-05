from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
import logging
import os
import time
import json
from datetime import datetime
from typing import Any, Optional
import re

from fastapi import Request, Response

# Helper function to filter sensitive data
def filter_sensitive_data(headers: dict, body: Optional[Any] = None) -> dict:
    # List of sensitive headers that need to be removed
    sensitive_headers = ['authorization', 'x-auth-token', 'set-cookie', 'cookie', 'session_token']
    filtered_headers = {key: value for key, value in headers.items() if key.lower() not in sensitive_headers}

    # If the body is a dictionary (JSON format), handle it correctly
    if isinstance(body, dict):
        # Modify sensitive fields directly in the dictionary
        if 'password' in body:
            body['password'] = "***"
        if 'passwd' in body:
            body['passwd'] = "***"
        if 'session_token' in body:
            body['session_token'] = "***"
    
    return filtered_headers, body


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

    async def dispatch(self, request: Request, call_next: ASGIApp) -> Response:
    # Exclude paths for docs, redoc, openapi, favicon (common static files)
        if request.url.path in ["/docs", "/openapi.json", "/redoc", "/favicon.ico"]:
            return await call_next(request)

        # Capture request body
        request_body = await self._get_request_body(request)
        start_time = time.time()

        # Check if the request is for a static file
        if request.url.path.startswith(("/game/static", "/pictures")):
            # Log only basic info for static requests (image, assets, etc.)
            response = await call_next(request)
            self._log_static_request(request, response, start_time, request_body)
            return response

        # For non-static (dynamic) requests, log full details
        response = await call_next(request)

        # Log response for binary and text responses
        if self._is_binary_response(response):
            self._log_binary_response(request, response, start_time, request_body)
        else:
            response_body, response = await self._capture_response_body(response, start_time)
            self._log_dynamic_response(request, response, response_body, start_time, request_body)

        return response


    async def _get_request_body(self, request: Request) -> Optional[Any]:
        try:
            # Try parsing JSON (dict format)
            return await request.json()
        except:
            try:
                # If it's not JSON, treat it as raw bytes and decode it
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
            return content.decode()[:2048]  # Limit to first 2048 bytes
        except UnicodeDecodeError:
            return "<binary content>"

    def _is_binary_response(self, response: Response) -> bool:
        content_type = response.headers.get("Content-Type", "")
        return "image" in content_type or "application/octet-stream" in content_type

    def _log_static_request(self, request: Request, response: Response, start_time: float, request_body: Optional[Any]):
        filtered_headers, _ = filter_sensitive_data(dict(request.headers), request_body)
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "method": request.method,
            "url": str(request.url),
            "status_code": response.status_code,
            "processing_time": time.time() - start_time,
            "client_ip": request.client.host if request.client else None,
            "request_body": request_body,
            "request_headers": filtered_headers,
            "response_metadata": {
                "content_type": response.headers.get("Content-Type"),
                "content_length": response.headers.get("Content-Length"),
                "response_headers": dict(response.headers)
            }
        }
        self.logger.info(json.dumps(log_data, default=str) + "\n")
        self.logger.handlers[0].flush()

    def _log_binary_response(self, request: Request, response: Response, start_time: float, request_body: Optional[Any]):
        filtered_headers, _ = filter_sensitive_data(dict(request.headers), request_body)
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "method": request.method,
            "url": str(request.url),
            "status_code": response.status_code,
            "processing_time": time.time() - start_time,
            "client_ip": request.client.host if request.client else None,
            "request_body": request_body,
            "request_headers": filtered_headers,
            "response_metadata": {
                "content_type": response.headers.get("Content-Type"),
                "content_length": response.headers.get("Content-Length"),
                "response_headers": dict(response.headers)
            }
        }
        self.logger.info(json.dumps(log_data, default=str) + "\n")
        self.logger.handlers[0].flush()

    def _log_dynamic_response(self, request: Request, response: Response, response_body: Optional[str], start_time: float, request_body: Optional[Any]):
        # Apply filter to the request and response body before logging
        filtered_request_headers, filtered_request_body = filter_sensitive_data(dict(request.headers), request_body)
        filtered_response_headers, filtered_response_body = filter_sensitive_data(dict(response.headers), response_body)

        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "method": request.method,
            "url": str(request.url),
            "status_code": response.status_code,
            "processing_time": time.time() - start_time,
            "client_ip": request.client.host if request.client else None,
            "request_body": filtered_request_body,
            "request_headers": filtered_request_headers,
            "response_body": filtered_response_body,
            "response_headers": filtered_response_headers
        }

        # Log the filtered request and response data
        self.logger.info(json.dumps(log_data, default=str) + "\n")
        self.logger.handlers[0].flush()



