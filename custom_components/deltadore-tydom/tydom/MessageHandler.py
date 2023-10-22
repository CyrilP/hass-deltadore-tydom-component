import json
from http.client import HTTPResponse
from http.server import BaseHTTPRequestHandler
from io import BytesIO
import traceback
import urllib3
import re

from .tydom_devices import *

from ..const import LOGGER

# Device dict for parsing
device_name = dict()
device_endpoint = dict()
device_type = dict()
device_metadata = dict()

class MessageHandler:
    """Handle incomming Tydom messages"""

    def __init__(self, tydom_client, cmd_prefix):
        self.tydom_client = tydom_client
        self.cmd_prefix = cmd_prefix

    @staticmethod
    def get_uri_origin(data) -> str:
        """Extract Uri-Origin from Tydom messages if present"""
        uri_origin = ""
        re_matcher = re.match(
            ".*Uri-Origin: ([a-zA-Z0-9\\-._~:/?#\\[\\]@!$&'\\(\\)\\*\\+,;%=]+).*",
            data,
        )

        if re_matcher:
            # LOGGER.info("///// Uri-Origin : %s", re_matcher.group(1))
            uri_origin = re_matcher.group(1)
        # else:
        # LOGGER.info("///// no match")
        return uri_origin

    @staticmethod
    def get_http_request_line(data) -> str:
        """Extract Http request line"""
        clean_data = data.replace('\\x02', '')
        request_line = ""
        re_matcher = re.match(
            "b'(.*)HTTP/1.1",
            clean_data,
        )
        if re_matcher:
            # LOGGER.info("///// PUT : %s", re_matcher.group(1))
            request_line = re_matcher.group(1)
        # else:
        #    LOGGER.info("///// no match")
        return request_line.strip()

    async def incoming_triage(self, bytes_str):
        """Identify message type and dispatch the result"""

        incoming = None

        # Find Uri-Origin in header if available
        uri_origin = MessageHandler.get_uri_origin(str(bytes_str))

        # Find http request line before http response
        http_request_line = MessageHandler.get_http_request_line(str(bytes_str))

        try:
            if http_request_line is not None and len(http_request_line) > 0:
                LOGGER.debug("%s detected !", http_request_line)
                try:
                    try:
                        incoming = self.parse_put_response(bytes_str)
                    except BaseException:
                        # Tywatt response starts at 7
                        incoming = self.parse_put_response(bytes_str, 7)
                    return await self.parse_response(
                        incoming, uri_origin, http_request_line
                    )
                except BaseException:
                    LOGGER.error("Error when parsing tydom message (%s)", bytes_str)
                    LOGGER.exception("Error when parsing tydom message")
                    return None
            elif len(uri_origin) > 0:
                response = self.response_from_bytes(bytes_str[len(self.cmd_prefix) :])
                incoming = response.data.decode("utf-8")
                try:
                    return await self.parse_response(
                        incoming, uri_origin, http_request_line
                    )
                except BaseException:
                    LOGGER.error("Error when parsing tydom message (%s)", bytes_str)
                    return None
            else:
                LOGGER.warning("Unknown tydom message type received (%s)", bytes_str)
                return None

        except Exception as ex:
            LOGGER.exception("exception")
            LOGGER.error(
                "Technical error when parsing tydom message (%s) : %s", bytes_str, ex
            )
            LOGGER.debug("Incoming payload (%s)", incoming)
            LOGGER.debug("exception : %s", ex)
            raise Exception(
                "Something really wrong happened!"
            ) from ex
            return None

    # Basic response parsing. Typically GET responses + instanciate covers and
    # alarm class for updating data
    async def parse_response(self, incoming, uri_origin, http_request_line):
        data = incoming
        msg_type = None
        first = str(data[:40])

        if data != "":
            if "/configs/file" in uri_origin:
                msg_type = "msg_config"
            elif "/devices/cmeta" in uri_origin:
                msg_type = "msg_cmetadata"
            elif "/configs/gateway/api_mode" in uri_origin:
                msg_type = "msg_api_mode"
            elif "/groups/file" in uri_origin:
                msg_type = "msg_groups"
            elif "/devices/meta" in uri_origin:
                msg_type = "msg_metadata"
            elif "/scenarios/file" in uri_origin:
                msg_type = "msg_scenarios"
            elif "cdata" in data:
                msg_type = "msg_cdata"
            elif "doctype" in first:
                msg_type = "msg_html"
            elif "/info" in uri_origin:
                msg_type = "msg_info"
            elif "id" in first:
                msg_type = "msg_data"

            if msg_type is None:
                LOGGER.warning("Unknown message type received %s", data)
            else:
                LOGGER.debug("Message received detected as (%s)", msg_type)
                try:
                    if msg_type == "msg_config":
                        parsed = json.loads(data)
                        return await MessageHandler.parse_config_data(parsed=parsed)

                    elif msg_type == "msg_cmetadata":
                        parsed = json.loads(data)
                        return await self.parse_cmeta_data(parsed=parsed)

                    elif msg_type == "msg_data":
                        parsed = json.loads(data)
                        return await self.parse_devices_data(parsed=parsed)

                    elif msg_type == "msg_cdata":
                        parsed = json.loads(data)
                        return await self.parse_devices_cdata(parsed=parsed)

                    elif msg_type == "msg_metadata":
                        parsed = json.loads(data)
                        return await self.parse_devices_metadata(parsed=parsed)

                    elif msg_type == "msg_html":
                        LOGGER.debug("HTML Response ?")

                    elif msg_type == "msg_info":
                        parsed = json.loads(data)
                        return await self.parse_msg_info(parsed)

                except Exception as e:
                    LOGGER.error("Error on parsing tydom response (%s)", e)
                    LOGGER.exception("Error on parsing tydom response")
                    traceback.print_exception(e)
            LOGGER.debug("Incoming data parsed with success")

    async def parse_devices_metadata(self, parsed):
        LOGGER.debug("metadata : %s", parsed)
        #LOGGER.error("metadata : %s", parsed)
        for device in parsed:
            id = device["id"]
            for endpoint in device["endpoints"]:
                id_endpoint = endpoint["id"]
                device_unique_id = str(id_endpoint) + "_" + str(id)
                device_metadata[device_unique_id] = dict()
                LOGGER.error("metadata unique id : %s", device_unique_id)
                for metadata in endpoint["metadata"]:
                    metadata_name = metadata["name"]
                    device_metadata[device_unique_id][metadata_name] = dict()
                    LOGGER.error("\tmetadata name : %s", metadata_name)
                    for meta in metadata:
                        if meta == "name":
                            continue
                        LOGGER.error("\t\tmetadata meta : %s => %s", meta, metadata[meta])
                        device_metadata[device_unique_id][metadata_name][meta] = metadata[meta]
        LOGGER.error("metadata result %s", device_metadata)
        return []

    async def parse_msg_info(self, parsed):
        LOGGER.debug("parse_msg_info : %s", parsed)

        return [
            Tydom(self.tydom_client, self.tydom_client.id, self.tydom_client.id, self.tydom_client.id, "Tydom Gateway", None, None, parsed)
        ]

    @staticmethod
    async def get_device(
        tydom_client, last_usage, uid, device_id, name, endpoint=None, data=None
    ) -> TydomDevice:
        """Get device class from its last usage"""

        LOGGER.error("- %s", name)

        # FIXME voir: class CoverDeviceClass(StrEnum):
        # Refer to the cover dev docs for device class descriptions
        # AWNING = "awning"
        # BLIND = "blind"
        # CURTAIN = "curtain"
        # DAMPER = "damper"
        # DOOR = "door"
        # GARAGE = "garage"
        # GATE = "gate"
        # SHADE = "shade"
        # SHUTTER = "shutter"
        # WINDOW = "window"
        match last_usage:
            case "shutter" | "klineShutter" | "awning":
                return TydomShutter(
                    tydom_client, uid, device_id, name, last_usage, endpoint, None, data
                )
            case "window" | "windowFrench" | "windowSliding" | "klineWindowFrench" | "klineWindowSliding":
                return TydomWindow(
                    tydom_client, uid, device_id, name, last_usage, endpoint, device_metadata[uid], data
                )
            case "belmDoor" | "klineDoor":
                return TydomDoor(
                    tydom_client, uid, device_id, name, last_usage, endpoint, device_metadata[uid], data
                )
            case "garage_door":
                return TydomGarage(
                    tydom_client, uid, device_id, name, last_usage, endpoint, device_metadata[uid], data
                )
            case "gate":
                return TydomGate(
                    tydom_client,
                    uid,
                    device_id,
                    name,
                    last_usage,
                    endpoint,
                    device_metadata[uid],
                    data,
                )
            case "light":
                return TydomLight(
                    tydom_client,
                    uid,
                    device_id,
                    name,
                    last_usage,
                    endpoint,
                    device_metadata[uid],
                    data,
                )
            case "conso":
                return TydomEnergy(
                    tydom_client, uid, device_id, name, last_usage, endpoint, device_metadata[uid], data
                )
            case "sensorDFR":
                return TydomSmoke(
                    tydom_client, uid, device_id, name, last_usage, endpoint, device_metadata[uid], data
                )
            case "boiler" | "sh_hvac" | "electric":
                return TydomBoiler(
                    tydom_client, uid, device_id, name, last_usage, endpoint, device_metadata[uid], data
                )
            case "alarm":
                return TydomAlarm(
                    tydom_client, uid, device_id, name, last_usage, endpoint, device_metadata[uid], data
                )
            case _:
                # TODO generic sensor ?
                LOGGER.warn("Unknown usage : %s", last_usage)
                return

    @staticmethod
    async def parse_config_data(parsed):
        LOGGER.debug("parse_config_data : %s", parsed)
        devices = []
        for i in parsed["endpoints"]:
            device_unique_id = str(i["id_endpoint"]) + "_" + str(i["id_device"])

            # device = await MessageHandler.get_device(i["last_usage"], device_unique_id, i["name"], i["id_endpoint"], None)
            # if device is not None:
            #    devices.append(device)

            LOGGER.warning(" config_data : %s - %s", device_unique_id, i["name"])

            device_name[device_unique_id] = i["name"]
            device_type[device_unique_id] = i["last_usage"]
            device_endpoint[device_unique_id] = i["id_endpoint"]

            if (
                i["last_usage"] == "shutter"
                or i["last_usage"] == "klineShutter"
                or i["last_usage"] == "light"
                or i["last_usage"] == "window"
                or i["last_usage"] == "windowFrench"
                or i["last_usage"] == "windowSliding"
                or i["last_usage"] == "belmDoor"
                or i["last_usage"] == "klineDoor"
                or i["last_usage"] == "klineWindowFrench"
                or i["last_usage"] == "klineWindowSliding"
                or i["last_usage"] == "garage_door"
                or i["last_usage"] == "gate"
            ):
                pass

            if i["last_usage"] == "boiler" or i["last_usage"] == "conso":
                pass
            if i["last_usage"] == "alarm":
                device_name[device_unique_id] = "Tyxal Alarm"

            if i["last_usage"] == "electric":
                pass

            if i["last_usage"] == "sensorDFR":
                pass

            if i["last_usage"] == "":
                device_type[device_unique_id] = "unknown"

        LOGGER.debug("Configuration updated")
        LOGGER.debug("devices : %s", devices)
        return devices

    async def parse_cmeta_data(self, parsed):
        LOGGER.debug("parse_cmeta_data : %s", parsed)
        for i in parsed:
            for endpoint in i["endpoints"]:
                if len(endpoint["cmetadata"]) > 0:
                    for elem in endpoint["cmetadata"]:
                        device_id = i["id"]
                        endpoint_id = endpoint["id"]
                        unique_id = str(endpoint_id) + "_" + str(device_id)

                        if elem["name"] == "energyIndex":
                            device_name[unique_id] = "Tywatt"
                            device_type[unique_id] = "conso"
                            for params in elem["parameters"]:
                                if params["name"] == "dest":
                                    for dest in params["enum_values"]:
                                        url = (
                                            "/devices/"
                                            + str(i["id"])
                                            + "/endpoints/"
                                            + str(endpoint["id"])
                                            + "/cdata?name="
                                            + elem["name"]
                                            + "&dest="
                                            + dest
                                            + "&reset=false"
                                        )
                                        self.tydom_client.add_poll_device_url(url)
                                        LOGGER.debug("Add poll device : %s", url)
                        elif elem["name"] == "energyInstant":
                            device_name[unique_id] = "Tywatt"
                            device_type[unique_id] = "conso"
                            for params in elem["parameters"]:
                                if params["name"] == "unit":
                                    for unit in params["enum_values"]:
                                        url = (
                                            "/devices/"
                                            + str(i["id"])
                                            + "/endpoints/"
                                            + str(endpoint["id"])
                                            + "/cdata?name="
                                            + elem["name"]
                                            + "&unit="
                                            + unit
                                            + "&reset=false"
                                        )
                                        self.tydom_client.add_poll_device_url(url)
                                        LOGGER.debug("Add poll device : " + url)
                        elif elem["name"] == "energyDistrib":
                            device_name[unique_id] = "Tywatt"
                            device_type[unique_id] = "conso"
                            for params in elem["parameters"]:
                                if params["name"] == "src":
                                    for src in params["enum_values"]:
                                        url = (
                                            "/devices/"
                                            + str(i["id"])
                                            + "/endpoints/"
                                            + str(endpoint["id"])
                                            + "/cdata?name="
                                            + elem["name"]
                                            + "&period=YEAR&periodOffset=0&src="
                                            + src
                                        )
                                        self.tydom_client.add_poll_device_url(url)
                                        LOGGER.debug("Add poll device : " + url)

        LOGGER.debug("Metadata configuration updated")

    async def parse_devices_data(self, parsed):
        LOGGER.debug("parse_devices_data : %s", parsed)
        devices = []

        for i in parsed:
            for endpoint in i["endpoints"]:
                if endpoint["error"] == 0 and len(endpoint["data"]) > 0:

                    try:
                        device_id = i["id"]
                        endpoint_id = endpoint["id"]
                        unique_id = str(endpoint_id) + "_" + str(device_id)
                        name_of_id = self.get_name_from_id(unique_id)
                        type_of_id = self.get_type_from_id(unique_id)

                        data = {}

                        for elem in endpoint["data"]:
                            element_name = elem["name"]
                            element_value = elem["value"]
                            element_validity = elem["validity"]

                            if element_validity == "upToDate":
                                data[element_name] = element_value

                        # Create the device
                        device = await MessageHandler.get_device(
                            self.tydom_client,
                            type_of_id,
                            unique_id,
                            device_id,
                            name_of_id,
                            endpoint_id,
                            data,
                        )
                        if device is not None:
                            devices.append(device)
                            LOGGER.info(
                                "Device update (id=%s, endpoint=%s, name=%s, type=%s)",
                                device_id,
                                endpoint_id,
                                name_of_id,
                                type_of_id,
                            )
                    except Exception as e:
                        LOGGER.exception("msg_data error in parsing !")
        return devices

    async def parse_devices_cdata(self, parsed):
        LOGGER.debug("parse_devices_data : %s", parsed)
        for i in parsed:
            for endpoint in i["endpoints"]:
                if endpoint["error"] == 0 and len(endpoint["cdata"]) > 0:
                    try:
                        device_id = i["id"]
                        endpoint_id = endpoint["id"]
                        unique_id = str(endpoint_id) + "_" + str(device_id)
                        name_of_id = self.get_name_from_id(unique_id)
                        type_of_id = self.get_type_from_id(unique_id)
                        LOGGER.info(
                            "Device configured (id=%s, endpoint=%s, name=%s, type=%s)",
                            device_id,
                            endpoint_id,
                            name_of_id,
                            type_of_id,
                        )

                        for elem in endpoint["cdata"]:
                            if type_of_id == "conso":
                                if elem["name"] == "energyIndex":
                                    device_class_of_id = "energy"
                                    state_class_of_id = "total_increasing"
                                    unit_of_measurement_of_id = "Wh"
                                    element_name = elem["parameters"]["dest"]
                                    element_index = "counter"

                                    attr_conso = {
                                        "device_id": device_id,
                                        "endpoint_id": endpoint_id,
                                        "id": unique_id,
                                        "name": name_of_id,
                                        "device_type": "sensor",
                                        "device_class": device_class_of_id,
                                        "state_class": state_class_of_id,
                                        "unit_of_measurement": unit_of_measurement_of_id,
                                        element_name: elem["values"][element_index],
                                    }

                                    # new_conso = Sensor(
                                    #    elem_name=element_name,
                                    #    tydom_attributes_payload=attr_conso,
                                    #    mqtt=self.mqtt_client,
                                    # )
                                    # await new_conso.update()

                                elif elem["name"] == "energyInstant":
                                    device_class_of_id = "current"
                                    state_class_of_id = "measurement"
                                    unit_of_measurement_of_id = "VA"
                                    element_name = elem["parameters"]["unit"]
                                    element_index = "measure"

                                    attr_conso = {
                                        "device_id": device_id,
                                        "endpoint_id": endpoint_id,
                                        "id": unique_id,
                                        "name": name_of_id,
                                        "device_type": "sensor",
                                        "device_class": device_class_of_id,
                                        "state_class": state_class_of_id,
                                        "unit_of_measurement": unit_of_measurement_of_id,
                                        element_name: elem["values"][element_index],
                                    }

                                    # new_conso = Sensor(
                                    #    elem_name=element_name,
                                    #    tydom_attributes_payload=attr_conso,
                                    #    mqtt=self.mqtt_client,
                                    # )
                                    # await new_conso.update()

                                elif elem["name"] == "energyDistrib":
                                    for elName in elem["values"]:
                                        if elName != "date":
                                            element_name = elName
                                            element_index = elName
                                            attr_conso = {
                                                "device_id": device_id,
                                                "endpoint_id": endpoint_id,
                                                "id": unique_id,
                                                "name": name_of_id,
                                                "device_type": "sensor",
                                                "device_class": "energy",
                                                "state_class": "total_increasing",
                                                "unit_of_measurement": "Wh",
                                                element_name: elem["values"][
                                                    element_index
                                                ],
                                            }

                                            # new_conso = Sensor(
                                            #    elem_name=element_name,
                                            #    tydom_attributes_payload=attr_conso,
                                            #    mqtt=self.mqtt_client,
                                            # )
                                            # await new_conso.update()

                    except Exception as e:
                        LOGGER.error("Error when parsing msg_cdata (%s)", e)

    # PUT response DIRTY parsing
    def parse_put_response(self, bytes_str, start=6):
        # TODO : Find a cooler way to parse nicely the PUT HTTP response
        resp = bytes_str[len(self.cmd_prefix) :].decode("utf-8")
        fields = resp.split("\r\n")
        fields = fields[start:]  # ignore the PUT / HTTP/1.1
        end_parsing = False
        i = 0
        output = str()
        while not end_parsing:
            field = fields[i]
            if len(field) == 0 or field == "0":
                end_parsing = True
            else:
                output += field
                i = i + 2
        parsed = json.loads(output)
        return json.dumps(parsed)

    # FUNCTIONS

    @staticmethod
    def response_from_bytes(data):
        sock = BytesIOSocket(data)
        response = HTTPResponse(sock)
        response.begin()
        return urllib3.HTTPResponse.from_httplib(response)

    @staticmethod
    def put_response_from_bytes(data):
        request = HTTPRequest(data)
        return request

    def get_type_from_id(self, id):
        device_type_detected = ""
        if id in device_type.keys():
            device_type_detected = device_type[id]
        else:
            LOGGER.warning("Unknown device type (%s)", id)
        return device_type_detected

    # Get pretty name for a device id
    def get_name_from_id(self, id):
        name = ""
        if id in device_name.keys():
            name = device_name[id]
        else:
            LOGGER.warning("Unknown device name (%s)", id)
        return name


class BytesIOSocket:
    def __init__(self, content):
        self.handle = BytesIO(content)

    def makefile(self, mode):
        return self.handle


class HTTPRequest(BaseHTTPRequestHandler):
    def __init__(self, request_text):
        self.raw_requestline = request_text
        self.error_code = self.error_message = None
        self.parse_request()

    def send_error(self, code, message):
        self.error_code = code
        self.error_message = message
