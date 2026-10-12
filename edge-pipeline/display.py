import cv2
import numpy as np


PPE_LABELS = {
    "helmet": "HEL",
    "vest": "VST",
}


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


def draw_person_alert(
    frame,
    box,
    center_point,
    alert_level,
    ppe_violations,
    track_id=None,
    unknown_ppe_count=0,
):
    """Draw a worker box, foot point, stable track ID and alert summary."""
    x1, y1, x2, y2 = box

    # Choose drawing color based on alert level
    color = (0, 90, 205)  # Muted burnt orange for NORMAL
    if alert_level == "WARNING":
        color = (0, 65, 210)  # Dark red-orange
    elif alert_level == "CRITICAL":
        color = (35, 45, 190)  # Dark red

    # Draw person box
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

    # Draw foot center (small filled circle)
    cv2.circle(frame, center_point, 5, color, -1)

    # Display alert text
    label_parts = []
    if track_id is not None:
        label_parts.append(f"ID {track_id}")
    label_parts.extend(
        (
            alert_level,
            f"PPE Miss: {len(ppe_violations)}",
            f"Unknown: {unknown_ppe_count}",
        )
    )
    label = " | ".join(label_parts)
    cv2.putText(
        frame,
        label,
        (x1, max(y1 - 10, 0)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        color,
        2,
    )


def _alert_color(alert_level):
    if alert_level == "CRITICAL":
        return (35, 45, 190)  # Dark red
    if alert_level == "WARNING":
        return (0, 65, 210)  # Dark red-orange
    return (0, 90, 205)  # Muted burnt orange


def _fit_text(text, max_chars=30):
    return text if len(text) <= max_chars else f"{text[:max_chars - 3]}..."


def draw_worker_card(frame, state, alert_level):
    """Draw one worker box with a compact, readable PPE status card."""
    x1, y1, x2, y2 = state["person"]["box"]
    frame_height, frame_width = frame.shape[:2]
    scale = max(0.35, min(0.44, frame_width / 4100))
    color = _alert_color(alert_level)
    thickness = max(2, round(frame_width / 900))
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, thickness)
    cv2.circle(frame, tuple(state["person"]["foot_point"]), thickness + 2, color, -1)

    worn = []
    missing = []
    unknown = []
    for ppe_type, record in state["ppe"].items():
        label = PPE_LABELS.get(ppe_type, ppe_type[:3].upper())
        confidence = f"{record['confidence'] * 100:.0f}"
        if record["state"] == "WORN":
            worn.append(f"{label} {confidence}")
        elif record["state"] == "NOT_WORN":
            missing.append(f"{label} {confidence}")
        else:
            unknown.append(label)

    rows = [
        (f"WORKER {state['track_id']}", color, True),
        (f"CONF  {state['person']['confidence'] * 100:.0f}%", (0, 0, 0), False),
        (_fit_text("WORN  " + (" ".join(worn) if worn else "-"), 25), (0, 0, 0), False),
        (_fit_text("MISS  " + (" ".join(missing) if missing else "-"), 25), (0, 0, 0), False),
        (_fit_text(f"UNK{len(unknown)} " + (" ".join(unknown) if unknown else "-"), 25), (0, 0, 0), False),
    ]
    card_width = max(180, min(220, round(frame_width * 0.115)))
    row_height = max(17, round(21 * scale))
    card_height = 10 + row_height * len(rows)
    gap = 5
    card_x1 = x2 + gap
    if card_x1 + card_width > frame_width - 4:
        card_x1 = max(4, x1 - card_width - gap)
    card_y1 = max(4, min(y1, frame_height - card_height - 4))
    card_x2 = card_x1 + card_width
    card_y2 = card_y1 + card_height

    overlay = frame.copy()
    cv2.rectangle(overlay, (card_x1, card_y1), (card_x2, card_y2), (245, 245, 241), -1)
    cv2.addWeighted(overlay, 0.84, frame, 0.16, 0, frame)
    cv2.rectangle(frame, (card_x1, card_y1), (card_x2, card_y2), color, 1)
    cv2.line(frame, (card_x1, card_y1 + row_height + 3), (card_x2, card_y1 + row_height + 3), color, 1)

    for index, (text, text_color, strong) in enumerate(rows):
        baseline = card_y1 + 6 + row_height * (index + 1) - 5
        cv2.putText(
            frame,
            text,
            (card_x1 + 7, baseline),
            cv2.FONT_HERSHEY_SIMPLEX,
            scale + (0.04 if strong else 0),
            text_color,
            2 if strong else 1,
            cv2.LINE_AA,
        )


def draw_debug_detections(frame, person_detections, ppe_detections):
    """Draw every raw detector box and confidence for model inspection."""
    groups = (
        (person_detections, (0, 90, 205), "PERSON"),
        (ppe_detections, (35, 45, 190), "PPE"),
    )
    for detections, color, prefix in groups:
        for detection in detections:
            x1, y1, x2, y2 = detection["box"]
            class_name = str(detection.get("class_name", prefix)).upper()
            confidence = float(detection.get("conf", 0.0)) * 100
            label = f"{prefix} / {class_name} / {confidence:.0f}%"
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            (text_width, text_height), _ = cv2.getTextSize(
                label, cv2.FONT_HERSHEY_SIMPLEX, 0.48, 1
            )
            label_y1 = max(0, y1 - text_height - 12)
            label_overlay = frame.copy()
            cv2.rectangle(
                label_overlay,
                (x1, label_y1),
                (min(frame.shape[1] - 1, x1 + text_width + 10), y1),
                (232, 232, 224),
                -1,
            )
            cv2.addWeighted(label_overlay, 0.66, frame, 0.34, 0, frame)
            cv2.putText(
                frame,
                label,
                (x1 + 5, max(text_height + 2, y1 - 5)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.48,
                color,
                1,
                cv2.LINE_AA,
            )
def draw_other_detections(
    frame,
    other_detections,
    color=(255, 255, 0),
    label_prefix="",
):
    """Draw PPE evidence, optionally identifying its worker association."""
    for det in other_detections:
        x1, y1, x2, y2 = det["box"]
        label = f"{label_prefix}{det['class_name']} {det['conf']}"
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        cv2.putText(
            frame,
            label,
            (x1, max(y1 - 5, 0)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            color,
            2,
        )
