async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """
    Set up Savant Energy from a config entry.
    Registers the coordinator and forwards setup to all platforms.
    Also handles Lovelace card installation and resource registration.
    """
    # Step 1: Copy the Lovelace card JS file
    card_copied_successfully = False
    resource_url = f"/local/{LOVELACE_CARD_FILENAME}"
    resource_type = "module"

    try:
        # Ensure www directory exists
        www_dir = hass.config.path("www")
        if not os.path.exists(www_dir):
            await hass.async_add_executor_job(os.makedirs, www_dir)
        
        # Copy the card file
        dest_path = os.path.join(www_dir, LOVELACE_CARD_FILENAME)
        src_path = os.path.join(os.path.dirname(__file__), LOVELACE_CARD_FILENAME)

        await hass.async_add_executor_job(shutil.copyfile, src_path, dest_path)
        _LOGGER.info(f"Copied Savant Energy Lovelace card to {dest_path}")
        card_copied_successfully = True
    except Exception as copy_exc:
        _LOGGER.error(f"Error copying Lovelace card: {copy_exc}\n{traceback.format_exc()}")
    
    # Step 2: Register the resource directly using the service call
    if card_copied_successfully:
        try:
            # Make absolutely sure the resource URL starts with /local/
            if not resource_url.startswith("/local/"):
                resource_url = f"/local/{LOVELACE_CARD_FILENAME}"
            
            _LOGGER.info(f"Attempting to register Lovelace resource: {resource_url}")
            
            # Check if resource already exists to avoid duplicates
            resources_state = hass.states.get("lovelace.resources")
            resource_exists = False
            
            if resources_state and hasattr(resources_state, "attributes"):
                resources = resources_state.attributes.get("resources", [])
                _LOGGER.info(f"Found {len(resources)} existing Lovelace resources")
                
                for resource in resources:
                    if resource.get("url") == resource_url:
                        _LOGGER.info(f"Resource already exists: {resource_url}")
                        resource_exists = True
                        break
            
            if not resource_exists:
                # Register the resource using the service call
                _LOGGER.info(f"Registering new Lovelace resource: {resource_url}")
                
                # Check if the service is available
                services = hass.services.async_services()
                if "lovelace" in services and "resources" in services.get("lovelace", {}):
                    try:
                        await hass.services.async_call(
                            "lovelace", 
                            "resources",
                            {
                                "url": resource_url,
                                "resource_type": resource_type,
                                "mode": "add"
                            },
                            blocking=True
                        )
                        _LOGGER.info(f"Successfully registered Lovelace resource: {resource_url}")
                    except Exception as service_exc:
                        _LOGGER.error(f"Service call failed: {service_exc}")
                        _LOGGER.warning(f"Please manually add the resource in Home Assistant UI: {resource_url}")
                else:
                    _LOGGER.warning("Lovelace resources service not available")
                    _LOGGER.warning(f"Please manually add the resource in Home Assistant UI: {resource_url}")
            else:
                _LOGGER.info("Skipping resource registration as it already exists")
                
        except Exception as e:
            _LOGGER.warning(
                f"Could not register the Lovelace resource. "
                f"Please add it manually in Home Assistant UI: URL: {resource_url}, Type: {resource_type}. "
                f"Error: {e}"
            )
    
    # Create coordinator and proceed with normal setup
    coordinator = SavantEnergyCoordinator(hass, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    
    # Get initial data before setting up platforms
    _LOGGER.info("Fetching initial data from Savant Energy controller")
    await coordinator.async_config_entry_first_refresh()
    
    if coordinator.data is None or not coordinator.data.get("snapshot_data"):
        _LOGGER.warning("Initial data fetch failed or returned no data - entities may be unavailable")
    
    # Register platforms
    _LOGGER.info("Setting up Savant Energy platforms")
    await hass.config_entries.async_forward_entry_setups(
        entry, ["sensor", "switch", "button", "binary_sensor", "scene"]
    )
    
    entry.async_on_unload(entry.add_update_listener(async_update_listener))
    
    return True
