import sys
with open('src/main.py', 'r', encoding='utf-8') as f:
    text = f.read()

text = text.replace('min_interval = 4.0', 'min_interval = 60.0')
text = text.replace('min_interval = 20.0', 'min_interval = 60.0')
text = text.replace('min_interval = 6.0', 'min_interval = 30.0')
text = text.replace('or total_ms >= self._slow_loop_log_threshold_ms', 'or (total_ms >= self._slow_loop_log_threshold_ms and canonical_state.street != "IDLE")')

with open('src/main.py', 'w', encoding='utf-8') as f:
    f.write(text)
print("Done")
