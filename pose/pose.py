import cv2
import json
import numpy as np
from kafka import KafkaConsumer, KafkaProducer
import torch
import torchreid
from ultralytics import YOLO
from boxmot import BoTSORT
from pathlib import Path
from PIL import Image

# --- Configuration ---
KAFKA_BROKER = 'kafka:29092'
INPUT_TOPIC = 'raw_video_frames'
OUTPUT_TOPIC = 'pose_estimation_results'

# --- AI Model Setup ---
pose_model = YOLO('yolov8n-pose.pt')
tracker = BoTSORT(
    model_weights=Path('osnet_x0_25_msmt17.pt'),
    device='cuda:0' if torch.cuda.is_available() else 'cpu',
    fp16=False,
    track_buffer=120,
    proximity_thresh=0.85,
    # Standard threshold for matching based on motion/location
    match_thresh=0.7
)

# --- Re-ID Feature Extractor Setup ---
device = 'cuda:0' if torch.cuda.is_available() else 'cpu'
transform, _ = torchreid.data.transforms.build_transforms(is_train=False, height=256, width=128)
reid_model = torchreid.models.build_model(name='osnet_x0_25', num_classes=1, pretrained=True)
reid_model.eval().to(device)

def get_features(frame, boxes):
    feature_dict = {}
    valid_crops, valid_boxes = [], []
    for box in boxes:
        x1, y1, x2, y2 = map(int, box)
        crop = frame[y1:y2, x1:x2]
        if crop.size > 0:
            valid_crops.append(crop)
            valid_boxes.append(box)
    if not valid_crops: return feature_dict
    images = [transform(Image.fromarray(cv2.cvtColor(c, cv2.COLOR_BGR2RGB))) for c in valid_crops]
    images = torch.stack(images).to(device)
    with torch.no_grad():
        features = reid_model(images)
    for i, box in enumerate(valid_boxes):
        feature_dict[tuple(box)] = features[i]
    return feature_dict

# --- Kafka Clients ---
consumer = KafkaConsumer(INPUT_TOPIC, bootstrap_servers=KAFKA_BROKER, value_deserializer=lambda v: json.loads(v.decode('utf-8')))
producer = KafkaProducer(bootstrap_servers=KAFKA_BROKER, value_serializer=lambda v: json.dumps(v).encode('utf-8'))

# --- Helper Function for IoU ---
def calculate_iou(boxA, boxB):
    xA, yA = max(boxA[0], boxB[0]), max(boxA[1], boxB[1])
    xB, yB = min(boxA[2], boxB[2]), min(boxA[3], boxB[3])
    interArea = max(0, xB - xA) * max(0, yB - yA)
    if interArea == 0: return 0
    boxAArea = (boxA[2] - boxA[0]) * (boxA[3] - boxA[1])
    boxBArea = (boxB[2] - boxB[0]) * (boxB[3] - boxB[1])
    return interArea / float(boxAArea + boxBArea - interArea)

print("Pose Estimation Service (BoTSORT - Final Fix) is running...")

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
    
    results = pose_model(frame)
    persons_in_frame = []

    if results[0].boxes is not None and len(results[0].boxes) > 0:
        detections_tensor = torch.cat([
            results[0].boxes.xyxy,
            results[0].boxes.conf.unsqueeze(1),
            results[0].boxes.cls.unsqueeze(1)
        ], dim=1)

        tracks = tracker.update(detections_tensor.cpu().numpy(), frame)

        if tracks.size > 0:
            # 1. Create a list of the original YOLO detections with their keypoints
            yolo_detections = []
            if results[0].keypoints is not None:
                for i in range(len(results[0].boxes)):
                    box = results[0].boxes.xyxy[i].cpu().numpy().astype(int)
                    keypoints_data = results[0].keypoints.data[i].cpu().numpy()
                    h, w, _ = frame.shape
                    kpts = [[float(y/h), float(x/w), float(c)] for x, y, c in keypoints_data]
                    yolo_detections.append({'box': box, 'keypoints': kpts})

            # 2. Get features for all the final tracked boxes at once
            tracked_boxes = tracks[:, :4].astype(int) # <-- THE FIX IS HERE
            feature_map = get_features(frame, tracked_boxes)

            # 3. Loop through each final track and build the person object
            for track in tracks:
                track_box = track[:4].astype(int)
                track_id = int(track[4])
                
                # Find the best YOLO detection that matches this track by IoU
                best_iou = 0
                best_kpts = []
                for det in yolo_detections:
                    iou = calculate_iou(track_box, det['box'])
                    if iou > best_iou:
                        best_iou = iou
                        best_kpts = det['keypoints']
                
                person_info = {
                    "person_id": track_id,
                    "box": [int(c) for c in track_box],
                    "keypoints": best_kpts # Now associated via IoU
                }

                # Safely get the feature for this track's box
                if tuple(track_box) in feature_map:
                    person_info["feature"] = feature_map[tuple(track_box)].tolist()
                
                persons_in_frame.append(person_info)
    
    if persons_in_frame:
        output_data = {"camera_id": data['camera_id'], "timestamp": data['timestamp'], "persons": persons_in_frame}
        producer.send(OUTPUT_TOPIC, value=output_data)
        print(f"Processed frame at {data['timestamp']}, detected {len(persons_in_frame)} persons.\n")
        print(f"keypoints: {person_info['keypoints']}\n")
        # print(f"feature: {person_info['feature']}\n")