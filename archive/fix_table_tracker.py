with open("src/bot/table_tracker.py", "r", encoding="utf-8") as f:
    content = f.read()

old_logic = "if pending is not None and abs(pending - clean_stack) < 0.1:"
new_logic = "if pending is not None and abs(pending - clean_stack) < max(p.current_stack * 0.05, 0.5):"
content = content.replace(old_logic, new_logic)

with open("src/bot/table_tracker.py", "w", encoding="utf-8") as f:
    f.write(content)
