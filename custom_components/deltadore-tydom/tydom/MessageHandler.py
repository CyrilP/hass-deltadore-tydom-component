import json
import logging
from http.client import HTTPResponse
from http.server import BaseHTTPRequestHandler
from io import BytesIO

import urllib3

logger = logging.getLogger(__name__)


class MessageHandler:
    def __init__(self, incoming_bytes, tydom_client):
        self.incoming_bytes = incoming_bytes
        self.tydom_client = tydom_client
        self.cmd_prefix = tydom_client.cmd_prefix

    async def incoming_triage(self):
        bytes_str = self.incoming_bytes
        incoming = None
        first = str(bytes_str[:40])

        logger.debug("Incoming data parsed with success")
