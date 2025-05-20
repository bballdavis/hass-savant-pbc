# Savant Energy Integration REST API

This section documents the HTTP REST API endpoints for managing Savant Energy scenes. These endpoints are suitable for use by custom Lovelace cards, external clients, or scripts that interact with Home Assistant over HTTP.

---

## REST API: List All Scenes
**Endpoint:** `GET /api/savant_energy/scenes`

Returns a list of all Savant scenes (scene_id and name only).

**Example Request:**
```
GET /api/savant_energy/scenes
```

**Example Response:**
```json
{
  "scenes": [
    {"scene_id": "savant_movie_night", "name": "Movie Night"},
    {"scene_id": "savant_party", "name": "Party"}
  ]
}
```

---

## REST API: Get Breaker States for a Scene
**Endpoint:** `GET /api/savant_energy/scene_breakers/{scene_id}`

Returns the breaker (relay) states for a specific scene, merging saved states with any new breaker switches currently available in Home Assistant. New breakers are added as `false` (off) by default.

**Example Request:**
```
GET /api/savant_energy/scene_breakers/savant_movie_night
```

**Example Response:**
```json
{
  "scene_id": "savant_movie_night",
  "breakers": {
    "switch.breaker_living_room": true,
    "switch.breaker_kitchen": false,
    "switch.breaker_new": false
  }
}
```

---

## REST API: Create a Scene
**Endpoint:** `POST /api/savant_energy/scenes`

Creates a new Savant scene. Scene names must be unique (case-insensitive).

**Request Body:**
```json
{
  "name": "Movie Night",
  "relay_states": {
    "switch.savant_living_room": true,
    "switch.savant_kitchen": false
  }
}
```

**Success Response:**
```json
{
  "status": "ok",
  "scene_id": "savant_movie_night"
}
```
**Error Response:**
```json
{
  "status": "error",
  "message": "A scene with the name 'Movie Night' already exists."
}
```

---

## REST API: Update a Scene
**Endpoint:** `POST /api/savant_energy/scenes/{scene_id}`

Updates an existing scene's name and/or relay states.

**Request Body:**
```json
{
  "name": "Cinema Mode",
  "relay_states": {
    "switch.savant_living_room_lights": true,
    "switch.savant_hallway_lights": false
  }
}
```

**Success Response:**
```json
{
  "status": "ok",
  "scene_id": "savant_movie_night"
}
```
**Error Response:**
```json
{
  "status": "error",
  "message": "Scene savant_movie_night not found."
}
```

---

## REST API: Delete a Scene
**Endpoint:** `DELETE /api/savant_energy/scenes/{scene_id}`

Deletes a scene by its ID. This action is irreversible.

**Example Request:**
```
DELETE /api/savant_energy/scenes/savant_movie_night
```

**Success Response:**
```json
{
  "status": "ok",
  "scene_id": "savant_movie_night"
}
```
**Error Response:**
```json
{
  "status": "error",
  "message": "Scene savant_movie_night not found."
}
```

---

# Home Assistant Service API

This section documents the Home Assistant service API for managing Savant Energy scenes. These services are available via Home Assistant's service call interface and can be called from automations, scripts, or external clients using the Home Assistant API.

## Service: `savant_energy.create_scene`
Create a new Savant scene. Scene names must be unique (case-insensitive). If a duplicate name is provided, the request will be rejected.

### Request Schema
- `name` (string, required): The name of the new scene.
- `relay_states` (object, required): A dictionary mapping relay entity IDs to boolean values (on/off).

#### Example Request
```json
{
  "name": "Movie Night",
  "relay_states": {
    "switch.savant_living_room": true,
    "switch.savant_kitchen": false
  }
}
```

### Response
- On success:
  ```json
  {
    "status": "ok",
    "scene_id": "savant_movie_night"
  }
  ```
- On error (e.g., duplicate name):
  ```json
  {
    "status": "error",
    "message": "A scene with the name 'Movie Night' already exists."
  }
  ```

## Service: `savant_energy.update_scene`
Update an existing scene's name and/or relay states. This service is used to modify a scene.

### Request Schema
- `scene_id` (string, required): The ID of the scene to update (e.g., `savant_movie_night`).
- `name` (string, optional): New name for the scene. If provided, the scene's display name will be changed.
- `relay_states` (object, optional): Dictionary of relay entity IDs to boolean values (on/off) to update. Only the specified relays will be changed; others will retain their existing state within the scene.

#### Example Request (Updating name and specific relays)
```json
{
  "scene_id": "savant_movie_night",
  "name": "Cinema Mode",
  "relay_states": {
    "switch.savant_living_room_lights": true,
    "switch.savant_hallway_lights": false
  }
}
```

#### Example Request (Updating only relay states)
```json
{
  "scene_id": "savant_movie_night",
  "relay_states": {
    "switch.savant_kitchen_lights": true
  }
}
```

### Response
- On success:
  ```json
  {
    "status": "ok",
    "scene_id": "savant_movie_night"
  }
  ```
- On error:
  ```json
  {
    "status": "error",
    "message": "Scene savant_movie_night not found."
  }
  ```

## Service: `savant_energy.delete_scene`
Delete a scene by its ID. This action is irreversible.

### Request Schema
- `scene_id` (string, required): The ID of the scene to delete (e.g., `savant_movie_night`).

#### Example Request
```json
{
  "scene_id": "savant_movie_night"
}
```

### Response
- On success:
  ```json
  {
    "status": "ok",
    "scene_id": "savant_movie_night"
  }
  ```
- On error:
  ```json
  {
    "status": "error",
    "message": "Scene savant_movie_night not found."
  }
  ```

## Service: `savant_energy.save_scenes`
Overwrite all scenes in storage and Home Assistant. This is an advanced operation and should only be used for bulk updates.

### Request Schema
- `scenes` (array, required): List of scene objects, each with `name` and `relay_states`.

#### Example Request
```json
{
  "scenes": [
    {"name": "Movie Night", "relay_states": {"switch.savant_living_room": true}},
    {"name": "Party", "relay_states": {"switch.savant_kitchen": true}}
  ]
}
```

### Response
- On success:
  ```json
  {
    "status": "ok",
    "count": 2
  }
  ```
- On error:
  ```json
  {
    "status": "error",
    "message": "..."
  }
  ```

## Service: `savant_energy.get_scenes`
Retrieve all scenes as a list of metadata (scene_id and name only).

### Response
- `scenes` (array): List of scenes, each with `scene_id` and `name`.

#### Example Response
```json
{
  "scenes": [
    {"scene_id": "savant_movie_night", "name": "Movie Night"},
    {"scene_id": "savant_party", "name": "Party"}
  ]
}
```

## Service: `savant_energy.get_scene_breakers`
Retrieve the breaker (relay) states for a specific scene, merging saved states with any new breaker switches currently available in Home Assistant. New breakers are added as `false` (off) by default.

### Request Schema
- `scene_id` (string, required): The ID of the scene to query.

### Response
- `scene_id` (string): The ID of the scene.
- `breakers` (object): Dictionary of breaker entity_ids to boolean (on/off) values. Includes all current breaker switches, with saved states preserved and new breakers added as off.

#### Example Request
```json
{
  "scene_id": "savant_movie_night"
}
```

#### Example Response
```json
{
  "scene_id": "savant_movie_night",
  "breakers": {
    "switch.breaker_living_room": true,
    "switch.breaker_kitchen": false,
    "switch.breaker_new": false
  }
}
```

---

## Error Handling
- All create/update/delete/save operations will return a JSON object with a `status` key (`ok` or `error`).
- On error, a `message` key will provide details.

## Notes
- Scene names are case-insensitive and must be unique.
- Always use the integration's services to manage scenes; do not manually edit the storage file.
- The `get_scene_breakers` endpoint ensures that any new breaker switches added to the system after a scene was created will appear in the response, defaulting to off unless previously saved.
- These endpoints require authentication (use a long-lived access token or call from the Home Assistant frontend).
- For scene creation, updating, and deletion, continue to use the Home Assistant service API as documented above.
