import cv2
import json
import torch
import numpy as np
from PIL import Image
from transformers import BlipProcessor, BlipForConditionalGeneration
from kafka import KafkaConsumer, KafkaProducer

# --- Kafka Configuration ---
# KAFKA_BROKER = 'kafka:29092'
KAFKA_BROKER = 'localhost:9092'
# KAFKA_BROKER = '10.139.40.73:9092'
INPUT_TOPIC = 'raw_video_frames'
OUTPUT_TOPIC = 'scene_understanding_results'

consumer = KafkaConsumer(INPUT_TOPIC, bootstrap_servers=KAFKA_BROKER, value_deserializer=lambda v: json.loads(v.decode('utf-8')))
producer = KafkaProducer(bootstrap_servers=KAFKA_BROKER, value_serializer=lambda v: json.dumps(v).encode('utf-8'))

# --- BLIP Model ---
device = "cuda" if torch.cuda.is_available() else "cpu"
processor = BlipProcessor.from_pretrained("Salesforce/blip-image-captioning-base")
model = BlipForConditionalGeneration.from_pretrained("Salesforce/blip-image-captioning-base").to(device)

print("Scene Understanding Service is running...")

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

    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    pil_image = Image.fromarray(rgb_frame)
    
    inputs = processor(pil_image, return_tensors="pt").to(device)
    with torch.no_grad():
        output = model.generate(**inputs)
    caption = processor.decode(output[0], skip_special_tokens=True)
    
    output_data = {
        "camera_id": data['camera_id'], 
        "timestamp": data['timestamp'], 
        "caption": caption,
        "clip_id": data.get('clip_id'),
        "frame_index": data.get('frame_index')
    }
    producer.send(OUTPUT_TOPIC, value=output_data)
    print(f"Generated caption for clip {data.get('clip_id', 'N/A')[:12]} frame {data.get('frame_index', 'N/A')}: '{caption}'")