# import os
# import json
# from collections import deque, defaultdict
# from kafka import KafkaConsumer, KafkaProducer
# from groq import Groq # CHANGED: Import Groq instead of Google's library
# import numpy as np

# # --- Configuration ---
# KAFKA_BROKER = 'localhost:9092'
# INPUT_TOPICS = ['object_detection_results', 'pose_estimation_results', 'facial_expression_results', 'scene_understanding_results']
# OUTPUT_TOPIC = 'final_analysis_alerts'
# HISTORY_LENGTH = 5
# ASSOCIATION_THRESHOLD = 0.3

# # --- Setup Groq API ---
# # CHANGED: Initialize the Groq client
# # Make sure to set your GROQ_API_KEY environment variable
# client = Groq(
# )
# MODEL_NAME = "llama-3.3-70b-versatile"   #"llama3-8b-8192" # A fast and capable model available on Groq

# # --- Kafka Clients ---
# consumer = KafkaConsumer(bootstrap_servers=KAFKA_BROKER, value_deserializer=lambda v: json.loads(v.decode('utf-8')))
# consumer.subscribe(INPUT_TOPICS)
# producer = KafkaProducer(bootstrap_servers=KAFKA_BROKER, value_serializer=lambda v: json.dumps(v).encode('utf-8'))

# # --- In-memory Buffers ---
# data_aggregator = defaultdict(dict) 
# history_buffer = defaultdict(lambda: deque(maxlen=HISTORY_LENGTH))

# def calculate_iou(boxA, boxB):
#     xA, yA = max(boxA[0], boxB[0]), max(boxA[1], boxB[1])
#     xB, yB = min(boxA[2], boxB[2]), min(boxA[3], boxB[3])
#     interArea = max(0, xB - xA) * max(0, yB - yA)
#     if interArea == 0: return 0
#     boxAArea = (boxA[2] - boxA[0]) * (boxA[3] - boxA[1])
#     boxBArea = (boxB[2] - boxB[0]) * (boxB[3] - boxB[1])
#     return interArea / float(boxAArea + boxBArea - interArea)

# def build_prompt(person_id, scrapbook, scene_caption):
#     # This function remains the same. The prompt structure is still excellent.
#     temporal_str = ""
#     for i, snapshot in enumerate(scrapbook):
#         time_offset = (len(scrapbook) - 1 - i) * 0.5
#         temporal_str += f"- t-{time_offset:.1f}s:\n"
#         temporal_str += f"  - Pose Keypoints: {snapshot.get('pose_keypoints')}\n"
#         temporal_str += f"  - Associated Objects: {snapshot.get('objects', ['none'])}\n"
#         temporal_str += f"  - Facial Emotion: {snapshot.get('emotion', 'unknown')}\n"

#     prompt = f"""
# System Instruction: You are an expert security analyst AI. Analyze the time-series data to identify behaviors and threats. Focus on the sequence of events to understand causality. Respond ONLY in the provided JSON schema.

# ## Subject ID: {person_id}
# ## Overall Scene Description: {scene_caption}

# ## Temporal Analysis (last {HISTORY_LENGTH * 0.5:.1f} seconds)
# {temporal_str}
# ## Analysis Request
# 1. Provide a detailed, descriptive label for the activity of Subject {person_id} based on the entire sequence.
# 2. Evaluate the situation and provide a suspicion score (0.0 to 1.0), severity level ('benign', 'low', 'medium', 'high'), and a concise reasoning explaining the causal links you observed.

# Respond in this JSON format:
# {{
#   "activity_description": "...",
#   "suspicion_score": 0.0,
#   "severity_level": "...",
#   "reasoning": "..."
# }}
# """
#     return prompt

# print("Generative Reasoning Service (Groq API) is running...")

# for message in consumer:
#     topic, data, timestamp = message.topic, message.value, message.value['timestamp']
#     agg = data_aggregator[timestamp]
#     agg[topic] = data

#     if 'pose_estimation_results' in agg:
#         tracked_persons = {p['person_id']: p for p in agg['pose_estimation_results']['persons']}
        
#         # Association logic remains the same
#         if 'object_detection_results' in agg:
#             for obj in agg['object_detection_results']['detections']:
#                 best_iou, best_person_id = max(((calculate_iou(p_data['bounding_box'], obj['bounding_box']), p_id) for p_id, p_data in tracked_persons.items()), default=(0, None))
#                 if best_iou > ASSOCIATION_THRESHOLD: tracked_persons[best_person_id].setdefault('objects', []).append(obj['class_name'])
        
#         if 'facial_expression_results' in agg:
#             for face in agg['facial_expression_results']['faces']:
#                 best_iou, best_person_id = max(((calculate_iou(p_data['bounding_box'], face['bounding_box']), p_id) for p_id, p_data in tracked_persons.items()), default=(0, None))
#                 if best_iou > ASSOCIATION_THRESHOLD: tracked_persons[best_person_id]['emotion'] = face['dominant_emotion']
        
#         scene_caption = agg.get('scene_understanding_results', {}).get('caption', 'N/A')

#         for person_id, person_data in tracked_persons.items():
#             snapshot = {"pose_keypoints": person_data['keypoints'], "objects": person_data.get('objects', []), "emotion": person_data.get('emotion', 'unknown')}
#             history_buffer[person_id].append(snapshot)
            
#             if len(history_buffer[person_id]) == HISTORY_LENGTH:
#                 prompt = build_prompt(person_id, history_buffer[person_id], scene_caption)
                
#                 try:
#                     # CHANGED: The API call to the LLM
#                     chat_completion = client.chat.completions.create(
#                         messages=[{"role": "user", "content": prompt}],
#                         model=MODEL_NAME,
#                         temperature=0.2, # Lower temperature for more deterministic, factual output
#                         response_format={"type": "json_object"}, # Enforce JSON output
#                     )
                    
#                     # CHANGED: How the response is parsed
#                     response_content = chat_completion.choices[0].message.content
#                     analysis = json.loads(response_content)
                    
#                     alert = {"camera_id": data['camera_id'], "timestamp": timestamp, "person_id": person_id, "analysis": analysis}
#                     producer.send(OUTPUT_TOPIC, value=alert)
#                     print(f"Generated Alert for Person {person_id}: {analysis['reasoning']}")
#                 except Exception as e:
#                     print(f"Error processing with LLM for person {person_id}: {e}")
        
#         del data_aggregator[timestamp]

import os
import json
import time
from collections import deque, defaultdict
from kafka import KafkaConsumer, KafkaProducer
from groq import Groq
import numpy as np

# --- Configuration ---
KAFKA_BROKER = 'kafka:29092' # Or Laptop A's IP if running distributed
INPUT_TOPICS = [
    'object_detection_results', 
    'pose_estimation_results', 
    'facial_expression_results', 
    'scene_understanding_results', 
    'interaction_analysis_results'
]
OUTPUT_TOPIC = 'final_analysis_alerts'
HISTORY_LENGTH = 30 # 15 seconds of data at 2 FPS
ANALYSIS_COOLDOWN_SECONDS = 60 # Analyze each subject/group once per minute
ASSOCIATION_THRESHOLD = 0.3

# --- Setup Groq API ---
client = Groq(
    api_key=os.environ.get("grok"),
)
MODEL_NAME = "llama-3.3-70b-versatile" # A fast and capable model available on Groq

# --- Kafka Clients ---
consumer = KafkaConsumer(bootstrap_servers=KAFKA_BROKER, value_deserializer=lambda v: json.loads(v.decode('utf-8')))
consumer.subscribe(INPUT_TOPICS)
producer = KafkaProducer(bootstrap_servers=KAFKA_BROKER, value_serializer=lambda v: json.dumps(v).encode('utf-8'))

# --- In-memory Buffers ---
data_aggregator = defaultdict(dict) 
history_buffer = defaultdict(lambda: deque(maxlen=HISTORY_LENGTH))
last_analysis_time = {}

# --- Helper Functions ---
def calculate_iou(boxA, boxB):
    xA, yA = max(boxA[0], boxB[0]), max(boxA[1], boxB[1])
    xB, yB = min(boxA[2], boxB[2]), min(boxA[3], boxB[3])
    interArea = max(0, xB - xA) * max(0, yB - yA)
    if interArea == 0: return 0
    boxAArea = (boxA[2] - boxA[0]) * (boxA[3] - boxA[1])
    boxBArea = (boxB[2] - boxB[0]) * (boxB[3] - boxB[1])
    return interArea / float(boxAArea + boxBArea - interArea)

def build_prompt(subject_data, is_group=False):
    
    scrapbook_for_scene = list(subject_data.values())[0] if is_group else subject_data
    start_caption = scrapbook_for_scene[0].get('scene_caption', 'N/A')
    end_caption = scrapbook_for_scene[-1].get('scene_caption', 'N/A')

    scene_str = f"""
## Scene Context Evolution (last {len(scrapbook_for_scene) * 0.5:.1f} seconds)
- Scene at start of window: {start_caption}
- Scene at end of window: {end_caption}
"""

    analysis_str = ""
    if is_group:
        analysis_str += f"## Group Interaction Analysis ({len(subject_data)} people)\n"
        for person_id, scrapbook in subject_data.items():
            analysis_str += f"\n### Subject ID: {person_id}\n"
            for i, snapshot in enumerate(scrapbook):
                time_offset = (len(scrapbook) - 1 - i) * 0.5
                analysis_str += f"- t-{time_offset:.1f}s: Objects={snapshot.get('objects', ['none'])}, Emotion={snapshot.get('emotion', 'unknown')}\n"
    else:
        person_id = subject_data[0]['person_id']
        analysis_str += f"## Temporal Analysis of Subject ID: {person_id}\n"
        for i, snapshot in enumerate(subject_data):
            time_offset = (len(subject_data) - 1 - i) * 0.5
            analysis_str += f"- t-{time_offset:.1f}s: Objects={snapshot.get('objects', ['none'])}, Emotion={snapshot.get('emotion', 'unknown')}\n"

    request_str = "Analyze the group's interaction" if is_group else "Analyze the subject's actions"
    request_str += " within the context of the evolving scene. Provide a suspicion score, severity, and reasoning."
    request_str +="also while making descion analyse pose and scene description for action and compare if it is reallly suspicious or not"
    
    prompt = f"""
System Instruction: You are an expert security analyst AI. Analyze the time-series data to identify behaviors and threats. Respond ONLY in a single, valid JSON object.

{scene_str}
{analysis_str}
## Analysis Request
{request_str}

Respond in this JSON format:
{{
  "activity_description": "...",
  "suspicion_score": 0.0,
  "severity_level": "...",
  "reasoning": "..."
}}
"""
    return prompt

def perform_analysis(subject_id, prompt_data, is_group):
    """Generic function to call the LLM and send an alert."""
    prompt = build_prompt(prompt_data, is_group)
    try:
        chat_completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=MODEL_NAME, temperature=0.2,
            response_format={"type": "json_object"},
        )
        response_content = chat_completion.choices[0].message.content
        analysis = json.loads(response_content)
        
        person_ids = list(prompt_data.keys()) if is_group else [subject_id]

        for pid in person_ids:
            last_snapshot = prompt_data[pid][-1] if is_group else prompt_data[-1]
            alert = {
                "camera_id": "Camera_01_Lobby",
                "timestamp": time.time(),
                "person_id": pid,
                "analysis": analysis,
                "feature": last_snapshot.get('feature', None)
            }
            if analysis['severity_level'] in ['low','medium', 'high']:
                alert['feature'] = last_snapshot.get('feature')

            producer.send(OUTPUT_TOPIC, value=alert)
        
        print(f"Generated Alert for Subject(s) {alert}")

    except Exception as e:
        print(f"Error processing with LLM for {subject_id}: {e}")

print("Generative Reasoning Service (Groq API) is running...")

for message in consumer:
    topic, data, timestamp = message.topic, message.value, message.value['timestamp']
    ts_key = int(timestamp)
    agg = data_aggregator[ts_key]
    agg[topic] = data

    if 'pose_estimation_results' in agg:
        tracked_persons = {p['person_id']: p for p in agg['pose_estimation_results']['persons']}
        scene_caption = agg.get('scene_understanding_results', {}).get('caption', 'N/A')
        
        if 'object_detection_results' in agg:
            for obj in agg['object_detection_results']['detections']:
                best_iou, best_person_id = max(((calculate_iou(p_data['box'], obj['bounding_box']), p_id) for p_id, p_data in tracked_persons.items()), default=(0, None))
                if best_iou > ASSOCIATION_THRESHOLD: tracked_persons[best_person_id].setdefault('objects', []).append(obj['class_name'])
        
        if 'facial_expression_results' in agg:
            for face in agg['facial_expression_results']['faces']:
                best_iou, best_person_id = max(((calculate_iou(p_data['box'], face['bounding_box']), p_id) for p_id, p_data in tracked_persons.items()), default=(0, None))
                if best_iou > ASSOCIATION_THRESHOLD: tracked_persons[best_person_id]['emotion'] = face['dominant_emotion']
        
        for person_id, person_data in tracked_persons.items():
            snapshot = {
                "person_id": person_id,
                "pose_keypoints": person_data['keypoints'], 
                "objects": person_data.get('objects', []), 
                "emotion": person_data.get('emotion', 'unknown'),
                "scene_caption": scene_caption,
                "feature": person_data.get('feature')
            }
            
            history_buffer[person_id].append(snapshot)

        groups = agg.get('interaction_analysis_results', {}).get('groups', [])
        people_in_groups = {p_id for group in groups for p_id in group}
        
        current_time = time.time()
        
        for group in groups:
            group_id = tuple(sorted(group))
            if all(len(history_buffer[p_id]) == HISTORY_LENGTH for p_id in group_id):
                if current_time - last_analysis_time.get(group_id, 0) > ANALYSIS_COOLDOWN_SECONDS:
                    group_scrapbooks = {p_id: history_buffer[p_id] for p_id in group_id}
                    perform_analysis(group_id, group_scrapbooks, is_group=True)
                    last_analysis_time[group_id] = current_time

        for person_id in tracked_persons:
            if person_id not in people_in_groups:
                if len(history_buffer[person_id]) == HISTORY_LENGTH:
                    if current_time - last_analysis_time.get(person_id, 0) > ANALYSIS_COOLDOWN_SECONDS:
                        perform_analysis(person_id, history_buffer[person_id], is_group=False)
                        last_analysis_time[person_id] = current_time
        
        if ts_key in data_aggregator: del data_aggregator[ts_key]