"""Constants for deltadore-tydom integration."""
from logging import Logger, getLogger

LOGGER: Logger = getLogger(__package__)

# This is the internal name of the integration, it should also match the directory
# name for the integration.
DOMAIN = "deltadore-tydom"
NAME = "Integration blueprint"
VERSION = "0.0.1"
ATTRIBUTION = "Data provided by http://jsonplaceholder.typicode.com/"

CONF_TYDOM_PASSWORD = "tydom_password"
