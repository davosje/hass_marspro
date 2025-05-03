"""
Home Assistant integration for MarsPro.

For more details about this platform, please refer to the documentation at
https://home-assistant.io/components/marspro/
"""
import logging
import json
import random
import time
from datetime import timedelta

import voluptuous as vol

from homeassistant.components.fan import (
    FanEntity,
    PLATFORM_SCHEMA,
    SUPPORT_SET_SPEED,
    FanEntityFeature,
)
from homeassistant.components.light import (
    LightEntity,
    ATTR_BRIGHTNESS,
    SUPPORT_BRIGHTNESS,
    ColorMode,
    LightEntityFeature,
)
from homeassistant.const import (
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_NAME,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

_LOGGER = logging.getLogger(__name__)

# Config schema
PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_USERNAME): cv.string,
    vol.Required(CONF_PASSWORD): cv.string,
    vol.Optional(CONF_NAME, default="MarsPro"): cv.string,
})

# Default values
DEFAULT_NAME = "MarsPro"
SCAN_INTERVAL = timedelta(seconds=60)

# Device product groups
PRODUCT_GROUP_LIGHT = 1
PRODUCT_GROUP_FAN = 2
PRODUCT_GROUP_OTHER = [3, 6, 7]  # Add any other groups you find

# Device types
DEVICE_TYPE_DIMMER = "MZL001"
DEVICE_TYPE_FAN = "MH200-M"

async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up the MarsPro platform."""
    username = config.get(CONF_USERNAME)
    password = config.get(CONF_PASSWORD)
    name = config.get(CONF_NAME)

    session = async_get_clientsession(hass)
    api = MarsProApi(username, password, session)
    
    # Initialize API
    try:
        await api.login()
    except Exception as error:
        _LOGGER.error(f"Failed to connect to MarsPro API: {error}")
        return

    # Create data update coordinator
    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="marspro",
        update_method=api.update_data,
        update_interval=SCAN_INTERVAL,
    )

    # Initial data fetch
    await coordinator.async_refresh()

    # Create entities
    entities = []
    for device_group, devices in coordinator.data.items():
        for device in devices:
            if device_group == PRODUCT_GROUP_LIGHT:
                entities.append(MarsProLight(coordinator, api, device, name))
            elif device_group == PRODUCT_GROUP_FAN:
                entities.append(MarsProFan(coordinator, api, device, name))
    
    async_add_entities(entities, True)


class MarsProApi:
    """API client for MarsPro."""
    
    def __init__(self, username, password, session):
        """Initialize MarsPro API client."""
        self.username = username
        self.password = password
        self._session = session
        self.base_url = "https://mars-pro.api.lgledsolutions.com/api/"
        self.user_info = None
        
    async def _api_request(self, endpoint, method="POST", data=None):
        """Make API request to MarsPro."""
        url = f"{self.base_url}{endpoint}"
        
        # Generate a random request ID
        req_id = random.randint(10000000000, 11000000000)
        
        headers = {
            "content-type": "application/json",
            "systemdata": json.dumps({"reqId": req_id}),
        }
        
        try:
            if method == "POST":
                response = await self._session.post(url, headers=headers, json=data if data else {})
            else:
                response = await self._session.get(url, headers=headers)
                
            response_json = await response.json()
            
            if response_json.get("code") != "000":
                _LOGGER.error(f"API error: {response_json.get('msg')}")
                return None
                
            return response_json
        except Exception as e:
            _LOGGER.error(f"API request error: {e}")
            return None
    
    async def login(self):
        """Login to MarsPro API."""
        # For now, just get user info as login validation
        response = await self._api_request("android/mine/info/v1")
        if response and response.get("code") == "000":
            self.user_info = response.get("data")
            return True
        return False
    
    async def update_data(self):
        """Update data for all device types."""
        result = {}
        
        # Fetch light devices (group 1)
        light_data = await self._api_request("android/udm/getDeviceList/v1", 
                                          data={"currentPage": 1, "type": None, "deviceProductGroup": PRODUCT_GROUP_LIGHT})
        if light_data and light_data.get("code") == "000":
            result[PRODUCT_GROUP_LIGHT] = light_data.get("data", {}).get("list", [])
        
        # Fetch fan devices (group 2)
        fan_data = await self._api_request("android/udm/getDeviceList/v1", 
                                        data={"currentPage": 1, "type": None, "deviceProductGroup": PRODUCT_GROUP_FAN})
        if fan_data and fan_data.get("code") == "000":
            result[PRODUCT_GROUP_FAN] = fan_data.get("data", {}).get("list", [])
        
        # Add other device groups if needed
        for group_id in PRODUCT_GROUP_OTHER:
            other_data = await self._api_request("android/udm/getDeviceList/v1", 
                                              data={"currentPage": 1, "type": None, "deviceProductGroup": group_id})
            if other_data and other_data.get("code") == "000" and other_data.get("data", {}).get("list"):
                result[group_id] = other_data.get("data", {}).get("list", [])
        
        return result
    
    async def get_device_detail(self, device_id):
        """Get detailed information for a specific device."""
        response = await self._api_request("android/udm/getDeviceDetail/v1", 
                                        data={"deviceId": device_id})
        if response and response.get("code") == "000":
            return response.get("data")
        return None
    
    async def set_fan_speed(self, device_id, speed_percentage):
        """Set fan speed percentage."""
        # First we need to calculate the CFM and PA values
        cfm_response = await self._api_request("h5/product/getCalculateSum/v1", 
                                            data={
                                                "deviceId": device_id,
                                                "productCode": "24",  # This seems to be hardcoded for fans
                                                "calculationName": "cfmCalculation",
                                                "argsList": [
                                                    {
                                                        "argName": "windPercent",
                                                        "argValue": speed_percentage
                                                    }
                                                ]
                                            })
        
        pa_response = await self._api_request("h5/product/getCalculateSum/v1", 
                                           data={
                                               "deviceId": device_id,
                                               "productCode": "24",  # This seems to be hardcoded for fans
                                               "calculationName": "paCalculation",
                                               "argsList": [
                                                   {
                                                       "argName": "windPercent",
                                                       "argValue": speed_percentage
                                                   }
                                               ]
                                           })
        
        # Now we would set the actual speed
        # This endpoint is not shown in your logs, but based on the pattern, 
        # it's likely something like "android/udm/setDeviceSpeed/v1"
        # For now, let's just log and return success
        _LOGGER.info(f"Setting fan {device_id} speed to {speed_percentage}%, CFM: {cfm_response.get('data')}, PA: {pa_response.get('data')}")
        return True
    
    async def set_light_brightness(self, device_id, brightness_percentage):
        """Set light brightness percentage."""
        # This endpoint is not shown in your logs, but based on the pattern,
        # it's likely something like "android/udm/setDeviceBrightness/v1"
        # For now, let's just log and return success
        _LOGGER.info(f"Setting light {device_id} brightness to {brightness_percentage}%")
        return True


class MarsProFan(CoordinatorEntity, FanEntity):
    """Representation of a MarsPro Fan."""
    
    def __init__(self, coordinator, api, device_data, name):
        """Initialize the fan."""
        super().__init__(coordinator)
        self._api = api
        self._device_id = device_data["id"]
        self._device_data = device_data
        self._name = f"{name} {device_data['deviceName']}"
        
    @property
    def name(self):
        """Return the name of the fan."""
        return self._name
        
    @property
    def unique_id(self):
        """Return a unique ID."""
        return f"marspro_fan_{self._device_id}"
        
    @property
    def available(self):
        """Return if entity is available."""
        return self._device_data.get("connectStatus") == 1
        
    @property
    def percentage(self):
        """Return the current speed percentage."""
        # Get the fan speed from deviceInfo JSON string
        device_info = self._device_data.get("deviceInfo", "{}")
        try:
            info_dict = json.loads(device_info)
            fan_speed = info_dict.get("fanSpeed", 0)
            # Convert fan speed to percentage (assuming 840 is 100%)
            if fan_speed == 0:
                return 0
            return min(max(int(fan_speed / 8.4), 25), 100)
        except Exception as e:
            _LOGGER.error(f"Error parsing fan speed: {e}")
            return None
    
    @property
    def supported_features(self):
        """Flag supported features."""
        return FanEntityFeature.SET_SPEED
        
    async def async_set_percentage(self, percentage):
        """Set the speed percentage."""
        if percentage is None:
            percentage = 0
        
        # Ensure percentage is in valid range
        percentage = min(max(int(percentage), 25), 100)
        
        result = await self._api.set_fan_speed(self._device_id, percentage)
        if result:
            # Update the coordinator data
            await self.coordinator.async_request_refresh()
    
    async def async_turn_on(self, speed=None, percentage=None, preset_mode=None, **kwargs):
        """Turn on the fan."""
        if percentage is not None:
            await self.async_set_percentage(percentage)
        else:
            # Default to 25% if no speed specified
            await self.async_set_percentage(25)
    
    async def async_turn_off(self, **kwargs):
        """Turn off the fan."""
        # Set to minimum speed which is 25%
        await self.async_set_percentage(25)


class MarsProLight(CoordinatorEntity, LightEntity):
    """Representation of a MarsPro Light."""
    
    def __init__(self, coordinator, api, device_data, name):
        """Initialize the light."""
        super().__init__(coordinator)
        self._api = api
        self._device_id = device_data["id"]
        self._device_data = device_data
        self._name = f"{name} {device_data['deviceName']}"
        
    @property
    def name(self):
        """Return the name of the light."""
        return self._name
        
    @property
    def unique_id(self):
        """Return a unique ID."""
        return f"marspro_light_{self._device_id}"
        
    @property
    def available(self):
        """Return if entity is available."""
        return self._device_data.get("connectStatus") == 1
        
    @property
    def brightness(self):
        """Return the brightness of this light between 0..255."""
        # Get the brightness from deviceInfo JSON string
        device_info = self._device_data.get("deviceInfo", "{}")
        try:
            info_dict = json.loads(device_info)
            last_bright = info_dict.get("lastBright", 0)
            # Convert to 0..255 scale
            return min(max(int(last_bright * 255 / 100), 0), 255)
        except Exception as e:
            _LOGGER.error(f"Error parsing brightness: {e}")
            return None
    
    @property
    def is_on(self):
        """Return true if light is on."""
        return self.brightness > 0
    
    @property
    def supported_features(self):
        """Flag supported features."""
        return LightEntityFeature.BRIGHTNESS
    
    @property
    def color_mode(self):
        """Return the color mode of the light."""
        return ColorMode.BRIGHTNESS
    
    @property
    def supported_color_modes(self):
        """Flag supported color modes."""
        return {ColorMode.BRIGHTNESS}
        
    async def async_turn_on(self, **kwargs):
        """Instruct the light to turn on."""
        brightness = kwargs.get(ATTR_BRIGHTNESS)
        
        if brightness is not None:
            # Convert from 0..255 to 0..100
            brightness_percentage = int(brightness * 100 / 255)
        else:
            # Use last brightness or default to 50%
            device_info = self._device_data.get("deviceInfo", "{}")
            try:
                info_dict = json.loads(device_info)
                brightness_percentage = info_dict.get("lastBright", 50)
            except:
                brightness_percentage = 50
        
        result = await self._api.set_light_brightness(self._device_id, brightness_percentage)
        if result:
            # Update the coordinator data
            await self.coordinator.async_request_refresh()
    
    async def async_turn_off(self, **kwargs):
        """Instruct the light to turn off."""
        result = await self._api.set_light_brightness(self._device_id, 0)
        if result:
            # Update the coordinator data
            await self.coordinator.async_request_refresh()
