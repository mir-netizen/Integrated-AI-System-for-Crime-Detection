import json
import time
from kafka import KafkaConsumer
from colorama import Fore, Style, init
from datetime import datetime

# Initialize colorama for colored output
init(autoreset=True)

# Configuration
KAFKA_BROKER = 'localhost:9092'
INPUT_TOPIC = 'clip_analysis_results'

# Colors for different severities
SEVERITY_COLORS = {
    "CRITICAL": Fore.RED,
    "HIGH": Fore.LIGHTRED_EX,
    "MEDIUM": Fore.YELLOW,
    "LOW": Fore.GREEN,
}

def display_clip_result(result):
    """Display clip analysis result in a formatted way"""
    
    print("\n" + "=" * 80)
    print(f"{Fore.CYAN}{'CLIP ANALYSIS RESULT':^80}{Style.RESET_ALL}")
    print("=" * 80)
    
    # Basic info
    print(f"{Fore.WHITE}Clip ID:{Style.RESET_ALL}      {result['clip_id']}")
    print(f"{Fore.WHITE}Input Type:{Style.RESET_ALL}   {result['input_type'].upper()}")
    print(f"{Fore.WHITE}Total Frames:{Style.RESET_ALL} {result['total_frames']}")
    print(f"{Fore.WHITE}Analyzed At:{Style.RESET_ALL}  {result.get('analysis_timestamp', 'N/A')}")
    print("-" * 80)
    
    # Main verdict
    verdict = result['verdict']
    confidence = result['confidence']
    threat_level = result['threat_level']
    severity = result['severity']
    
    if verdict == "SUSPICIOUS":
        color = Fore.RED
        symbol = "🚨"
    elif verdict == "SAFE":
        color = Fore.GREEN
        symbol = "✅"
    else:
        color = Fore.YELLOW
        symbol = "❓"
    
    print(f"\n{color}{Style.BRIGHT}{symbol} VERDICT: {verdict}{Style.RESET_ALL}")
    print(f"{Fore.WHITE}Confidence:{Style.RESET_ALL}   {confidence}%")
    print(f"{Fore.WHITE}Threat Level:{Style.RESET_ALL} {threat_level}/10")
    
    severity_color = SEVERITY_COLORS.get(severity, Fore.WHITE)
    print(f"{Fore.WHITE}Severity:{Style.RESET_ALL}     {severity_color}{severity}{Style.RESET_ALL}")
    
    # Weapons detected
    if result.get('weapons_detected'):
        print(f"\n{Fore.RED}{Style.BRIGHT}⚠️  WEAPONS DETECTED:{Style.RESET_ALL}")
        for weapon in result['weapons_detected']:
            print(f"   {Fore.RED}▪ Frame {weapon['frame']}: {weapon['type']} "
                  f"(confidence: {weapon['confidence']:.0%}){Style.RESET_ALL}")
    
    # Reasons
    if result.get('reasons'):
        print(f"\n{Fore.CYAN}Detailed Reasons:{Style.RESET_ALL}")
        for i, reason in enumerate(result['reasons'], 1):
            print(f"   {Fore.WHITE}{i}.{Style.RESET_ALL} {reason}")
    
    # Key frames
    if result.get('key_frames'):
        key_frames_str = ", ".join(map(str, result['key_frames']))
        print(f"\n{Fore.CYAN}Key Frames:{Style.RESET_ALL} {key_frames_str}")
    
    # Summary
    if result.get('summary'):
        print(f"\n{Fore.CYAN}Summary:{Style.RESET_ALL}")
        print(f"   {result['summary']}")
    
    print("=" * 80 + "\n")


def main():
    """Main function to consume and display clip analysis results"""
    
    print("=" * 80)
    print(f"{Fore.CYAN}{Style.BRIGHT}{'CLIP ANALYSIS RESULTS VIEWER':^80}{Style.RESET_ALL}")
    print("=" * 80)
    print(f"Kafka Broker: {KAFKA_BROKER}")
    print(f"Listening on topic: {INPUT_TOPIC}")
    print("=" * 80)
    print(f"\n{Fore.YELLOW}Waiting for clip analysis results...{Style.RESET_ALL}\n")
    
    # Create Kafka consumer
    consumer = KafkaConsumer(
        INPUT_TOPIC,
        bootstrap_servers=KAFKA_BROKER,
        value_deserializer=lambda v: json.loads(v.decode('utf-8')),
        auto_offset_reset='earliest',  # Start from beginning to see all results
        enable_auto_commit=True,
        group_id='clip_output_viewer'
    )
    
    try:
        # Listen for messages
        for message in consumer:
            result = message.value
            display_clip_result(result)
            
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}Shutting down...{Style.RESET_ALL}")
    
    finally:
        consumer.close()
        print(f"{Fore.GREEN}Viewer stopped.{Style.RESET_ALL}\n")


if __name__ == "__main__":
    main()
