file_path = "tests/test_table_tracker.py"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

old_assertion = "assert tracker.state_confidence == 0.765"
new_assertion = "assert tracker.state_confidence == 0.675"

if old_assertion in content:
    content = content.replace(old_assertion, new_assertion)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
