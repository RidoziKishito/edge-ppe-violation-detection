import cv2
import numpy as np


def point_in_polygon(point, polygon):
    """
    Check whether a point (x, y) lies inside a polygon.
    Uses cv2.pointPolygonTest for very fast performance.
    """
    poly_array = np.array(polygon, np.int32)
    # Returns > 0 if inside, = 0 if on edge, < 0 if outside
    result = cv2.pointPolygonTest(poly_array, point, False)
    return result >= 0


def get_person_zones(person_center, zones_config):
    """
    Return the list of zones that the person is currently inside.
    """
    active_zones = []
    for zone in zones_config.get("zones", []):
        if point_in_polygon(person_center, zone["polygon"]):
            active_zones.append(zone)
    return active_zones


def check_ppe_violation(person_box, all_detections):
    """
    Check whether this person is missing required PPE.
    Approach: scan the Dataset V2 negative labels 'no_helmet' and 'no_vest'.
    If the center of such detection lies inside the person's bbox -> count as violation.
    """
    px1, py1, px2, py2 = person_box
    violations = []

    violation_classes = ["no_helmet", "no_vest"]

    for det in all_detections:
        cls_name = det["class_name"]
        if cls_name in violation_classes:
            # Compute center of violation object
            vx1, vy1, vx2, vy2 = det["box"]
            v_center_x = (vx1 + vx2) // 2
            v_center_y = (vy1 + vy2) // 2

            # If the violation center lies inside the person's bbox
            if px1 <= v_center_x <= px2 and py1 <= v_center_y <= py2:
                violations.append(cls_name)

    return violations


def associate_ppe_detections(persons, ppe_detections):
    """Assign each PPE detection to at most one tracked person.

    The baseline remains center containment. If multiple overlapping person boxes
    contain the same PPE center, the evidence is left unassigned instead of being
    counted for both workers.
    """
    assignments = {int(person["track_id"]): [] for person in persons}
    unassigned = []

    for detection in ppe_detections:
        class_name = detection["class_name"].lower()
        if class_name == "none":
            unassigned.append(
                {**detection, "reason_code": "UNMAPPED_CLASS"}
            )
            continue

        x1, y1, x2, y2 = detection["box"]
        center = ((x1 + x2) / 2, (y1 + y2) / 2)
        owners = []
        for person in persons:
            px1, py1, px2, py2 = person["box"]
            if px1 <= center[0] <= px2 and py1 <= center[1] <= py2:
                owners.append(person)

        if len(owners) == 1:
            assignments[int(owners[0]["track_id"])].append(detection)
        else:
            reason = "NO_VALID_PERSON_OWNER" if not owners else "AMBIGUOUS_OWNER"
            unassigned.append({**detection, "reason_code": reason})

    return assignments, unassigned


def classify_alert(active_zones, ppe_violations):
    """
    Classify alert level based on Zone type and PPE violations.
    Returns one of: NORMAL, WARNING, or CRITICAL
    """
    is_danger_zone = any(z["type"] == "danger_zone" for z in active_zones)
    is_warning_zone = any(z["type"] == "warning_zone" for z in active_zones)
    has_violation = len(ppe_violations) > 0

    # CRITICAL cases
    if is_danger_zone and has_violation:
        return "CRITICAL"
    if is_warning_zone and has_violation:
        return "CRITICAL"

    # WARNING cases
    if is_danger_zone and not has_violation:
        return "WARNING"
    if is_warning_zone and not has_violation:
        return "WARNING"
    if not is_danger_zone and not is_warning_zone and has_violation:
        return "WARNING"

    # NORMAL case
    return "NORMAL"
