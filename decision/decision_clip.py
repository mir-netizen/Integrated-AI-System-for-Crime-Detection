import os
import json
import time
from collections import defaultdict
from kafka import KafkaConsumer, KafkaProducer
from groq import Groq
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# ============================================================================
# CLIP-BASED ANALYSIS CONFIGURATION
# ============================================================================
DEMO_MODE = True
SAVE_ALERTS_TO_FILE = True
ALERT_LOG_FILE = "clip_analysis_results.json"
VERBOSE_LOGGING = False  # Set to False to reduce noise

# --- Configuration ---
KAFKA_BROKER = os.getenv('KAFKA_BROKER', 'localhost:9092')
INPUT_TOPICS = [
    'raw_video_frames',  # Need this to receive END_OF_CLIP markers!
    'object_detection_results', 
    'object_detection1_results', 
    'pose_estimation_results', 
    'facial_expression_results', 
    'scene_understanding_results', 
    'interaction_analysis_results',
    'action_recognition_results'  # NEW: 7th service for temporal action recognition
]
OUTPUT_TOPIC = 'clip_analysis_results'

# Clip aggregation settings
CLIP_AGGREGATION_WINDOW = 60.0  # Wait up to 60 seconds for all clip data
CLIP_CLEANUP_INTERVAL = 120.0  # Clean up completed clips after 2 minutes

# Required services (pose is mandatory)
REQUIRED_SERVICES = ['pose_estimation_results']
OPTIONAL_SERVICES = [
    'object_detection_results',
    'object_detection1_results',
    'facial_expression_results',
    'scene_understanding_results',
    'interaction_analysis_results'
]

# --- Setup Groq API ---
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
# GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
client = Groq(api_key=GROQ_API_KEY)
MODEL_NAME = "llama-3.3-70b-versatile"

# --- Kafka Clients ---
consumer = KafkaConsumer(
    bootstrap_servers=KAFKA_BROKER,
    value_deserializer=lambda v: json.loads(v.decode('utf-8')),
    auto_offset_reset='latest',  # Read only NEW messages after consumer starts
    enable_auto_commit=True,
    group_id='clip_analysis_group_v3'  # New group to reset offset
)
consumer.subscribe(INPUT_TOPICS)
producer = KafkaProducer(
    bootstrap_servers=KAFKA_BROKER,
    value_serializer=lambda v: json.dumps(v).encode('utf-8')
)

# --- In-memory Clip Buffers ---
clip_buffers = {}  # {clip_id: {"frames": {}, "metadata": {}, "start_time": float}}
completed_clips = set()
last_cleanup_time = time.time()


class ClipAnalyzer:
    """Manages clip-based analysis of images and videos"""
    
    def __init__(self):
        self.clip_buffers = {}
        self.completed_clips = set()
    
    def add_frame_data(self, clip_id, frame_idx, service_name, data):
        """Add service data for a specific frame in a clip"""
        if clip_id not in self.clip_buffers:
            self.clip_buffers[clip_id] = {
                "frames": {},
                "metadata": {
                    "input_type": None,
                    "total_frames": None,
                    "end_marker_received": False,
                    "start_time": time.time(),
                    "camera_id": data.get('camera_id'),  # Store camera_id
                    "session_id": data.get('session_id')  # Store session_id
                }
            }
            if VERBOSE_LOGGING:
                print(f"\n🆕 Created new clip buffer for: {clip_id}")
        
        # Initialize frame dict if not exists
        if frame_idx not in self.clip_buffers[clip_id]["frames"]:
            self.clip_buffers[clip_id]["frames"][frame_idx] = {}
        
        # Store service data for this frame
        self.clip_buffers[clip_id]["frames"][frame_idx][service_name] = data
    
    def mark_clip_complete(self, clip_id, total_frames, input_type, camera_id=None, session_id=None):
        """Mark that all frames have been sent for this clip"""
        # Create clip buffer if it doesn't exist yet (END_OF_CLIP might arrive first)
        if clip_id not in self.clip_buffers:
            self.clip_buffers[clip_id] = {
                "frames": {},
                "metadata": {
                    "input_type": None,
                    "total_frames": None,
                    "end_marker_received": False,
                    "start_time": time.time(),
                    "camera_id": camera_id,
                    "session_id": session_id
                }
            }
        
        self.clip_buffers[clip_id]["metadata"]["end_marker_received"] = True
        self.clip_buffers[clip_id]["metadata"]["total_frames"] = total_frames
        self.clip_buffers[clip_id]["metadata"]["input_type"] = input_type
        if camera_id:
            self.clip_buffers[clip_id]["metadata"]["camera_id"] = camera_id
        if session_id:
            self.clip_buffers[clip_id]["metadata"]["session_id"] = session_id
        
        if VERBOSE_LOGGING:
            print(f"\n🏁 END MARKER received for clip {clip_id}")
            print(f"   Expected frames: {total_frames}")
            print(f"   Input type: {input_type}")
            print(f"   Current frames in buffer: {len(self.clip_buffers[clip_id]['frames'])}")
    
    def is_clip_ready_for_analysis(self, clip_id):
        """Check if we have all data needed to analyze this clip"""
        if clip_id not in self.clip_buffers:
            return False
        
        clip_data = self.clip_buffers[clip_id]
        metadata = clip_data["metadata"]
        
        # Must have received end marker
        if not metadata["end_marker_received"]:
            return False
        
        expected_frames = metadata["total_frames"]
        received_frames = len(clip_data["frames"])
        
        if VERBOSE_LOGGING:
            print(f"\n📊 Checking clip {clip_id} readiness:")
            print(f"   Expected frames: {expected_frames}")
            print(f"   Received frames: {received_frames}")
        
        # Must have data for all frames
        if received_frames < expected_frames:
            return False
        
        # Check each frame has required services
        for frame_idx in range(expected_frames):
            if frame_idx not in clip_data["frames"]:
                if VERBOSE_LOGGING:
                    print(f"   ❌ Missing frame {frame_idx}")
                    print(f"   Available frames: {sorted(clip_data['frames'].keys())}")
                return False
            
            frame_services = set(clip_data["frames"][frame_idx].keys())
            
            if VERBOSE_LOGGING:
                print(f"   Frame {frame_idx} services: {frame_services}")
            
            # Must have at least pose data
            if 'pose_estimation_results' not in frame_services:
                if VERBOSE_LOGGING:
                    print(f"   ❌ Frame {frame_idx} missing pose data")
                return False
        
        if VERBOSE_LOGGING:
            print(f"   ✅ Clip {clip_id} is ready for analysis!")
        
        return True
    
    def get_timeout_clips(self):
        """Get clips that have exceeded the wait time"""
        current_time = time.time()
        timeout_clips = []
        
        for clip_id, clip_data in self.clip_buffers.items():
            if clip_id in self.completed_clips:
                continue
            
            metadata = clip_data["metadata"]
            wait_time = current_time - metadata["start_time"]
            
            if wait_time >= CLIP_AGGREGATION_WINDOW:
                timeout_clips.append(clip_id)
        
        return timeout_clips
    
    def analyze_clip(self, clip_id):
        """Perform holistic analysis of entire clip"""
        if clip_id not in self.clip_buffers:
            return None
        
        clip_data = self.clip_buffers[clip_id]
        metadata = clip_data["metadata"]
        frames = clip_data["frames"]
        
        print(f"\n{'='*70}")
        print(f"🔍 ANALYZING CLIP: {clip_id}")
        print(f"{'='*70}")
        input_type = metadata.get('input_type', 'unknown')
        print(f"Input Type: {input_type.upper() if input_type else 'UNKNOWN'}")
        print(f"Total Frames: {metadata['total_frames']}")
        print(f"{'='*70}")
        
        # Aggregate all frame data
        all_data = {
            "poses": [],
            "objects": [],
            "faces": [],
            "scenes": [],
            "interactions": [],
            "actions": []  # NEW: Action recognition data
        }
        
        for frame_idx in sorted(frames.keys()):
            frame_data = frames[frame_idx]
            
            # Extract data from each service
            all_data["poses"].append(frame_data.get("pose_estimation_results", {}))
            
            # Combine both object detection results
            obj1 = frame_data.get("object_detection_results", {})
            obj2 = frame_data.get("object_detection1_results", {})
            combined_objects = self._merge_object_detections(obj1, obj2)
            all_data["objects"].append(combined_objects)
            
            all_data["faces"].append(frame_data.get("facial_expression_results", {}))
            all_data["scenes"].append(frame_data.get("scene_understanding_results", {}))
            all_data["interactions"].append(frame_data.get("interaction_analysis_results", {}))
            all_data["actions"].append(frame_data.get("action_recognition_results", {}))  # NEW
        
        # Check for weapons across all frames
        weapons_detected = self._check_for_weapons(all_data["objects"])
        
        # Build LLM prompt for holistic analysis
        llm_prompt = self._build_clip_analysis_prompt(
            metadata["input_type"],
            metadata["total_frames"],
            all_data,
            weapons_detected
        )
        
        # Call LLM
        print(f"\n🤖 Sending clip data to LLM for analysis...")
        llm_response = self._call_llm_api(llm_prompt)
        
        # Parse LLM response and build result
        result = {
            "clip_id": clip_id,
            "camera_id": metadata.get("camera_id"),  # Add camera_id
            "session_id": metadata.get("session_id"),  # Add session_id
            "input_type": metadata["input_type"],
            "total_frames": metadata["total_frames"],
            "analysis_timestamp": datetime.now().isoformat(),
            "verdict": llm_response.get("verdict", "UNKNOWN"),
            "confidence": llm_response.get("confidence", 0),
            "threat_level": llm_response.get("threat_level", 0),
            "severity": self._get_severity(llm_response.get("threat_level", 0)),
            "reasons": llm_response.get("reasons", []),
            "key_frames": llm_response.get("key_frames", []),
            "summary": llm_response.get("summary", "No analysis available"),
            "weapons_detected": weapons_detected
        }
        
        # Send result to output topic
        print(f"\n📤 Publishing decision result:")
        print(f"   clip_id: {result.get('clip_id', 'N/A')}")
        print(f"   camera_id: {result.get('camera_id', 'N/A')}")
        print(f"   session_id: {result.get('session_id', 'N/A')}")
        print(f"   verdict: {result.get('verdict', 'N/A')}")
        producer.send(OUTPUT_TOPIC, value=result)
        producer.flush()
        print(f"✅ Decision result published to {OUTPUT_TOPIC}")
        
        # Mark as completed
        self.completed_clips.add(clip_id)
        
        # Save to file if enabled
        if SAVE_ALERTS_TO_FILE:
            self._save_result_to_file(result)
        
        # Display result
        self._display_result(result)
        
        return result
    
    def _merge_object_detections(self, obj1, obj2):
        """Merge results from both object detection services"""
        merged = {
            "detections": [],
            "timestamp": obj1.get("timestamp") or obj2.get("timestamp")
        }
        
        if "detections" in obj1:
            merged["detections"].extend(obj1["detections"])
        if "detections" in obj2:
            merged["detections"].extend(obj2["detections"])
        
        return merged
    
    def _check_for_weapons(self, objects_data):
        """Check if weapons are detected in any frame"""
        weapons = []
        weapon_types = ["gun", "knife", "firearm", "blade", "weapon"]
        
        for frame_idx, obj_data in enumerate(objects_data):
            if "detections" not in obj_data:
                continue
            
            for detection in obj_data["detections"]:
                class_name = detection.get("class", "").lower()
                if any(weapon in class_name for weapon in weapon_types):
                    weapons.append({
                        "frame": frame_idx,
                        "type": class_name,
                        "confidence": detection.get("confidence", 0)
                    })
        
        return weapons
    
    def _build_clip_analysis_prompt(self, input_type, total_frames, all_data, weapons_detected):
        """Build prompt for LLM to analyze the entire clip"""
        
        prompt = f"""You are an expert security analyst reviewing {'an image' if input_type == 'image' else 'a 10-second video clip'}.

INPUT: {input_type.upper()} with {total_frames} frame(s)

Your task is to provide a SINGLE overall assessment of whether this {input_type} is SUSPICIOUS or SAFE.

AVAILABLE DATA:
- Person detection and pose information (body positions, gestures)
- Object detection results (especially weapons)
- Facial expressions and emotions
- Scene descriptions
- Person interactions and spatial relationships
- Temporal action recognition (fighting, assault, theft, vandalism, etc.)

{'⚠️ WEAPONS DETECTED: ' + str(len(weapons_detected)) + ' weapon(s) found across frames' if weapons_detected else ''}

ANALYSIS DATA:
{json.dumps(all_data, indent=2)}

Please analyze this {input_type} and respond with a JSON object containing:
{{
  "verdict": "SUSPICIOUS" or "SAFE",
  "confidence": <0-100>,
  "threat_level": <0-10>,
  "reasons": [<list of specific behaviors that are suspicious or safe>],
  "key_frames": [<list of frame numbers where suspicious activity occurs, empty if image>],
  "summary": "<1-2 sentence overall assessment>"
}}

GUIDELINES:
- For IMAGES: Analyze the single frame holistically
- For VIDEOS: Look for patterns, escalation, sustained behaviors across frames
- WEAPONS = Automatic HIGH threat (8-10)
- Physical violence/aggression = HIGH threat (7-9)
- Normal activity = LOW threat (0-3)
- Consider ALL people in the scene, not just individuals
- Be objective and evidence-based

Respond ONLY with valid JSON, no additional text.
"""
        
        return prompt
    
    def _call_llm_api(self, prompt):
        """Call Groq LLM API and parse response"""
        try:
            completion = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=1000
            )
            
            response_text = completion.choices[0].message.content.strip()
            
            # Try to extract JSON from response
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()
            
            result = json.loads(response_text)
            return result
            
        except Exception as e:
            print(f"❌ Error calling LLM API: {e}")
            return {
                "verdict": "UNKNOWN",
                "confidence": 0,
                "threat_level": 5,
                "reasons": [f"Analysis failed: {str(e)}"],
                "key_frames": [],
                "summary": "Unable to complete analysis due to error"
            }
    
    def _get_severity(self, threat_level):
        """Convert threat level to severity category"""
        if threat_level >= 9:
            return "CRITICAL"
        elif threat_level >= 7:
            return "HIGH"
        elif threat_level >= 4:
            return "MEDIUM"
        else:
            return "LOW"
    
    def _save_result_to_file(self, result):
        """Save analysis result to JSON file"""
        try:
            # Load existing results
            if os.path.exists(ALERT_LOG_FILE):
                with open(ALERT_LOG_FILE, 'r') as f:
                    results = json.load(f)
            else:
                results = []
            
            # Append new result
            results.append(result)
            
            # Save back to file
            with open(ALERT_LOG_FILE, 'w') as f:
                json.dump(results, f, indent=2)
                
        except Exception as e:
            print(f"❌ Error saving result to file: {e}")
    
    def _display_result(self, result):
        """Display analysis result in console"""
        print(f"\n{'='*70}")
        print(f"📊 CLIP ANALYSIS RESULT")
        print(f"{'='*70}")
        print(f"Clip ID: {result['clip_id']}")
        print(f"Input Type: {result['input_type'].upper()}")
        print(f"Total Frames: {result['total_frames']}")
        print(f"")
        
        # Main verdict
        verdict = result['verdict']
        if verdict == "SUSPICIOUS":
            symbol = "🚨"
            color = "RED"
        elif verdict == "SAFE":
            symbol = "✅"
            color = "GREEN"
        else:
            symbol = "❓"
            color = "YELLOW"
        
        print(f"{symbol} VERDICT: {verdict}")
        print(f"Confidence: {result['confidence']}%")
        print(f"Threat Level: {result['threat_level']}/10")
        print(f"Severity: {result['severity']}")
        print(f"")
        
        # Weapons
        if result.get('weapons_detected'):
            print(f"⚠️  WEAPONS DETECTED:")
            for weapon in result['weapons_detected']:
                print(f"   - Frame {weapon['frame']}: {weapon['type']} ({weapon['confidence']:.0%})")
            print(f"")
        
        # Reasons
        if result.get('reasons'):
            print(f"Reasons:")
            for i, reason in enumerate(result['reasons'], 1):
                print(f"  {i}. {reason}")
            print(f"")
        
        # Key frames
        if result.get('key_frames'):
            print(f"Key Frames: {', '.join(map(str, result['key_frames']))}")
            print(f"")
        
        # Summary
        print(f"Summary:")
        print(f"  {result['summary']}")
        print(f"{'='*70}\n")
    
    def cleanup_old_clips(self):
        """Remove completed clips that are no longer needed"""
        current_time = time.time()
        clips_to_remove = []
        
        for clip_id, clip_data in self.clip_buffers.items():
            if clip_id in self.completed_clips:
                age = current_time - clip_data["metadata"]["start_time"]
                if age > CLIP_CLEANUP_INTERVAL:
                    clips_to_remove.append(clip_id)
        
        for clip_id in clips_to_remove:
            del self.clip_buffers[clip_id]
            self.completed_clips.discard(clip_id)
            if VERBOSE_LOGGING:
                print(f"🧹 Cleaned up completed clip: {clip_id}")


# ============================================================================
# MAIN PROCESSING LOOP
# ============================================================================

print("=" * 70)
print("CLIP-BASED ANALYSIS SERVICE STARTED")
print("=" * 70)
print(f"Kafka Broker: {KAFKA_BROKER}")
print(f"Input Topics: {', '.join(INPUT_TOPICS)}")
print(f"Output Topic: {OUTPUT_TOPIC}")
print(f"LLM Model: {MODEL_NAME}")
print(f"Results File: {ALERT_LOG_FILE}")
print("=" * 70)
print("Waiting for clips to analyze...\n")

analyzer = ClipAnalyzer()
last_status_time = time.time()
STATUS_INTERVAL = 5.0  # Print status every 5 seconds
message_count = 0

print("✅ Consumer subscribed and ready!")
print(f"🔄 Polling for messages...\n")

while True:
    try:
        # Poll for new messages
        messages = consumer.poll(timeout_ms=100, max_records=100)
        
        # Debug: Log if we received any messages
        if messages:
            total_messages = sum(len(records) for records in messages.values())
            if total_messages > 0:
                message_count += total_messages
                if VERBOSE_LOGGING:
                    print(f"📨 Received {total_messages} messages (Total: {message_count})")
        
        # Process incoming messages
        for topic_partition, records in messages.items():
            for message in records:
                topic = message.topic
                data = message.value
                
                if VERBOSE_LOGGING:
                    print(f"📋 Processing message from topic: {topic}")
                
                # Check if this is raw_video_frames topic
                if topic == 'raw_video_frames':
                    # Check if this is an end marker
                    if data.get("message_type") == "END_OF_CLIP":
                        clip_id = data.get("clip_id")
                        total_frames = data.get("total_frames")
                        input_type = data.get("input_type")
                        camera_id = data.get("camera_id")
                        session_id = data.get("session_id")
                        
                        print(f"🎯 Detected END_OF_CLIP marker from {topic}!")
                        analyzer.mark_clip_complete(clip_id, total_frames, input_type, camera_id, session_id)
                        continue
                    else:
                        # This is a regular frame, skip it (we only care about END marker)
                        if VERBOSE_LOGGING:
                            # Debug: Show what fields are in the message
                            has_msg_type = "message_type" in data
                            msg_type = data.get("message_type", "NONE")
                            print(f"   ⏭️  Skipping raw_video_frames (has message_type: {has_msg_type}, value: {msg_type})")
                        continue
                
                # Regular service data from analysis topics
                clip_id = data.get("clip_id")
                frame_index = data.get("frame_index")
                
                if clip_id is not None and frame_index is not None:
                    analyzer.add_frame_data(clip_id, frame_index, topic, data)
                    
                    if VERBOSE_LOGGING:
                        print(f"📥 {topic[:20]:20s} | Clip: {clip_id[:12]:12s} | Frame: {frame_index:2d}")
        
        # Check which clips are ready for analysis
        for clip_id in list(analyzer.clip_buffers.keys()):
            if clip_id in analyzer.completed_clips:
                continue
            
            if analyzer.is_clip_ready_for_analysis(clip_id):
                analyzer.analyze_clip(clip_id)
        
        # Check for timeout clips
        timeout_clips = analyzer.get_timeout_clips()
        for clip_id in timeout_clips:
            print(f"\n⏰ Clip {clip_id} timed out, analyzing with available data...")
            analyzer.analyze_clip(clip_id)
        
        # Periodic status update
        current_time = time.time()
        if current_time - last_status_time > STATUS_INTERVAL:
            print(f"\n📊 STATUS UPDATE (Total messages: {message_count})")
            if len(analyzer.clip_buffers) > 0:
                for cid, cdata in analyzer.clip_buffers.items():
                    metadata = cdata["metadata"]
                    frames_count = len(cdata["frames"])
                    print(f"   Clip: {cid[:12]}")
                    print(f"     - Frames: {frames_count}/{metadata.get('total_frames', '?')}")
                    print(f"     - End Marker: {metadata['end_marker_received']}")
                    print(f"     - Input Type: {metadata.get('input_type', '?')}")
                    if frames_count > 0:
                        frame_idx = list(cdata["frames"].keys())[0]
                        services = list(cdata["frames"][frame_idx].keys())
                        print(f"     - Services (frame {frame_idx}): {len(services)}")
            else:
                print(f"   ⏳ No active clips. Waiting for messages...")
            last_status_time = current_time
        
        # Periodic cleanup
        if current_time - last_cleanup_time > CLIP_CLEANUP_INTERVAL:
            analyzer.cleanup_old_clips()
            last_cleanup_time = current_time
    
    except KeyboardInterrupt:
        print("\n" + "=" * 70)
        print("SHUTDOWN: User interrupted")
        print("=" * 70)
        break
    
    except Exception as e:
        print(f"\n❌ ERROR in main loop: {e}")
        import traceback
        traceback.print_exc()
        time.sleep(1)

# Cleanup
consumer.close()
producer.close()
print("\nClip Analysis Service stopped.")
