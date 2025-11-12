import cv2
import json
import numpy as np
import os
from deepface import DeepFace
from kafka import KafkaConsumer, KafkaProducer

# --- Kafka Configuration ---
KAFKA_BROKER = os.getenv('KAFKA_BROKER', 'localhost:9092')
INPUT_TOPIC = 'raw_video_frames'
OUTPUT_TOPIC = 'facial_expression_results'

consumer = KafkaConsumer(INPUT_TOPIC, bootstrap_servers=KAFKA_BROKER, value_deserializer=lambda v: json.loads(v.decode('utf-8')))
producer = KafkaProducer(bootstrap_servers=KAFKA_BROKER, value_serializer=lambda v: json.dumps(v).encode('utf-8'))

print("Facial Expression Service is running...")

for message in consumer:
    data = message.value
    
    # Skip END_OF_CLIP markers
    if data.get('message_type') == 'END_OF_CLIP':
        continue
    
    # Skip if no frame_hex
    if 'frame_hex' not in data:
        continue
    
    frame_bytes = np.frombuffer(bytes.fromhex(data['frame_hex']), dtype=np.uint8)
    frame = cv2.imdecode(frame_bytes, cv2.IMREAD_COLOR)
    if frame is None: continue

    try:
        results = DeepFace.analyze(img_path=frame, actions=['emotion'], enforce_detection=False, detector_backend='mtcnn')
        if not isinstance(results, list): results = [results]

        faces = []
        for face_data in results:
            region = face_data['region']
            if region['w'] > 0 and region['h'] > 0:
                face_info = {"dominant_emotion": face_data['dominant_emotion'], "bounding_box": [region['x'], region['y'], region['x'] + region['w'], region['y'] + region['h']]}
                faces.append(face_info)

                # --- VISUALIZATION START (for this face) ---
                x, y, w, h = region['x'], region['y'], region['w'], region['h']
                label = face_info['dominant_emotion']
                cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 0, 255), 2)
                cv2.putText(frame, label, (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                # --- VISUALIZATION END ---

        if faces:
            output_data = {
                "camera_id": data['camera_id'], 
                "timestamp": data['timestamp'], 
                "faces": faces,
                "clip_id": data.get('clip_id'),
                "frame_index": data.get('frame_index')
            }
            producer.send(OUTPUT_TOPIC, value=output_data)
            print(f"Detected {len(faces)} faces for clip {data.get('clip_id', 'N/A')[:12]} frame {data.get('frame_index', 'N/A')}")
            print(f"output_data: {output_data}\n")
    except Exception as e:
        pass
    
    # --- VISUALIZATION START (display frame) ---
    cv2.imshow("Facial Expression Output", frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break
    # --- VISUALIZATION END ---

cv2.destroyAllWindows()
