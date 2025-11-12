from flask import Flask, render_template, Response, jsonify, request
from kafka import KafkaConsumer, KafkaProducer
import json
import cv2
import numpy as np
from datetime import datetime
import threading
import time
from collections import deque
import os
import uuid
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB max file size

# Create upload folder if not exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Global variables for storing latest data from ALL 7 modules
latest_detections = deque(maxlen=50)
active_alerts = []
system_stats = {
    'total_frames_processed': 0,
    'violent_events': 0,
    'suspicious_events': 0,
    'normal_events': 0,
    'cameras_active': set()
}

# Module-specific data storage
module_data = {
    'pose': deque(maxlen=20),
    'object': deque(maxlen=20),
    'weapon': deque(maxlen=20),
    'face': deque(maxlen=20),
    'scene': deque(maxlen=20),
    'interaction': deque(maxlen=20),
    'action': deque(maxlen=20),
    'decision': deque(maxlen=20),
    'output': deque(maxlen=20)
}

# Frame storage by timestamp/camera_id for matching with detections
frame_storage = {}  # Key: (camera_id, timestamp) -> Value: frame_hex
frame_storage_lock = threading.Lock()

# Session-based results storage
session_results = {}

latest_frame = None
frame_lock = threading.Lock()

# Kafka configuration
KAFKA_BROKER = os.getenv('KAFKA_BROKER', 'localhost:9092')

# Consumer for RAW VIDEO FRAMES (to store frame_hex)
def consume_raw_frames():
    """Consume raw video frames to store frame_hex for visualization"""
    consumer = KafkaConsumer(
        'raw_video_frames',
        bootstrap_servers=KAFKA_BROKER,
        value_deserializer=lambda v: json.loads(v.decode('utf-8')),
        auto_offset_reset='latest'
    )
    print("✅ Raw frames consumer started")
    
    for message in consumer:
        try:
            data = message.value
            
            # Skip END_OF_CLIP markers
            if data.get('message_type') == 'END_OF_CLIP' or data.get('end_of_clip'):
                continue
            
            if 'frame_hex' in data:
                camera_id = data.get('camera_id', 'unknown')
                timestamp = data.get('timestamp', '')
                
                # Store frame_hex with key (camera_id, timestamp)
                with frame_storage_lock:
                    frame_storage[(camera_id, timestamp)] = data['frame_hex']
                    
                    # Keep only last 100 frames to avoid memory issues
                    if len(frame_storage) > 100:
                        # Remove oldest entries
                        oldest_keys = list(frame_storage.keys())[:50]
                        for key in oldest_keys:
                            del frame_storage[key]
                            
                print(f"📦 Stored frame for {camera_id} at {timestamp[:19]}")
                
        except Exception as e:
            print(f"Error storing raw frame: {e}")

# Consumer for POSE service
def consume_pose():
    """Consume pose estimation results"""
    consumer = KafkaConsumer(
        'pose_estimation_results',
        bootstrap_servers=KAFKA_BROKER,
        value_deserializer=lambda v: json.loads(v.decode('utf-8')),
        auto_offset_reset='earliest',  # Changed to earliest to see all messages
        group_id='gui-pose-group'  # Add group_id for proper offset tracking
    )
    print("✅ Pose consumer started")
    
    for message in consumer:
        try:
            data = message.value
            data['received_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            # Try to attach frame_hex from storage
            camera_id = data.get('camera_id', 'unknown')
            timestamp = data.get('timestamp', '')
            with frame_storage_lock:
                if (camera_id, timestamp) in frame_storage:
                    data['frame_hex'] = frame_storage[(camera_id, timestamp)]
            
            module_data['pose'].append(data)
        except Exception as e:
            print(f"Error processing pose: {e}")

# Consumer for OBJECT service
def consume_object():
    """Consume object detection results"""
    consumer = KafkaConsumer(
        'object_detection_results',
        bootstrap_servers=KAFKA_BROKER,
        value_deserializer=lambda v: json.loads(v.decode('utf-8')),
        auto_offset_reset='latest'
    )
    print("✅ Object consumer started")
    
    for message in consumer:
        try:
            data = message.value
            data['received_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            # Try to attach frame_hex from storage
            camera_id = data.get('camera_id', 'unknown')
            timestamp = data.get('timestamp', '')
            with frame_storage_lock:
                if (camera_id, timestamp) in frame_storage:
                    data['frame_hex'] = frame_storage[(camera_id, timestamp)]
            
            module_data['object'].append(data)
            print(f"📦 Object detection received: {len(data.get('detections', []))} objects")
        except Exception as e:
            print(f"Error processing object: {e}")

def consume_weapon():
    """Consume weapon detection results"""
    consumer = KafkaConsumer(
        'object_detection1_results',
        bootstrap_servers=KAFKA_BROKER,
        value_deserializer=lambda v: json.loads(v.decode('utf-8')),
        auto_offset_reset='latest'
    )
    print("✅ weapon consumer started")
    
    for message in consumer:
        try:
            data = message.value
            data['received_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            # Try to attach frame_hex from storage
            camera_id = data.get('camera_id', 'unknown')
            timestamp = data.get('timestamp', '')
            with frame_storage_lock:
                if (camera_id, timestamp) in frame_storage:
                    data['frame_hex'] = frame_storage[(camera_id, timestamp)]
            
            module_data['weapon'].append(data)
            print(f"🔫 Weapon detection received: {len(data.get('detections', []))} weapons")
        except Exception as e:
            print(f"Error processing weapon: {e}")


# Consumer for FACE service
def consume_face():
    """Consume facial expression recognition results"""
    consumer = KafkaConsumer(
        'facial_expression_results',
        bootstrap_servers=KAFKA_BROKER,
        value_deserializer=lambda v: json.loads(v.decode('utf-8')),
        auto_offset_reset='latest'
    )
    print("✅ Face consumer started")
    
    for message in consumer:
        try:
            data = message.value
            data['received_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            # Try to attach frame_hex from storage
            camera_id = data.get('camera_id', 'unknown')
            timestamp = data.get('timestamp', '')
            with frame_storage_lock:
                if (camera_id, timestamp) in frame_storage:
                    data['frame_hex'] = frame_storage[(camera_id, timestamp)]
            
            module_data['face'].append(data)
            print(f"👤 Face expression received: {len(data.get('faces', []))} faces")
        except Exception as e:
            print(f"Error processing face: {e}")

# Consumer for SCENE service
def consume_scene():
    """Consume scene understanding results"""
    consumer = KafkaConsumer(
        'scene_understanding_results',
        bootstrap_servers=KAFKA_BROKER,
        value_deserializer=lambda v: json.loads(v.decode('utf-8')),
        auto_offset_reset='latest'
    )
    print("✅ Scene consumer started")
    
    for message in consumer:
        try:
            data = message.value
            data['received_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            module_data['scene'].append(data)
            print(f"🖼️  Scene understanding received: {data.get('description', 'N/A')[:50]}")
        except Exception as e:
            print(f"Error processing scene: {e}")

# Consumer for INTERACTION service
def consume_interaction():
    """Consume interaction analysis results"""
    consumer = KafkaConsumer(
        'interaction_analysis_results',
        bootstrap_servers=KAFKA_BROKER,
        value_deserializer=lambda v: json.loads(v.decode('utf-8')),
        auto_offset_reset='latest'
    )
    print("✅ Interaction consumer started")
    
    for message in consumer:
        try:
            data = message.value
            data['received_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            module_data['interaction'].append(data)
            print(f"🤝 Interaction analysis received: {len(data.get('interactions', []))} interactions")
        except Exception as e:
            print(f"Error processing interaction: {e}")

# Consumer for ACTION service
def consume_action():
    """Consume action recognition results"""
    consumer = KafkaConsumer(
        'action_recognition_results',
        bootstrap_servers=KAFKA_BROKER,
        value_deserializer=lambda v: json.loads(v.decode('utf-8')),
        auto_offset_reset='latest'
    )
    print("✅ Action consumer started")
    
    for message in consumer:
        try:
            data = message.value
            data['received_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            module_data['action'].append(data)
            print(f"🎬 Action recognition received: {data.get('action', 'N/A')}")
        except Exception as e:
            print(f"Error processing action: {e}")

# Consumer for DECISION service
def consume_decisions():
    """Consume final decision results from decision service"""
    consumer = KafkaConsumer(
        'clip_analysis_results',
        bootstrap_servers=KAFKA_BROKER,
        value_deserializer=lambda v: json.loads(v.decode('utf-8')),
        auto_offset_reset='latest'
    )
    
    print("✅ Decision consumer started")
    
    for message in consumer:
        try:
            data = message.value
            data['received_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            # Store in both decision and output module data
            module_data['decision'].append(data)
            module_data['output'].append(data)
            
            # Update statistics
            system_stats['total_frames_processed'] += 1
            system_stats['cameras_active'].add(data.get('camera_id', 'unknown'))
            
            category = data.get('final_category', 'normal')
            if category == 'violent':
                system_stats['violent_events'] += 1
            elif category == 'suspicious':
                system_stats['suspicious_events'] += 1
            else:
                system_stats['normal_events'] += 1
            
            # Add to latest detections
            latest_detections.append(data)
            
            # Check for alerts (violent or suspicious)
            if category in ['violent', 'suspicious']:
                alert = {
                    'timestamp': data['received_at'],
                    'camera_id': data.get('camera_id', 'unknown'),
                    'category': category,
                    'action': data.get('final_action', 'unknown'),
                    'confidence': data.get('final_confidence', 0),
                    'severity': 'HIGH' if category == 'violent' else 'MEDIUM'
                }
                active_alerts.append(alert)
                if len(active_alerts) > 20:
                    active_alerts.pop(0)
            
        except Exception as e:
            print(f"Error processing decision: {e}")

def consume_frames():
    """Consume video frames for live display"""
    consumer = KafkaConsumer(
        'raw_video_frames',
        bootstrap_servers=KAFKA_BROKER,
        value_deserializer=lambda v: json.loads(v.decode('utf-8')),
        auto_offset_reset='latest'
    )
    
    print("✅ Frame consumer started")
    
    for message in consumer:
        try:
            data = message.value
            
            if 'frame_hex' in data:
                # Decode frame
                frame_bytes = np.frombuffer(bytes.fromhex(data['frame_hex']), dtype=np.uint8)
                frame = cv2.imdecode(frame_bytes, cv2.IMREAD_COLOR)
                
                if frame is not None:
                    # Resize for display
                    frame = cv2.resize(frame, (640, 480))
                    
                    # Add camera ID overlay
                    camera_id = data.get('camera_id', 'unknown')
                    cv2.putText(frame, f"Camera: {camera_id}", (10, 30),
                              cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                    
                    # Update latest frame
                    with frame_lock:
                        global latest_frame
                        latest_frame = frame
                        
        except Exception as e:
            print(f"Error processing frame: {e}")

def generate_frames():
    """Generate frames for video stream"""
    global latest_frame
    
    while True:
        with frame_lock:
            if latest_frame is not None:
                # Encode frame as JPEG
                ret, buffer = cv2.imencode('.jpg', latest_frame)
                frame = buffer.tobytes()
                
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
            else:
                # Send placeholder
                time.sleep(0.1)

@app.route('/')
def index():
    """Main dashboard page"""
    return render_template('dashboard.html')

@app.route('/modules')
def modules():
    """All modules output page (text)"""
    return render_template('modules.html')

@app.route('/visual')
def visual_modules():
    """Visual modules output page with images"""
    return render_template('modules_visual.html')

@app.route('/upload')
def upload_page():
    """Video upload and analysis page"""
    return render_template('upload.html')

@app.route('/api/upload', methods=['POST'])
def upload_file():
    """Handle image/video upload and start processing"""
    if 'file' not in request.files:
        return jsonify({'status': 'error', 'message': 'No file provided'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'status': 'error', 'message': 'No file selected'}), 400
    
    # Check file extension
    filename = secure_filename(file.filename)
    file_ext = filename.lower().split('.')[-1]
    
    valid_image_exts = ['jpg', 'jpeg', 'png', 'bmp']
    valid_video_exts = ['mp4', 'avi', 'mov', 'mkv', 'flv', 'wmv']
    
    if file_ext not in valid_image_exts + valid_video_exts:
        return jsonify({'status': 'error', 'message': 'Invalid file format. Please upload image (jpg, png) or video (mp4, avi, mov, mkv)'}), 400
    
    # Generate session ID
    session_id = str(uuid.uuid4())
    file_type = 'image' if file_ext in valid_image_exts else 'video'
    
    # Save file
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], f"{session_id}_{filename}")
    file.save(filepath)
    
    # Initialize session results
    session_results[session_id] = {
        'status': 'processing',
        'filepath': filepath,
        'file_type': file_type,
        'results': {
            'pose': [],
            'object': [],
            'weapon': [],
            'face': [],
            'scene': [],
            'interaction': [],
            'action': [],
            'decision': []
        }
    }
    
    # Start processing in background
    if file_type == 'image':
        thread = threading.Thread(target=process_image, args=(session_id, filepath), daemon=True)
    else:
        thread = threading.Thread(target=process_video, args=(session_id, filepath), daemon=True)
    thread.start()
    
    return jsonify({
        'status': 'success',
        'session_id': session_id,
        'file_type': file_type,
        'message': f'{file_type.capitalize()} uploaded successfully. Processing started.'
    })

@app.route('/api/results/<session_id>')
def get_results(session_id):
    """Get processing results for a session"""
    if session_id not in session_results:
        return jsonify({'status': 'error', 'message': 'Invalid session ID'}), 404
    
    session = session_results[session_id]
    return jsonify({
        'status': session['status'],
        'results': session['results']
    })

def process_image(session_id, filepath):
    """Process single image through all modules via Kafka"""
    try:
        # Create Kafka producer
        producer = KafkaProducer(
            bootstrap_servers=KAFKA_BROKER,
            value_serializer=lambda v: json.dumps(v).encode('utf-8')
        )
        
        # Read image
        frame = cv2.imread(filepath)
        if frame is None:
            session_results[session_id]['status'] = 'error'
            session_results[session_id]['message'] = 'Failed to read image'
            return
        
        camera_id = f"uploaded_{session_id[:8]}"
        
        # Create consumers for this session
        consumers = {
            'pose': create_session_consumer('pose_estimation_results', session_id),
            'object': create_session_consumer('object_detection_results', session_id),
            'weapon': create_session_consumer('object_detection1_results', session_id),
            'face': create_session_consumer('facial_expression_results', session_id),
            'scene': create_session_consumer('scene_understanding_results', session_id),
            'interaction': create_session_consumer('interaction_analysis_results', session_id),
            'action': create_session_consumer('action_recognition_results', session_id),
            'decision': create_session_consumer('clip_analysis_results', session_id)
        }
        
        # Start consumer threads
        for module, consumer in consumers.items():
            thread = threading.Thread(
                target=consume_session_results,
                args=(session_id, module, consumer),
                daemon=True
            )
            thread.start()
        
        # Encode frame
        ret, buffer = cv2.imencode('.jpg', frame)
        frame_hex = buffer.tobytes().hex()
        
        # Send to Kafka
        message = {
            'camera_id': camera_id,
            'session_id': session_id,
            'clip_id': session_id,  # Add clip_id for services
            'frame_number': 1,
            'frame_index': 1,  # Add frame_index for consistency
            'timestamp': datetime.now().isoformat(),
            'frame_hex': frame_hex,
            'input_type': 'image',  # Add input_type for decision module
            'total_frames': 1,  # Single image = 1 frame
            'source': 'web_upload'
        }
        
        producer.send('raw_video_frames', value=message)
        
        # Send END signal for image (single frame clip)
        end_message = {
            'camera_id': camera_id,
            'session_id': session_id,
            'clip_id': session_id,
            'frame_number': 1,
            'timestamp': datetime.now().isoformat(),
            'end_of_clip': True,
            'message_type': 'END_OF_CLIP',
            'input_type': 'image',
            'total_frames': 1,
            'source': 'web_upload'
        }
        producer.send('raw_video_frames', value=end_message)
        producer.flush()
        
        # Wait for results (10 seconds for single image)
        time.sleep(10)
        
        # Mark as complete
        session_results[session_id]['status'] = 'complete'
        
    except Exception as e:
        print(f"Error processing image: {e}")
        session_results[session_id]['status'] = 'error'
        session_results[session_id]['message'] = str(e)

def process_video(session_id, filepath):
    """Process video through all modules via Kafka"""
    try:
        # Create Kafka producer
        producer = KafkaProducer(
            bootstrap_servers=KAFKA_BROKER,
            value_serializer=lambda v: json.dumps(v).encode('utf-8')
        )
        
        # Open video
        cap = cv2.VideoCapture(filepath)
        if not cap.isOpened():
            session_results[session_id]['status'] = 'error'
            return
        
        frame_number = 0
        camera_id = f"uploaded_{session_id[:8]}"
        
        # Create consumers for this session
        consumers = {
            'pose': create_session_consumer('pose_estimation_results', session_id),
            'object': create_session_consumer('object_detection_results', session_id),
            'weapon': create_session_consumer('object_detection1_results', session_id),
            'face': create_session_consumer('facial_expression_results', session_id),
            'scene': create_session_consumer('scene_understanding_results', session_id),
            'interaction': create_session_consumer('interaction_analysis_results', session_id),
            'action': create_session_consumer('action_recognition_results', session_id),
            'decision': create_session_consumer('clip_analysis_results', session_id)
        }
        
        # Start consumer threads
        for module, consumer in consumers.items():
            thread = threading.Thread(
                target=consume_session_results,
                args=(session_id, module, consumer),
                daemon=True
            )
            thread.start()
        
        # Process video frames
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            
            frame_number += 1
            
            # Encode frame
            ret, buffer = cv2.imencode('.jpg', frame)
            frame_hex = buffer.tobytes().hex()
            
            # Send to Kafka
            message = {
                'camera_id': camera_id,
                'session_id': session_id,
                'clip_id': session_id,  # Add clip_id for services
                'frame_number': frame_number,
                'frame_index': frame_number,  # Add frame_index for consistency
                'timestamp': datetime.now().isoformat(),
                'frame_hex': frame_hex,
                'input_type': 'video',  # Add input_type for decision module
                'source': 'web_upload'
            }
            
            producer.send('raw_video_frames', value=message)
            time.sleep(0.1)  # Control frame rate
        
        # Get total frames for END signal
        total_frames = frame_number
        
        # Send END signal
        end_message = {
            'camera_id': camera_id,
            'session_id': session_id,
            'clip_id': session_id,  # Add clip_id for services
            'frame_number': frame_number,
            'timestamp': datetime.now().isoformat(),
            'end_of_clip': True,
            'message_type': 'END_OF_CLIP',  # Add message type
            'input_type': 'video',  # Add input_type
            'total_frames': total_frames,  # Add total_frames
            'source': 'web_upload'
        }
        producer.send('raw_video_frames', value=end_message)
        
        cap.release()
        producer.flush()
        
        # Wait for all results (max 30 seconds)
        time.sleep(30)
        
        # Mark as complete
        session_results[session_id]['status'] = 'complete'
        
    except Exception as e:
        print(f"Error processing video: {e}")
        session_results[session_id]['status'] = 'error'
        session_results[session_id]['message'] = str(e)

def create_session_consumer(topic, session_id):
    """Create Kafka consumer for specific session"""
    return KafkaConsumer(
        topic,
        bootstrap_servers=KAFKA_BROKER,
        value_deserializer=lambda v: json.loads(v.decode('utf-8')),
        auto_offset_reset='earliest',  # Read from beginning to catch all messages
        consumer_timeout_ms=300000,  # Wait up to 300 seconds for decision layer
        group_id=None  # Don't use consumer groups to avoid offset tracking issues
    )

def consume_session_results(session_id, module, consumer):
    """Consume results for specific session"""
    try:
        print(f"🔍 Starting consumer for {module.upper()} with session_id: {session_id[:8]}...")
        for message in consumer:
            data = message.value
            
            # Debug: Print received message details
            msg_session = data.get('session_id', 'N/A')
            msg_camera = data.get('camera_id', 'N/A')
            msg_clip = data.get('clip_id', 'N/A')
            print(f"📥 {module.upper()} received: session={msg_session[:8] if isinstance(msg_session, str) else msg_session}, camera={msg_camera}, clip={msg_clip[:8] if isinstance(msg_clip, str) else msg_clip}")
            
            # Check if it's for this session (check session_id, camera_id, or clip_id)
            is_match = (
                data.get('session_id') == session_id or 
                data.get('camera_id', '').endswith(session_id[:8]) or
                data.get('clip_id') == session_id  # Decision layer uses clip_id
            )
            
            if is_match:
                session_results[session_id]['results'][module].append(data)
                print(f"✅ {module.upper()} result stored for session {session_id[:8]}! Total: {len(session_results[session_id]['results'][module])}")
            else:
                print(f"❌ {module.upper()} message doesn't match session {session_id[:8]}")
                
    except Exception as e:
        print(f"❌ Consumer error for {module}: {e}")
        import traceback
        traceback.print_exc()

@app.route('/video_feed')
def video_feed():
    """Video streaming route"""
    return Response(generate_frames(),
                   mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/api/stats')
def get_stats():
    """Get system statistics"""
    stats = system_stats.copy()
    stats['cameras_active'] = len(stats['cameras_active'])
    stats['active_alerts'] = len(active_alerts)
    return jsonify(stats)

@app.route('/api/detections')
def get_detections():
    """Get latest detections"""
    return jsonify(list(latest_detections))

@app.route('/api/alerts')
def get_alerts():
    """Get active alerts"""
    return jsonify(active_alerts)

@app.route('/api/clear_alerts', methods=['POST'])
def clear_alerts():
    """Clear all alerts"""
    active_alerts.clear()
    return jsonify({'status': 'success'})

@app.route('/api/modules/pose')
def get_pose_data():
    """Get pose estimation data"""
    return jsonify(list(module_data['pose']))

@app.route('/api/modules/object')
def get_object_data():
    """Get object detection data"""
    return jsonify(list(module_data['object']))

@app.route('/api/modules/weapon')
def get_weapon_data():
    """Get weapon detection data"""
    return jsonify(list(module_data['weapon']))

@app.route('/api/modules/face')
def get_face_data():
    """Get face recognition data"""
    return jsonify(list(module_data['face']))

@app.route('/api/modules/scene')
def get_scene_data():
    """Get scene description data"""
    return jsonify(list(module_data['scene']))

@app.route('/api/modules/interaction')
def get_interaction_data():
    """Get person interaction data"""
    return jsonify(list(module_data['interaction']))

@app.route('/api/modules/action')
def get_action_data():
    """Get action recognition data"""
    return jsonify(list(module_data['action']))

@app.route('/api/modules/decision')
def get_decision_data():
    """Get final decision data"""
    return jsonify(list(module_data['decision']))

@app.route('/api/modules/all')
def get_all_modules():
    """Get data from all modules"""
    return jsonify({
        'pose': list(module_data['pose'])[-5:] if module_data['pose'] else [],
        'object': list(module_data['object'])[-5:] if module_data['object'] else [],
        'weapon': list(module_data['weapon'])[-5:] if module_data['weapon'] else [],
        'face': list(module_data['face'])[-5:] if module_data['face'] else [],
        'scene': list(module_data['scene'])[-5:] if module_data['scene'] else [],
        'interaction': list(module_data['interaction'])[-5:] if module_data['interaction'] else [],
        'action': list(module_data['action'])[-5:] if module_data['action'] else [],
        'decision': list(module_data['decision'])[-5:] if module_data['decision'] else [],
        'output': list(module_data['output'])[-5:] if module_data['output'] else []
    })

def draw_pose_on_frame(frame_hex, persons):
    """Draw pose keypoints on frame"""
    # Decode frame
    frame_bytes = np.frombuffer(bytes.fromhex(frame_hex), dtype=np.uint8)
    frame = cv2.imdecode(frame_bytes, cv2.IMREAD_COLOR)
    
    if frame is None:
        return None
    
    h, w = frame.shape[:2]
    
    # If no persons detected, add text overlay
    if len(persons) == 0:
        cv2.putText(frame, "No persons detected", (20, 40),
                   cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        return frame
    
    # COCO keypoint connections
    connections = [
        (0, 1), (0, 2), (1, 3), (2, 4),  # Head
        (5, 6), (5, 7), (7, 9), (6, 8), (8, 10),  # Arms
        (5, 11), (6, 12), (11, 12),  # Torso
        (11, 13), (13, 15), (12, 14), (14, 16)  # Legs
    ]
    
    for person in persons:
        keypoints = person.get('keypoints', [])
        if not keypoints:
            continue
        
        # Draw connections
        for start_idx, end_idx in connections:
            if start_idx < len(keypoints) and end_idx < len(keypoints):
                kp1 = keypoints[start_idx]
                kp2 = keypoints[end_idx]
                
                if kp1[2] > 0.5 and kp2[2] > 0.5:  # Confidence threshold
                    x1, y1 = int(kp1[1] * w), int(kp1[0] * h)
                    x2, y2 = int(kp2[1] * w), int(kp2[0] * h)
                    cv2.line(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
        
        # Draw keypoints
        for kp in keypoints:
            if kp[2] > 0.5:  # Confidence threshold
                x, y = int(kp[1] * w), int(kp[0] * h)
                cv2.circle(frame, (x, y), 4, (0, 0, 255), -1)
    
    return frame

def draw_objects_on_frame(frame_hex, detections):
    """Draw object bounding boxes on frame"""
    # Decode frame
    frame_bytes = np.frombuffer(bytes.fromhex(frame_hex), dtype=np.uint8)
    frame = cv2.imdecode(frame_bytes, cv2.IMREAD_COLOR)
    
    if frame is None:
        return None
    
    h, w = frame.shape[:2]
    
    # If no detections, add text overlay
    if len(detections) == 0:
        cv2.putText(frame, "No objects detected", (20, 40),
                   cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        return frame
    
    for det in detections:
        bbox = det.get('bounding_box', [])  # Changed from 'bbox' to 'bounding_box'
        label = det.get('class_name', 'unknown')
        conf = det.get('confidence', 0)
        
        if len(bbox) == 4:
            x1, y1, x2, y2 = bbox
            x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
            
            # Draw box
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            
            # Draw label
            label_text = f"{label} {conf:.2f}"
            cv2.putText(frame, label_text, (x1, y1 - 10),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
    
    return frame

def draw_weapons_on_frame(frame_hex, detections):
    """Draw weapon bounding boxes on frame with RED color"""
    # Decode frame
    frame_bytes = np.frombuffer(bytes.fromhex(frame_hex), dtype=np.uint8)
    frame = cv2.imdecode(frame_bytes, cv2.IMREAD_COLOR)
    
    if frame is None:
        return None
    
    h, w = frame.shape[:2]
    
    # If no weapons detected, add green text overlay
    if len(detections) == 0:
        cv2.putText(frame, "✓ No weapons detected", (20, 40),
                   cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        return frame
    
    for det in detections:
        bbox = det.get('bounding_box', [])  # Changed from 'bbox' to 'bounding_box'
        label = det.get('class_name', 'weapon')
        conf = det.get('confidence', 0)
        
        if len(bbox) == 4:
            x1, y1, x2, y2 = bbox
            x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
            
            # Draw RED box for weapons
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 3)
            
            # Draw label with red background
            label_text = f"⚠️ {label} {conf:.2f}"
            (text_w, text_h), _ = cv2.getTextSize(label_text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
            cv2.rectangle(frame, (x1, y1 - text_h - 10), (x1 + text_w, y1), (0, 0, 255), -1)
            cv2.putText(frame, label_text, (x1, y1 - 5),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    
    return frame

def draw_faces_on_frame(frame_hex, faces):
    """Draw face bounding boxes with expressions"""
    # Decode frame
    frame_bytes = np.frombuffer(bytes.fromhex(frame_hex), dtype=np.uint8)
    frame = cv2.imdecode(frame_bytes, cv2.IMREAD_COLOR)
    
    if frame is None:
        return None
    
    h, w = frame.shape[:2]
    
    # If no faces detected, add text overlay
    if len(faces) == 0:
        cv2.putText(frame, "No faces detected", (20, 40),
                   cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2)
        return frame
    
    for face in faces:
        bbox = face.get('bounding_box', [])  # Changed from 'bbox' to 'bounding_box'
        expression = face.get('dominant_emotion', 'neutral')  # Changed from 'expression' to 'dominant_emotion'
        
        if len(bbox) == 4:
            x1, y1, x2, y2 = bbox
            x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
            
            # Color based on expression
            color = (0, 255, 255)  # Yellow for neutral
            if expression in ['angry', 'fear', 'disgust', 'sad']:
                color = (0, 0, 255)  # Red for negative
            elif expression in ['happy', 'surprise']:
                color = (0, 255, 0)  # Green for positive
            
            # Draw box
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            
            # Draw label (no confidence in face data)
            label_text = f"{expression}"
            cv2.putText(frame, label_text, (x1, y1 - 10),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
    
    return frame

@app.route('/api/visualize/pose/<int:index>')
def visualize_pose(index):
    """Get pose visualization image"""
    try:
        if len(module_data['pose']) == 0:
            # Return placeholder image
            placeholder = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(placeholder, "No Data Available", (150, 240),
                       cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
            ret, buffer = cv2.imencode('.jpg', placeholder)
            return Response(buffer.tobytes(), mimetype='image/jpeg')
        
        if index >= len(module_data['pose']):
            index = len(module_data['pose']) - 1
        
        data = list(module_data['pose'])[index]
        frame_hex = data.get('frame_hex')
        persons = data.get('persons', [])
        
        if not frame_hex:
            # Return placeholder image with data info
            placeholder = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(placeholder, "Image Data Not Available", (120, 220),
                       cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
            cv2.putText(placeholder, f"Persons detected: {len(persons)}", (180, 270),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            ret, buffer = cv2.imencode('.jpg', placeholder)
            return Response(buffer.tobytes(), mimetype='image/jpeg')
        
        frame = draw_pose_on_frame(frame_hex, persons)
        if frame is None:
            placeholder = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(placeholder, "Failed to Process Frame", (130, 240),
                       cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
            ret, buffer = cv2.imencode('.jpg', placeholder)
            return Response(buffer.tobytes(), mimetype='image/jpeg')
        
        # Encode as JPEG
        ret, buffer = cv2.imencode('.jpg', frame)
        return Response(buffer.tobytes(), mimetype='image/jpeg')
    except Exception as e:
        print(f"Error in visualize_pose: {e}")
        placeholder = np.zeros((480, 640, 3), dtype=np.uint8)
        cv2.putText(placeholder, f"Error: {str(e)}", (100, 240),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        ret, buffer = cv2.imencode('.jpg', placeholder)
        return Response(buffer.tobytes(), mimetype='image/jpeg')

@app.route('/api/visualize/object/<int:index>')
def visualize_object(index):
    """Get object detection visualization image"""
    try:
        if len(module_data['object']) == 0:
            placeholder = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(placeholder, "No Data Available", (150, 240),
                       cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
            ret, buffer = cv2.imencode('.jpg', placeholder)
            return Response(buffer.tobytes(), mimetype='image/jpeg')
        
        if index >= len(module_data['object']):
            index = len(module_data['object']) - 1
        
        data = list(module_data['object'])[index]
        frame_hex = data.get('frame_hex')
        detections = data.get('detections', [])
        
        if not frame_hex:
            placeholder = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(placeholder, "Image Data Not Available", (120, 220),
                       cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
            cv2.putText(placeholder, f"Objects detected: {len(detections)}", (160, 270),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            ret, buffer = cv2.imencode('.jpg', placeholder)
            return Response(buffer.tobytes(), mimetype='image/jpeg')
        
        frame = draw_objects_on_frame(frame_hex, detections)
        if frame is None:
            placeholder = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(placeholder, "Failed to Process Frame", (130, 240),
                       cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
            ret, buffer = cv2.imencode('.jpg', placeholder)
            return Response(buffer.tobytes(), mimetype='image/jpeg')
        
        ret, buffer = cv2.imencode('.jpg', frame)
        return Response(buffer.tobytes(), mimetype='image/jpeg')
    except Exception as e:
        print(f"Error in visualize_object: {e}")
        placeholder = np.zeros((480, 640, 3), dtype=np.uint8)
        cv2.putText(placeholder, f"Error: {str(e)}", (100, 240),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        ret, buffer = cv2.imencode('.jpg', placeholder)
        return Response(buffer.tobytes(), mimetype='image/jpeg')

@app.route('/api/visualize/weapon/<int:index>')
def visualize_weapon(index):
    """Get weapon detection visualization image"""
    try:
        if len(module_data['weapon']) == 0:
            placeholder = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(placeholder, "No Data Available", (150, 240),
                       cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
            ret, buffer = cv2.imencode('.jpg', placeholder)
            return Response(buffer.tobytes(), mimetype='image/jpeg')
        
        if index >= len(module_data['weapon']):
            index = len(module_data['weapon']) - 1
        
        data = list(module_data['weapon'])[index]
        frame_hex = data.get('frame_hex')
        detections = data.get('detections', [])
        
        if not frame_hex:
            placeholder = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(placeholder, "Image Data Not Available", (120, 220),
                       cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
            cv2.putText(placeholder, f"Weapons detected: {len(detections)}", (160, 270),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            ret, buffer = cv2.imencode('.jpg', placeholder)
            return Response(buffer.tobytes(), mimetype='image/jpeg')
        
        frame = draw_weapons_on_frame(frame_hex, detections)
        if frame is None:
            placeholder = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(placeholder, "Failed to Process Frame", (130, 240),
                       cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
            ret, buffer = cv2.imencode('.jpg', placeholder)
            return Response(buffer.tobytes(), mimetype='image/jpeg')
        
        ret, buffer = cv2.imencode('.jpg', frame)
        return Response(buffer.tobytes(), mimetype='image/jpeg')
    except Exception as e:
        print(f"Error in visualize_weapon: {e}")
        placeholder = np.zeros((480, 640, 3), dtype=np.uint8)
        cv2.putText(placeholder, f"Error: {str(e)}", (100, 240),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        ret, buffer = cv2.imencode('.jpg', placeholder)
        return Response(buffer.tobytes(), mimetype='image/jpeg')

@app.route('/api/visualize/face/<int:index>')
def visualize_face(index):
    """Get face expression visualization image"""
    try:
        if len(module_data['face']) == 0:
            placeholder = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(placeholder, "No Data Available", (150, 240),
                       cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
            ret, buffer = cv2.imencode('.jpg', placeholder)
            return Response(buffer.tobytes(), mimetype='image/jpeg')
        
        if index >= len(module_data['face']):
            index = len(module_data['face']) - 1
        
        data = list(module_data['face'])[index]
        frame_hex = data.get('frame_hex')
        faces = data.get('faces', [])
        
        if not frame_hex:
            placeholder = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(placeholder, "Image Data Not Available", (120, 220),
                       cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
            cv2.putText(placeholder, f"Faces detected: {len(faces)}", (180, 270),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            ret, buffer = cv2.imencode('.jpg', placeholder)
            return Response(buffer.tobytes(), mimetype='image/jpeg')
        
        frame = draw_faces_on_frame(frame_hex, faces)
        if frame is None:
            placeholder = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(placeholder, "Failed to Process Frame", (130, 240),
                       cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
            ret, buffer = cv2.imencode('.jpg', placeholder)
            return Response(buffer.tobytes(), mimetype='image/jpeg')
        
        ret, buffer = cv2.imencode('.jpg', frame)
        return Response(buffer.tobytes(), mimetype='image/jpeg')
    except Exception as e:
        print(f"Error in visualize_face: {e}")
        placeholder = np.zeros((480, 640, 3), dtype=np.uint8)
        cv2.putText(placeholder, f"Error: {str(e)}", (100, 240),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        ret, buffer = cv2.imencode('.jpg', placeholder)
        return Response(buffer.tobytes(), mimetype='image/jpeg')

if __name__ == '__main__':
    # Start background threads for ALL 8 modules + raw frames consumer
    threads = [
        threading.Thread(target=consume_raw_frames, daemon=True, name="RawFrames-Consumer"),
        threading.Thread(target=consume_pose, daemon=True, name="Pose-Consumer"),
        threading.Thread(target=consume_object, daemon=True, name="Object-Consumer"),
        threading.Thread(target=consume_weapon, daemon=True, name="Weapon-Consumer"),
        threading.Thread(target=consume_face, daemon=True, name="Face-Consumer"),
        threading.Thread(target=consume_scene, daemon=True, name="Scene-Consumer"),
        threading.Thread(target=consume_interaction, daemon=True, name="Interaction-Consumer"),
        threading.Thread(target=consume_action, daemon=True, name="Action-Consumer"),
        threading.Thread(target=consume_decisions, daemon=True, name="Decision-Consumer"),
        threading.Thread(target=consume_frames, daemon=True, name="Frame-Consumer")
    ]
    
    for thread in threads:
        thread.start()
        time.sleep(0.2)  # Stagger startup
    
    print("=" * 70)
    print("🎨 SURVEILLANCE SYSTEM GUI - ALL 8 MODULES")
    print("=" * 70)
    print("📡 Kafka Consumers Active:")
    print("   1. 🧍 Pose Estimation")
    print("   2. 📦 Object Detection")
    print("   3. � Weapon Detection")
    print("   4. 👤 Facial Expression")
    print("   5. 🖼️  Scene Understanding")
    print("   6. 🤝 Interaction Analysis")
    print("   7. 🎬 Action Recognition")
    print("   8. 🧠 Clip Analysis (Decision)")
    print("=" * 70)
    print("🌐 Open browser: http://localhost:5000")
    print("=" * 70)
    
    # Run Flask app
    app.run(debug=False, host='0.0.0.0', port=5000, threaded=True)
