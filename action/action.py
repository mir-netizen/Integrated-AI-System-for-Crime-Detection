import cv2
import json
import numpy as np
import os
import torch
from kafka import KafkaConsumer, KafkaProducer
from collections import deque
import logging

# --- Kafka Configuration ---
KAFKA_BROKER = os.getenv('KAFKA_BROKER', 'localhost:9092')
INPUT_TOPIC = 'raw_video_frames'
POSE_TOPIC = 'pose_estimation_results'  # NEW: Subscribe to pose data
OUTPUT_TOPIC = 'action_recognition_results'

# --- Action Recognition Configuration ---
FRAME_BUFFER_SIZE = 16  # Number of frames needed for action recognition
FRAME_SKIP = 2  # Process every Nth frame to match model input requirements
CONFIDENCE_THRESHOLD = 0.5

# Criminal action categories we want to detect
CRIMINAL_ACTIONS = {
    'fighting', 'assault', 'punching', 'kicking', 'pushing', 'hitting',
    'stealing', 'theft', 'robbery', 'shoplifting', 'pickpocketing',
    'vandalism', 'breaking', 'destroying', 'smashing',
    'threatening', 'weapon_attack', 'stabbing', 'shooting',
    'running_away', 'fleeing', 'escaping'
}

# Safe actions for reference
SAFE_ACTIONS = {
    'walking', 'standing', 'sitting', 'talking', 'waving', 
    'handshaking', 'hugging', 'eating', 'drinking', 'reading'
}

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# --- Initialize Kafka Clients ---
try:
    # Consumer for video frames
    consumer = KafkaConsumer(
        INPUT_TOPIC,
        bootstrap_servers=KAFKA_BROKER,
        value_deserializer=lambda v: json.loads(v.decode('utf-8')),
        auto_offset_reset='latest',
        enable_auto_commit=True
    )
    
    # Consumer for pose data (separate consumer for parallel processing)
    pose_consumer = KafkaConsumer(
        POSE_TOPIC,
        bootstrap_servers=KAFKA_BROKER,
        value_deserializer=lambda v: json.loads(v.decode('utf-8')),
        auto_offset_reset='latest',
        enable_auto_commit=True,
        consumer_timeout_ms=100  # Non-blocking for multi-consumer setup
    )
    
    producer = KafkaProducer(
        bootstrap_servers=KAFKA_BROKER,
        value_serializer=lambda v: json.dumps(v).encode('utf-8')
    )
    logging.info("✅ Kafka clients created successfully")
except Exception as e:
    logging.error(f"❌ Error creating Kafka clients: {e}")
    exit(1)

# --- Action Recognition Model Setup ---
try:
    # Suppress deprecation warnings
    import warnings
    warnings.filterwarnings('ignore', category=UserWarning)
    
    # Use CPU (optimized for CPU inference)
    device = 'cpu'
    logging.info(f"🔧 Using device: {device} (CPU optimized)")
    
    # Load X3D-S model (smallest, fastest, works great on CPU)
    # Model size: ~3.8M parameters (~15MB)
    logging.info("📥 Loading X3D-S model (this may take a moment on first run)...")
    model = torch.hub.load('facebookresearch/pytorchvideo', 'x3d_s', pretrained=True)
    model = model.eval()
    model = model.to(device)
    
    # Set to inference mode for CPU optimization
    torch.set_grad_enabled(False)
    
    # Define preprocessing parameters (optimized for CPU)
    side_size = 182  # Smaller for X3D-S
    mean = torch.tensor([0.45, 0.45, 0.45]).view(3, 1, 1, 1)
    std = torch.tensor([0.225, 0.225, 0.225]).view(3, 1, 1, 1)
    crop_size = 182
    num_frames_needed = 13  # X3D-S uses 13 frames
    
    # No complex transforms needed - we'll do it manually in preprocessing
    transform = None
    
    # Kinetics-400 action labels (complete list)
    KINETICS_LABELS = {
        0: "abseiling", 1: "air_drumming", 2: "answering_questions", 3: "applauding", 4: "applying_cream",
        5: "archery", 6: "arm_wrestling", 7: "arranging_flowers", 8: "assembling_computer", 9: "auctioning",
        10: "baby_waking_up", 11: "baking_cookies", 12: "balloon_blowing", 13: "bandaging", 14: "barbequing",
        15: "bartending", 16: "beatboxing", 17: "bee_keeping", 18: "belly_dancing", 19: "bench_pressing",
        20: "bending_back", 21: "bending_metal", 22: "biking_through_snow", 23: "blasting_sand", 24: "blowing_glass",
        25: "blowing_leaves", 26: "blowing_nose", 27: "blowing_out_candles", 28: "bobsledding", 29: "bookbinding",
        30: "bouncing_on_trampoline", 31: "bowling", 32: "braiding_hair", 33: "breading_or_breadcrumbing", 34: "breakdancing",
        35: "brush_painting", 36: "brushing_hair", 37: "brushing_teeth", 38: "building_cabinet", 39: "building_shed",
        40: "bungee_jumping", 41: "busking", 42: "canoeing_or_kayaking", 43: "capoeira", 44: "carrying_baby",
        45: "cartwheeling", 46: "carving_pumpkin", 47: "catching_fish", 48: "catching_or_throwing_baseball", 49: "catching_or_throwing_frisbee",
        50: "catching_or_throwing_softball", 51: "celebrating", 52: "changing_oil", 53: "changing_wheel", 54: "checking_tires",
        55: "cheerleading", 56: "chopping_wood", 57: "clapping", 58: "clay_pottery_making", 59: "clean_and_jerk",
        60: "cleaning_floor", 61: "cleaning_gutters", 62: "cleaning_pool", 63: "cleaning_shoes", 64: "cleaning_toilet",
        65: "cleaning_windows", 66: "climbing_a_rope", 67: "climbing_ladder", 68: "climbing_tree", 69: "contact_juggling",
        70: "cooking_chicken", 71: "cooking_egg", 72: "cooking_on_campfire", 73: "cooking_sausages", 74: "counting_money",
        75: "country_line_dancing", 76: "cracking_neck", 77: "crawling_baby", 78: "crossing_river", 79: "crying",
        80: "curling_hair", 81: "cutting_nails", 82: "cutting_pineapple", 83: "cutting_watermelon", 84: "dancing_ballet",
        85: "dancing_charleston", 86: "dancing_gangnam_style", 87: "dancing_macarena", 88: "deadlifting", 89: "decorating_the_christmas_tree",
        90: "digging", 91: "dining", 92: "disc_golfing", 93: "diving_cliff", 94: "dodgeball",
        95: "doing_aerobics", 96: "doing_laundry", 97: "doing_nails", 98: "drawing", 99: "dribbling_basketball",
        100: "drinking", 101: "drinking_beer", 102: "drinking_shots", 103: "driving_car", 104: "driving_tractor",
        105: "drop_kicking", 106: "drumming_fingers", 107: "dunking_basketball", 108: "dying_hair", 109: "eating_burger",
        110: "eating_cake", 111: "eating_carrots", 112: "eating_chips", 113: "eating_doughnuts", 114: "eating_hotdog",
        115: "eating_ice_cream", 116: "eating_spaghetti", 117: "eating_watermelon", 118: "egg_hunting", 119: "exercising_arm",
        120: "exercising_with_an_exercise_ball", 121: "extinguishing_fire", 122: "faceplanting", 123: "feeding_birds", 124: "feeding_fish",
        125: "feeding_goats", 126: "filling_eyebrows", 127: "finger_snapping", 128: "fixing_hair", 129: "flipping_pancake",
        130: "flying_kite", 131: "folding_clothes", 132: "folding_napkins", 133: "folding_paper", 134: "front_raises",
        135: "frying_vegetables", 136: "garbage_collecting", 137: "gargling", 138: "getting_a_haircut", 139: "getting_a_tattoo",
        140: "giving_or_receiving_award", 141: "golf_chipping", 142: "golf_driving", 143: "golf_putting", 144: "grinding_meat",
        145: "grooming_dog", 146: "grooming_horse", 147: "gymnastics_tumbling", 148: "hammer_throw", 149: "headbanging",
        150: "headbutting", 151: "high_jump", 152: "high_kick", 153: "hitting_baseball", 154: "hockey_stop",
        155: "holding_snake", 156: "hopscotch", 157: "hoverboarding", 158: "hugging", 159: "hula_hooping",
        160: "hurdling", 161: "hurling_sport", 162: "ice_climbing", 163: "ice_fishing", 164: "ice_skating",
        165: "ironing", 166: "javelin_throw", 167: "jetskiing", 168: "jogging", 169: "juggling_balls",
        170: "juggling_fire", 171: "juggling_soccer_ball", 172: "jumping_into_pool", 173: "jumpstyle_dancing", 174: "kicking_field_goal",
        175: "kicking_soccer_ball", 176: "kissing", 177: "kitesurfing", 178: "knitting", 179: "krumping",
        180: "laughing", 181: "laying_bricks", 182: "long_jump", 183: "lunge", 184: "making_a_cake",
        185: "making_a_sandwich", 186: "making_bed", 187: "making_jewelry", 188: "making_pizza", 189: "making_snowman",
        190: "making_sushi", 191: "making_tea", 192: "marching", 193: "massaging_back", 194: "massaging_feet",
        195: "massaging_legs", 196: "massaging_person's_head", 197: "milking_cow", 198: "mopping_floor", 199: "motorcycling",
        200: "moving_furniture", 201: "mowing_lawn", 202: "news_anchoring", 203: "opening_bottle", 204: "opening_present",
        205: "paragliding", 206: "parasailing", 207: "parkour", 208: "passing_American_football_in_game", 209: "passing_American_football_not_in_game",
        210: "peeling_apples", 211: "peeling_potatoes", 212: "petting_animal_not_cat", 213: "petting_cat", 214: "picking_fruit",
        215: "planting_trees", 216: "plastering", 217: "playing_accordion", 218: "playing_badminton", 219: "playing_bagpipes",
        220: "playing_basketball", 221: "playing_bass_guitar", 222: "playing_cards", 223: "playing_cello", 224: "playing_chess",
        225: "playing_clarinet", 226: "playing_controller", 227: "playing_cricket", 228: "playing_cymbals", 229: "playing_didgeridoo",
        230: "playing_drums", 231: "playing_flute", 232: "playing_guitar", 233: "playing_harmonica", 234: "playing_harp",
        235: "playing_ice_hockey", 236: "playing_keyboard", 237: "playing_kickball", 238: "playing_monopoly", 239: "playing_organ",
        240: "playing_paintball", 241: "playing_piano", 242: "playing_poker", 243: "playing_recorder", 244: "playing_saxophone",
        245: "playing_squash_or_racquetball", 246: "playing_tennis", 247: "playing_trombone", 248: "playing_trumpet", 249: "playing_ukulele",
        250: "playing_violin", 251: "playing_volleyball", 252: "playing_xylophone", 253: "pole_vault", 254: "presenting_weather_forecast",
        255: "pull_ups", 256: "pumping_fist", 257: "pumping_gas", 258: "punching_bag", 259: "punching_person",
        260: "push_up", 261: "pushing_car", 262: "pushing_cart", 263: "pushing_wheelchair", 264: "reading_book",
        265: "reading_newspaper", 266: "recording_music", 267: "riding_a_bike", 268: "riding_camel", 269: "riding_elephant",
        270: "riding_mechanical_bull", 271: "riding_mountain_bike", 272: "riding_mule", 273: "riding_or_walking_with_horse", 274: "riding_scooter",
        275: "riding_unicycle", 276: "ripping_paper", 277: "robot_dancing", 278: "rock_climbing", 279: "rock_scissors_paper",
        280: "roller_skating", 281: "running_on_treadmill", 282: "sailing", 283: "salsa_dancing", 284: "sanding_floor",
        285: "scrambling_eggs", 286: "scuba_diving", 287: "setting_table", 288: "shaking_hands", 289: "shaking_head",
        290: "sharpening_knives", 291: "sharpening_pencil", 292: "shaving_head", 293: "shaving_legs", 294: "shearing_sheep",
        295: "shining_shoes", 296: "shooting_basketball", 297: "shooting_goal_soccer", 298: "shot_put", 299: "shoveling_snow",
        300: "shredding_paper", 301: "shuffling_cards", 302: "side_kick", 303: "sign_language_interpreting", 304: "singing",
        305: "situp", 306: "skateboarding", 307: "ski_jumping", 308: "skiing_crosscountry", 309: "skiing_slalom",
        310: "skipping_rope", 311: "skydiving", 312: "slacklining", 313: "slapping", 314: "sled_dog_racing",
        315: "smoking", 316: "smoking_hookah", 317: "snatch_weight_lifting", 318: "sneezing", 319: "sniffing",
        320: "snorkeling", 321: "snowboarding", 322: "snowkiting", 323: "snowmobiling", 324: "somersaulting",
        325: "spinning_poi", 326: "spray_painting", 327: "spraying", 328: "springboard_diving", 329: "squat",
        330: "stacking_cups", 331: "standing_on_hands", 332: "steer_roping", 333: "stomping_grapes", 334: "stretching_arm",
        335: "stretching_leg", 336: "strumming_guitar", 337: "surfing_crowd", 338: "surfing_water", 339: "sweeping_floor",
        340: "swimming_backstroke", 341: "swimming_breast_stroke", 342: "swimming_butterfly_stroke", 343: "swing_dancing", 344: "swinging_legs",
        345: "swinging_on_something", 346: "sword_fighting", 347: "tai_chi", 348: "taking_a_shower", 349: "tango_dancing",
        350: "tap_dancing", 351: "tapping_guitar", 352: "tapping_pen", 353: "tasting_beer", 354: "tasting_food",
        355: "testifying", 356: "texting", 357: "throwing_axe", 358: "throwing_ball", 359: "throwing_discus",
        360: "tickling", 361: "tobogganing", 362: "tossing_coin", 363: "tossing_salad", 364: "training_dog",
        365: "trapezing", 366: "trimming_or_shaving_beard", 367: "trimming_trees", 368: "triple_jump", 369: "tying_bow_tie",
        370: "tying_knot_not_on_a_tie", 371: "tying_tie", 372: "unboxing", 373: "unloading_truck", 374: "using_computer",
        375: "using_remote_controller_not_gaming", 376: "using_segway", 377: "vault", 378: "waiting_in_line", 379: "walking_the_dog",
        380: "washing_dishes", 381: "washing_feet", 382: "washing_hair", 383: "washing_hands", 384: "water_skiing",
        385: "water_sliding", 386: "watering_plants", 387: "waxing_back", 388: "waxing_chest", 389: "waxing_eyebrows",
        390: "waxing_legs", 391: "weaving_basket", 392: "welding", 393: "whistling", 394: "windsurfing",
        395: "wrapping_present", 396: "wrestling", 397: "writing", 398: "yawning", 399: "yoga"
    }
    
    # Criminal action keywords for filtering (from Kinetics-400)
    CRIMINAL_ACTIONS_MODEL = {
        'punching_person', 'punching_bag', 'sword_fighting', 'wrestling', 
        'slapping', 'headbutting', 'drop_kicking', 'high_kick', 'side_kick'
    }
    
    logging.info("✅ X3D-S model loaded successfully (CPU optimized)")
    
except Exception as e:
    logging.error(f"❌ Error loading X3D model: {e}")
    logging.info("⚠️  Falling back to heuristic-based action detection")
    model = None
    device = 'cpu'
    transform = None

# --- Frame Buffer Management ---
class ClipFrameBuffer:
    """Manages frame buffers for each clip"""
    def __init__(self):
        self.buffers = {}  # {clip_id: deque of frames}
        self.metadata = {}  # {clip_id: metadata}
    
    def add_frame(self, clip_id, frame_index, frame, timestamp, camera_id):
        """Add frame to clip buffer"""
        if clip_id not in self.buffers:
            self.buffers[clip_id] = deque(maxlen=FRAME_BUFFER_SIZE)
            self.metadata[clip_id] = {
                'camera_id': camera_id,
                'start_time': timestamp,
                'frame_count': 0
            }
        
        self.buffers[clip_id].append({
            'frame': frame,
            'index': frame_index,
            'timestamp': timestamp
        })
        self.metadata[clip_id]['frame_count'] += 1
    
    def is_ready(self, clip_id):
        """Check if we have enough frames for action recognition"""
        if clip_id not in self.buffers:
            return False
        return len(self.buffers[clip_id]) >= FRAME_BUFFER_SIZE
    
    def get_frames(self, clip_id):
        """Get frames for action recognition"""
        if clip_id not in self.buffers:
            return None
        return list(self.buffers[clip_id])
    
    def clear_clip(self, clip_id):
        """Clear buffer for completed clip"""
        if clip_id in self.buffers:
            del self.buffers[clip_id]
        if clip_id in self.metadata:
            del self.metadata[clip_id]

frame_buffer = ClipFrameBuffer()

class PoseDataBuffer:
    """
    Buffer to store pose data synchronized with video frames
    Handles time lag between frame arrival and pose processing
    """
    def __init__(self):
        self.buffers = {}  # {camera_id: [(timestamp, pose_data)]}
        self.last_update = {}  # {camera_id: timestamp}
    
    def add_pose_data(self, camera_id, timestamp, pose_data):
        """Add pose data to buffer (indexed by camera_id and timestamp)"""
        if camera_id not in self.buffers:
            self.buffers[camera_id] = []
            self.last_update[camera_id] = timestamp
        
        # Store with timestamp for later matching
        self.buffers[camera_id].append((timestamp, pose_data))
        self.last_update[camera_id] = timestamp
        
        # Keep only recent data (last 100 frames to handle lag)
        if len(self.buffers[camera_id]) > 100:
            self.buffers[camera_id] = self.buffers[camera_id][-100:]
    
    def get_pose_data(self, camera_id, timestamp, window=10):
        """
        Get pose data for a time window around timestamp
        Uses larger window to account for processing lag
        """
        if camera_id not in self.buffers:
            return None
        
        matching_data = []
        min_lag = float('inf')
        max_lag = float('-inf')
        
        for pose_timestamp, pose_data in self.buffers[camera_id]:
            # Match with time tolerance (pose may arrive late)
            time_diff = abs(pose_timestamp - timestamp)
            if time_diff < window:
                matching_data.append(pose_data)
                
                # Track lag for debugging
                lag = pose_timestamp - timestamp
                min_lag = min(min_lag, lag)
                max_lag = max(max_lag, lag)
        
        if matching_data:
            logging.debug(f"🕐 Pose lag: min={min_lag:.2f}s, max={max_lag:.2f}s, count={len(matching_data)}")
        
        return matching_data if matching_data else None
    
    def wait_for_pose_data(self, camera_id, timestamp, timeout=2, window=10):
        """
        Wait for pose data to arrive (with timeout)
        Useful when processing END_OF_CLIP markers
        """
        import time
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            pose_data = self.get_pose_data(camera_id, timestamp, window)
            if pose_data and len(pose_data) >= 5:  # Need at least 5 pose frames
                return pose_data
            time.sleep(0.1)  # Wait 100ms before retry
        
        # Return whatever we have (even if incomplete)
        return self.get_pose_data(camera_id, timestamp, window)
    
    def cleanup_old(self, max_age=30):
        """Remove old pose data (older than max_age seconds)"""
        import time
        current_time = time.time()
        
        to_remove = []
        for clip_id, last_time in self.last_update.items():
            if current_time - last_time > max_age:
                to_remove.append(clip_id)
        
        for clip_id in to_remove:
            if clip_id in self.buffers:
                del self.buffers[clip_id]
            if clip_id in self.last_update:
                del self.last_update[clip_id]

pose_buffer = PoseDataBuffer()

# --- Action Recognition Functions ---

def load_kinetics_labels():
    """Load Kinetics-400 action labels (400 action categories)"""
    # Kinetics-400 labels (subset of criminal-related actions)
    # In production, load from: https://dl.fbaipublicfiles.com/pyslowfast/dataset/class_names/kinetics_classnames.json
    labels = [
        'punching person (boxing)', 'punching bag', 'pushing other person',
        'fighting or sparring with partner', 'kicking field goal',
        'wrestling', 'slapping', 'shooting basketball', 'throwing ball',
        'headbutting', 'pushing cart', 'pulling rope (game)',
        'arm wrestling', 'running on treadmill', 'jogging',
        'walking', 'marching', 'dancing', 'jumping', 'exercising',
        'holding or opening umbrella', 'hugging (not baby)', 'kissing',
        'shaking hands', 'waving hand', 'high fiving', 'clapping'
        # ... 400 total labels
    ]
    return labels

def pose_based_action_detection(pose_data_list):
    """
    Detect actions using pose keypoints from YOLOv8-pose
    Keypoints: [nose, eyes, ears, shoulders, elbows, wrists, hips, knees, ankles]
    Format: [[y, x, confidence], ...] for 17 keypoints
    
    STRICT THRESHOLDS: Only detect actual fighting, not walking/moving
    """
    if not pose_data_list or len(pose_data_list) < 5:  # Need at least 5 frames
        return None
    
    total_fighting_indicators = 0
    frames_with_fighting = 0
    aggressive_score = 0
    
    for pose_frame in pose_data_list:
        if 'persons' not in pose_frame or len(pose_frame['persons']) == 0:
            continue
        
        frame_fighting_score = 0
        
        for person in pose_frame['persons']:
            keypoints = person.get('keypoints', [])
            if len(keypoints) < 17:
                continue
            
            # Extract key body parts (normalized coordinates)
            left_wrist = keypoints[9]   # [y, x, conf]
            right_wrist = keypoints[10]
            left_elbow = keypoints[7]
            right_elbow = keypoints[8]
            left_shoulder = keypoints[5]
            right_shoulder = keypoints[6]
            nose = keypoints[0]
            left_knee = keypoints[13]
            right_knee = keypoints[14]
            left_hip = keypoints[11]
            right_hip = keypoints[12]
            
            # Require high confidence for all key points
            if (left_wrist[2] < 0.6 or right_wrist[2] < 0.6 or
                left_shoulder[2] < 0.6 or right_shoulder[2] < 0.6):
                continue
            
            person_indicators = 0
            
            # INDICATOR 1: BOTH arms raised high above shoulders (fighting stance)
            # Walking/waving only raises ONE arm usually
            left_arm_raised = left_wrist[0] < (left_shoulder[0] - 0.15)  # Much higher
            right_arm_raised = right_wrist[0] < (right_shoulder[0] - 0.15)
            
            if left_arm_raised and right_arm_raised:  # BOTH arms raised
                person_indicators += 3
                frame_fighting_score += 1.0
            
            # INDICATOR 2: Arms extended forward (punching motion)
            # Must be forward extension, not just raised
            if left_elbow[2] > 0.6 and right_elbow[2] > 0.6:
                # Check horizontal extension (x coordinate difference)
                left_extended_forward = abs(left_wrist[1] - left_shoulder[1]) > 0.2
                right_extended_forward = abs(right_wrist[1] - right_shoulder[1]) > 0.2
                
                # Arms extended at shoulder height (not up or down)
                left_shoulder_height = abs(left_wrist[0] - left_shoulder[0]) < 0.1
                right_shoulder_height = abs(right_wrist[0] - right_shoulder[0]) < 0.1
                
                if (left_extended_forward and left_shoulder_height) or \
                   (right_extended_forward and right_shoulder_height):
                    person_indicators += 4
                    frame_fighting_score += 1.5
            
            # INDICATOR 3: High leg kick (knee significantly raised)
            # Walking raises knee only slightly
            if left_knee[2] > 0.6 and right_knee[2] > 0.6 and left_hip[2] > 0.6:
                left_knee_high = left_knee[0] < (left_hip[0] - 0.2)  # Much higher than hip
                right_knee_high = right_knee[0] < (right_hip[0] - 0.2)
                
                if left_knee_high or right_knee_high:
                    person_indicators += 5  # Strong indicator
                    frame_fighting_score += 2.0
            
            # INDICATOR 4: Multiple persons in close proximity (fighting/grappling)
            if len(pose_frame['persons']) >= 2:
                person_indicators += 2
                frame_fighting_score += 0.8
            
            total_fighting_indicators += person_indicators
            
            # Count frame as "fighting frame" if person shows strong indicators
            if person_indicators >= 5:
                frames_with_fighting += 1
    
    # STRICT THRESHOLDS: Require consistent fighting across multiple frames
    avg_score = total_fighting_indicators / max(len(pose_data_list), 1)
    fighting_ratio = frames_with_fighting / max(len(pose_data_list), 1)
    
    logging.debug(f"🥊 Pose analysis: total_indicators={total_fighting_indicators}, "
                 f"fighting_frames={frames_with_fighting}/{len(pose_data_list)}, "
                 f"ratio={fighting_ratio:.2f}, avg_score={avg_score:.2f}")
    
    # FIGHTING: Need high indicators AND at least 30% frames showing fighting
    if total_fighting_indicators >= 20 and frames_with_fighting >= 3 and fighting_ratio >= 0.3:
        return {
            'action': 'fighting_or_assault',
            'confidence': min(0.92, 0.5 + fighting_ratio * 0.5),
            'category': 'potentially_violent',
            'detection_method': 'pose_keypoints',
            'fighting_indicators': total_fighting_indicators,
            'fighting_frames': frames_with_fighting,
            'pose_score': float(avg_score)
        }
    # AGGRESSIVE: Moderate indicators across frames
    elif total_fighting_indicators >= 12 and frames_with_fighting >= 2:
        return {
            'action': 'aggressive_posture',
            'confidence': min(0.80, 0.4 + fighting_ratio * 0.4),
            'category': 'potentially_violent',
            'detection_method': 'pose_keypoints',
            'fighting_indicators': total_fighting_indicators,
            'fighting_frames': frames_with_fighting,
            'pose_score': float(avg_score)
        }
    
    # Don't return "active_movement" - let motion analysis handle normal movement
    return None  # No fighting detected, fall back to motion analysis

def heuristic_action_detection(frames):
    """
    Enhanced heuristic-based action detection using multi-feature motion analysis
    Works well for surveillance footage where deep learning models may fail
    """
    if len(frames) < 2:
        return {'action': 'insufficient_frames', 'confidence': 0.0, 'category': 'unknown'}
    
    # Feature 1: Frame-to-frame differences (motion intensity)
    motion_scores = []
    motion_spikes = []
    prev_frame = frames[0]['frame']
    
    for i in range(1, len(frames)):
        curr_frame = frames[i]['frame']
        
        # Convert to grayscale for better motion detection
        if len(prev_frame.shape) == 3:
            prev_gray = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY)
            curr_gray = cv2.cvtColor(curr_frame, cv2.COLOR_BGR2GRAY)
        else:
            prev_gray = prev_frame
            curr_gray = curr_frame
        
        # Calculate frame difference
        diff = cv2.absdiff(prev_gray, curr_gray)
        motion_score = np.mean(diff)
        motion_scores.append(motion_score)
        
        # Detect sudden spikes (indicative of violent actions)
        if i > 1 and motion_score > 1.5 * motion_scores[-2]:
            motion_spikes.append(motion_score)
        
        prev_frame = curr_frame
    
    # Statistical features
    avg_motion = np.mean(motion_scores)
    max_motion = np.max(motion_scores)
    motion_variance = np.var(motion_scores)
    motion_std = np.std(motion_scores)
    spike_count = len(motion_spikes)
    
    # Debug logging to understand the motion values
    logging.info(f"📊 Motion Analysis: avg={avg_motion:.1f}, max={max_motion:.1f}, "
                f"var={motion_variance:.1f}, std={motion_std:.1f}, spikes={spike_count}")
    
    # Feature 2: Optical flow magnitude (if high motion detected)
    flow_magnitude = 0
    if avg_motion > 15:
        try:
            # Calculate optical flow between first and middle frame
            gray1 = cv2.cvtColor(frames[0]['frame'], cv2.COLOR_BGR2GRAY)
            gray2 = cv2.cvtColor(frames[len(frames)//2]['frame'], cv2.COLOR_BGR2GRAY)
            flow = cv2.calcOpticalFlowFarneback(gray1, gray2, None, 0.5, 3, 15, 3, 5, 1.2, 0)
            flow_magnitude = np.mean(np.sqrt(flow[..., 0]**2 + flow[..., 1]**2))
        except:
            flow_magnitude = avg_motion / 10  # Rough estimate
    
    # Enhanced classification rules (LOWERED THRESHOLDS for better sensitivity)
    confidence = 0.0
    action = 'unknown'
    category = 'neutral'
    
    # Rule 1: Violent/aggressive actions (MUCH LOWER THRESHOLDS)
    if (max_motion > 35 and motion_variance > 80) or (spike_count >= 3 and avg_motion > 20):
        action = 'fighting_or_assault'
        confidence = min(0.90, (max_motion + motion_variance) / 150)
        category = 'potentially_violent'
        
    elif (max_motion > 25 and motion_std > 6) or (spike_count >= 2 and avg_motion > 15):
        action = 'aggressive_movement'
        confidence = min(0.85, (max_motion + motion_std * 3) / 120)
        category = 'potentially_violent'
        
    elif (max_motion > 20 and motion_variance > 40) or (avg_motion > 18 and motion_std > 5):
        action = 'rapid_movement'
        confidence = 0.80
        category = 'potentially_violent'
        
    # Rule 2: Suspicious rapid movements
    elif avg_motion > 25 and flow_magnitude > 2.0:
        action = 'running_or_chasing'
        confidence = 0.75
        category = 'suspicious'
        
    elif avg_motion > 20 or max_motion > 30:
        action = 'fast_movement'
        confidence = 0.70
        category = 'active'
        
    # Rule 3: Normal activity
    elif avg_motion > 12:
        action = 'walking_or_moving'
        confidence = 0.75
        category = 'normal'
        
    elif avg_motion > 4:
        action = 'slow_movement'
        confidence = 0.80
        category = 'normal'
        
    # Rule 4: Minimal activity
    else:
        action = 'standing_or_sitting'
        confidence = 0.90
        category = 'stationary'
    
    return {
        'action': action,
        'confidence': float(confidence),
        'category': category,
        'motion_intensity': float(avg_motion),
        'motion_variance': float(motion_variance),
        'motion_std': float(motion_std),
        'max_motion': float(max_motion),
        'spike_count': spike_count,
        'flow_magnitude': float(flow_magnitude)
    }

def recognize_action_with_model(frames, model, device):
    """
    Use X3D-S model for action recognition (CPU optimized)
    Returns top predicted actions from Kinetics-400
    """
    try:
        # Prepare frames for X3D-S model input
        # X3D-S expects: (batch, channels, time, height, width)
        # We need 13 frames for X3D-S
        
        # Sample 13 frames uniformly from buffer
        frame_indices = np.linspace(0, len(frames) - 1, num_frames_needed, dtype=int)
        
        frame_tensors = []
        for idx in frame_indices:
            frame = frames[idx]['frame']
            # Convert BGR to RGB
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            # Resize to 182x182 (X3D-S input size)
            frame_resized = cv2.resize(frame_rgb, (182, 182))
            frame_tensors.append(frame_resized)
        
        # Stack frames: (T, H, W, C) -> (C, T, H, W)
        video_array = np.stack(frame_tensors, axis=0)  # (13, 182, 182, 3)
        video_tensor = torch.from_numpy(video_array).permute(3, 0, 1, 2).float()  # (3, 13, 182, 182)
        
        # Manual preprocessing (normalize to 0-1, then standardize)
        video_tensor = video_tensor / 255.0
        video_tensor = (video_tensor - mean) / std
        
        # Add batch dimension
        video_input = video_tensor.unsqueeze(0).to(device)  # (1, 3, 13, 182, 182)
        
        # Run inference (CPU optimized, no grad)
        with torch.no_grad():
            predictions = model(video_input)
            probabilities = torch.nn.functional.softmax(predictions, dim=1)
            # Get top 10 to increase chance of finding violent actions
            top_probs, top_classes = torch.topk(probabilities, k=10)
        
        # Get top 10 predictions and filter for relevant actions
        results = []
        criminal_results = []
        all_predictions = []  # For debugging
        
        for prob, cls_idx in zip(top_probs[0], top_classes[0]):
            cls_idx = int(cls_idx)
            if cls_idx in KINETICS_LABELS:
                action_name = KINETICS_LABELS[cls_idx]
                confidence = float(prob)
                category = classify_action_category(action_name)
                
                all_predictions.append(f"{action_name}({confidence:.2f})")
                
                result_dict = {
                    'action': action_name,
                    'confidence': confidence,
                    'category': category,
                    'class_id': cls_idx
                }
                
                # Prioritize criminal actions even with lower confidence
                if category == 'potentially_violent' and confidence > 0.10:
                    criminal_results.append(result_dict)
                elif confidence > 0.25:  # Higher threshold for non-criminal
                    results.append(result_dict)
        
        # Log top predictions for debugging
        logging.debug(f"Top-10: {', '.join(all_predictions[:10])}")
        
        # Return criminal action if found, otherwise best non-criminal
        if criminal_results:
            return criminal_results[0]  # Return highest confidence criminal action
        elif results:
            return results[0]
        else:
            # Fallback to heuristic if X3D confidence is too low
            return heuristic_action_detection(frames)
    
    except Exception as e:
        logging.error(f"Error in model inference: {e}")
        return heuristic_action_detection(frames)

def classify_action_category(action_name):
    """Classify action into criminal/safe categories"""
    action_lower = action_name.lower().replace(' ', '_')
    
    # Check model-specific criminal actions first (more precise)
    try:
        if action_lower in CRIMINAL_ACTIONS_MODEL:
            return 'potentially_violent'
    except:
        pass
    
    # Check general criminal action keywords
    for criminal_action in CRIMINAL_ACTIONS:
        if criminal_action in action_lower:
            return 'potentially_violent'
    
    # Check safe actions
    for safe_action in SAFE_ACTIONS:
        if safe_action in action_lower:
            return 'safe'
    
    return 'neutral'

def process_clip_for_actions(clip_id, frames, metadata, pose_data=None):
    """
    Process buffered frames for action recognition
    
    Args:
        clip_id: Unique identifier for the clip
        frames: List of video frames
        metadata: Camera and timestamp information
        pose_data: Optional list of pose keypoint data from pose service
    """
    try:
        logging.info(f"🎬 Analyzing actions for clip {clip_id[:12]} ({len(frames)} frames)")
        
        # PRIORITY 1: Use pose keypoints if available AND high confidence
        pose_result = None
        if pose_data and len(pose_data) >= 5:  # Need at least 5 pose frames
            pose_result = pose_based_action_detection(pose_data)
            
            # Only use pose result if it detects fighting with high confidence
            # Don't use it for normal movement - let motion analysis handle that
            if pose_result and pose_result['category'] == 'potentially_violent':
                if pose_result['confidence'] > 0.7:
                    logging.info(f"✅ Pose detection: {pose_result['action']} "
                               f"(conf: {pose_result['confidence']:.2f}, "
                               f"indicators: {pose_result['fighting_indicators']}, "
                               f"fighting_frames: {pose_result['fighting_frames']})")
                    return pose_result
                else:
                    logging.debug(f"⚠️  Pose confidence too low ({pose_result['confidence']:.2f}), "
                                f"combining with motion analysis")
        
        # PRIORITY 2: Use motion heuristics (proven to work for surveillance)
        heuristic_result = heuristic_action_detection(frames)
        
        # PRIORITY 3: Try X3D for specific action classification (if available and confident)
        if model is not None and heuristic_result['confidence'] < 0.9:
            # Only use X3D to refine high-motion detections
            if heuristic_result.get('motion_intensity', 0) > 40:
                try:
                    x3d_result = recognize_action_with_model(frames, model, device)
                    # Use X3D result only if it's violent and confident enough
                    if (x3d_result.get('category') == 'potentially_violent' and 
                        x3d_result.get('confidence', 0) > 0.30):
                        # Combine: Use X3D's specific action name with heuristic's motion data
                        result = {
                            'action': x3d_result['action'],
                            'confidence': max(heuristic_result['confidence'], x3d_result['confidence']),
                            'category': 'potentially_violent',
                            'motion_intensity': heuristic_result.get('motion_intensity', 0),
                            'motion_variance': heuristic_result.get('motion_variance', 0),
                            'detection_method': 'hybrid_x3d_motion'
                        }
                        logging.info(f"✅ Hybrid: X3D identified specific action, motion confirmed")
                        return result
                except Exception as e:
                    logging.debug(f"X3D failed, using heuristic: {e}")
        
        # Default: Use heuristic result (more reliable for surveillance)
        result = heuristic_result
        result['detection_method'] = 'motion_heuristic'
        
        # Prepare output
        output_data = {
            'clip_id': clip_id,
            'camera_id': metadata['camera_id'],
            'timestamp': metadata['start_time'],
            'frame_count': len(frames),
            'detected_action': result.get('action', 'unknown'),
            'confidence': result.get('confidence', 0.0),
            'category': result.get('category', 'neutral'),
            'motion_intensity': result.get('motion_intensity', 0.0),
            'motion_variance': result.get('motion_variance', 0.0)
        }
        
        # Send to Kafka
        producer.send(OUTPUT_TOPIC, value=output_data)
        
        logging.info(f"✅ Action detected: {result.get('action')} "
                    f"(confidence: {result.get('confidence', 0):.2f}, "
                    f"category: {result.get('category', 'neutral')})")
        
        return output_data
        
    except Exception as e:
        logging.error(f"❌ Error processing clip for actions: {e}")
        return None

# --- Main Processing Loop ---
logging.info("=" * 70)
logging.info("🎬 ACTION RECOGNITION SERVICE STARTED")
logging.info("=" * 70)
logging.info(f"Kafka Broker: {KAFKA_BROKER}")
logging.info(f"Input Topic: {INPUT_TOPIC}")
logging.info(f"Output Topic: {OUTPUT_TOPIC}")
logging.info(f"Frame Buffer Size: {FRAME_BUFFER_SIZE}")
logging.info(f"Device: {device}")
logging.info("=" * 70)
logging.info("Waiting for video frames...\n")

processed_clips = set()
import time
last_cleanup = time.time()

try:
    # Poll both consumers in a loop
    while True:
        # 1. Process pose data FIRST (non-blocking, frequent polling)
        # Poll pose data multiple times to catch up with lag
        for _ in range(5):  # Poll 5 times to catch any backlog
            try:
                pose_messages = pose_consumer.poll(timeout_ms=10, max_records=20)
                for topic_partition, messages in pose_messages.items():
                    for message in messages:
                        try:
                            pose_data = message.value
                            camera_id = pose_data.get('camera_id', 'unknown')
                            timestamp = pose_data.get('timestamp', time.time())
                            
                            # Store pose data in buffer
                            pose_buffer.add_pose_data(camera_id, timestamp, pose_data)
                            
                        except Exception as e:
                            logging.error(f"Error processing pose data: {e}")
            except Exception as e:
                logging.error(f"Error polling pose consumer: {e}")
        
        # 2. Process video frames
        try:
            frame_messages = consumer.poll(timeout_ms=100, max_records=5)
            for topic_partition, messages in frame_messages.items():
                for message in messages:
                    try:
                        data = message.value
                        
                        # Skip END_OF_CLIP markers
                        if data.get('message_type') == 'END_OF_CLIP':
                            clip_id = data.get('clip_id')
                            
                            # Process clip if we have enough frames
                            if clip_id and clip_id not in processed_clips:
                                if frame_buffer.is_ready(clip_id):
                                    frames = frame_buffer.get_frames(clip_id)
                                    metadata = frame_buffer.metadata.get(clip_id, {})
                                    
                                    # WAIT for pose data to arrive (with timeout)
                                    camera_id = metadata.get('camera_id', 'unknown')
                                    timestamp = metadata.get('timestamp', time.time())
                                    
                                    logging.info(f"⏳ Waiting for pose data for clip {clip_id[:12]}...")
                                    pose_data = pose_buffer.wait_for_pose_data(
                                        camera_id, timestamp, 
                                        timeout=2,  # Wait up to 2 seconds
                                        window=10   # 10-second time window
                                    )
                                    
                                    if pose_data:
                                        logging.info(f"✅ Got {len(pose_data)} pose frames for clip")
                                    else:
                                        logging.warning(f"⚠️  No pose data available for clip (will use motion analysis)")
                                    
                                    process_clip_for_actions(clip_id, frames, metadata, pose_data)
                                    
                                    processed_clips.add(clip_id)
                                    frame_buffer.clear_clip(clip_id)
                                else:
                                    logging.warning(f"⚠️  Clip {clip_id[:12]} ended but not enough frames "
                                                  f"({len(frame_buffer.buffers.get(clip_id, []))} < {FRAME_BUFFER_SIZE})")
                            continue
                        
                        # Skip if no frame_hex
                        if 'frame_hex' not in data:
                            continue
                        
                        # Decode frame
                        frame_bytes = np.frombuffer(bytes.fromhex(data['frame_hex']), dtype=np.uint8)
                        frame = cv2.imdecode(frame_bytes, cv2.IMREAD_COLOR)
                        
                        if frame is None:
                            continue
                        
                        # Extract metadata
                        clip_id = data.get('clip_id')
                        frame_index = data.get('frame_index', 0)
                        timestamp = data.get('timestamp')
                        camera_id = data.get('camera_id', 'unknown')
                        
                        if not clip_id:
                            continue
                        
                        # Add frame to buffer
                        frame_buffer.add_frame(clip_id, frame_index, frame, timestamp, camera_id)
                        
                        # Process when buffer is full (for continuous analysis)
                        if frame_buffer.is_ready(clip_id) and clip_id not in processed_clips:
                            frames = frame_buffer.get_frames(clip_id)
                            metadata = frame_buffer.metadata.get(clip_id, {})
                            
                            # Get synchronized pose data (no wait for continuous processing)
                            camera_id = metadata.get('camera_id', 'unknown')
                            timestamp = metadata.get('timestamp', time.time())
                            pose_data = pose_buffer.get_pose_data(camera_id, timestamp, window=10)
                            
                            if pose_data:
                                logging.debug(f"📍 Got {len(pose_data)} pose frames for continuous analysis")
                            
                            process_clip_for_actions(clip_id, frames, metadata, pose_data)
                            
                    except Exception as e:
                        logging.error(f"❌ Error processing frame message: {e}")
                        continue
        except Exception as e:
            logging.error(f"Error polling frame consumer: {e}")
        
        # 3. Periodic cleanup of old pose data
        current_time = time.time()
        if current_time - last_cleanup > 30:
            pose_buffer.cleanup_old(max_age=30)
            last_cleanup = current_time

except KeyboardInterrupt:
    logging.info("\n" + "=" * 70)
    logging.info("🛑 Action Recognition Service stopped by user")
    logging.info("=" * 70)

except Exception as e:
    logging.error(f"❌ Fatal error in main loop: {e}")
    import traceback
    traceback.print_exc()

finally:
    consumer.close()
    producer.close()
    logging.info("✅ Kafka clients closed")
