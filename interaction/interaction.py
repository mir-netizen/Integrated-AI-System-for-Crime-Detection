import json
from kafka import KafkaConsumer, KafkaProducer
from itertools import combinations
import numpy as np

# --- Configuration ---
KAFKA_BROKER = 'kafka:29092'
INPUT_TOPIC = 'pose_estimation_results'
OUTPUT_TOPIC = 'interaction_analysis_results'
INTERACTION_DISTANCE_THRESHOLD = 200 # Pixel distance between centers to be considered 'interacting'

consumer = KafkaConsumer(INPUT_TOPIC, bootstrap_servers=KAFKA_BROKER, value_deserializer=lambda v: json.loads(v.decode('utf-8')))
producer = KafkaProducer(bootstrap_servers=KAFKA_BROKER, value_serializer=lambda v: json.dumps(v).encode('utf-8'))

def get_box_center(box):
    x1, y1, x2, y2 = box
    return np.array([(x1 + x2) / 2, (y1 + y2) / 2])

print("Interaction Analysis Service is running...")

for message in consumer:
    data = message.value
    persons = data.get('persons', [])
    if len(persons) < 2: continue

    # Find pairs of people who are close to each other
    interacting_pairs = []
    for p1, p2 in combinations(persons, 2):
        center1 = get_box_center(p1['box'])
        center2 = get_box_center(p2['box'])
        distance = np.linalg.norm(center1 - center2)
        
        if distance < INTERACTION_DISTANCE_THRESHOLD:
            interacting_pairs.append(sorted([p1['person_id'], p2['person_id']]))

    if not interacting_pairs: continue

    # Union-find algorithm to merge pairs into larger groups
    parent = {person['person_id']: person['person_id'] for person in persons}
    def find(i):
        if parent[i] == i: return i
        parent[i] = find(parent[i])
        return parent[i]
    def union(i, j):
        root_i = find(i)
        root_j = find(j)
        if root_i != root_j: parent[root_j] = root_i

    for p1_id, p2_id in interacting_pairs:
        union(p1_id, p2_id)
        
    groups = {}
    for person in persons:
        root = find(person['person_id'])
        if root not in groups: groups[root] = []
        groups[root].append(person['person_id'])

    final_groups = [g for g in groups.values() if len(g) > 1]

    if final_groups:
        output_data = {"camera_id": data['camera_id'], "timestamp": data['timestamp'], "groups": final_groups}
        producer.send(OUTPUT_TOPIC, value=output_data)
        print(f"Detected {len(final_groups)} interacting group(s): {final_groups}")