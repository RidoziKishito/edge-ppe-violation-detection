import cv2
import numpy as np


def draw_zones(frame, zones_config):
    """Draw safety / danger zones on the frame"""
    for zone in zones_config.get("zones", []):
        pts = np.array(zone["polygon"], np.int32).reshape((-1, 1, 2))
        color = (0, 0, 255) if zone["type"] == "danger_zone" else (0, 255, 255)
        cv2.polylines(frame, [pts], isClosed=True, color=color, thickness=2)
        cv2.putText(
            frame,
            zone["name"],
            (pts[0][0][0], pts[0][0][1] - 5),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            color,
            2,
        )


def draw_person_alert(frame, box, center_point, alert_level, ppe_violations):
    """Draw person's bounding box, foot center dot and alert text"""
    x1, y1, x2, y2 = box

    # Choose drawing color based on alert level
    color = (0, 255, 0)  # Green for NORMAL
    if alert_level == "WARNING":
        color = (0, 165, 255)  # Orange
    elif alert_level == "CRITICAL":
        color = (0, 0, 255)  # Red

    # Draw person box
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

    # Draw foot center (small filled circle)
    cv2.circle(frame, center_point, 5, color, -1)

    # Display alert text
    label = f"{alert_level} | PPE Miss: {len(ppe_violations)}"
    cv2.putText(
        frame,
        label,
        (x1, max(y1 - 10, 0)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        color,
        2,
    )


def draw_other_detections(frame, other_detections):
    """Draw other PPE detections (helmet, vest, etc.) for debugging"""
    for det in other_detections:
        x1, y1, x2, y2 = det["box"]
        label = f"{det['class_name']} {det['conf']}"
        # Draw light blue box for debug detections
        cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 255, 0), 2)
        cv2.putText(
            frame,
            label,
            (x1, max(y1 - 5, 0)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (255, 255, 0),
            2,
        )
