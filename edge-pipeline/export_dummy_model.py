from ultralytics import YOLO

# Load the pre-trained YOLO11 nano model
model = YOLO("yolo11n.pt")

# Export to ONNX format
model.export(format="onnx")
