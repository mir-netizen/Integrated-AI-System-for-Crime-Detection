import json
from kafka import KafkaConsumer, KafkaProducer
from itertools import combinations
import numpy as np
from collections import defaultdict, deque

# --- Configuration ---
# KAFKA_BROKER = 'kafka:29092'
KAFKA_BROKER = 'localhost:9092'
INPUT_TOPIC = 'pose_estimation_results'
OUTPUT_TOPIC = 'interaction_analysis_results'
INTERACTION_DISTANCE_THRESHOLD = 200 # Pixel distance between centers to be considered 'interacting'
MOTION_HISTORY_LENGTH = 10 # Number of frames to track for motion analysis

consumer = KafkaConsumer(INPUT_TOPIC, bootstrap_servers=KAFKA_BROKER, value_deserializer=lambda v: json.loads(v.decode('utf-8')))
producer = KafkaProducer(bootstrap_servers=KAFKA_BROKER, value_serializer=lambda v: json.dumps(v).encode('utf-8'))

# Track person positions and keypoints over time for motion analysis
person_history = defaultdict(lambda: {
    'positions': deque(maxlen=MOTION_HISTORY_LENGTH),
    'keypoints': deque(maxlen=MOTION_HISTORY_LENGTH),
    'timestamps': deque(maxlen=MOTION_HISTORY_LENGTH)
})

def get_box_center(box):
    x1, y1, x2, y2 = box
    return np.array([(x1 + x2) / 2, (y1 + y2) / 2])

def calculate_motion_metrics(person_id, current_keypoints):
    """Analyze motion patterns to distinguish between different activities."""
    history = person_history[person_id]
    
    if len(history['keypoints']) < 3:
        return {
            'velocity': 0.0,
            'acceleration': 0.0,
            'jerk': 0.0,
            'periodicity': 0.0,
            'limb_speed': 0.0
        }
    
    # Calculate velocity (speed of movement)
    positions = np.array(list(history['positions']))
    velocities = np.linalg.norm(np.diff(positions, axis=0), axis=1)
    avg_velocity = np.mean(velocities) if len(velocities) > 0 else 0.0
    
    # Calculate acceleration (change in velocity)
    if len(velocities) > 1:
        accelerations = np.diff(velocities)
        avg_acceleration = np.mean(np.abs(accelerations))
    else:
        avg_acceleration = 0.0
    
    # Calculate jerk (change in acceleration) - fighting tends to have high jerk
    if len(velocities) > 2:
        jerks = np.diff(np.diff(velocities))
        avg_jerk = np.mean(np.abs(jerks))
    else:
        avg_jerk = 0.0
    
    # Calculate periodicity (dancing has more periodic/rhythmic motion)
    if len(velocities) >= 5:
        # Use autocorrelation to detect periodic patterns
        velocity_normalized = (velocities - np.mean(velocities)) / (np.std(velocities) + 1e-6)
        autocorr = np.correlate(velocity_normalized, velocity_normalized, mode='full')
        autocorr = autocorr[len(autocorr)//2:]
        # Look for peaks in autocorrelation (indicates periodicity)
        if len(autocorr) > 1:
            periodicity = np.max(autocorr[1:]) / (autocorr[0] + 1e-6)
        else:
            periodicity = 0.0
    else:
        periodicity = 0.0
    
    # Calculate limb movement speed (arms/legs) - key distinguisher
    keypoints_array = np.array(list(history['keypoints']))
    if len(keypoints_array) > 1:
        # Focus on key joints: shoulders (5,6), elbows (7,8), wrists (9,10), knees (13,14), ankles (15,16)
        limb_indices = [5, 6, 7, 8, 9, 10, 13, 14, 15, 16]
        limb_movements = []
        for idx in limb_indices:
            if idx < len(current_keypoints):
                joint_positions = keypoints_array[:, idx, :2]  # x, y coordinates
                joint_velocities = np.linalg.norm(np.diff(joint_positions, axis=0), axis=1)
                if len(joint_velocities) > 0:
                    limb_movements.append(np.mean(joint_velocities))
        avg_limb_speed = np.mean(limb_movements) if limb_movements else 0.0
    else:
        avg_limb_speed = 0.0
    
    return {
        'velocity': float(avg_velocity),
        'acceleration': float(avg_acceleration),
        'jerk': float(avg_jerk),
        'periodicity': float(periodicity),
        'limb_speed': float(avg_limb_speed)
    }

def interpret_motion_pattern(motion_metrics):
    """
    Interpret motion patterns without premature classification.
    Returns descriptive characteristics that the LLM can use for context-aware analysis.
    """
    velocity = motion_metrics['velocity']
    jerk = motion_metrics['jerk']
    periodicity = motion_metrics['periodicity']
    limb_speed = motion_metrics['limb_speed']
    
    # Describe movement intensity
    if velocity < 3:
        movement_intensity = "stationary"
    elif velocity < 8:
        movement_intensity = "slow_movement"
    elif velocity < 15:
        movement_intensity = "moderate_movement"
    else:
        movement_intensity = "fast_movement"
    
    # Describe movement smoothness
    if jerk < 5:
        movement_quality = "smooth"
    elif jerk < 10:
        movement_quality = "moderate_changes"
    elif jerk < 15:
        movement_quality = "rapid_changes"
    else:
        movement_quality = "erratic"
    
    # Describe movement pattern
    if periodicity > 0.6:
        movement_pattern = "highly_rhythmic"
    elif periodicity > 0.4:
        movement_pattern = "somewhat_rhythmic"
    elif periodicity > 0.2:
        movement_pattern = "irregular"
    else:
        movement_pattern = "random"
    
    # Describe limb activity
    if limb_speed < 5:
        limb_activity = "minimal"
    elif limb_speed < 15:
        limb_activity = "moderate"
    elif limb_speed < 25:
        limb_activity = "active"
    else:
        limb_activity = "highly_active"
    
    return {
        'movement_intensity': movement_intensity,
        'movement_quality': movement_quality,
        'movement_pattern': movement_pattern,
        'limb_activity': limb_activity
    }

print("Interaction Analysis Service with Motion Detection is running...")

for message in consumer:
    data = message.value
    persons = data.get('persons', [])
    timestamp = data.get('timestamp')
    
    # Update motion history for all persons
    person_activities = {}
    for person in persons:
        person_id = person['person_id']
        center = get_box_center(person['box'])
        keypoints = np.array(person.get('keypoints', []))
        
        # Update history
        person_history[person_id]['positions'].append(center)
        person_history[person_id]['keypoints'].append(keypoints)
        person_history[person_id]['timestamps'].append(timestamp)
        
        # Calculate motion metrics
        motion_metrics = calculate_motion_metrics(person_id, keypoints)
        person_activities[person_id] = {
            'motion_metrics': motion_metrics,
            'box': person['box'],
            'center': center
        }
    
    if len(persons) < 2:
        # Single person - still analyze their activity
        if persons:
            person = persons[0]
            person_id = person['person_id']
            activity = person_activities[person_id]
            motion_interpretation = interpret_motion_pattern(activity['motion_metrics'])
            
            output_data = {
                "camera_id": data['camera_id'],
                "timestamp": timestamp,
                "groups": [],
                "individual_activities": [{
                    "person_id": person_id,
                    "motion_metrics": activity['motion_metrics'],
                    "motion_interpretation": motion_interpretation
                }],
                "clip_id": data.get('clip_id'),
                "frame_index": data.get('frame_index')
            }
            producer.send(OUTPUT_TOPIC, value=output_data)
            print(f"Single person detected - Movement: {motion_interpretation['movement_intensity']}, "
                  f"Quality: {motion_interpretation['movement_quality']}, "
                  f"Pattern: {motion_interpretation['movement_pattern']}")
        continue

    # Find pairs of people who are close to each other
    interacting_pairs = []
    pair_info = {}
    
    for p1, p2 in combinations(persons, 2):
        p1_id = p1['person_id']
        p2_id = p2['person_id']
        center1 = person_activities[p1_id]['center']
        center2 = person_activities[p2_id]['center']
        distance = np.linalg.norm(center1 - center2)
        
        if distance < INTERACTION_DISTANCE_THRESHOLD:
            pair_key = tuple(sorted([p1_id, p2_id]))
            interacting_pairs.append(pair_key)
            pair_info[pair_key] = {
                'distance': distance,
                'p1_metrics': person_activities[p1_id]['motion_metrics'],
                'p2_metrics': person_activities[p2_id]['motion_metrics']
            }

    if not interacting_pairs:
        # No interactions, but analyze individual activities
        individual_activities = []
        for person in persons:
            person_id = person['person_id']
            activity = person_activities[person_id]
            motion_interpretation = interpret_motion_pattern(activity['motion_metrics'])
            individual_activities.append({
                "person_id": person_id,
                "motion_metrics": activity['motion_metrics'],
                "motion_interpretation": motion_interpretation
            })
        
        output_data = {
            "camera_id": data['camera_id'],
            "timestamp": timestamp,
            "groups": [],
            "individual_activities": individual_activities,
            "clip_id": data.get('clip_id'),
            "frame_index": data.get('frame_index')
        }
        producer.send(OUTPUT_TOPIC, value=output_data)
        continue

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

    # Analyze each group's activity
    group_activities = []
    for group in final_groups:
        # Calculate average motion metrics for the group
        group_metrics = {
            'velocity': [],
            'jerk': [],
            'periodicity': [],
            'limb_speed': []
        }
        
        min_distance = float('inf')
        for p1_id, p2_id in combinations(group, 2):
            pair_key = tuple(sorted([p1_id, p2_id]))
            if pair_key in pair_info:
                min_distance = min(min_distance, pair_info[pair_key]['distance'])
        
        for person_id in group:
            metrics = person_activities[person_id]['motion_metrics']
            for key in group_metrics:
                group_metrics[key].append(metrics[key])
        
        # Average the metrics
        avg_metrics = {key: np.mean(values) for key, values in group_metrics.items()}
        
        # Interpret group motion pattern
        motion_interpretation = interpret_motion_pattern(avg_metrics)
        
        group_activities.append({
            "group_members": group,
            "avg_motion_metrics": avg_metrics,
            "motion_interpretation": motion_interpretation,
            "min_distance": float(min_distance)
        })

    output_data = {
        "camera_id": data['camera_id'],
        "timestamp": timestamp,
        "groups": final_groups,
        "group_activities": group_activities,
        "clip_id": data.get('clip_id'),
        "frame_index": data.get('frame_index')
    }
    producer.send(OUTPUT_TOPIC, value=output_data)
    
    for activity in group_activities:
        interp = activity['motion_interpretation']
        metrics = activity['avg_motion_metrics']
        print(f"Group {activity['group_members']} - Movement: {interp['movement_intensity']}, "
              f"Quality: {interp['movement_quality']}, Pattern: {interp['movement_pattern']}, "
              f"Distance: {activity['min_distance']:.1f}px")
        print(f"  Raw metrics: vel={metrics['velocity']:.2f}, jerk={metrics['jerk']:.2f}, "
              f"periodicity={metrics['periodicity']:.2f}, limb_speed={metrics['limb_speed']:.2f}\n")