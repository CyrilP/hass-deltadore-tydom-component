import json
import logging
from http.client import HTTPResponse
from http.server import BaseHTTPRequestHandler
from io import BytesIO
import traceback
import urllib3
import re

from .tydom_devices import *

logger = logging.getLogger(__name__)

# Dicts
deviceAlarmKeywords = [
    "alarmMode",
    "alarmState",
    "alarmSOS",
    "zone1State",
    "zone2State",
    "zone3State",
    "zone4State",
    "zone5State",
    "zone6State",
    "zone7State",
    "zone8State",
    "gsmLevel",
    "inactiveProduct",
    "zone1State",
    "liveCheckRunning",
    "networkDefect",
    "unitAutoProtect",
    "unitBatteryDefect",
    "unackedEvent",
    "alarmTechnical",
    "systAutoProtect",
    "systBatteryDefect",
    "systSupervisionDefect",
    "systOpenIssue",
    "systTechnicalDefect",
    "videoLinkDefect",
    "outTemperature",
    "kernelUpToDate",
    "irv1State",
    "irv2State",
    "irv3State",
    "irv4State",
    "simDefect",
    "remoteSurveyDefect",
    "systSectorDefect",
]
deviceAlarmDetailsKeywords = [
    "alarmSOS",
    "zone1State",
    "zone2State",
    "zone3State",
    "zone4State",
    "zone5State",
    "zone6State",
    "zone7State",
    "zone8State",
    "gsmLevel",
    "inactiveProduct",
    "zone1State",
    "liveCheckRunning",
    "networkDefect",
    "unitAutoProtect",
    "unitBatteryDefect",
    "unackedEvent",
    "alarmTechnical",
    "systAutoProtect",
    "systBatteryDefect",
    "systSupervisionDefect",
    "systOpenIssue",
    "systTechnicalDefect",
    "videoLinkDefect",
    "outTemperature",
]

deviceLightKeywords = [
    "level",
    "onFavPos",
    "thermicDefect",
    "battDefect",
    "loadDefect",
    "cmdDefect",
    "onPresenceDetected",
    "onDusk",
]
deviceLightDetailsKeywords = [
    "onFavPos",
    "thermicDefect",
    "battDefect",
    "loadDefect",
    "cmdDefect",
    "onPresenceDetected",
    "onDusk",
]

deviceDoorKeywords = ["openState", "intrusionDetect"]
deviceDoorDetailsKeywords = [
    "onFavPos",
    "thermicDefect",
    "obstacleDefect",
    "intrusion",
    "battDefect",
]

deviceCoverKeywords = [
    "position",
    "slope",
    "onFavPos",
    "thermicDefect",
    "obstacleDefect",
    "intrusion",
    "battDefect",
]
deviceCoverDetailsKeywords = [
    "onFavPos",
    "thermicDefect",
    "obstacleDefect",
    "intrusion",
    "battDefect",
    "position",
    "slope",
]

deviceBoilerKeywords = [
    "thermicLevel",
    "delayThermicLevel",
    "temperature",
    "authorization",
    "hvacMode",
    "timeDelay",
    "tempoOn",
    "antifrostOn",
    "openingDetected",
    "presenceDetected",
    "absence",
    "loadSheddingOn",
    "setpoint",
    "delaySetpoint",
    "anticipCoeff",
    "outTemperature",
]

deviceSwitchKeywords = ["thermicDefect"]
deviceSwitchDetailsKeywords = ["thermicDefect"]

deviceMotionKeywords = ["motionDetect"]
deviceMotionDetailsKeywords = ["motionDetect"]

device_conso_classes = {
    "energyInstantTotElec": "current",
    "energyInstantTotElec_Min": "current",
    "energyInstantTotElec_Max": "current",
    "energyScaleTotElec_Min": "current",
    "energyScaleTotElec_Max": "current",
    "energyInstantTotElecP": "power",
    "energyInstantTotElec_P_Min": "power",
    "energyInstantTotElec_P_Max": "power",
    "energyScaleTotElec_P_Min": "power",
    "energyScaleTotElec_P_Max": "power",
    "energyInstantTi1P": "power",
    "energyInstantTi1P_Min": "power",
    "energyInstantTi1P_Max": "power",
    "energyScaleTi1P_Min": "power",
    "energyScaleTi1P_Max": "power",
    "energyInstantTi1I": "current",
    "energyInstantTi1I_Min": "current",
    "energyInstantTi1I_Max": "current",
    "energyScaleTi1I_Min": "current",
    "energyScaleTi1I_Max": "current",
    "energyTotIndexWatt": "energy",
    "energyIndexHeatWatt": "energy",
    "energyIndexECSWatt": "energy",
    "energyIndexHeatGas": "energy",
    "outTemperature": "temperature",
}

device_conso_unit_of_measurement = {
    "energyInstantTotElec": "A",
    "energyInstantTotElec_Min": "A",
    "energyInstantTotElec_Max": "A",
    "energyScaleTotElec_Min": "A",
    "energyScaleTotElec_Max": "A",
    "energyInstantTotElecP": "W",
    "energyInstantTotElec_P_Min": "W",
    "energyInstantTotElec_P_Max": "W",
    "energyScaleTotElec_P_Min": "W",
    "energyScaleTotElec_P_Max": "W",
    "energyInstantTi1P": "W",
    "energyInstantTi1P_Min": "W",
    "energyInstantTi1P_Max": "W",
    "energyScaleTi1P_Min": "W",
    "energyScaleTi1P_Max": "W",
    "energyInstantTi1I": "A",
    "energyInstantTi1I_Min": "A",
    "energyInstantTi1I_Max": "A",
    "energyScaleTi1I_Min": "A",
    "energyScaleTi1I_Max": "A",
    "energyTotIndexWatt": "Wh",
    "energyIndexHeatWatt": "Wh",
    "energyIndexECSWatt": "Wh",
    "energyIndexHeatGas": "Wh",
    "outTemperature": "C",
}
device_conso_keywords = device_conso_classes.keys()

deviceSmokeKeywords = ["techSmokeDefect"]

# Device dict for parsing
device_name = dict()
device_endpoint = dict()
device_type = dict()


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
            # logger.info("///// Uri-Origin : %s", re_matcher.group(1))
            uri_origin = re_matcher.group(1)
        # else:
        # logger.info("///// no match")
        return uri_origin

    @staticmethod
    def get_http_request_line(data) -> str:
        """Extract Http request line"""
        request_line = ""
        re_matcher = re.match(
            "b'(.*)HTTP/1.1",
            data,
        )
        if re_matcher:
            # logger.info("///// PUT : %s", re_matcher.group(1))
            request_line = re_matcher.group(1)
        # else:
        #    logger.info("///// no match")
        return request_line

    async def incoming_triage(self, bytes_str):
        """Identify message type and dispatch the result"""

        incoming = None
        first = str(bytes_str[:40])

        # Find Uri-Origin in header if available
        uri_origin = MessageHandler.get_uri_origin(str(bytes_str))

        # Find http request line before http response
        http_request_line = MessageHandler.get_http_request_line(str(bytes_str))

        try:
            if len(http_request_line) > 0:
                logger.debug("%s detected !", http_request_line)
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
                    logger.error("Error when parsing tydom message (%s)", bytes_str)
                    return None
            elif len(uri_origin) > 0:
                response = self.response_from_bytes(bytes_str[len(self.cmd_prefix) :])
                incoming = response.data.decode("utf-8")
                try:
                    return await self.parse_response(
                        incoming, uri_origin, http_request_line
                    )
                except BaseException:
                    logger.error("Error when parsing tydom message (%s)", bytes_str)
                    return None
            else:
                logger.warning("Unknown tydom message type received (%s)", bytes_str)
                return None

            """
            if "/refresh/all" in uri_origin:
                pass
            elif ("PUT /devices/data" in http_request_line) or (
                "/devices/cdata" in http_request_line
            ):
                logger.debug("PUT /devices/data message detected !")
                try:
                    try:
                        incoming = self.parse_put_response(bytes_str)
                    except BaseException:
                        # Tywatt response starts at 7
                        incoming = self.parse_put_response(bytes_str, 7)
                    return await self.parse_response(incoming)
                except BaseException:
                    logger.error(
                        "Error when parsing devices/data tydom message (%s)", bytes_str
                    )
                    return None
            elif "scn" in first:
                try:
                    incoming = str(bytes_str)
                    scenarii = await self.parse_response(incoming)
                    logger.debug("Scenarii message processed")
                    return scenarii
                except BaseException:
                    logger.error(
                        "Error when parsing Scenarii tydom message (%s)", bytes_str
                    )
                    return None
            elif "POST" in http_request_line:
                try:
                    incoming = self.parse_put_response(bytes_str)
                    post = await self.parse_response(incoming)
                    logger.debug("POST message processed")
                    return post
                except BaseException:
                    logger.error(
                        "Error when parsing POST tydom message (%s)", bytes_str
                    )
                    return None
            elif "/devices/meta" in uri_origin:
                pass
            elif "HTTP/1.1" in first:
                response = self.response_from_bytes(bytes_str[len(self.cmd_prefix) :])
                incoming = response.data.decode("utf-8")
                try:
                    return await self.parse_response(incoming)
                except BaseException:
                    logger.error(
                        "Error when parsing HTTP/1.1 tydom message (%s)", bytes_str
                    )
                    return None
            else:
                logger.warning("Unknown tydom message type received (%s)", bytes_str)
                return None """

        except Exception as ex:
            logger.error(
                "Technical error when parsing tydom message (%s) : %s", bytes_str, ex
            )
            logger.debug("Incoming payload (%s)", incoming)
            logger.debug("exception : %s", ex)
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
                logger.warning("Unknown message type received %s", data)
            else:
                logger.debug("Message received detected as (%s)", msg_type)
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

                    elif msg_type == "msg_html":
                        logger.debug("HTML Response ?")

                    elif msg_type == "msg_info":
                        parsed = json.loads(data)
                        return await self.parse_msg_info(parsed)

                except Exception as e:
                    logger.error("Error on parsing tydom response (%s)", e)
                    traceback.print_exception(e)
            logger.debug("Incoming data parsed with success")

    async def parse_msg_info(self, parsed):
        logger.debug("parse_msg_info : %s", parsed)
        product_name = parsed["productName"]
        main_version_sw = parsed["mainVersionSW"]
        main_version_hw = parsed["mainVersionHW"]
        main_id = parsed["mainId"]
        main_reference = parsed["mainReference"]
        key_version_sw = parsed["keyVersionSW"]
        key_version_hw = parsed["keyVersionHW"]
        key_version_stack = parsed["keyVersionStack"]
        key_reference = parsed["keyReference"]
        boot_reference = parsed["bootReference"]
        boot_version = parsed["bootVersion"]
        update_available = parsed["updateAvailable"]
        return [
            Tydom(
                product_name,
                main_version_sw,
                main_version_hw,
                main_id,
                main_reference,
                key_version_sw,
                key_version_hw,
                key_version_stack,
                key_reference,
                boot_reference,
                boot_version,
                update_available,
            )
        ]

    @staticmethod
    async def get_device(
        tydom_client, last_usage, uid, device_id, name, endpoint=None, data=None
    ) -> TydomDevice:
        """Get device class from its last usage"""

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
                    tydom_client, uid, device_id, name, last_usage, endpoint, data
                )
            case "window" | "windowFrench" | "windowSliding" | "klineWindowFrench" | "klineWindowSliding":
                return TydomWindow(
                    tydom_client, uid, device_id, name, last_usage, endpoint, data
                )
            case "belmDoor" | "klineDoor":
                return TydomDoor(
                    tydom_client, uid, device_id, name, last_usage, endpoint, data
                )
            case "garage_door":
                return TydomGarage(
                    tydom_client, uid, device_id, name, last_usage, endpoint, data
                )
            case "gate":
                return TydomGate(
                    tydom_client,
                    uid,
                    device_id,
                    name,
                    last_usage,
                    endpoint,
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
                    data,
                )
            case "conso":
                return TydomEnergy(
                    tydom_client, uid, device_id, name, last_usage, endpoint, data
                )
            case "smoke":
                return TydomSmoke(
                    tydom_client, uid, device_id, name, last_usage, endpoint, data
                )
            case "boiler" | "sh_hvac":
                return TydomBoiler(
                    tydom_client, uid, device_id, name, last_usage, endpoint, data
                )
            case "alarm":
                return TydomAlarm(
                    tydom_client, uid, device_id, name, last_usage, endpoint, data
                )
            case _:
                logger.warn("Unknown usage : %s", last_usage)
                return

    @staticmethod
    async def parse_config_data(parsed):
        logger.debug("parse_config_data : %s", parsed)
        devices = []
        for i in parsed["endpoints"]:
            device_unique_id = str(i["id_endpoint"]) + "_" + str(i["id_device"])

            # device = await MessageHandler.get_device(i["last_usage"], device_unique_id, i["name"], i["id_endpoint"], None)
            # if device is not None:
            #    devices.append(device)

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
                device_name[device_unique_id] = i["name"]
                device_type[device_unique_id] = i["last_usage"]
                device_endpoint[device_unique_id] = i["id_endpoint"]

            if i["last_usage"] == "boiler" or i["last_usage"] == "conso":
                device_name[device_unique_id] = i["name"]
                device_type[device_unique_id] = i["last_usage"]
                device_endpoint[device_unique_id] = i["id_endpoint"]

            if i["last_usage"] == "alarm":
                device_name[device_unique_id] = "Tyxal Alarm"
                device_type[device_unique_id] = "alarm"
                device_endpoint[device_unique_id] = i["id_endpoint"]

            if i["last_usage"] == "electric":
                device_name[device_unique_id] = i["name"]
                device_type[device_unique_id] = "boiler"
                device_endpoint[device_unique_id] = i["id_endpoint"]

            if i["last_usage"] == "sensorDFR":
                device_name[device_unique_id] = i["name"]
                device_type[device_unique_id] = "smoke"
                device_endpoint[device_unique_id] = i["id_endpoint"]

            if i["last_usage"] == "":
                device_name[device_unique_id] = i["name"]
                device_type[device_unique_id] = "unknown"
                device_endpoint[device_unique_id] = i["id_endpoint"]

        logger.debug("Configuration updated")
        logger.debug("devices : %s", devices)
        return devices

    async def parse_cmeta_data(self, parsed):
        logger.debug("parse_cmeta_data : %s", parsed)
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
                                        logger.debug("Add poll device : %s", url)
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
                                        logger.debug("Add poll device : " + url)
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
                                        logger.debug("Add poll device : " + url)

        logger.debug("Metadata configuration updated")

    async def parse_devices_data(self, parsed):
        logger.debug("parse_devices_data : %s", parsed)
        devices = []

        for i in parsed:
            for endpoint in i["endpoints"]:
                if endpoint["error"] == 0 and len(endpoint["data"]) > 0:
                    try:
                        attr_alarm = {}
                        attr_cover = {}
                        attr_door = {}
                        attr_ukn = {}
                        attr_window = {}
                        attr_light = {}
                        attr_gate = {}
                        attr_boiler = {}
                        attr_smoke = {}
                        device_id = i["id"]
                        endpoint_id = endpoint["id"]
                        unique_id = str(endpoint_id) + "_" + str(device_id)
                        name_of_id = self.get_name_from_id(unique_id)
                        type_of_id = self.get_type_from_id(unique_id)

                        logger.info(
                            "Device update (id=%s, endpoint=%s, name=%s, type=%s)",
                            device_id,
                            endpoint_id,
                            name_of_id,
                            type_of_id,
                        )

                        data = {}

                        for elem in endpoint["data"]:
                            element_name = elem["name"]
                            element_value = elem["value"]
                            element_validity = elem["validity"]

                            if element_validity == "upToDate":
                                data[element_name] = element_value

                            print_id = name_of_id if len(name_of_id) != 0 else device_id

                            if type_of_id == "light":
                                if (
                                    element_name in deviceLightKeywords
                                    and element_validity == "upToDate"
                                ):
                                    attr_light["device_id"] = device_id
                                    attr_light["endpoint_id"] = endpoint_id
                                    attr_light["id"] = (
                                        str(device_id) + "_" + str(endpoint_id)
                                    )
                                    attr_light["light_name"] = print_id
                                    attr_light["name"] = print_id
                                    attr_light["device_type"] = "light"
                                    attr_light[element_name] = element_value

                            if type_of_id == "shutter" or type_of_id == "klineShutter":
                                if (
                                    element_name in deviceCoverKeywords
                                    and element_validity == "upToDate"
                                ):
                                    attr_cover["device_id"] = device_id
                                    attr_cover["endpoint_id"] = endpoint_id
                                    attr_cover["id"] = (
                                        str(device_id) + "_" + str(endpoint_id)
                                    )
                                    attr_cover["cover_name"] = print_id
                                    attr_cover["name"] = print_id
                                    attr_cover["device_type"] = "cover"

                                    if element_name == "slope":
                                        attr_cover["tilt"] = element_value
                                    else:
                                        attr_cover[element_name] = element_value

                            if type_of_id == "belmDoor" or type_of_id == "klineDoor":
                                if (
                                    element_name in deviceDoorKeywords
                                    and element_validity == "upToDate"
                                ):
                                    attr_door["device_id"] = device_id
                                    attr_door["endpoint_id"] = endpoint_id
                                    attr_door["id"] = (
                                        str(device_id) + "_" + str(endpoint_id)
                                    )
                                    attr_door["door_name"] = print_id
                                    attr_door["name"] = print_id
                                    attr_door["device_type"] = "sensor"
                                    attr_door["element_name"] = element_name
                                    attr_door[element_name] = element_value

                            if (
                                type_of_id == "windowFrench"
                                or type_of_id == "window"
                                or type_of_id == "windowSliding"
                                or type_of_id == "klineWindowFrench"
                                or type_of_id == "klineWindowSliding"
                            ):
                                if (
                                    element_name in deviceDoorKeywords
                                    and element_validity == "upToDate"
                                ):
                                    attr_window["device_id"] = device_id
                                    attr_window["endpoint_id"] = endpoint_id
                                    attr_window["id"] = (
                                        str(device_id) + "_" + str(endpoint_id)
                                    )
                                    attr_window["door_name"] = print_id
                                    attr_window["name"] = print_id
                                    attr_window["device_type"] = "sensor"
                                    attr_window["element_name"] = element_name
                                    attr_window[element_name] = element_value

                            if type_of_id == "boiler":
                                if (
                                    element_name in deviceBoilerKeywords
                                    and element_validity == "upToDate"
                                ):
                                    attr_boiler["device_id"] = device_id
                                    attr_boiler["endpoint_id"] = endpoint_id
                                    attr_boiler["id"] = (
                                        str(device_id) + "_" + str(endpoint_id)
                                    )
                                    # attr_boiler['boiler_name'] = print_id
                                    attr_boiler["name"] = print_id
                                    attr_boiler["device_type"] = "climate"
                                    attr_boiler[element_name] = element_value

                            if type_of_id == "alarm":
                                if (
                                    element_name in deviceAlarmKeywords
                                    and element_validity == "upToDate"
                                ):
                                    attr_alarm["device_id"] = device_id
                                    attr_alarm["endpoint_id"] = endpoint_id
                                    attr_alarm["id"] = (
                                        str(device_id) + "_" + str(endpoint_id)
                                    )
                                    attr_alarm["alarm_name"] = "Tyxal Alarm"
                                    attr_alarm["name"] = "Tyxal Alarm"
                                    attr_alarm["device_type"] = "alarm_control_panel"
                                    attr_alarm[element_name] = element_value

                            if type_of_id == "garage_door" or type_of_id == "gate":
                                if (
                                    element_name in deviceSwitchKeywords
                                    and element_validity == "upToDate"
                                ):
                                    attr_gate["device_id"] = device_id
                                    attr_gate["endpoint_id"] = endpoint_id
                                    attr_gate["id"] = (
                                        str(device_id) + "_" + str(endpoint_id)
                                    )
                                    attr_gate["switch_name"] = print_id
                                    attr_gate["name"] = print_id
                                    attr_gate["device_type"] = "switch"
                                    attr_gate[element_name] = element_value

                            if type_of_id == "conso":
                                if (
                                    element_name in device_conso_keywords
                                    and element_validity == "upToDate"
                                ):
                                    attr_conso = {
                                        "device_id": device_id,
                                        "endpoint_id": endpoint_id,
                                        "id": str(device_id) + "_" + str(endpoint_id),
                                        "name": print_id,
                                        "device_type": "sensor",
                                        element_name: element_value,
                                    }

                                    if element_name in device_conso_classes:
                                        attr_conso[
                                            "device_class"
                                        ] = device_conso_classes[element_name]

                                    if element_name in device_conso_unit_of_measurement:
                                        attr_conso[
                                            "unit_of_measurement"
                                        ] = device_conso_unit_of_measurement[
                                            element_name
                                        ]

                                    # new_conso = Sensor(
                                    #    elem_name=element_name,
                                    #    tydom_attributes_payload=attr_conso,
                                    #    mqtt=self.mqtt_client,
                                    # )
                                    # await new_conso.update()

                            if type_of_id == "smoke":
                                if (
                                    element_name in deviceSmokeKeywords
                                    and element_validity == "upToDate"
                                ):
                                    attr_smoke["device_id"] = device_id
                                    attr_smoke["device_class"] = "smoke"
                                    attr_smoke["endpoint_id"] = endpoint_id
                                    attr_smoke["id"] = (
                                        str(device_id) + "_" + str(endpoint_id)
                                    )
                                    attr_smoke["name"] = print_id
                                    attr_smoke["device_type"] = "sensor"
                                    attr_smoke["element_name"] = element_name
                                    attr_smoke[element_name] = element_value

                            if type_of_id == "unknown":
                                if (
                                    element_name in deviceMotionKeywords
                                    and element_validity == "upToDate"
                                ):
                                    attr_ukn["device_id"] = device_id
                                    attr_ukn["endpoint_id"] = endpoint_id
                                    attr_ukn["id"] = (
                                        str(device_id) + "_" + str(endpoint_id)
                                    )
                                    attr_ukn["name"] = print_id
                                    attr_ukn["device_type"] = "sensor"
                                    attr_ukn["element_name"] = element_name
                                    attr_ukn[element_name] = element_value
                                elif (
                                    element_name in deviceDoorKeywords
                                    and element_validity == "upToDate"
                                ):
                                    attr_ukn["device_id"] = device_id
                                    attr_ukn["endpoint_id"] = endpoint_id
                                    attr_ukn["id"] = (
                                        str(device_id) + "_" + str(endpoint_id)
                                    )
                                    attr_ukn["name"] = print_id
                                    attr_ukn["device_type"] = "sensor"
                                    attr_ukn["element_name"] = element_name
                                    attr_ukn[element_name] = element_value

                    except Exception as e:
                        logger.error("msg_data error in parsing !")
                        logger.error(e)

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

                    if (
                        "device_type" in attr_cover
                        and attr_cover["device_type"] == "cover"
                    ):
                        # new_cover = Cover(
                        #    tydom_attributes=attr_cover, mqtt=self.mqtt_client
                        # )
                        # await new_cover.update()
                        pass
                    elif (
                        "device_type" in attr_door
                        and attr_door["device_type"] == "sensor"
                    ):
                        # new_door = Sensor(
                        #    elem_name=attr_door["element_name"],
                        #    tydom_attributes_payload=attr_door,
                        #    mqtt=self.mqtt_client,
                        # )
                        # await new_door.update()
                        pass
                    elif (
                        "device_type" in attr_window
                        and attr_window["device_type"] == "sensor"
                    ):
                        # new_window = Sensor(
                        #    elem_name=attr_window["element_name"],
                        #    tydom_attributes_payload=attr_window,
                        #    mqtt=self.mqtt_client,
                        # )
                        # await new_window.update()
                        pass
                    elif (
                        "device_type" in attr_light
                        and attr_light["device_type"] == "light"
                    ):
                        # new_light = Light(
                        #    tydom_attributes=attr_light, mqtt=self.mqtt_client
                        # )
                        # await new_light.update()
                        pass
                    elif (
                        "device_type" in attr_boiler
                        and attr_boiler["device_type"] == "climate"
                    ):
                        # new_boiler = Boiler(
                        #    tydom_attributes=attr_boiler,
                        #    tydom_client=self.tydom_client,
                        #    mqtt=self.mqtt_client,
                        # )
                        # await new_boiler.update()
                        pass
                    elif (
                        "device_type" in attr_gate
                        and attr_gate["device_type"] == "switch"
                    ):
                        # new_gate = Switch(
                        #    tydom_attributes=attr_gate, mqtt=self.mqtt_client
                        # )
                        # await new_gate.update()
                        pass
                    elif (
                        "device_type" in attr_smoke
                        and attr_smoke["device_type"] == "sensor"
                    ):
                        # new_smoke = Sensor(
                        #    elem_name=attr_smoke["element_name"],
                        #    tydom_attributes_payload=attr_smoke,
                        #    mqtt=self.mqtt_client,
                        # )
                        # await new_smoke.update()
                        pass
                    elif (
                        "device_type" in attr_ukn
                        and attr_ukn["device_type"] == "sensor"
                    ):
                        # new_ukn = Sensor(
                        #    elem_name=attr_ukn["element_name"],
                        #    tydom_attributes_payload=attr_ukn,
                        #    mqtt=self.mqtt_client,
                        # )
                        # await new_ukn.update()
                        pass

                    # Get last known state (for alarm) # NEW METHOD
                    elif (
                        "device_type" in attr_alarm
                        and attr_alarm["device_type"] == "alarm_control_panel"
                    ):
                        state = None
                        sos_state = False
                        try:
                            if (
                                "alarmState" in attr_alarm
                                and attr_alarm["alarmState"] == "ON"
                            ) or (
                                "alarmState" in attr_alarm and attr_alarm["alarmState"]
                            ) == "QUIET":
                                state = "triggered"

                            elif (
                                "alarmState" in attr_alarm
                                and attr_alarm["alarmState"] == "DELAYED"
                            ):
                                state = "pending"

                            if (
                                "alarmSOS" in attr_alarm
                                and attr_alarm["alarmSOS"] == "true"
                            ):
                                state = "triggered"
                                sos_state = True

                            elif (
                                "alarmMode" in attr_alarm
                                and attr_alarm["alarmMode"] == "ON"
                            ):
                                state = "armed_away"
                            elif (
                                "alarmMode" in attr_alarm
                                and attr_alarm["alarmMode"] == "ZONE"
                            ):
                                state = "armed_home"
                            elif (
                                "alarmMode" in attr_alarm
                                and attr_alarm["alarmMode"] == "OFF"
                            ):
                                state = "disarmed"
                            elif (
                                "alarmMode" in attr_alarm
                                and attr_alarm["alarmMode"] == "MAINTENANCE"
                            ):
                                state = "disarmed"

                            if sos_state:
                                logger.warning("SOS !")

                            if not (state is None):
                                # alarm = Alarm(
                                #    current_state=state,
                                #    alarm_pin=self.tydom_client.alarm_pin,
                                #    tydom_attributes=attr_alarm,
                                #    mqtt=self.mqtt_client,
                                # )
                                # await alarm.update()
                                pass

                        except Exception as e:
                            logger.error("Error in alarm parsing !")
                            logger.error(e)
                            pass
                    else:
                        pass
        return devices

    async def parse_devices_cdata(self, parsed):
        logger.debug("parse_devices_data : %s", parsed)
        for i in parsed:
            for endpoint in i["endpoints"]:
                if endpoint["error"] == 0 and len(endpoint["cdata"]) > 0:
                    try:
                        device_id = i["id"]
                        endpoint_id = endpoint["id"]
                        unique_id = str(endpoint_id) + "_" + str(device_id)
                        name_of_id = self.get_name_from_id(unique_id)
                        type_of_id = self.get_type_from_id(unique_id)
                        logger.info(
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
                        logger.error("Error when parsing msg_cdata (%s)", e)

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
            logger.warning("Unknown device type (%s)", id)
        return device_type_detected

    # Get pretty name for a device id
    def get_name_from_id(self, id):
        name = ""
        if id in device_name.keys():
            name = device_name[id]
        else:
            logger.warning("Unknown device name (%s)", id)
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
