import cv2
import mediapipe as mp
import serial
import time
import math
import collections
import numpy as np
import csv

# ==========================
# ESP32 SERIAL CONFIGURATION
# ==========================

import serial.tools.list_ports

# Manual COM port setting (e.g., "COM3", "COM10"). Set to "" or None for auto-detection.
ESP32_PORT = ""

# Time in seconds of no motion before turning off the lights (e.g. 10 for demo, 300 for 5 minutes)
MOTION_TIMEOUT = 200

esp32 = None

if ESP32_PORT:
    print(f"Attempting connection to configured ESP32 port: {ESP32_PORT}...")
    try:
        s = serial.Serial(ESP32_PORT, 115200, timeout=0.05)
        time.sleep(2)
        s.write(b"\n")
        print(f"--> SUCCESS: Connected to ESP32 on configured port {ESP32_PORT}!")
        esp32 = s
    except Exception as e:
        print(f"Could not connect to configured port {ESP32_PORT}: {e}")

if not esp32:
    ports = list(serial.tools.list_ports.comports())
    print("Scanning available COM ports...")
    for p in ports:
        print(f"Found: {p.device} - {p.description}")

    # Try to connect to the ESP32
    for p in ports:
        # Skip standard bluetooth ports as they cause slow timeouts
        if "Bluetooth" in p.description or "Standard Serial over Bluetooth" in p.description:
            continue
        
        print(f"Attempting to connect to {p.device}...")
        try:
            # Set timeout to 0.05s to prevent blocking on serial reads
            s = serial.Serial(p.device, 115200, timeout=0.05)
            time.sleep(2)
            s.write(b"\n")
            print(f"--> SUCCESS: Connected to ESP32 on {p.device}!")
            esp32 = s
            break
        except Exception as e:
            print(f"Could not connect on {p.device}: {e}")

if not esp32:
    print("Warning: Could not connect to any ESP32 COM port. Serial commands will be mocked.")

# ==========================
# MEDIAPIPE INITIALIZATION
# ==========================

mp_face_mesh = mp.solutions.face_mesh
face_mesh = mp_face_mesh.FaceMesh(
    max_num_faces=1,
    refine_landmarks=True,
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5
)

mp_hands = mp.solutions.hands
hands = mp_hands.Hands(
    max_num_hands=2,
    min_detection_confidence=0.7,
    min_tracking_confidence=0.7
)

mp_drawing = mp.solutions.drawing_utils
mp_drawing_styles = mp.solutions.drawing_styles

# ==========================
# CAMERA
# ==========================

cap = cv2.VideoCapture(0)
# Give camera a moment to release and initialize if busy
for i in range(3):
    if cap.isOpened():
        break
    print("Camera busy, retrying in 1s...")
    time.sleep(1)
    cap = cv2.VideoCapture(0)

if not cap.isOpened():
    print("Error: Could not open webcam.")

last_command = ""
last_write_time = 0
write_interval = 0.05  # 50ms rate limit to prevent flooding the serial port

# ==========================
# SEND COMMAND
# ==========================

def send_command(cmd, force=False):
    global last_command, last_write_time, esp32
    current_time = time.time()
    if cmd != last_command or force:
        if force or (current_time - last_write_time >= write_interval):
            if esp32:
                try:
                    esp32.write((cmd + "\n").encode())
                except Exception as e:
                    print(f"Warning: Serial connection lost while writing. Switching to mock mode. Error: {e}")
                    esp32 = None
            print("Sent:", cmd)
            last_command = cmd
            last_write_time = current_time

# ==========================
# HELPER FUNCTIONS
# ==========================

def get_distance(p1, p2):
    return math.sqrt((p1.x - p2.x)**2 + (p1.y - p2.y)**2)

# 6-point EAR calculation
def calculate_ear(indices, landmarks):
    p1 = landmarks[indices[0]]
    p2 = landmarks[indices[1]]
    p3 = landmarks[indices[2]]
    p4 = landmarks[indices[3]]
    p5 = landmarks[indices[4]]
    p6 = landmarks[indices[5]]
    
    d_v1 = get_distance(p2, p6)
    d_v2 = get_distance(p3, p5)
    d_h = get_distance(p1, p4)
    
    if d_h == 0:
        return 0.0
    return (d_v1 + d_v2) / (2.0 * d_h)

# ==========================
# STATE & CONFIGURATION
# ==========================

# Standard 6-point indices for EAR
right_eye_indices = [33, 160, 158, 133, 153, 144]
left_eye_indices = [362, 385, 387, 263, 373, 380]

# Blink tracking
blink_counter = 0
last_blink_time = 0
eyes_closed = False
blink_window = 1.2  # seconds
light_on = True

# Color shifting state (HSV Hue 0-255)
hue = 15  # Start warm (orange)
head_roll = 0.0
last_color_shift_time = 0
COLOR_SHIFT_INTERVAL = 0.5  # shift color every 0.5s so user can select/stop on one

# Mode state
current_mode = "NORMAL"
last_energy_cmd_time = 0

# Pinch gestures timing
last_left_pinch_time = 0
last_right_pinch_time = 0
pinch_cooldown = 0.25  # seconds

# Overlay status messaging
status_message = ""
status_msg_time = 0

# LDR, PIR, ACS712 & Relay tracking
last_motion_time = time.time()
ldr_val = 0    # Default initial value showing optimal light (0 = Light, 1 = Dark)
pir_val = 0    # Default no motion detected
acs_val = 0    # Default raw current sensor reading
relay_state = "OFF" # Default relay state

# =========================================================
# NEW FEATURES: MUSIC REACTIVE & EMERGENCY MODES SETUP
# =========================================================

# Emergency variables
security_mode_enabled = False
emergency_active = False
emergency_trigger_time = 0.0
emergency_counter = 0
pre_emergency_mode = "NORMAL"
pre_emergency_light_on = True
pre_emergency_relay_state = "OFF"

# CSV logging helper
def log_emergency_event(trigger_time, duration):
    lt = time.localtime(trigger_time)
    date_str = time.strftime("%Y-%m-%d", lt)
    time_str = time.strftime("%H:%M:%S", lt)
    try:
        # Check if file exists to write headers
        file_exists = False
        try:
            with open("emergency_log.csv", "r") as check_f:
                file_exists = True
        except FileNotFoundError:
            pass

        with open("emergency_log.csv", mode="a", newline="") as log_file:
            writer = csv.writer(log_file)
            if not file_exists:
                writer.writerow(["Date", "Time", "Duration (seconds)"])
            writer.writerow([date_str, time_str, f"{duration:.1f}"])
        print(f"Logged Emergency Event to CSV: {date_str} {time_str} ({duration:.1f}s)")
    except Exception as e:
        print(f"Error logging emergency event: {e}")

# Trigger Emergency Mode
def trigger_emergency():
    global emergency_active, current_mode, pre_emergency_mode, emergency_trigger_time, emergency_counter
    global pre_emergency_light_on, pre_emergency_relay_state, status_message, status_msg_time, light_on, relay_state
    if emergency_active:
        return

    emergency_active = True
    pre_emergency_mode = current_mode
    pre_emergency_light_on = light_on
    pre_emergency_relay_state = relay_state

    current_mode = "EMERGENCY"
    emergency_trigger_time = time.time()
    emergency_counter += 1

    light_on = True
    relay_state = "ON"

    # Send physical outputs trigger to ESP32
    send_command("MODE_EMERGENCY")

    # Update Blynk Vpins via ESP32
    send_command("B_WRITE,21,255") # Emergency status LED (255)
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(emergency_trigger_time))
    evt_msg = f"Emergency Alert: Motion detected while security mode is active. Time: {timestamp}"
    send_command(f"B_WRITE,22,{evt_msg}") # Notification string
    send_command(f"B_WRITE,23,{emergency_counter}") # Emergency Counter

    status_message = "EMERGENCY ACTIVE"
    status_msg_time = time.time()

# Clear Emergency Mode
def clear_emergency():
    global emergency_active, current_mode, pre_emergency_mode, light_on, relay_state, status_message, status_msg_time
    if not emergency_active:
        return

    emergency_active = False
    duration = time.time() - emergency_trigger_time
    log_emergency_event(emergency_trigger_time, duration)

    # Clear status LED on Blynk
    send_command("B_WRITE,21,0")

    # Restore pre-emergency states
    current_mode = pre_emergency_mode
    light_on = pre_emergency_light_on
    relay_state = pre_emergency_relay_state

    send_command(f"MODE_{current_mode}")
    if light_on:
        send_command("LIGHT_ON")
        send_command("RELAY_ON")
    else:
        send_command("LIGHT_OFF")
        send_command("RELAY_OFF")

    status_message = f"EMERGENCY CLEARED -> MODE: {current_mode}"
    status_msg_time = time.time()

# ==========================
# MAIN LOOP
# ==========================

while True:
    success, frame = cap.read()
    if not success:
        break

    frame = cv2.flip(frame, 1)
    h, w, _ = frame.shape
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    # Emergency automatic deactivation check (clear if no motion for 30s)
    if emergency_active:
        if time.time() - last_motion_time > 30.0:
            clear_emergency()

    # Energy Saving Mode: Automatic brightness based on ambient light
    if current_mode == "ENERGY":
        current_time = time.time()
        if current_time - last_energy_cmd_time > 1.0: # Update every 1 second
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            avg_brightness = np.mean(gray)
            # Map avg_brightness (0-255) to LED brightness (255-20) inversely
            target_brightness = int(np.interp(avg_brightness, [50, 200], [255, 20]))
            send_command(f"BRIGHTNESS,{target_brightness}")
            last_energy_cmd_time = current_time

    # Read sensor data from ESP32 if available (non-blocking)
    if esp32:
        try:
            while esp32.in_waiting > 0:
                line = esp32.readline().decode('utf-8', errors='ignore').strip()
                if line:
                    print("ESP32 Serial RX:", line)  # Show serial prints in console for live debugging
                
                # Expected format from ESP32: "BLYNK,V20,val" or "BLYNK,V27,val"
                if line.startswith("BLYNK,"):
                    parts = line.split(",")
                    if len(parts) >= 3:
                        pin_str = parts[1]
                        val_str = parts[2]
                        try:
                            val = int(val_str)
                            if pin_str == "V27": # Security Mode Switch
                                security_mode_enabled = (val == 1)
                                if not security_mode_enabled and emergency_active:
                                    clear_emergency()
                                status_message = f"SECURITY: {'ARMED' if security_mode_enabled else 'DISARMED'}"
                                status_msg_time = time.time()
                        except ValueError:
                            pass

                # Expected format from ESP32: "SENSOR,ldr_val,pir_val,acs_val"
                elif line.startswith("SENSOR,"):
                    parts = line.split(",")
                    try:
                        if len(parts) >= 3:
                            ldr_val = int(parts[1])
                            pir_val = int(parts[2])
                            if len(parts) >= 4:
                                acs_val = int(parts[3])
                            
                            current_time = time.time()
                            
                            if pir_val == 1:
                                last_motion_time = current_time
                            
                            # Emergency Trigger Check (Triggers ONLY when Security Mode is ARMED)
                            if pir_val == 1 and not emergency_active:
                                if security_mode_enabled:
                                    trigger_emergency()

                            # If emergency is not active, run normal motion control logic
                            if not emergency_active:
                                # Logic 1: If PIR detects motion (1), turn light ON
                                if pir_val == 1:
                                    if not light_on:
                                        send_command("LIGHT_ON")
                                        send_command("RELAY_ON")
                                        light_on = True
                                        relay_state = "ON"
                                        status_message = "SENSORS -> LIGHT & RELAY ON"
                                        status_msg_time = current_time
                                
                                # Logic 2: If no motion for > MOTION_TIMEOUT (200s), turn light OFF automatically
                                elif current_time - last_motion_time > MOTION_TIMEOUT:
                                    if light_on:
                                        send_command("LIGHT_OFF")
                                        send_command("RELAY_OFF")
                                        light_on = False
                                        relay_state = "OFF"
                                        status_message = "SENSORS -> LIGHT & RELAY OFF"
                                        status_msg_time = current_time
                    except ValueError as ve:
                        print(f"Warning: Error parsing sensor values: {ve}")
        except Exception as e:
            print(f"Warning: Serial connection lost while reading. Switching to mock mode. Error: {e}")
            esp32 = None

    # Process models
    results_face = face_mesh.process(rgb)
    results_hands = hands.process(rgb)

    # Initialize variables for display
    avg_EAR = 0.0
    mouth_ratio = 0.0
    mouth_open = False
    left_hand_pinch = False
    right_hand_pinch = False

    # Face/Head Logic
    if results_face.multi_face_landmarks:
        face = results_face.multi_face_landmarks[0]
        
        # Calculate eye aspect ratio
        left_EAR = calculate_ear(left_eye_indices, face.landmark)
        right_EAR = calculate_ear(right_eye_indices, face.landmark)
        avg_EAR = (left_EAR + right_EAR) / 2.0

        current_time = time.time()

        # Double blink detection
        if avg_EAR < 0.22:
            if not eyes_closed:
                eyes_closed = True
                print("Eyes Closed (Blink started)")
        else:
            if eyes_closed:
                eyes_closed = False
                blink_counter += 1
                print(f"Blink detected! Count: {blink_counter}")
                if blink_counter == 1:
                    last_blink_time = current_time
                elif blink_counter == 2:
                    if current_time - last_blink_time <= blink_window and not emergency_active:
                        if light_on:
                            send_command("LIGHT_OFF")
                            send_command("RELAY_OFF")
                            light_on = False
                            relay_state = "OFF"
                            status_message = "BLINK 2x -> LIGHT & RELAY OFF"
                            status_msg_time = current_time
                            print("Action: LIGHT & RELAY OFF")
                        else:
                            send_command("LIGHT_ON")
                            send_command("RELAY_ON")
                            light_on = True
                            relay_state = "ON"
                            status_message = "BLINK 2x -> LIGHT & RELAY ON"
                            status_msg_time = current_time
                            print("Action: LIGHT & RELAY ON")
                        blink_counter = 0
                    else:
                        last_blink_time = current_time
                        blink_counter = 1

        if blink_counter > 0 and (current_time - last_blink_time > blink_window):
            blink_counter = 0

        # Mouth open detection (Upper lip inner center = 13, Lower lip inner center = 14)
        upper_lip = face.landmark[13]
        lower_lip = face.landmark[14]
        mouth_dist = get_distance(upper_lip, lower_lip)
        eye_dist = get_distance(face.landmark[33], face.landmark[263])
        mouth_ratio = mouth_dist / eye_dist
        mouth_open = mouth_ratio > 0.15

        if mouth_open and not emergency_active:
            if current_time - last_color_shift_time > COLOR_SHIFT_INTERVAL:
                # Shift color dynamically when mouth is open (larger step to show distinction, but paced by interval)
                hue = (hue + 16) % 256
                send_command(f"HSV,{hue},255,255")
                status_message = f"MOUTH OPEN -> COLOR (Hue: {hue})"
                status_msg_time = current_time
                last_color_shift_time = current_time
                
        # Smile detection for Relax Mode (Mouth corners 61 and 291)
        left_mouth = face.landmark[61]
        right_mouth = face.landmark[291]
        left_cheek = face.landmark[234]
        right_cheek = face.landmark[454]
        mouth_width = get_distance(left_mouth, right_mouth)
        face_width = get_distance(left_cheek, right_cheek)
        
        if face_width > 0:
            smile_ratio = mouth_width / face_width
            is_smiling = smile_ratio > 0.45
            if is_smiling and current_mode != "RELAX" and not emergency_active:
                current_mode = "RELAX"
                send_command("MODE_RELAX")
                status_message = "MODE: RELAX (Smile)"
                status_msg_time = current_time

    # Hand movement & pinch detection
    if results_hands.multi_hand_landmarks:
        for hand_landmarks in results_hands.multi_hand_landmarks:
            # Draw hand skeleton
            mp_drawing.draw_landmarks(
                frame,
                hand_landmarks,
                mp_hands.HAND_CONNECTIONS,
                mp_drawing_styles.get_default_hand_landmarks_style(),
                mp_drawing_styles.get_default_hand_connections_style()
            )

            # Get coordinates for wrist, thumb tip, and index tip
            wrist = hand_landmarks.landmark[0]
            thumb_tip = hand_landmarks.landmark[4]
            index_tip = hand_landmarks.landmark[8]
            
            pinch_dist = get_distance(thumb_tip, index_tip)
            is_pinching = pinch_dist < 0.045
            
            # Draw line between thumb and index tips
            tx, ty = int(thumb_tip.x * w), int(thumb_tip.y * h)
            ix, iy = int(index_tip.x * w), int(index_tip.y * h)
            line_color = (0, 255, 0) if is_pinching else (0, 0, 255)
            cv2.line(frame, (tx, ty), (ix, iy), line_color, 2)
            cv2.circle(frame, (tx, ty), 5, line_color, -1)
            cv2.circle(frame, (ix, iy), 5, line_color, -1)

            # Step-based brightness control using Left and Right Hand Pinches
            current_time = time.time()
            if is_pinching and not emergency_active:
                # Check screen side to identify Left Hand vs Right Hand status
                if wrist.x < 0.5:
                    left_hand_pinch = True
                    if current_time - last_left_pinch_time > pinch_cooldown:
                        send_command("BRIGHTNESS_DOWN")
                        last_left_pinch_time = current_time
                        status_message = "LEFT PINCH -> BRIGHTNESS DOWN"
                        status_msg_time = current_time
                else:
                    right_hand_pinch = True
                    if current_time - last_right_pinch_time > pinch_cooldown:
                        send_command("BRIGHTNESS_UP")
                        last_right_pinch_time = current_time
                        status_message = "RIGHT PINCH -> BRIGHTNESS UP"
                        status_msg_time = current_time

    # Draw Status Dashboard Overlay (Aesthetic Sidebar)
    overlay = frame.copy()
    cv2.rectangle(overlay, (10, 10), (320, 410), (25, 25, 25), -1)
    cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)
    cv2.rectangle(frame, (10, 10), (320, 410), (100, 100, 100), 1)

    font = cv2.FONT_HERSHEY_SIMPLEX
    cv2.putText(frame, "AI SMART LED SYSTEM", (20, 32), font, 0.6, (255, 255, 255), 2)
    cv2.line(frame, (20, 42), (310, 42), (150, 150, 150), 1)

    # Light State
    l_color = (0, 255, 0) if light_on else (0, 0, 255)
    l_text = "ON" if light_on else "OFF"
    cv2.putText(frame, f"Light State: {l_text}", (20, 65), font, 0.5, l_color, 2)

    # Active Color / Last Command
    cv2.putText(frame, f"Last Command: {last_command}", (20, 95), font, 0.5, (255, 255, 255), 1)
    
    # Active Mode
    cv2.putText(frame, f"Mode: {current_mode}", (180, 95), font, 0.5, (255, 0, 255), 2)

    # EAR and Blink tracking
    cv2.putText(frame, f"Eye EAR: {avg_EAR:.2f}", (20, 125), font, 0.5, (255, 255, 255), 1)
    blink_dots = "*" * blink_counter
    cv2.putText(frame, f"Blinks: {blink_dots:<2}", (180, 125), font, 0.5, (0, 255, 255), 2)

    # Mouth Open Info
    m_color = (0, 255, 0) if mouth_open else (180, 180, 180)
    m_text = "OPEN" if mouth_open else "CLOSED"
    cv2.putText(frame, f"Mouth: {m_text} ({mouth_ratio:.2f})", (20, 155), font, 0.5, m_color, 1)

    # Hand Pinches Info
    lh_status = "PINCHING" if left_hand_pinch else "OPEN"
    lh_color = (0, 255, 0) if left_hand_pinch else (180, 180, 180)
    cv2.putText(frame, f"Left Hand: {lh_status}", (20, 185), font, 0.5, lh_color, 1)

    # Right Hand Pinch
    rh_status = "PINCHING" if right_hand_pinch else "OPEN"
    rh_color = (0, 255, 0) if right_hand_pinch else (180, 180, 180)
    cv2.putText(frame, f"Right Hand: {rh_status}", (20, 215), font, 0.5, rh_color, 1)

    # LDR and PIR readings
    cv2.putText(frame, f"LDR Light: {ldr_val}", (20, 245), font, 0.5, (255, 255, 255), 1)
    motion_status = "DETECTED" if pir_val == 1 else "NO MOTION"
    motion_color = (0, 255, 0) if pir_val == 1 else (180, 180, 180)
    cv2.putText(frame, f"PIR Motion: {motion_status}", (20, 275), font, 0.5, motion_color, 1)

    # ACS and Relay readings
    cv2.putText(frame, f"ACS Current: {acs_val}", (20, 305), font, 0.5, (255, 255, 255), 1)
    relay_color = (0, 255, 0) if relay_state == "ON" else (0, 0, 255)
    cv2.putText(frame, f"Relay State: {relay_state}", (20, 335), font, 0.5, relay_color, 2)

    # Security armed status
    sec_color = (0, 255, 0) if security_mode_enabled else (180, 180, 180)
    sec_status = "ARMED" if security_mode_enabled else "DISARMED"
    cv2.putText(frame, f"Security Mode: {sec_status}", (20, 360), font, 0.5, sec_color, 2)

    # Emergency Flashing Overlay Warning
    if emergency_active:
        if int(time.time() * 2.5) % 2 == 0:
            cv2.putText(frame, "EMERGENCY ACTIVE", (350, 45), font, 0.7, (0, 0, 255), 2)

    # Status Notification Message
    if time.time() - status_msg_time < 1.5:
        cv2.putText(frame, status_message, (15, 435), font, 0.6, (0, 255, 255), 2)

    cv2.imshow("AI Smart Control", frame)

    key = cv2.waitKey(1)
    if key == 27:  # ESC key
        break
    elif key == ord('s'):
        current_mode = "STUDY"
        send_command("MODE_STUDY")
        status_message = "MODE: STUDY"
        status_msg_time = time.time()
    elif key == ord('n'):
        current_mode = "NIGHT"
        send_command("MODE_NIGHT")
        status_message = "MODE: NIGHT"
        status_msg_time = time.time()
    elif key == ord('e'):
        current_mode = "ENERGY"
        status_message = "MODE: ENERGY SAVING"
        status_msg_time = time.time()
    elif key == ord('r'):
        current_mode = "NORMAL"
        send_command("MODE_NORMAL")
        status_message = "MODE: NORMAL"
        status_msg_time = time.time()
    elif key == ord('y'):
        security_mode_enabled = not security_mode_enabled
        if not security_mode_enabled and emergency_active:
            clear_emergency()
        status_message = f"SECURITY: {'ARMED' if security_mode_enabled else 'DISARMED'}"
        status_msg_time = time.time()

cap.release()
cv2.destroyAllWindows()
if esp32:
    esp32.close()
