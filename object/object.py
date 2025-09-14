import cv2
import json
import numpy as np
from ultralytics import YOLO
from kafka import KafkaConsumer, KafkaProducer

# --- Kafka Configuration ---
KAFKA_BROKER = 'kafka:29092'
# KAFKA_BROKER = '10.139.40.73:9092'
INPUT_TOPIC = 'raw_video_frames'
OUTPUT_TOPIC = 'object_detection_results'

consumer = KafkaConsumer(INPUT_TOPIC, bootstrap_servers=KAFKA_BROKER, value_deserializer=lambda v: json.loads(v.decode('utf-8')))
producer = KafkaProducer(bootstrap_servers=KAFKA_BROKER, value_serializer=lambda v: json.dumps(v).encode('utf-8'))

model = YOLO('yolov8n.pt')
print("Object Detection Service is running...")

for message in consumer:
    data = message.value
    frame_bytes = np.frombuffer(bytes.fromhex(data['frame_hex']), dtype=np.uint8)
    frame = cv2.imdecode(frame_bytes, cv2.IMREAD_COLOR)
    if frame is None: continue

    results = model(frame)
    result = results[0]
    
    detections = []
    if result.boxes is not None and len(result.boxes) > 0:
        boxes, confs, class_ids = result.boxes.xyxy.cpu().numpy(), result.boxes.conf.cpu().numpy(), result.boxes.cls.cpu().numpy()
        for box, conf, cls in zip(boxes, confs, class_ids):
            if conf > 0.5:
                detection_data = {"class_name": result.names[int(cls)], "confidence": float(conf), "bounding_box": [int(coord) for coord in box]}
                detections.append(detection_data)
                
                # # --- VISUALIZATION START (for this object) ---
                # x1, y1, x2, y2 = detection_data['bounding_box']
                # label = f"{detection_data['class_name']}: {detection_data['confidence']:.2f}"
                # cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                # cv2.putText(frame, label, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
                # # --- VISUALIZATION END ---

    if detections:
        output_data = {"camera_id": data['camera_id'], "timestamp": data['timestamp'], "detections": detections}
        producer.send(OUTPUT_TOPIC, value=output_data)
        print(f"Detected {len(detections)} objects for frame {data['timestamp']}")

    # # --- VISUALIZATION START (display frame) ---
    # cv2.imshow("Object Detection Output", frame)
    # if cv2.waitKey(1) & 0xFF == ord('q'):
    #     break
    # # --- VISUALIZATION END ---

# cv2.destroyAllWindows()