#!/usr/bin/env python3
"""
Weather Information Plugin
Retrieves current weather data using wttr.in service.
"""

import sys
import json
import asyncio
import subprocess
import urllib.parse
from typing import Dict, Any


async def execute(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get weather information for a city.

    Args:
        parameters: {
            "city": str,
            "units": "metric" | "imperial",
            "format": "brief" | "detailed"
        }

    Returns:
        {
            "success": bool,
            "result": str,
            "error": str | None,
            "metadata": dict
        }
    """
    city = parameters['city']
    units = parameters.get('units', 'metric')
    output_format = parameters.get('format', 'brief')

    try:
        # Determine wttr.in format code
        # Format: 1 = current weather, 2 = today + tomorrow, 3 = 3 days
        wttr_format = '1' if output_format == 'brief' else '2'

        # The city goes into a URL PATH: "New York" / "São Paulo" must be percent-encoded, or
        # curl is handed a URL with a raw space or non-ASCII byte and every multi-word or
        # accented city fails with an empty error.
        place = urllib.parse.quote(city.strip())
        # wttr.in picks units from the CALLER'S location unless told (`m` metric, `u` USCS), so
        # the `units` parameter used to be accepted and ignored: "metric" came back in °F.
        unit_flag = 'u' if units == 'imperial' else 'm'
        page_url = f"https://wttr.in/{place}"

        url = f"{page_url}?{unit_flag}&format=%l:+%C,+temperature+%t+(feels+like+%f),+humidity+%h,+wind+%w"

        if output_format == 'detailed':
            # Get more detailed ASCII art format
            url = f"{page_url}?{unit_flag}&{wttr_format}"

        # Use curl to fetch weather data
        result = subprocess.run(
            # -w appends the HTTP status on its own last line: wttr.in answers an unknown place
            # with HTTP 500 and a prose body, which used to be returned as the "weather".
            ['curl', '-s', '-m', '10', '-w', '\n%{http_code}', url],
            capture_output=True,
            text=True,
            timeout=12
        )

        if result.returncode != 0:
            return {
                "success": False,
                "result": None,
                "error": f"Failed to fetch weather data: {result.stderr}",
                "metadata": {
                    "city": city,
                    "units": units
                }
            }

        body, _, status = result.stdout.rstrip().rpartition('\n')
        weather_data = body.strip()

        if status != '200' or not weather_data:
            return {
                "success": False,
                "result": None,
                "error": (f"No weather for '{city}' (weather service HTTP {status or 'no response'}): "
                          f"{weather_data[:160] or 'empty reply'}"),
                "metadata": {
                    "city": city,
                    "units": units
                }
            }

        # Parse brief format: "Location: Conditions Temperature Humidity Wind"
        if output_format == 'brief':
            # Format the output nicely
            # The source link makes the reading CITABLE: answers are expected to cite what they
            # state, and a weather figure with no URL was a reason to reach for web search instead.
            formatted = (f"🌤️  Current weather for {city} "
                         f"({'°C, metric' if units != 'imperial' else '°F, imperial'}):\n\n"
                         f"{weather_data}\n\nSource: [wttr.in — {city}]({page_url})")
        else:
            # Detailed format includes ASCII art
            formatted = weather_data

        return {
            "success": True,
            "result": formatted,
            "error": None,
            "metadata": {
                "city": city,
                "units": units,
                "format": output_format,
                "data_length": len(weather_data)
            }
        }

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "result": None,
            "error": "Weather service request timed out. Please try again.",
            "metadata": {
                "city": city,
                "timeout": True
            }
        }

    except Exception as e:
        return {
            "success": False,
            "result": None,
            "error": f"Unexpected error: {str(e)}",
            "metadata": {
                "city": city,
                "error_type": type(e).__name__
            }
        }


# Communication protocol (boilerplate)
if __name__ == "__main__":
    try:
        input_data = sys.stdin.read()
        parameters = json.loads(input_data)
        result = asyncio.run(execute(parameters))
        print(json.dumps(result))
        sys.exit(0 if result['success'] else 1)
    except Exception as e:
        error_result = {
            "success": False,
            "result": None,
            "error": f"Plugin error: {str(e)}",
            "metadata": {}
        }
        print(json.dumps(error_result))
        sys.exit(1)
