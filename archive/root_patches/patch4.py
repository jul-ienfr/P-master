import sys

with open('src/vision/detector.py', 'r', encoding='utf-8') as f:
    content = f.read()

old_code = '''        yolo_state = self._run_yolo_detection(frame, conf_threshold)
        if self._has_meaningful_signal(yolo_state):
            return yolo_state'''

new_code = '''        yolo_state = self._run_yolo_detection(frame, conf_threshold)
        if self._has_meaningful_signal(yolo_state):
            yolo_state.metadata["table_detected"] = True
            return yolo_state'''

content = content.replace(old_code, new_code)

with open('src/vision/detector.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("Patch applied for analyze_frame table_detected")
