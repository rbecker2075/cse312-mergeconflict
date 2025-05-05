from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
from starlette.responses import StreamingResponse
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
    sensitive_headers = ['authorization', 'x-auth-token', 'set-cookie', 'cookie', 'session_token']
    filtered_headers = {key: value for key, value in headers.items() if key.lower() not in sensitive_headers}

    if isinstance(body, dict):
        # Modify sensitive fields in the body
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
        log_dir = "/app/host_mount"
        os.makedirs(log_dir, exist_ok=True)

        log_file = os.path.join(log_dir, "full_request_response.log")
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
        if request.url.path.startswith("/game/static") and not request.url.path.startswith("/game/static/game"):
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
            decoded_content = self._decode_content(content)
            self.logger.info(decoded_content + "\n")
            self.logger.handlers[0].flush()

        if hasattr(response, "body_iterator"):
            # Wrap the original iterator for streaming responses
            response.body_iterator = logging_wrapper(response.body_iterator)
            return (self._decode_content(content), response)  # Instead of "<streaming response>", return actual content

        # For non-streaming responses
        try:
            body = response.body
            decoded_body = self._decode_content(body)
            return (decoded_body, response)
        except AttributeError:
            return (None, response)

    def _decode_content(self, content: bytes) -> Any:
        try:
            # Decode content as UTF-8 text, ignoring errors
            return content.decode('utf-8', errors='ignore')[:2048]  # Limit to first 2048 bytes
        except UnicodeDecodeError:
            return "<binary content>"

    def _is_binary_response(self, response: Response) -> bool:
        content_type = response.headers.get("Content-Type", "")
        # Treat JavaScript and HTML as text
        return "image" in content_type or "application/octet-stream" in content_type

    def _log_static_request(self, request: Request, response: Response, start_time: float, request_body: Optional[Any]):
        filtered_headers, _ = filter_sensitive_data(dict(request.headers), request_body)
        
        # Skip logging the body for image routes
        is_image_request = "image" in response.headers.get("Content-Type", "")
        is_pictures_endpoint = request.url.path.startswith("/pictures/")
        is_assets_endpoint = request.url.path.startswith("/game/static/assets/")
        
        # Determine response body content
        response_body = ""
        if not (is_image_request and (is_pictures_endpoint or is_assets_endpoint)):
            try:
                if response.status_code != 304:
                    body = response.body
                    content = body[:2048]  # Capture only the first 2048 bytes
                    response_body = self._decode_content(content)
            except AttributeError:
                pass  # If the response body is not available, proceed with no content logged

        # Log in the same format as dynamic requests
        request_str = self.format_request(request, request_body)
        response_str = self.format_response(response, response_body)

        self.logger.info("Request:\r\n" + request_str)
        self.logger.info("Response:\r\n" + response_str)
        self.logger.handlers[0].flush()

    def _log_binary_response(self, request: Request, response: Response, start_time: float, request_body: Optional[Any]):
        filtered_headers, _ = filter_sensitive_data(dict(request.headers), request_body)

        # Log in text format instead of JSON
        log_data = (
            f"Method: {request.method}\n"
            f"URL: {str(request.url)}\n"
            f"Status Code: {response.status_code}\n"
            f"Client IP: {request.client.host if request.client else 'N/A'}\n"
            f"Request Body: {request_body}\n"
            f"Request Headers:\n"
            f"{self._format_headers(filtered_headers)}\n"
            f"Response Metadata:\n"
            f"Content-Type: {response.headers.get('Content-Type')}\n"
            f"Content-Length: {response.headers.get('Content-Length')}\n"
            f"Response Headers:\n"
            f"{self._format_headers(dict(response.headers))}\n"
        )
        self.logger.info(log_data + "\n")
        self.logger.handlers[0].flush()

    def _log_dynamic_response(self, request: Request, response: Response, response_body: Optional[str], start_time: float, request_body: Optional[Any]):
        filtered_request_headers, filtered_request_body = filter_sensitive_data(dict(request.headers), request_body)
        filtered_response_headers, filtered_response_body = filter_sensitive_data(dict(response.headers), response_body)

        log_data = (
            f"Method: {request.method}\n"
            f"URL: {str(request.url)}\n"
            f"Status Code: {response.status_code}\n"
            f"Client IP: {request.client.host if request.client else 'N/A'}\n"
            f"Request Body: {filtered_request_body}\n"
            f"Request Headers:\n"
            f"{self._format_headers(filtered_request_headers)}\n"
            f"Response Body: {filtered_response_body}\n"
            f"Response Headers:\n"
            f"{self._format_headers(filtered_response_headers)}\n"
        )

        self.logger.info(log_data + "\n")
        self.logger.handlers[0].flush()

    def _format_headers(self, headers: dict) -> str:
        return "\n".join([f"{key}: {value}" for key, value in headers.items()])

    def format_request(self, request: Request, request_body: Optional[Any]) -> str:
        method = request.method
        url = str(request.url)
        version = '1.1'  # Assuming HTTP/1.1 unless otherwise specified
        
        headers = request.headers
        filtered_headers, _ = filter_sensitive_data(dict(headers), request_body)
        headers_str = self._format_headers(filtered_headers)
        
        body = json.dumps(request_body) if request_body else ""
        
        request_str = f"{method} {url} HTTP/{version}\r\n{headers_str}\r\n\r\n{body}\r\n"
        return request_str

    def format_response(self, response: Response, response_body: Optional[str]) -> str:
        version = '1.1'  # Assuming HTTP/1.1 unless otherwise specified

        # For both regular and streaming responses, we should use status_code
        status_code = response.status_code
        status_text = "OK"  # Default status text for non-streaming responses
        
        # Only for non-streaming responses, we can try to get the status text from response.status
        if not isinstance(response, StreamingResponse):
            # Try to get the status text, if it's available
            status_text = getattr(response, 'status', 'OK')

        headers = response.headers
        filtered_headers, _ = filter_sensitive_data(dict(headers), response_body)
        headers_str = self._format_headers(filtered_headers)
        
        body = response_body or ""
        
        # Build the response string
        response_str = f"HTTP/{version} {status_code} {status_text}\r\n{headers_str}\r\n\r\n{body}\r\n"
        return response_str
