import cv2
import json
import numpy as np
from kafka import KafkaConsumer
import time
import torch

# --- Configuration ---
KAFKA_BROKER = 'localhost:9092'
INPUT_TOPICS = [
    'raw_video_frames',
    'pose_estimation_results',
    'final_analysis_alerts',
    'suspicious_features_gallery' # ADDED: Listen for the database of suspicious people
]
WINDOW_NAME = "AI Surveillance Live Feed"
SIMILARITY_THRESHOLD = 0.85 # High threshold for a confident match

# --- State Management ---
latest_frame = None
person_states = {} # {person_id: {'box': [], 'severity': 'benign', 'feature': ...}}
suspicious_gallery = [] # This will hold the latest gallery of suspicious fingerprints

def get_color_for_severity(severity, suspicion_score, is_known_suspicious):
    """Returns a BGR color tuple based on the alert and tracking status."""
    # Blue for a known suspicious person takes highest priority
    if is_known_suspicious:
        return (255, 0, 0) # Blue
    # if severity == 'high' and suspicion_score >= 0.7:
    #     return (0, 0, 255)  # Red
    # elif severity in ['medium', 'low']:
    #     return (0, 165, 255) # Orange
    else:
        return (0, 255, 0)   # Green

def cosine_similarity(feature1, feature2):
    """Calculates similarity between two appearance fingerprints."""
    feature1_norm = torch.nn.functional.normalize(feature1, p=2, dim=0)
    feature2_norm = torch.nn.functional.normalize(feature2, p=2, dim=0)
    return torch.dot(feature1_norm, feature2_norm).item()

# --- Kafka Client ---
consumer = KafkaConsumer(
    *INPUT_TOPICS,
    bootstrap_servers=KAFKA_BROKER,
    value_deserializer=lambda v: json.loads(v.decode('utf-8')),
    auto_offset_reset='latest'
)

print("Visualization Service is running... Press 'q' in the video window to quit.")
cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)

while True:
    messages = consumer.poll(timeout_ms=1, max_records=100)
    for topic_partition, records in messages.items():
        for record in records:
            topic = record.topic
            data = record.value
            
            # ADDED: Handle the new gallery topic
            if topic == 'suspicious_features_gallery':
                suspicious_gallery = [torch.tensor(f) for f in data['gallery']]
                continue # No need to do anything else with this message

            if topic == 'raw_video_frames':
                frame_bytes = np.frombuffer(bytes.fromhex(data['frame_hex']), dtype=np.uint8)
                latest_frame = cv2.imdecode(frame_bytes, cv2.IMREAD_COLOR)

            elif topic == 'pose_estimation_results':
                for person in data.get('persons', []):
                    pid = person['person_id']
                    if pid not in person_states:
                        person_states[pid] = {}
                    person_states[pid]['box'] = person['box']
                    # ADDED: Store the person's current appearance feature
                    if 'feature' in person:
                        person_states[pid]['feature'] = person['feature']
                    person_states[pid]['last_seen'] = time.time()

            elif topic == 'final_analysis_alerts':
                pid = data['person_id']
                if pid not in person_states:
                    person_states[pid] = {}
                person_states[pid]['severity'] = data['analysis']['severity_level']
                person_states[pid]['suspicion_score'] = data['analysis']['suspicion_score']
                person_states[pid]['alert_timestamp'] = data['timestamp']
                person_states[pid]['last_seen'] = time.time()

    if latest_frame is not None:
        display_frame = latest_frame.copy()
        
        current_time = time.time()
        stale_pids = [pid for pid, state in person_states.items() if current_time - state.get('last_seen', 0) > 5.0]
        for pid in stale_pids:
            del person_states[pid]

        for pid, state in person_states.items():
            box = state.get('box')
            severity = state.get('severity', 'benign')
            suspicion_score = state.get('suspicion_score', 0.0)
            
            if box:
                # ADDED: The "Compare" logic
                is_known_suspicious = False
                current_feature = state.get('feature')
                if current_feature and suspicious_gallery:
                    current_feature_tensor = torch.tensor(current_feature)
                    for known_feature in suspicious_gallery:
                        if cosine_similarity(current_feature_tensor, known_feature) > SIMILARITY_THRESHOLD:
                            is_known_suspicious = True
                            break

                color = get_color_for_severity(severity, suspicion_score, is_known_suspicious)
                x1, y1, x2, y2 = box
                cv2.rectangle(display_frame, (x1, y1), (x2, y2), color, 2)
                
                label = f"Person {pid}: {severity.upper()}"
                
                # ADDED: Update label if person is a known suspicious individual
                if is_known_suspicious:
                    label = f"Person {pid}: KNOWN SUSPICIOUS"
                
                alert_ts = state.get('alert_timestamp')
                if alert_ts:
                    ts_str = time.strftime('%H:%M:%S', time.localtime(alert_ts))
                    label += f" ({ts_str})"
                
                cv2.putText(display_frame, label, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

        cv2.imshow(WINDOW_NAME, display_frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

consumer.close()
cv2.destroyAllWindows()
print("Visualization service stopped.")

