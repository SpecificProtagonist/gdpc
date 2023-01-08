"""Provides the HTTPInterface class, which contains direct wrappers for the endpoints of the
GDMC HTTP interface.\n

It is recommended to use the higher-level `editor.Editor` instead.
"""


from typing import Union, Tuple, Optional, List, Dict, Any
from functools import partial
import time

import requests
from requests.exceptions import ConnectionError as RequestConnectionError
from termcolor import colored

from .utility import eprint, withRetries
from .lookup import SUPPORTED_MINECRAFT_VERSIONS


def _onRequestRetry(e: Exception, retriesLeft: int):
    eprint(colored(color="yellow", text=\
        "HTTP request failed! Is Minecraft running? If so, try reducing your render distance.\n"
        f"Error: {e}"
        f"I'll retry in a bit ({retriesLeft} retries left).\n"
    ))
    time.sleep(3)


def _get(*args, retries: int, **kwargs):
    return withRetries(partial(requests.get, *args, **kwargs), retries=retries, onRetry=_onRequestRetry)

def _put(*args, retries: int, **kwargs):
    return withRetries(partial(requests.put, *args, **kwargs), retries=retries, onRetry=_onRequestRetry)

def _post(*args, retries: int, **kwargs):
    return withRetries(partial(requests.post, *args, **kwargs), retries=retries, onRetry=_onRequestRetry)


class HTTPInterface:
    """Provides direct wrappers for the endpoints of the Minecraft HTTP interface.\n
    It is recommended to use the higher-level `editor.Editor` instead."""

    def __init__(self, host: str = "http://localhost:9000"):
        self.host = host


    def getBlock(self, x: int, y: int, z: int, dx: Optional[int] = None, dy: Optional[int] = None, dz: Optional[int] = None, dimension: Optional[str] = None, includeState=False, includeData=False, retries=5, timeout=None):
        """Returns the blocks in the specified region.

        <dimension> can be one of {"overworld", "the_nether", "the_end"} (default "overworld").

        Returns a list with a dict for each retrieved block. The dicts have the following keys/values:
        - "x", "y", "z": Coordinates of the block (int).
        - "id":    Namespaced ID of the block (str).
        - "state": Block state dict (Dict[str, str]). Present if and only if <includeState> is True.
        - "data":  NBT data dict (Dict[str,Any]). Present if and only if <includeData> is True.

        If a set of coordinates is invalid, the returned block ID will be "minecraft:void_air".
        """
        url = f"{self.host}/blocks"
        parameters = {
            'x': x,
            'y': y,
            'z': z,
            'dx': dx,
            'dy': dy,
            'dz': dz,
            'includeState': True if includeState else None,
            'includeData':  True if includeData  else None,
            'dimension': dimension,
        }
        response = _get(url, params=parameters, headers={"accept": "application/json"}, retries=retries, timeout=timeout)
        blocks: List[Dict[str, Any]] = response.json()
        return blocks


    def placeBlock(self, x: int, y: int, z: int, blockStr: str, dimension: Optional[str] = None, doBlockUpdates=True, spawnDrops=False, customFlags: str = "", retries=5, timeout=None):
        """Places one or multiple blocks in the world.

        Each line of <blockStr> should describe a single block placement, using one of the
        following formats:
        1. <block>
        2. <position> <block>

        Placeholder explanation:
        - <block>: The (optionally namespaced) id of a block, optionally with block state info.
        NBT data is not supported. Examples: "minecraft:oak_log[axis=y]", "stone".
        - <position>: The (x,y,z) coordinates where to place the block. Coordinates can be given using
        tilde notation, in which case they are seen as relative to this function's <x>,<y>,<z>
        parameters. Examples: "1 2 3", "~4 ~5 ~6"

        <dimension> can be one of {"overworld", "the_nether", "the_end"} (default "overworld").

        The <doBlockUpdates>, <spawnDrops> and <customFlags> parameters control block update behavior.
        See the API documentation for more info.

        Returns a list with one string for each block placement. If the block placement was successful,
        the string is "1" if the block changed, or "0" otherwise. If the placement failed, it is the
        error message.
        """
        url = f"{self.host}/blocks"
        if customFlags != "":
            blockUpdateParams = {"customFlags": customFlags}
        else:
            blockUpdateParams = {"doBlockUpdates": doBlockUpdates, "spawnDrops": spawnDrops}

        parameters = {'x': x, 'y': y, 'z': z}
        parameters.update(blockUpdateParams)

        return _put(url, data=bytes(blockStr, "utf-8"), params=parameters, retries=retries, timeout=timeout).text.split("\n")


    def runCommand(self, command: str, dimension: Optional[str] = None, retries=5, timeout=None):
        """Executes one or multiple Minecraft commands (separated by newlines).

        The leading "/" must be omitted.

        <dimension> can be one of {"overworld", "the_nether", "the_end"} (default "overworld").

        Returns a list with one string for each command. If the command was successful, the string
        is its return value. Otherwise, it is the error message.
        """
        url = f"{self.host}/command"
        return _post(url, bytes(command, "utf-8"), params={'dimension': dimension}, retries=retries, timeout=timeout).text.split("\n")


    def getBuildArea(self, retries=5, timeout=None) -> Tuple[bool, Union[Tuple[int,int,int,int,int,int],str]]:
        """Retrieves the build area that was specified with /setbuildarea in-game.

        Fails if the build area was not specified yet.

        Returns (success, result).
        If a build area was specified, result is a 6-tuple (xFrom, yFrom, zFrom, xTo, yTo, zTo).
        Otherwise, result is the error message string.
        """
        response = _get(f"{self.host}/buildarea", retries=retries, timeout=timeout)

        if not response.ok or response.json() == -1:
            return False, response.text

        buildAreaJson = response.json()
        x1 = buildAreaJson["xFrom"]
        y1 = buildAreaJson["yFrom"]
        z1 = buildAreaJson["zFrom"]
        x2 = buildAreaJson["xTo"]
        y2 = buildAreaJson["yTo"]
        z2 = buildAreaJson["zTo"]
        return True, (x1, y1, z1, x2, y2, z2)


    def getChunks(self, x: int, z: int, dx: int = 1, dz: int = 1, dimension: Optional[str] = None, asBytes=False, retries=5, timeout=None):
        """Returns raw chunk data.

        <x> and <z> specify the position in chunk coordinates, and <dx> and <dz> specify how many
        chunks to get.
        <dimension> can be one of {"overworld", "the_nether", "the_end"} (default "overworld").

        If <asBytes> is True, returns raw binary data. Otherwise, returns a human-readable
        representation.

        On error, returns the error message instead.
        """
        url = f"{self.host}/chunks"
        parameters = {
            "x": x,
            "z": z,
            "dx": dx,
            "dz": dz,
            "dimension": dimension,
        }
        acceptType = "application/octet-stream" if asBytes else "text/plain"
        response = _get(url, params=parameters, headers={"Accept": acceptType}, retries=retries, timeout=timeout)
        if response.status_code >= 400:
            eprint(f"Error: {response.text}")

        return response.content if asBytes else response.text


    def getVersion(self, retries=5, timeout=None):
        """Returns the Minecraft version as a string."""
        return _get(f"{self.host}/version", retries=retries, timeout=timeout).text


    def checkConnection(self) -> Tuple[bool, Optional[bool]]:
        """Returns booleans (<connected>, <versionSupported>).\n
        <connected> is True if a HTTP request is succesfully received.\\
        <versionSupported> is True if the detected Minecraft version is guaranteed to be supported.\n
        If <connected> is False, <versionSupported> is None.
        """
        try:
            minecraftVersion = self.getVersion(retries=0)
        except RequestConnectionError:
            return False, None

        return True, minecraftVersion in SUPPORTED_MINECRAFT_VERSIONS
