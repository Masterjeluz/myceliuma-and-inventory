import secrets
import time


def _generate_id(prefix: str) -> str:
    timestamp_ms = int(time.time() * 1000)
    random_part = secrets.token_hex(4)
    return f"{prefix}_{timestamp_ms:x}{random_part}"


def generate_object_id() -> str:
    """Generate a collision-resistant, sortable, stable object ID (obj_...)."""
    return _generate_id("obj")


def generate_project_id() -> str:
    """Generate a collision-resistant, sortable, stable project ID (proj_...)."""
    return _generate_id("proj")


def generate_idea_id() -> str:
    """Generate a collision-resistant, sortable, stable idea ID (idea_...)."""
    return _generate_id("idea")


def generate_relationship_id() -> str:
    """Generate a collision-resistant, sortable, stable relationship ID (rel_...)."""
    return _generate_id("rel")


def generate_event_id() -> str:
    """Generate a collision-resistant, sortable, stable event ID (evt_...)."""
    return _generate_id("evt")


def generate_hardware_id() -> str:
    """Generate a collision-resistant, sortable, stable hardware ID (hw_...)."""
    return _generate_id("hw")


def generate_sensor_id() -> str:
    """Generate a collision-resistant, sortable, stable sensor ID (sns_...)."""
    return _generate_id("sns")


def generate_camera_id() -> str:
    """Generate a collision-resistant, sortable, stable camera ID (cam_...)."""
    return _generate_id("cam")


def generate_location_id() -> str:
    """Generate a collision-resistant, sortable, stable location ID (loc_...)."""
    return _generate_id("loc")


def generate_model_id() -> str:
    """Generate a collision-resistant, sortable, stable model ID (mod_...)."""
    return _generate_id("mod")


def generate_task_id() -> str:
    """Generate a collision-resistant, sortable, stable task ID (task_...)."""
    return _generate_id("task")


def generate_actuator_id() -> str:
    """Generate a collision-resistant, sortable, stable actuator ID (act_...)."""
    return _generate_id("act")


def generate_file_id() -> str:
    """Generate a collision-resistant, sortable, stable file ID (file_...)."""
    return _generate_id("file")
