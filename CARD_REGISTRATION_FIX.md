# Lovelace Card Registration Fix

## Issues with Previous Approach

The original implementation had several problems that prevented proper card registration:

1. **Manual Storage File Modification**: The code was directly patching `.storage/lovelace_resources` which is not the recommended approach and can cause conflicts
2. **Incorrect URL Patterns**: Using `/hacsfiles/` prefix when the integration is not distributed through HACS
3. **File System Complexity**: Copying files to `www/community/` directory manually instead of using Home Assistant's static path system
4. **Missing Frontend Integration**: Not using Home Assistant's proper frontend resource registration system

## How the Fix Works

The new implementation follows the same pattern used by HACS and other well-established integrations:

### 1. Static Path Registration
Instead of copying files around, we register a static path directly with Home Assistant's HTTP component:

```python
# Use Home Assistant's HTTP component to register static path
local_path = f"/local/{DOMAIN}"

# Try the new method first (HA 2024.7+)
try:
    from homeassistant.components.http import StaticPathConfig
    await hass.http.async_register_static_paths([
        StaticPathConfig(local_path, os.path.dirname(__file__), True)
    ])
except (ImportError, AttributeError):
    # Fallback to legacy method
    hass.http.register_static_path(local_path, os.path.dirname(__file__), True)
```

This serves the card file directly from the integration directory at `/local/savant_energy/savant-energy-scenes-card.js`.

### 2. Frontend Resource Registration
We use Home Assistant's official frontend module to register the JavaScript resource:

```python
# Register the JavaScript resource with Home Assistant's frontend
frontend.add_extra_js_url(hass, resource_url)
```

This properly informs Home Assistant's frontend about the custom card without manually modifying storage files.

### 3. Compatibility
The implementation includes backward compatibility for older Home Assistant versions by falling back to the legacy `register_static_path` method if the newer `async_register_static_paths` is not available.

## Benefits of This Approach

1. **Cleaner Integration**: No manual file copying or storage file modification
2. **Better Compatibility**: Works with both YAML and Storage mode Lovelace configurations
3. **Proper Resource Management**: Uses Home Assistant's official frontend resource system
4. **Future-Proof**: Compatible with both current and newer versions of Home Assistant
5. **No File Conflicts**: Serves files directly from the integration directory

## What Users Need to Do

After this fix, users will need to:

1. **Remove Old Resources**: If they manually added the card to Lovelace resources, they should remove those entries
2. **Clear Browser Cache**: Refresh their browser to ensure the new resource URL is loaded
3. **Restart Home Assistant**: This ensures the new static path registration takes effect

The card will now be automatically available and properly registered when the integration loads.

## Verification

You can verify the fix is working by:

1. Checking the Home Assistant logs for: `"Successfully registered Lovelace card resource: /local/savant_energy/savant-energy-scenes-card.js"`
2. Accessing the card directly at `http://your-ha-instance:8123/local/savant_energy/savant-energy-scenes-card.js`
3. Confirming the card appears in Lovelace without manual resource configuration

## References

This implementation follows the same patterns used by:
- HACS integration (`custom_components/hacs/frontend.py`)
- Home Assistant core lovelace system
- Other established custom integrations

The key insight was that integrations should use `frontend.add_extra_js_url()` combined with proper static path registration rather than manually managing storage files or copying files to special directories.
