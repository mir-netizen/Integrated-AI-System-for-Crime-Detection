import cv2
import time
import json
import logging
import os
import sys
import hashlib
from kafka import KafkaProducer
from kafka.errors import KafkaError

# --- Configuration ---
KAFKA_BROKER = 'localhost:9092'
OUTPUT_TOPIC = 'raw_video_frames'
CAMERA_ID = "Camera_01_Lobby"
FPS = 2 # Desired frames per second to process

# --- CLIP-BASED ANALYSIS CONFIGURATION ---
MAX_VIDEO_DURATION = 10  # Maximum video duration in seconds
MAX_FRAMES = MAX_VIDEO_DURATION * FPS  # Maximum frames to process (20 frames for 10 seconds)

# Set INPUT_FILE to your test image/video path
INPUT_FILE = None  # Will be set via command line argument
LOOP_VIDEO = False  # Deprecated - now processes once per clip
REAL_TIME_PLAYBACK = False  # Process at maximum speed for clip analysis

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def create_kafka_producer():
    """Creates and returns a Kafka producer."""
    try:
        producer = KafkaProducer(
            bootstrap_servers=KAFKA_BROKER,
            value_serializer=lambda v: json.dumps(v).encode('utf-8'),
            retries=5
        )
        logging.info("Kafka producer created successfully.")
        return producer
    except KafkaError as e:
        logging.error(f"Error creating Kafka producer: {e}")
        return None

def generate_clip_id(file_path):
    """Generate unique ID for this image/video clip"""
    timestamp = time.time()
    file_name = os.path.basename(file_path)
    clip_hash = hashlib.md5(f"{file_name}_{timestamp}".encode()).hexdigest()[:8]
    return f"clip_{clip_hash}"

def is_image_file(file_path):
    """Check if file is an image"""
    image_extensions = ('.jpg', '.jpeg', '.png', '.gif', '.bmp')
    return file_path.lower().endswith(image_extensions)

def is_video_file(file_path):
    """Check if file is a video"""
    video_extensions = ('.mp4', '.avi', '.mov', '.mkv', '.flv', '.wmv')
    return file_path.lower().endswith(video_extensions)

def process_clip(producer, input_file, clip_id):
    """Process a complete image or video clip"""
    
    # Determine input type
    if is_image_file(input_file):
        input_type = "image"
        logging.info(f"Processing IMAGE: {input_file}")
    elif is_video_file(input_file):
        input_type = "video"
        logging.info(f"Processing VIDEO (max {MAX_VIDEO_DURATION}s): {input_file}")
    else:
        logging.error(f"Unsupported file type: {input_file}")
        return False
    
    frames_to_send = []
    
    # Extract frames
    cap = cv2.VideoCapture(input_file)
    if not cap.isOpened():
        logging.error(f"Could not open file: {input_file}")
        return False
    
    # Get video properties
    total_frames_in_file = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    original_fps = cap.get(cv2.CAP_PROP_FPS)
    
    if input_type == "image":
        # For images, just read one frame
        ret, frame = cap.read()
        if ret:
            frames_to_send.append(frame)
        logging.info(f"Extracted 1 frame from image")
    else:
        # For videos, extract up to MAX_FRAMES
        frame_count = 0
        frames_extracted = 0
        
        # Calculate frame skip to get ~2 FPS
        skip_frames = max(1, int(original_fps / FPS))
        
        logging.info(f"Video info: {total_frames_in_file} frames, {original_fps:.2f} FPS")
        logging.info(f"Extracting frames at {FPS} FPS (skip every {skip_frames} frames)")
        
        while frames_extracted < MAX_FRAMES:
            ret, frame = cap.read()
            if not ret:
                break
            
            # Only keep every Nth frame
            if frame_count % skip_frames == 0:
                frames_to_send.append(frame)
                frames_extracted += 1
            
            frame_count += 1
        
        logging.info(f"Extracted {len(frames_to_send)} frames from video")
    
    cap.release()
    
    if len(frames_to_send) == 0:
        logging.error("No frames extracted from input file")
        return False
    
    # Send all frames with clip metadata
    total_frames = len(frames_to_send)
    
    logging.info("=" * 70)
    logging.info(f"SENDING CLIP: {clip_id}")
    logging.info(f"Input Type: {input_type.upper()}")
    logging.info(f"Total Frames: {total_frames}")
    logging.info("=" * 70)
    
    for frame_idx, frame in enumerate(frames_to_send):
        try:
            # Encode frame to JPEG and then to a hex string
            _, buffer = cv2.imencode('.jpg', frame)
            frame_hex = buffer.tobytes().hex()
            
            timestamp = time.time()
            
            # Prepare data payload with clip metadata
            data = {
                "camera_id": CAMERA_ID,
                "timestamp": timestamp,
                "frame_hex": frame_hex,
                "clip_id": clip_id,
                "input_type": input_type,
                "frame_index": frame_idx,
                "total_frames": total_frames,
                "source": "clip_analysis"
            }
            
            # Send data to Kafka
            producer.send(OUTPUT_TOPIC, value=data)
            logging.info(f"Sent frame {frame_idx + 1}/{total_frames} (timestamp: {timestamp:.3f})")
            
            # Small delay between frames
            time.sleep(0.5)
            
        except Exception as e:
            logging.error(f"Error sending frame {frame_idx}: {e}")
    
    # Send END marker to signal all frames sent
    try:
        end_marker = {
            "camera_id": CAMERA_ID,
            "clip_id": clip_id,
            "input_type": input_type,
            "total_frames": total_frames,
            "message_type": "END_OF_CLIP",
            "timestamp": time.time()
        }
        
        producer.send(OUTPUT_TOPIC, value=end_marker)
        producer.flush()
        
        logging.info("=" * 70)
        logging.info(f"END MARKER SENT for clip {clip_id}")
        logging.info(f"All {total_frames} frames transmitted successfully")
        logging.info("=" * 70)
        
    except Exception as e:
        logging.error(f"Error sending end marker: {e}")
        return False
    
    return True

def main():
    global INPUT_FILE
    
    # Get input file from command line argument
    if len(sys.argv) > 1:
        INPUT_FILE = sys.argv[1]
    
    if INPUT_FILE is None or not os.path.exists(INPUT_FILE):
        logging.error("=" * 70)
        logging.error("CLIP ANALYSIS MODE - INPUT FILE REQUIRED")
        logging.error("=" * 70)
        logging.error("Usage: python video_demo.py <path_to_image_or_video>")
        logging.error("Examples:")
        logging.error("  python video_demo.py img.jpg          (analyze image)")
        logging.error("  python video_demo.py test_video.mp4   (analyze 10-sec video)")
        logging.error("")
        logging.error("Supported formats:")
        logging.error("  Images: .jpg, .jpeg, .png, .gif, .bmp")
        logging.error("  Videos: .mp4, .avi, .mov, .mkv")
        logging.error("=" * 70)
        return
    
    producer = create_kafka_producer()
    if not producer:
        return
    
    # Generate unique clip ID
    clip_id = generate_clip_id(INPUT_FILE)
    
    logging.info("=" * 70)
    logging.info("CLIP-BASED ANALYSIS MODE ACTIVATED")
    logging.info("=" * 70)
    logging.info(f"Input File: {INPUT_FILE}")
    logging.info(f"Clip ID: {clip_id}")
    logging.info(f"Max Video Duration: {MAX_VIDEO_DURATION} seconds")
    logging.info(f"Processing FPS: {FPS}")
    logging.info("=" * 70)
    
    try:
        # Process the clip
        success = process_clip(producer, INPUT_FILE, clip_id)
        
        if success:
            logging.info("✅ Clip processing completed successfully")
            logging.info(f"Now wait for analysis results for clip: {clip_id}")
        else:
            logging.error("❌ Clip processing failed")
    
    except KeyboardInterrupt:
        logging.info("=" * 70)
        logging.info("Interrupted by user. Shutting down.")
        logging.info("=" * 70)
    
    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        # Cleanup
        if producer:
            producer.close()
        
        logging.info("=" * 70)
        logging.info("CLIP ANALYSIS MODE SHUTDOWN COMPLETE")
        logging.info("=" * 70)

if __name__ == "__main__":
    main()
