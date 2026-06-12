import cv2
import mediapipe as mp
import serial
import time
import math
import collections

# ==========================
# ESP32 SERIAL
# ==========================

PORT = "COM10"

try:
    esp32 = serial.Serial(PORT, 115200)
    time.sleep(2)
    print(f"Connected to ESP32 on {PORT}")
except Exception as e:
    print(f"Warning: Could not connect to ESP32 on {PORT}. Serial commands will be mocked. Error: {e}")
    esp32 = None

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

last_command = ""
last_write_time = 0
write_interval = 0.05  # 50ms rate limit to prevent flooding the serial port

# ==========================
# SEND COMMAND
# ==========================

def send_command(cmd, force=False):
    global last_command, last_write_time
    current_time = time.time()
    if cmd != last_command or force:
        if force or (current_time - last_write_time >= write_interval):
            if esp32:
                esp32.write((cmd + "\n").encode())
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

# Pinch gestures timing
last_left_pinch_time = 0
last_right_pinch_time = 0
pinch_cooldown = 0.25  # seconds

# Overlay status messaging
status_message = ""
status_msg_time = 0

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
                    if current_time - last_blink_time <= blink_window:
                        if light_on:
                            send_command("LIGHT_OFF")
                            light_on = False
                            status_message = "BLINK 2x -> LIGHT OFF"
                            status_msg_time = current_time
                            print("Action: LIGHT OFF")
                        else:
                            send_command("LIGHT_ON")
                            light_on = True
                            status_message = "BLINK 2x -> LIGHT ON"
                            status_msg_time = current_time
                            print("Action: LIGHT ON")
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

        if mouth_open:
            # Shift color dynamically when mouth is open
            hue = (hue + 4) % 256
            send_command(f"HSV,{hue},255,255")
            status_message = f"MOUTH OPEN -> COLOR (Hue: {hue})"
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

            # Use screen side to identify Left Hand vs Right Hand
            current_time = time.time()
            if wrist.x < 0.5:
                left_hand_pinch = is_pinching
            else:
                right_hand_pinch = is_pinching

            if is_pinching:
                # Pinch Y controls brightness (higher hand = brighter)
                pinch_y = (thumb_tip.y + index_tip.y) / 2.0
                y_val = max(0.2, min(0.8, pinch_y))
                normalized_y = (0.8 - y_val) / 0.6  # 1.0 at y=0.2 (top), 0.0 at y=0.8 (bottom)
                target_brightness = int(5 + normalized_y * 250)
                
                send_command(f"BRIGHTNESS,{target_brightness}")
                status_message = f"PINCH -> BRIGHTNESS {target_brightness}"
                status_msg_time = current_time
                
                # Draw pinch indicator on the frame
                px, py = int((thumb_tip.x + index_tip.x) / 2 * w), int(pinch_y * h)
                cv2.circle(frame, (px, py), 8, (0, 255, 0), -1)
                cv2.putText(frame, f"Brightness: {target_brightness}", (px + 15, py + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

    # Draw Status Dashboard Overlay (Aesthetic Sidebar)
    overlay = frame.copy()
    cv2.rectangle(overlay, (10, 10), (320, 235), (25, 25, 25), -1)
    cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)
    cv2.rectangle(frame, (10, 10), (320, 235), (100, 100, 100), 1)

    font = cv2.FONT_HERSHEY_SIMPLEX
    cv2.putText(frame, "AI SMART LED SYSTEM", (20, 32), font, 0.6, (255, 255, 255), 2)
    cv2.line(frame, (20, 42), (310, 42), (150, 150, 150), 1)

    # Light State
    l_color = (0, 255, 0) if light_on else (0, 0, 255)
    l_text = "ON" if light_on else "OFF"
    cv2.putText(frame, f"Light State: {l_text}", (20, 65), font, 0.5, l_color, 2)

    # Active Color / Last Command
    cv2.putText(frame, f"Last Command: {last_command}", (20, 95), font, 0.5, (255, 255, 255), 1)

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

    rh_status = "PINCHING" if right_hand_pinch else "OPEN"
    rh_color = (0, 255, 0) if right_hand_pinch else (180, 180, 180)
    cv2.putText(frame, f"Right Hand: {rh_status}", (20, 215), font, 0.5, rh_color, 1)

    # Status Notification Message
    if time.time() - status_msg_time < 1.5:
        cv2.putText(frame, status_message, (15, 255), font, 0.6, (0, 255, 255), 2)

    cv2.imshow("AI Smart Control", frame)

    key = cv2.waitKey(1)
    if key == 27:  # ESC key
        break

cap.release()
cv2.destroyAllWindows()
if esp32:
    esp32.close()
